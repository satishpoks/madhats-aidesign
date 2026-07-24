"""Shared FastAPI dependencies."""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.db import get_supabase
from app.services import admin_auth, admin_users
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


@dataclass
class AdminContext:
    """Who is calling an /admin route and what stores they may touch.

    allowed_store_ids is None for a super admin (== all stores). user_id/email
    are None for the env-secret super (no admin_users row).
    """

    user_id: str | None
    email: str | None
    is_super: bool
    allowed_store_ids: set[str] | None


def _super_from_secret() -> AdminContext:
    return AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)


async def require_admin_ctx(
    x_admin_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> AdminContext:
    """Authenticate an /admin request via X-Admin-Secret (super) or Bearer JWT.

    For a Bearer token the user row + assignments are re-loaded every request so
    disable/re-assignment is immediate.
    """
    expected = settings.admin_secret
    if x_admin_secret and hmac.compare_digest(x_admin_secret, expected):
        return _super_from_secret()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        user_id = admin_auth.decode_token(token)
        if user_id:
            user = admin_users.get_by_id(user_id)
            if user and user.get("status") == "active":
                is_super = bool(user.get("is_super"))
                return AdminContext(
                    user_id=user["id"],
                    email=user.get("email"),
                    is_super=is_super,
                    allowed_store_ids=None if is_super else admin_users.allowed_store_ids(user["id"]),
                )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def require_super(ctx: AdminContext) -> None:
    if not ctx.is_super:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin required")


def assert_store_allowed(ctx: AdminContext, store_id: str | None) -> None:
    if ctx.is_super:
        return
    if store_id is None or ctx.allowed_store_ids is None or store_id not in ctx.allowed_store_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this store")


async def require_admin(
    x_admin_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Backward-compatible authentication gate for routers that only need to
    confirm *some* admin is calling (no per-store scoping). Accepts the same
    credentials as require_admin_ctx."""
    await require_admin_ctx(x_admin_secret=x_admin_secret, authorization=authorization)
