"""Store (tenant) resolution.

A storefront widget sends its publishable key as the `X-Store-Key` header. We
resolve it to a store row here. Results are cached briefly to avoid a DB hit on
every request; the cache is small (one entry per active store).
"""
from __future__ import annotations

import time

import structlog

from app.db import get_supabase

log = structlog.get_logger()

_COLUMNS = (
    "id, slug, name, public_key, shopify_domain, allowed_origins, "
    "persona_name, persona_avatar_url, greeting_template, brand, "
    "sales_notification_email, status"
)

_TTL = 60  # seconds
_cache: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str) -> dict | None:
    hit = _cache.get(key)
    if hit and (time.monotonic() - hit[0]) < _TTL:
        return hit[1]
    return None


def _cache_put(key: str, store: dict) -> None:
    _cache[key] = (time.monotonic(), store)


def resolve_store(public_key: str) -> dict | None:
    """Return the active store for a publishable key, or None."""
    if not public_key:
        return None
    cached = _cache_get(f"pk:{public_key}")
    if cached:
        return cached

    sb = get_supabase()
    res = (
        sb.table("stores")
        .select(_COLUMNS)
        .eq("public_key", public_key)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    store = res.data[0]
    _cache_put(f"pk:{public_key}", store)
    _cache_put(f"id:{store['id']}", store)
    return store


def get_store(store_id: str) -> dict | None:
    if not store_id:
        return None
    cached = _cache_get(f"id:{store_id}")
    if cached:
        return cached

    sb = get_supabase()
    res = sb.table("stores").select(_COLUMNS).eq("id", store_id).limit(1).execute()
    if not res.data:
        return None
    store = res.data[0]
    _cache_put(f"id:{store_id}", store)
    return store
