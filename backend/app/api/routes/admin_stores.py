"""Admin store (tenant) management. All routes gated by X-Admin-Secret.

Onboarding a new store: POST /admin/stores -> (auto public_key) -> then
POST /admin/stores/{id}/sync to pull its Shopify catalogue.
"""
from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.db import get_supabase
from app.models.store import CreateStoreRequest, StoreResponse, SyncResponse, UpdateStoreRequest
from app.services.branding import validate_brand
from app.services.catalogue_sync import sync_store_catalogue

router = APIRouter(tags=["admin-stores"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


def _gen_public_key(slug: str) -> str:
    return f"mh_pk_{slug}_{secrets.token_hex(6)}"


@router.post("/admin/stores", response_model=StoreResponse)
async def create_store(body: CreateStoreRequest) -> dict:
    sb = get_supabase()
    if sb.table("stores").select("id").eq("slug", body.slug).limit(1).execute().data:
        raise HTTPException(status_code=409, detail="slug already exists")

    row = {
        "slug": body.slug,
        "name": body.name,
        "public_key": _gen_public_key(body.slug),
        "shopify_domain": body.shopify_domain,
        "allowed_origins": body.allowed_origins,
        "persona_name": body.persona_name,
        "greeting_template": body.greeting_template,
        "sales_notification_email": body.sales_notification_email,
        "brand": body.brand,
        "status": "active",
    }
    res = sb.table("stores").insert(row).execute()
    log.info("store_created", slug=body.slug)
    return res.data[0]


@router.get("/admin/stores")
async def list_stores() -> list[dict]:
    sb = get_supabase()
    res = sb.table("stores").select(
        "id, slug, name, public_key, shopify_domain, status, created_at"
    ).order("created_at").execute()
    return res.data or []


@router.post("/admin/stores/{store_id}/sync", response_model=SyncResponse)
async def sync_store(store_id: str) -> dict:
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    store = res.data[0]
    if not store.get("shopify_domain"):
        raise HTTPException(status_code=400, detail="Store has no shopify_domain to sync from")

    try:
        return await sync_store_catalogue(store)
    except Exception as exc:  # noqa: BLE001
        log.error("catalogue_sync_failed", store_id=store_id, error=str(exc))
        raise HTTPException(status_code=502, detail=f"Catalogue sync failed: {exc}") from exc


@router.get("/admin/stores/{store_id}")
async def get_store_admin(store_id: str) -> dict:
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    return res.data[0]


@router.patch("/admin/stores/{store_id}")
async def update_store(store_id: str, body: UpdateStoreRequest) -> dict:
    sb = get_supabase()
    patch: dict = {}
    if body.brand is not None:
        try:
            patch["brand"] = validate_brand(body.brand)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = sb.table("stores").update(patch).eq("id", store_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    log.info("store_branding_updated", store_id=store_id)  # no PII
    return res.data[0]
