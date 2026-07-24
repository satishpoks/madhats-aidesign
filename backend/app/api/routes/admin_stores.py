"""Admin store (tenant) management. All routes gated by X-Admin-Secret.

Onboarding a new store: POST /admin/stores -> (auto public_key) -> then
POST /admin/stores/{id}/sync to pull its Shopify catalogue.
"""
from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx, require_super
from app.db import get_supabase
from app.models.store import CreateStoreRequest, StoreResponse, SyncResponse, UpdateStoreRequest
from app.services.branding import validate_brand
from app.services.catalogue_sync import sync_store_catalogue
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import media_url, upload_asset

router = APIRouter(tags=["admin-stores"])
log = structlog.get_logger()


def _gen_public_key(slug: str) -> str:
    return f"mh_pk_{slug}_{secrets.token_hex(6)}"


@router.post("/admin/stores", response_model=StoreResponse)
async def create_store(body: CreateStoreRequest, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    require_super(ctx)
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
async def list_stores(ctx: AdminContext = Depends(require_admin_ctx)) -> list[dict]:
    sb = get_supabase()
    res = sb.table("stores").select(
        "id, slug, name, public_key, shopify_domain, status, created_at"
    ).order("created_at").execute()
    rows = res.data or []
    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        rows = [r for r in rows if r["id"] in allowed]
    return rows


@router.post("/admin/stores/{store_id}/sync", response_model=SyncResponse)
async def sync_store(store_id: str, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    assert_store_allowed(ctx, store_id)
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
async def get_store_admin(
    store_id: str, request: Request, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    row = res.data[0]
    brand = row.get("brand") or {}
    logo_path = brand.get("logo_url")
    if logo_path:
        # Display-only: convert the raw storage path to a signed /media proxy
        # URL. Never mutate the DB row or what PATCH later receives — the
        # frontend strips logo_url before PATCHing, so this is safe.
        row = {**row, "brand": {**brand, "logo_url": media_url(logo_path, str(request.base_url))}}
    return row


@router.patch("/admin/stores/{store_id}")
async def update_store(
    store_id: str, body: UpdateStoreRequest, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    existing_res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not existing_res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    existing = existing_res.data[0]

    patch: dict = {}
    if body.brand is not None:
        try:
            validated = validate_brand(body.brand)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        existing_brand = dict(existing.get("brand") or {})
        # Merge, don't replace: keys the client omits (esp. logo_url, and the
        # internal watermark_asset_url) must survive the save. The frontend
        # BrandingView intentionally strips logo_url from the PATCH body and
        # relies on the backend to preserve it.
        patch["brand"] = {**existing_brand, **validated}
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = sb.table("stores").update(patch).eq("id", store_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    log.info("store_branding_updated", store_id=store_id)  # no PII
    return res.data[0]


@router.post("/admin/stores/{store_id}/logo")
async def upload_store_logo(
    store_id: str,
    request: Request,
    file: UploadFile = File(...),
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    store = res.data[0]
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "logo", mime)
    brand = dict(store.get("brand") or {})
    brand["logo_url"] = path
    sb.table("stores").update({"brand": brand}).eq("id", store_id).execute()
    log.info("store_logo_uploaded", store_id=store_id)  # no PII
    return {"logo_url": media_url(path, str(request.base_url))}
