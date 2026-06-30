"""Shared FastAPI dependencies."""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.db import get_supabase
from app.services.stores import resolve_store

# Single shared limiter, keyed by client IP. Imported by main.py and routes.
limiter = Limiter(key_func=get_remote_address)


def get_supabase_dep():
    return get_supabase()


async def require_store(x_store_key: str | None = Header(default=None)) -> dict:
    """Resolve the tenant from the X-Store-Key header. 401 if missing/unknown."""
    if not x_store_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Store-Key header",
        )
    store = resolve_store(x_store_key)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown or inactive store key",
        )
    return store


async def require_admin(x_admin_secret: str | None = Header(default=None)) -> None:
    """Gate /admin/* routes on the X-Admin-Secret header (constant-time compare)."""
    expected = settings.admin_secret
    if not x_admin_secret or not hmac.compare_digest(x_admin_secret, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin secret")
