"""Supabase Storage helpers.

The bucket is private. Customer-facing URLs are ALWAYS signed with a TTL — a raw
public path is never returned to a client.
"""
from __future__ import annotations

import uuid

import structlog

from app.config import settings
from app.db import get_supabase

log = structlog.get_logger()

_BUCKET = settings.supabase_storage_bucket


def _bucket():
    return get_supabase().storage.from_(_BUCKET)


def upload_asset(file_bytes: bytes, filename: str, content_type: str) -> str:
    """Upload bytes to storage and return the storage path (NOT a URL)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    path = f"uploads/{uuid.uuid4().hex}.{ext}"
    _bucket().upload(
        path=path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    log.info("asset_uploaded", path=path, size=len(file_bytes))
    return path


def write_generated(image_bytes: bytes, tier: str, content_type: str = "image/png") -> str:
    """Store a generated (clean) image and return its storage path."""
    path = f"generated/{tier}/{uuid.uuid4().hex}.png"
    _bucket().upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return path


def write_watermarked(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Store a watermarked image and return its storage path."""
    path = f"watermarked/{uuid.uuid4().hex}.png"
    _bucket().upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return path


def generate_signed_url(path: str, ttl: int | None = None) -> str:
    """Return a signed, TTL-limited URL for a stored object."""
    if not path:
        return ""
    ttl = ttl if ttl is not None else settings.signed_url_ttl
    resp = _bucket().create_signed_url(path, ttl)
    # supabase-py returns {"signedURL": "..."} (key casing varies by version)
    return resp.get("signedURL") or resp.get("signedUrl") or resp.get("signed_url", "")
