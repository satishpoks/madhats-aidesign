"""admin_users + admin_user_stores data access.

The email lookup is case-insensitive (stored lowercased). Store assignments
live in the join table; `allowed_store_ids` is read fresh per admin request so
re-assignment/disable takes effect immediately.
"""
from __future__ import annotations

from app.db import get_supabase
from app.services.admin_auth import hash_password


def get_by_email(email: str) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("admin_users").select("*").eq("email", email.strip().lower())
        .limit(1).execute()
    )
    return res.data[0] if res.data else None


def get_by_id(user_id: str) -> dict | None:
    sb = get_supabase()
    res = sb.table("admin_users").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def allowed_store_ids(user_id: str) -> set[str]:
    sb = get_supabase()
    res = (
        sb.table("admin_user_stores").select("store_id")
        .eq("admin_user_id", user_id).execute()
    )
    return {r["store_id"] for r in (res.data or [])}


def _set_stores(user_id: str, store_ids: list[str]) -> None:
    sb = get_supabase()
    sb.table("admin_user_stores").delete().eq("admin_user_id", user_id).execute()
    for sid in store_ids:
        sb.table("admin_user_stores").insert(
            {"admin_user_id": user_id, "store_id": sid}
        ).execute()


def _stores_for(user_id: str) -> list[dict]:
    ids = allowed_store_ids(user_id)
    if not ids:
        return []
    sb = get_supabase()
    res = sb.table("stores").select("id, name").execute()
    return [{"id": r["id"], "name": r["name"]} for r in (res.data or []) if r["id"] in ids]


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "is_super": row.get("is_super", False),
        "status": row.get("status", "active"),
        "stores": _stores_for(row["id"]),
    }


def list_users() -> list[dict]:
    sb = get_supabase()
    res = sb.table("admin_users").select("*").order("created_at").execute()
    return [_public(r) for r in (res.data or [])]


def create_user(email: str, password: str, is_super: bool, store_ids: list[str]) -> dict:
    sb = get_supabase()
    row = {
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "is_super": is_super,
        "status": "active",
    }
    res = sb.table("admin_users").insert(row).execute()
    created = res.data[0]
    if store_ids:
        _set_stores(created["id"], store_ids)
    return _public(created)


def update_user(
    user_id: str,
    *,
    is_super: bool | None = None,
    status: str | None = None,
    password: str | None = None,
    store_ids: list[str] | None = None,
) -> dict:
    sb = get_supabase()
    patch: dict = {}
    if is_super is not None:
        patch["is_super"] = is_super
    if status is not None:
        patch["status"] = status
    if password is not None:
        patch["password_hash"] = hash_password(password)
    if patch:
        sb.table("admin_users").update(patch).eq("id", user_id).execute()
    if store_ids is not None:
        _set_stores(user_id, store_ids)
    return _public(get_by_id(user_id) or {"id": user_id, "email": "", "is_super": False, "status": "active"})


def delete_user(user_id: str) -> bool:
    sb = get_supabase()
    res = sb.table("admin_users").delete().eq("id", user_id).execute()
    return bool(res.data)
