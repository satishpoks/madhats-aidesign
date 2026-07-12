from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_store
from app.db import get_supabase
from app.models.session import (
    ChatMessageOut,
    CreateBlankSessionRequest,
    CreateSessionRequest,
    SessionDetail,
    SessionResponse,
)
from app.services import hat_types as hat_types_service
from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState
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
        "view_images": product.get("view_images") or {},
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


@router.post("/sessions/blank", response_model=SessionResponse)
async def create_blank_session(
    body: CreateBlankSessionRequest, store: dict = Depends(require_store)
) -> SessionResponse:
    hat = hat_types_service.get_hat_type(body.hat_type_id, store_id=store["id"])
    if not hat:
        raise HTTPException(status_code=404, detail="Unknown hat_type_id for this store")

    # Colour is optional now — the landing picker only chooses the hat type; the
    # customer picks the colour in chat (after quantity). Only seed hat_colour
    # when a colour was actually supplied.
    colour = None
    if body.colour:
        colour = body.colour if isinstance(body.colour, dict) else {"name": body.colour, "hex": body.colour}
    blanks = hat.get("blank_view_images") or {}
    share_token = secrets.token_urlsafe(16)
    product_ref = {
        "product_id": hat["id"],
        "style": hat.get("style", ""),
        "colour": (colour.get("name") or colour.get("hex")) if colour else "",
        "name": hat["name"],
        "reference_image_url": blanks.get("front", ""),
        "view_images": blanks,
    }
    collected = {
        "flow_mode": "blank",
        "hat_type_id": hat["id"],
        # The hat type's colourways, offered as chips at ASK_HAT_COLOUR.
        "hat_colours": hat.get("colours") or [],
        "placement_zones": hat.get("placement_zones") or [],
        "decoration_types": hat.get("decoration_types") or [],
    }
    if colour:
        collected["hat_colour"] = colour
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
                "flow_mode": "blank",
                "product_ref": product_ref,
                "collected": collected,
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

    collected = session.get("collected") or {}
    data = _public_data(ConversationState(session["state"]), collected)

    return SessionDetail(
        session_id=session["id"],
        share_token=session["share_token"],
        state=session["state"],
        channel=session["channel"],
        entry_path=session["entry_path"],
        product_ref=session.get("product_ref"),
        collected=collected,
        status=session["status"],
        messages=messages,
        data=data,
    )
