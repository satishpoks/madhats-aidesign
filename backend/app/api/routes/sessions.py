from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_store
from app.db import get_supabase
from app.models.session import (
    ChatMessageOut,
    CreateSessionRequest,
    SessionDetail,
    SessionResponse,
)
from app.services.products import get_product

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionResponse)
async def create_session(
    body: CreateSessionRequest, store: dict = Depends(require_store)
) -> SessionResponse:
    product = get_product(body.product_id, store_id=store["id"])
    if not product:
        raise HTTPException(status_code=404, detail="Unknown product_id for this store")

    share_token = secrets.token_urlsafe(16)
    product_ref = {
        "product_id": product["id"],
        "style": product["style"],
        "colour": product["colour"],
        "name": product["name"],
        "reference_image_url": product["reference_image_url"],
    }

    sb = get_supabase()
    res = (
        sb.table("design_sessions")
        .insert(
            {
                "store_id": store["id"],
                "share_token": share_token,
                "state": "greeting",
                "channel": body.channel,
                "entry_path": body.entry_path,
                "product_ref": product_ref,
                "collected": {},
                "status": "draft",
            }
        )
        .execute()
    )
    row = res.data[0]
    return SessionResponse(session_id=row["id"], share_token=share_token, state=row["state"])


@router.get("/sessions/{token}", response_model=SessionDetail)
async def get_session(token: str) -> SessionDetail:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("share_token", token).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]

    msgs = (
        sb.table("chat_messages")
        .select("role, content, state_before, state_after, created_at")
        .eq("session_id", session["id"])
        .order("created_at")
        .execute()
    )
    messages = [ChatMessageOut(**m) for m in (msgs.data or [])]

    return SessionDetail(
        session_id=session["id"],
        share_token=session["share_token"],
        state=session["state"],
        channel=session["channel"],
        entry_path=session["entry_path"],
        product_ref=session.get("product_ref"),
        collected=session.get("collected") or {},
        status=session["status"],
        messages=messages,
    )
