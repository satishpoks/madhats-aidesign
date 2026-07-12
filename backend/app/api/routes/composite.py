"""On-screen composite preview for the blank-hat flow (POST /composite/{id})."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.db import get_supabase
from app.services import colours
from app.services import composite as composite_svc
from app.storage import media_url

router = APIRouter(tags=["composite"])
log = structlog.get_logger()


@router.post("/composite/{session_id}")
async def make_composite(session_id: str, request: Request) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]
    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}
    view_paths = product_ref.get("view_images") or {}
    # Resolve the tint colour: an explicit swatch hex, else a typed colour name
    # ("blue") mapped to a real hex, else neutral grey — so a typed name never
    # renders as a grey block.
    colour_hex = colours.resolve_hex(collected.get("hat_colour"))

    try:
        paths = composite_svc.render_composite_views(
            view_paths, colour_hex, collected.get("elements") or []
        )
    except Exception as exc:  # noqa: BLE001 — never dead-end the chat
        log.warning("composite_render_failed", session_id=session_id, error_type=type(exc).__name__)
        return {"views": {}, "error": "composite_failed"}

    collected["composite_views"] = paths
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()

    base = str(request.base_url)
    return {"views": {v: media_url(p, base) for v, p in paths.items()}}
