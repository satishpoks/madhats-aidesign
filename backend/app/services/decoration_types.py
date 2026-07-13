"""Decoration-types access (admin-managed, per store). supabase-py only."""
from __future__ import annotations

from app.db import get_supabase


def list_types(store_id: str, active_only: bool = False) -> list[dict]:
    q = get_supabase().table("decoration_types").select("*").eq("store_id", store_id)
    if active_only:
        q = q.eq("active", True)
    return q.order("sort_order").order("created_at").execute().data or []


def create_type(store_id: str, name: str) -> dict:
    row = {"store_id": store_id, "name": name}
    return get_supabase().table("decoration_types").insert(row).execute().data[0]


def delete_type(type_id: str, store_id: str) -> None:
    get_supabase().table("decoration_types").delete().eq("id", type_id).eq("store_id", store_id).execute()
