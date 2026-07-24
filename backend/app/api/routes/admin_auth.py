"""Admin-user authentication: login, whoami, change-password.

Login verifies email+password and returns a 12h JWT plus the user's profile
(assigned stores). /me hydrates the frontend on reload. No admin email is ever
logged (structlog would be PII); we log the user id only.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.deps import AdminContext, require_admin_ctx
from app.db import get_supabase
from app.services import admin_auth, admin_users

router = APIRouter(tags=["admin-auth"])
log = structlog.get_logger()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _stores_public(store_ids: set[str] | None) -> list[dict]:
    """Resolve store ids to {id,name,public_key}. None == all stores (super)."""
    sb = get_supabase()
    res = sb.table("stores").select("id, name, public_key").order("name").execute()
    rows = res.data or []
    if store_ids is None:
        return [{"id": r["id"], "name": r["name"], "public_key": r["public_key"]} for r in rows]
    return [
        {"id": r["id"], "name": r["name"], "public_key": r["public_key"]}
        for r in rows if r["id"] in store_ids
    ]


def _profile(ctx: AdminContext) -> dict:
    return {
        "email": ctx.email,
        "is_super": ctx.is_super,
        "stores": _stores_public(ctx.allowed_store_ids),
    }


@router.post("/admin/auth/login")
async def login(body: LoginRequest) -> dict:
    user = admin_users.get_by_email(body.email)
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not admin_auth.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = admin_auth.create_token(user["id"])
    is_super = bool(user.get("is_super"))
    store_ids = None if is_super else admin_users.allowed_store_ids(user["id"])
    log.info("admin_login", user_id=user["id"])  # no email (PII)
    profile = {
        "email": user["email"],
        "is_super": is_super,
        "stores": _stores_public(store_ids),
    }
    return {"token": token, "profile": profile}


@router.get("/admin/auth/me")
async def me(ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    return _profile(ctx)


@router.post("/admin/auth/change-password")
async def change_password(
    body: ChangePasswordRequest, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="The env super admin has no password to change")
    user = admin_users.get_by_id(ctx.user_id)
    if not user or not admin_auth.verify_password(body.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    admin_users.update_user(ctx.user_id, password=body.new_password)
    log.info("admin_password_changed", user_id=ctx.user_id)
    return {"ok": True}
