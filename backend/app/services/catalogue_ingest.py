"""Sidecar-driven catalogue ingest — the backend cannot fetch the feed itself.

Shopify's Cloudflare edge refuses the BACKEND container's HTTP client from a
hosting ASN while accepting the Alpine-curl SIDECAR's, from the same droplet,
the same IP, seconds apart. Measured on the staging droplet 2026-07-29, the two
probes run back to back:

    backend  container, 6 requests, no delay -> 429 429 429 429 429 429
    watchdog container, 6 requests, no delay -> 200 200 200 200 200 200

Read that carefully before "simplifying" any of this, because three plausible
explanations are already ruled out by it:
  * NOT rate limiting  — a six-request burst from the sidecar passes clean.
  * NOT the User-Agent — a browser UA is refused from the backend too.
  * NOT the flags      — bare `curl <url>` is refused from the backend too.
The variable is the client itself (Debian curl 8.14.1/OpenSSL 3.5.6 refused,
Alpine curl 8.11.1/OpenSSL 3.3.2 accepted). httpx and curl_cffi are refused as
well. So the fetch lives in the sidecar and the backend only ingests.

Flow, one store:
    sidecar: GET  /admin/catalogue/sync-targets           -> "<store_id> <base>"
    sidecar: curl <base>/products.json?limit=250&page=N   -> raw feed page
    sidecar: POST /admin/stores/{id}/catalogue/pages/{N}  (body = that page)
    ...until a short page, then...
    sidecar: POST /admin/stores/{id}/catalogue/commit     -> swaps the catalogue

Pages buffer in memory and the delete/insert happens ONLY at commit, so a fetch
that dies half way through leaves the live catalogue untouched. That is the
whole reason for the two-step shape — a page-at-a-time writer would leave a
half-wiped catalogue whenever the feed hiccuped mid-run.

Scheduling lives here too, not in the sidecar: that image is Alpine with no
tzdata (`TZ=Australia/Sydney date` prints UTC), so it cannot know when midnight
Sydney is. The sidecar polls; this module decides.
"""
from __future__ import annotations

import time
from datetime import datetime

import structlog

from app.db import get_supabase
from app.services.catalogue_sync import (
    _normalise_base,
    _to_row,
    replace_catalogue,
    sync_timezone,
)

log = structlog.get_logger()

# A buffer older than this is abandoned rather than committed — a sidecar that
# died mid-run must not have its stale pages committed by a later run.
BUFFER_TTL_SECONDS = 3600.0
# How long a handed-out target stays claimed, so a 30s poll cannot start the
# same store twice while the first run is still uploading pages.
CLAIM_TTL_SECONDS = 900.0

_buffers: dict[str, dict] = {}
_queued: set[str] = set()
_claims: dict[str, float] = {}
_last_nightly_date: str | None = None


def reset_state() -> None:
    """Test hook — clears every module-level buffer/claim/queue."""
    global _last_nightly_date
    _buffers.clear()
    _queued.clear()
    _claims.clear()
    _last_nightly_date = None


# ---------------------------------------------------------------- scheduling

def enqueue(store_id: str) -> None:
    """Ask for `store_id` to be synced on the sidecar's next poll."""
    _queued.add(store_id)
    _claims.pop(store_id, None)          # an explicit request overrides a claim
    log.info("catalogue_sync_queued", store_id=store_id)


def _nightly_due(now: datetime | None = None) -> bool:
    """True once per local calendar day, on the first poll after midnight.

    Deliberately does NOT fire on the first call after a restart: the first
    poll only arms the date. Otherwise every deploy would kick off a full
    refresh of every store.
    """
    global _last_nightly_date
    today = (now or datetime.now(sync_timezone())).astimezone(sync_timezone()).date().isoformat()
    if _last_nightly_date is None:
        _last_nightly_date = today
        return False
    if _last_nightly_date != today:
        _last_nightly_date = today
        return True
    return False


def _syncable_stores() -> list[dict]:
    res = get_supabase().table("stores").select("id, slug, shopify_domain, status").execute()
    return [s for s in (res.data or []) if s.get("shopify_domain") and s.get("status") == "active"]


def claim_targets(now: datetime | None = None) -> list[dict]:
    """Stores the sidecar should fetch right now, marked as claimed.

    Returns `[{"store_id": ..., "base": "https://..."}]` — queued stores always,
    plus every store once the local date rolls over.
    """
    stores = _syncable_stores()
    if _nightly_due(now):
        _queued.update(s["id"] for s in stores)

    deadline = time.monotonic()
    targets = []
    for store in stores:
        sid = store["id"]
        if sid not in _queued:
            continue
        if _claims.get(sid, 0.0) > deadline:
            continue                      # already in flight
        _claims[sid] = deadline + CLAIM_TTL_SECONDS
        targets.append({"store_id": sid, "base": _normalise_base(store["shopify_domain"])})
    return targets


# ------------------------------------------------------------------- ingest

def _expire_buffers() -> None:
    cutoff = time.monotonic() - BUFFER_TTL_SECONDS
    for sid in [k for k, v in _buffers.items() if v["ts"] < cutoff]:
        log.warning("catalogue_buffer_expired", store_id=sid)
        _buffers.pop(sid, None)


def ingest_page(store: dict, page: int, payload: dict) -> int:
    """Buffer one fetched page. Page 1 starts a fresh buffer.

    Returns the number of PRODUCTS in the page (not rows kept) — the sidecar
    compares it against the page limit to know whether to ask for another.
    """
    _expire_buffers()
    sid = store["id"]
    if page <= 1:
        _buffers.pop(sid, None)

    buf = _buffers.setdefault(sid, {"rows": [], "fetched": 0, "ts": time.monotonic()})
    buf["ts"] = time.monotonic()

    products = payload.get("products") or []
    buf["fetched"] += len(products)
    domain = store["shopify_domain"]
    buf["rows"].extend(r for p in products if (r := _to_row(sid, domain, p)))
    return len(products)


def commit(store: dict) -> dict:
    """Swap the store's catalogue for everything buffered, then clear it."""
    sid = store["id"]
    _expire_buffers()
    buf = _buffers.pop(sid, None)
    _claims.pop(sid, None)
    _queued.discard(sid)

    if buf is None:
        raise LookupError("no buffered pages for this store — fetch them first")
    if not buf["rows"]:
        # Refuse rather than wipe: an empty feed is far more likely to be a
        # broken fetch than a store that genuinely sells nothing.
        raise ValueError("refusing to commit an empty catalogue")

    return replace_catalogue(sid, buf["rows"], fetched=buf["fetched"])


def abandon(store_id: str) -> None:
    """Drop a partial buffer — the sidecar's fetch failed part way through."""
    _buffers.pop(store_id, None)
    _claims.pop(store_id, None)
    log.warning("catalogue_ingest_abandoned", store_id=store_id)
