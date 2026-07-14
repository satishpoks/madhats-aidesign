"""Graphics library access (clipart + company graphics). supabase-py only."""
from __future__ import annotations

from app.db import get_supabase


def list_graphics(store_id: str, category: str | None = None, active_only: bool = False) -> list[dict]:
    q = get_supabase().table("graphics").select("*").eq("store_id", store_id)
    if category:
        q = q.eq("category", category)
    if active_only:
        q = q.eq("active", True)
    return q.order("sort_order").order("created_at").execute().data or []


def get_graphic(graphic_id: str, store_id: str | None = None) -> dict | None:
    q = get_supabase().table("graphics").select("*").eq("id", graphic_id)
    if store_id:
        q = q.eq("store_id", store_id)
    res = q.limit(1).execute()
    return res.data[0] if res.data else None


def create_graphic(store_id: str, category: str, name: str, storage_path: str) -> dict:
    row = {"store_id": store_id, "category": category, "name": name, "storage_path": storage_path}
    return get_supabase().table("graphics").insert(row).execute().data[0]


def delete_graphic(graphic_id: str) -> None:
    get_supabase().table("graphics").delete().eq("id", graphic_id).execute()
