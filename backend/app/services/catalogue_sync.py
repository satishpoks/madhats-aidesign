"""Catalogue sync — pull a store's Shopify products.json into product_references.

Generalises the manual MadHats seed: given a store with a shopify_domain, fetch
its public products feed, map each product to our schema (scoped by store_id),
and replace that store's catalogue. Provider keys are untouched (shared, env).
"""
from __future__ import annotations

import html
import re

import httpx
import structlog

from app.db import get_supabase

log = structlog.get_logger()

_PAGE_LIMIT = 250
_MAX_PAGES = 10

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


async def _fetch_products(domain: str) -> list[dict]:
    base = domain.strip().rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
    products: list[dict] = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            resp = await client.get(
                f"{base}/products.json", params={"limit": _PAGE_LIMIT, "page": page}
            )
            resp.raise_for_status()
            batch = resp.json().get("products", [])
            if not batch:
                break
            products.extend(batch)
            if len(batch) < _PAGE_LIMIT:
                break
    return products


def _to_row(store_id: str, domain: str, product: dict) -> dict | None:
    image_srcs = [img.get("src") for img in product.get("images", []) if img.get("src")]
    if not image_srcs:
        return None  # cannot composite without a reference photo
    style = _derive_style(product)
    handle = product.get("handle", "")
    base = domain.strip().rstrip("/")
    if not base.startswith("http"):
        base = f"https://{base}"
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
    skipped = len(products) - len(rows)

    sb = get_supabase()
    sb.table("product_references").delete().eq("store_id", store["id"]).execute()
    if rows:
        # chunked insert to stay well under payload limits
        for i in range(0, len(rows), 100):
            sb.table("product_references").insert(rows[i : i + 100]).execute()

    log.info("catalogue_synced", store_id=store["id"], imported=len(rows), skipped=skipped)
    return {"fetched": len(products), "imported": len(rows), "skipped": skipped}
