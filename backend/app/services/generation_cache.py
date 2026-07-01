"""Generation cache — avoids re-paying for identical generations.

Cache key = sha256(product_id + colour + prompt_hash + asset_hash). Looks up the
generations table for a prior complete row with the same key before calling a provider.
"""
from __future__ import annotations

import hashlib

import structlog

from app.db import get_supabase

log = structlog.get_logger()


def cache_key(product_id: str, colour: str, prompt_hash: str, asset_hash: str) -> str:
    raw = f"{product_id}|{colour}|{prompt_hash}|{asset_hash}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup(key: str) -> dict | None:
    """Return a prior complete generation row matching this cache key, if any.

    Stub results are explicitly excluded. The stub adapter returns a
    placeholder (placehold.co) image, and the cache key is derived only from
    product/colour/prompt/asset — NOT the active provider. Without this guard a
    stub row written while ``IMAGE_PROVIDER_PREVIEW=stub`` would be served as a
    cache hit forever after switching to ``gemini_flash``, so the real Gemini
    call never runs and every email ships the placeholder. A placeholder must
    never masquerade as a cached real design.
    """
    sb = get_supabase()
    res = (
        sb.table("generations")
        .select("*")
        .eq("prompt_hash", key)
        .eq("status", "complete")
        .neq("model", "stub")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if res.data:
        log.info("generation_cache_hit")
        return res.data[0]
    return None
