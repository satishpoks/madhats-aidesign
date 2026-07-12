from __future__ import annotations

import hashlib
import uuid

import structlog
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.db import get_supabase
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import generate_signed_url, upload_asset

router = APIRouter(tags=["uploads"])
log = structlog.get_logger()


class PinRequest(BaseModel):
    view: str
    x_pct: float
    y_pct: float
    comment: str


@router.post("/uploads/logo/{session_id}")
async def upload_logo(session_id: str, file: UploadFile = File(...)) -> dict:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")

    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")

    sb = get_supabase()
    sess = sb.table("design_sessions").select("id, collected").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")

    asset_hash = hashlib.sha256(data).hexdigest()
    path = upload_asset(data, file.filename or f"{uuid.uuid4().hex}", mime)

    collected = sess.data[0].get("collected") or {}
    collected["uploaded_asset_path"] = path
    collected["asset_hash"] = asset_hash
    collected["has_logo"] = True
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()

    return {"asset_url": generate_signed_url(path), "asset_hash": asset_hash}


@router.post("/uploads/pin/{session_id}")
async def add_pin(session_id: str, body: PinRequest) -> dict:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("id, collected").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")

    collected = sess.data[0].get("collected") or {}
    pins = collected.get("pin_annotations") or []
    pin_id = uuid.uuid4().hex
    pins.append(
        {
            "pin_id": pin_id,
            "view": body.view,
            "x_pct": body.x_pct,
            "y_pct": body.y_pct,
            "comment": body.comment,
        }
    )
    collected["pin_annotations"] = pins
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()

    return {"pin_id": pin_id}
