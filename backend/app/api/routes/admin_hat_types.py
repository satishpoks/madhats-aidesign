"""Admin blank-hat catalogue management. Gated by X-Admin-Secret."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api.deps import require_admin, require_store
from app.models.hat_type import CreateHatTypeRequest, HatTypeAdmin, UpdateHatTypeRequest
from app.services import hat_types as svc
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import media_url, upload_asset

router = APIRouter(tags=["admin-hat-types"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()

_VIEWS = {"front", "back", "left", "right"}


def _with_view_images(row: dict, base_url: str) -> dict:
    imgs = row.get("blank_view_images") or {}
    row["view_images"] = {v: media_url(p, base_url) for v, p in imgs.items() if p}
    return row


@router.post("/admin/hat-types", response_model=HatTypeAdmin)
async def create_hat_type(body: CreateHatTypeRequest, store: dict = Depends(require_store)) -> dict:
    payload = body.model_dump()
    payload["colours"] = [c if isinstance(c, dict) else c.model_dump() for c in payload.get("colours", [])]
    return svc.create_hat_type(store["id"], payload)


@router.get("/admin/hat-types", response_model=list[HatTypeAdmin])
async def list_hat_types(request: Request, store: dict = Depends(require_store)) -> list[dict]:
    base = str(request.base_url)
    return [_with_view_images(row, base) for row in svc.list_hat_types(store["id"])]


@router.patch("/admin/hat-types/{hat_type_id}", response_model=HatTypeAdmin)
async def update_hat_type(
    hat_type_id: str, body: UpdateHatTypeRequest, store: dict = Depends(require_store)
) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "colours" in patch:
        patch["colours"] = [c if isinstance(c, dict) else dict(c) for c in patch["colours"]]
    row = svc.get_hat_type(hat_type_id, store_id=store["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    if patch.get("active") and not svc.all_angles_present(row):
        raise HTTPException(status_code=400, detail="All four angle images required before activating")
    updated = svc.update_hat_type(hat_type_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    return updated


@router.delete("/admin/hat-types/{hat_type_id}")
async def delete_hat_type(hat_type_id: str, store: dict = Depends(require_store)) -> dict:
    row = svc.get_hat_type(hat_type_id, store_id=store["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    svc.delete_hat_type(hat_type_id)
    return {"deleted": True}


@router.post("/admin/hat-types/{hat_type_id}/angle/{view}")
async def upload_angle(
    request: Request,
    hat_type_id: str,
    view: str,
    file: UploadFile = File(...),
    store: dict = Depends(require_store),
) -> dict:
    row = svc.get_hat_type(hat_type_id, store_id=store["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    if view not in _VIEWS:
        raise HTTPException(status_code=400, detail="view must be front|back|left|right")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "blank", mime)
    updated = svc.set_angle(hat_type_id, view, path)
    imgs = updated["blank_view_images"]
    base = str(request.base_url)
    return {
        "blank_view_images": imgs,
        "view_images": {v: media_url(p, base) for v, p in imgs.items() if p},
    }
