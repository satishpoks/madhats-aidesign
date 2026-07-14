"""Supabase Storage helpers.

The bucket is private. Customer-facing URLs are ALWAYS signed with a TTL — a raw
public path is never returned to a client.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import jwt
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


def write_composite(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Store a composited preview image and return its storage path."""
    path = f"composite/{uuid.uuid4().hex}.png"
    _bucket().upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return path


def download_asset(path: str) -> bytes | None:
    """Download raw bytes of a stored object, or None on any failure."""
    if not path or path.startswith("http"):
        return None
    try:
        return _bucket().download(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("asset_download_failed", error=str(exc))
        return None


def generate_signed_url(path: str, ttl: int | None = None) -> str:
    """Return a signed, TTL-limited URL for a stored object."""
    if not path:
        return ""
    ttl = ttl if ttl is not None else settings.signed_url_ttl
    resp = _bucket().create_signed_url(path, ttl)
    # supabase-py returns {"signedURL": "..."} (key casing varies by version)
    return resp.get("signedURL") or resp.get("signedUrl") or resp.get("signed_url", "")


# --- Media proxy capability tokens ---------------------------------------
# The backend proxies private storage objects to client browsers (see
# app/api/routes/media.py). A raw Supabase signed URL can't be handed to an
# <img> because its host is the backend-only storage address (host.docker.internal
# in docker dev). Instead we mint a short-lived capability token that names ONE
# object path, embed it in a same-backend /media/{token} URL, and stream the
# bytes server-side. The token IS the authorisation — an <img> can't send the
# X-Admin-Secret header, so URL-based capability is what makes admin images load.


class MediaTokenError(Exception):
    """Raised when a media proxy token is missing, expired, or malformed."""


def make_media_token(path: str, ttl: int | None = None) -> str:
    """Sign a capability token authorising a fetch of exactly ``path``."""
    ttl = ttl if ttl is not None else settings.signed_url_ttl
    exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    return jwt.encode(
        {"path": path, "purpose": "media", "exp": exp},
        settings.admin_secret,  # reuse the server secret for signing
        algorithm="HS256",
    )


def decode_media_token(token: str) -> str:
    """Validate a media token and return the storage path it authorises."""
    try:
        payload = jwt.decode(token, settings.admin_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:  # covers expired + malformed
        raise MediaTokenError(str(exc)) from exc
    if payload.get("purpose") != "media":
        raise MediaTokenError("wrong purpose")
    path = payload.get("path")
    if not path:
        raise MediaTokenError("no path")
    return path


def media_url(path: str | None, base_url: str) -> str | None:
    """Turn a stored object path into a client-fetchable proxy URL.

    - Empty/None -> None.
    - External URLs (Shopify product images, stub placeholders) pass through
      unchanged — the browser can already reach those.
    - Private storage paths become an absolute ``{base_url}media/{token}`` URL
      served by this backend. ``base_url`` is the request's own base (e.g.
      http://100.103.149.17:8000/) so the URL is reachable from wherever the
      client reached the API.
    """
    if not path:
        return None
    if path.startswith("http"):
        return path
    return f"{base_url}media/{make_media_token(path)}"
