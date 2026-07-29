"""Catalogue sync — pull a store's Shopify products.json into product_references.

Generalises the manual MadHats seed: given a store with a shopify_domain, fetch
its public products feed, map each product to our schema (scoped by store_id),
and replace that store's catalogue. Provider keys are untouched (shared, env).
"""
from __future__ import annotations

import asyncio
import html
import json
import re
from datetime import datetime, time as dtime, timedelta, timezone as _tz
from functools import lru_cache
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import structlog

from app.db import get_supabase

log = structlog.get_logger()

_PAGE_LIMIT = 250
_MAX_PAGES = 10
_FETCH_TIMEOUT_SECONDS = 60
_CURL_BIN = "curl"

# Nightly catalogue refresh runs at 00:00 in this zone.
SYNC_TIMEZONE_KEY = "Australia/Sydney"


@lru_cache(maxsize=1)
def sync_timezone() -> ZoneInfo:
    """Resolved lazily, never at import.

    `ZoneInfo` needs a tz database, which Windows does not ship (the `tzdata`
    package covers it — see pyproject). Resolving at module scope means a
    missing database takes down every import of this module, and with it the
    admin routes and app startup, over a once-a-night clock. Fail at the call
    instead.
    """
    return ZoneInfo(SYNC_TIMEZONE_KEY)


class CatalogueFetchError(RuntimeError):
    """A page of a store's Shopify feed could not be fetched."""


# Keyword → canonical style slug (best-effort from product type/title).
_STYLE_KEYWORDS = {
    "bucket": "bucket_hat",
    "trucker": "trucker",
    "snapback": "snapback",
    "beanie": "beanie",
    "visor": "visor",
    "five panel": "five_panel",
    "5 panel": "five_panel",
    "dad": "dad_hat",
    "baseball": "baseball_cap",
}


def _strip_html(raw: str | None) -> str:
    text = re.sub(r"<[^>]+>", " ", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()[:600]


def _derive_style(product: dict) -> str:
    haystack = f"{product.get('product_type','')} {product.get('title','')} {' '.join(product.get('tags', []) if isinstance(product.get('tags'), list) else [str(product.get('tags',''))])}".lower()
    for kw, slug in _STYLE_KEYWORDS.items():
        if kw in haystack:
            return slug
    return "cap"


def _first_colour(product: dict) -> str:
    for opt in product.get("options", []):
        if str(opt.get("name", "")).lower() in ("colour", "color"):
            vals = opt.get("values") or []
            if vals:
                return str(vals[0])
    variants = product.get("variants") or []
    if variants and variants[0].get("option1"):
        return str(variants[0]["option1"])
    return ""


def _map_views(image_srcs: list[str]) -> dict:
    """Map product photos to angle keys by filename keyword, plus front.

    Only GENUINE, keyword-matched angles are recorded — we no longer fabricate
    back/left/right from arbitrary positional images. A decorated face with no
    real per-angle photo is left ABSENT here, so the canvas render loop
    (generate.py) can SKIP it rather than compositing a back decoration onto a
    front-facing cap (C6.1). Front is always available — it is the reference
    photo (image_srcs[0]).
    """
    views: dict[str, str] = {}
    angle_kw = {
        "front": ["front"],
        "back": ["back", "rear"],
        "left": ["left", "side"],
        "right": ["right", "angled"],
    }
    for src in image_srcs:
        low = src.lower()
        for key, kws in angle_kw.items():
            if key not in views and any(k in low for k in kws):
                views[key] = src
    if image_srcs:
        views.setdefault("front", image_srcs[0])
    return views


def _decoration_types(style: str) -> list[str]:
    if style in ("trucker",):
        return ["print", "embroidery", "patch"]
    return ["print", "embroidery"]


def _placement_zones(style: str) -> list[str]:
    if style in ("bucket_hat", "visor"):
        return ["front_panel", "side"]
    return ["front_panel", "side", "back"]


def _normalise_base(domain: str) -> str:
    base = domain.strip().rstrip("/")
    return base if base.startswith("http") else f"https://{base}"


async def _curl_get_json(url: str) -> dict:
    """GET `url` with the curl BINARY and parse the JSON body.

    Deliberately NOT httpx. Shopify fronts the storefront with Cloudflare,
    which scores the caller's TLS fingerprint together with its ASN. From a
    hosting ASN the Python TLS stack is rejected outright — measured on the
    production droplet (DigitalOcean SYD1), same host, same egress IP, same
    URL, seconds apart, 2026-07-29:

        httpx                          -> 429
        curl_cffi(impersonate="chrome") -> 429
        curl binary                    -> 200

    The identical httpx call returns 200 from a residential ASN, which is why
    this only ever fails in production and looks like "the sync is broken" in
    dev. Swapping this back to httpx for tidiness will silently break the
    nightly sync on the server; `curl` is installed in backend/Dockerfile for
    exactly this reason and is not a debugging convenience.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            _CURL_BIN,
            "-sS",                       # quiet, but keep errors on stderr
            "--compressed",              # the feed is ~2 MB/page uncompressed
            "--location",
            "--max-time", str(_FETCH_TIMEOUT_SECONDS),
            "-H", "Accept: application/json",
            "-w", "\n%{http_code}",      # status trails the body, after the last \n
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:     # image built without curl
        raise CatalogueFetchError(
            "curl binary not found — backend/Dockerfile must install it"
        ) from exc

    out, err = await proc.communicate()
    if proc.returncode != 0:
        detail = err.decode("utf-8", "replace").strip()[:200]
        raise CatalogueFetchError(f"curl exited {proc.returncode}: {detail}")

    body, _, status = out.rpartition(b"\n")
    code = status.decode("ascii", "replace").strip()
    endpoint = url.split("?", 1)[0]
    if code != "200":
        raise CatalogueFetchError(f"HTTP {code} from {endpoint}")
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise CatalogueFetchError(f"non-JSON response from {endpoint}") from exc


async def _fetch_products(domain: str) -> list[dict]:
    base = _normalise_base(domain)
    products: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        payload = await _curl_get_json(
            f"{base}/products.json?" + urlencode({"limit": _PAGE_LIMIT, "page": page})
        )
        batch = payload.get("products", [])
        if not batch:
            break
        products.extend(batch)
        if len(batch) < _PAGE_LIMIT:
            break
    return products


def seconds_until_next_sync(now: datetime | None = None) -> int:
    """Whole seconds from `now` until the next 00:00 in SYNC_TIMEZONE.

    Computed here, in Python, because the scheduler sidecar's image
    (curlimages/curl, Alpine) ships NO tzdata: `TZ=Australia/Sydney date`
    prints UTC there. Any midnight arithmetic done in that shell would run on
    UTC and fire at 10:00 Sydney — silently, and correctly-looking in the logs.
    Verified 2026-07-29. Keep the clock in the container that has tzdata.
    """
    tz = sync_timezone()
    now = (now or datetime.now(tz)).astimezone(tz)
    next_midnight = datetime.combine(now.date() + timedelta(days=1), dtime(0, 0), tzinfo=tz)
    # Subtract in UTC, NOT in local time. Python ignores the offset when both
    # operands carry the same tzinfo object, so `next_midnight - now` is
    # wall-clock arithmetic: on a DST-transition night it answers 24h for the
    # 23h that actually elapse, and the sidecar wakes at 01:00.
    return max(
        1,
        int((next_midnight.astimezone(_tz.utc) - now.astimezone(_tz.utc)).total_seconds()),
    )


def _to_row(store_id: str, domain: str, product: dict) -> dict | None:
    image_srcs = [img.get("src") for img in product.get("images", []) if img.get("src")]
    if not image_srcs:
        return None  # cannot composite without a reference photo
    style = _derive_style(product)
    handle = product.get("handle", "")
    base = _normalise_base(domain)
    return {
        "store_id": store_id,
        "shopify_product_id": str(product.get("id") or handle),
        "style": style,
        "colour": _first_colour(product),
        "name": product.get("title", "Untitled"),
        "description": _strip_html(product.get("body_html")),
        "store_url": f"{base}/products/{handle}",
        "reference_image_url": image_srcs[0],
        "view_images": _map_views(image_srcs),
        "placement_zones": _placement_zones(style),
        "decoration_types": _decoration_types(style),
    }


async def sync_store_catalogue(store: dict) -> dict:
    """Replace `store`'s catalogue from its Shopify products.json.

    Returns { fetched, imported, skipped }.
    """
    domain = store.get("shopify_domain")
    if not domain:
        raise ValueError("store has no shopify_domain")

    products = await _fetch_products(domain)
    rows = [r for p in products if (r := _to_row(store["id"], domain, p))]
    return replace_catalogue(store["id"], rows, fetched=len(products))


def replace_catalogue(store_id: str, rows: list[dict], *, fetched: int) -> dict:
    """Swap a store's catalogue for `rows`. The ONLY writer of product_references.

    Called both by the direct fetch path and by the sidecar ingest commit, so
    the delete/insert semantics stay in one place.
    """
    sb = get_supabase()
    sb.table("product_references").delete().eq("store_id", store_id).execute()
    if rows:
        # chunked insert to stay well under payload limits
        for i in range(0, len(rows), 100):
            sb.table("product_references").insert(rows[i : i + 100]).execute()

    skipped = fetched - len(rows)
    log.info("catalogue_synced", store_id=store_id, imported=len(rows), skipped=skipped)
    return {"fetched": fetched, "imported": len(rows), "skipped": skipped}


async def sync_all_stores() -> dict:
    """Sync every active store that has a shopify_domain.

    One store's failure is recorded and skipped, never raised: the nightly job
    must not drop nine catalogues because the tenth store's feed is down.
    """
    sb = get_supabase()
    stores = sb.table("stores").select("*").eq("status", "active").execute().data or []

    results: list[dict] = []
    for store in stores:
        if not store.get("shopify_domain"):
            continue
        entry = {"store_id": store["id"], "slug": store.get("slug")}
        try:
            results.append({**entry, "ok": True, **await sync_store_catalogue(store)})
        except Exception as exc:  # noqa: BLE001 — one bad feed must not stop the rest
            log.error("catalogue_sync_failed", store_id=store["id"], error=str(exc))
            results.append({**entry, "ok": False, "error": str(exc)})

    succeeded = sum(1 for r in results if r["ok"])
    log.info("catalogue_sync_all", stores=len(results), succeeded=succeeded)
    return {
        "stores": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }
