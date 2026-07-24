"""Super-admin-only management of admin users + their store assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.deps import AdminContext, require_admin_ctx, require_super
from app.services import admin_users

router = APIRouter(tags=["admin-users"])


def _require_super_dep(ctx: AdminContext = Depends(require_admin_ctx)) -> AdminContext:
    require_super(ctx)
    return ctx


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    is_super: bool = False
    store_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    is_super: bool | None = None
    status: str | None = None
    password: str | None = None
    store_ids: list[str] | None = None


@router.get("/admin/users")
async def list_users(ctx: AdminContext = Depends(_require_super_dep)) -> list[dict]:
    return admin_users.list_users()


@router.post("/admin/users")
async def create_user(body: CreateUserRequest, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    if admin_users.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="An admin with that email already exists")
    return admin_users.create_user(
        email=body.email, password=body.password,
        is_super=body.is_super, store_ids=body.store_ids,
    )


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserRequest, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    if admin_users.get_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return admin_users.update_user(
        user_id, is_super=body.is_super, status=body.status,
        password=body.password, store_ids=body.store_ids,
    )


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    return {"deleted": admin_users.delete_user(user_id)}
