"""Admin graphics-library management (clipart + company). Gated by X-Admin-Secret."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.deps import AdminContext, assert_store_allowed, require_admin, require_admin_ctx, require_store
from app.models.graphics import GRAPHIC_CATEGORIES, GraphicAdmin
from app.services import graphics as svc
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import media_url, upload_asset

router = APIRouter(tags=["admin-graphics"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


def _to_admin(row: dict, base_url: str) -> dict:
    return {
        "id": row["id"],
        "category": row["category"],
        "name": row.get("name") or "",
        "active": bool(row.get("active", True)),
        "sort_order": row.get("sort_order", 0),
        "url": media_url(row["storage_path"], base_url) or "",
    }


@router.get("/admin/graphics", response_model=list[GraphicAdmin])
async def list_graphics(
    request: Request,
    category: str | None = None,
    store: dict = Depends(require_store),
    ctx: AdminContext = Depends(require_admin_ctx),
) -> list[dict]:
    assert_store_allowed(ctx, store["id"])
    cat = category if category in GRAPHIC_CATEGORIES else None
    base = str(request.base_url)
    return [_to_admin(row, base) for row in svc.list_graphics(store["id"], category=cat)]


@router.post("/admin/graphics", response_model=GraphicAdmin)
async def create_graphic(
    request: Request,
    category: str = Form(...),
    name: str = Form(""),
    file: UploadFile = File(...),
    store: dict = Depends(require_store),
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    assert_store_allowed(ctx, store["id"])
    if category not in GRAPHIC_CATEGORIES:
        raise HTTPException(status_code=400, detail="category must be clipart|company")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "graphic", mime)
    row = svc.create_graphic(store["id"], category, name.strip(), path)
    log.info("graphic_created", store_id=store["id"], category=category)  # no PII
    return _to_admin(row, str(request.base_url))


@router.delete("/admin/graphics/{graphic_id}")
async def delete_graphic(
    graphic_id: str,
    store: dict = Depends(require_store),
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    assert_store_allowed(ctx, store["id"])
    row = svc.get_graphic(graphic_id, store_id=store["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Graphic not found")
    svc.delete_graphic(graphic_id)
    return {"deleted": True}
