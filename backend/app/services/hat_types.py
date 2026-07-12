"""Hat-type catalogue access (blank-hat design flow). supabase-py only."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import get_supabase

_VIEWS = ("front", "back", "left", "right")


def all_angles_present(row: dict) -> bool:
    imgs = row.get("blank_view_images") or {}
    return all(imgs.get(v) for v in _VIEWS)


def create_hat_type(store_id: str, body: dict) -> dict:
    row = {**body, "store_id": store_id}
    res = get_supabase().table("hat_types").insert(row).execute()
    return res.data[0]


def list_hat_types(store_id: str, active_only: bool = False) -> list[dict]:
    q = get_supabase().table("hat_types").select("*").eq("store_id", store_id)
    if active_only:
        q = q.eq("active", True)
    return q.order("name").execute().data or []


def get_hat_type(hat_type_id: str, store_id: str | None = None) -> dict | None:
    q = get_supabase().table("hat_types").select("*").eq("id", hat_type_id)
    if store_id:
        q = q.eq("store_id", store_id)
    res = q.limit(1).execute()
    return res.data[0] if res.data else None


def update_hat_type(hat_type_id: str, patch: dict) -> dict | None:
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    res = get_supabase().table("hat_types").update(patch).eq("id", hat_type_id).execute()
    return res.data[0] if res.data else None


def delete_hat_type(hat_type_id: str) -> None:
    get_supabase().table("hat_types").delete().eq("id", hat_type_id).execute()


def set_angle(hat_type_id: str, view: str, path: str) -> dict:
    row = get_hat_type(hat_type_id)
    if row is None:
        raise ValueError("hat type not found")
    imgs = dict(row.get("blank_view_images") or {})
    imgs[view] = path
    return update_hat_type(hat_type_id, {"blank_view_images": imgs})
