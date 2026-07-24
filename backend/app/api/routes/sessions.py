from __future__ import annotations

import secrets
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from app.api.deps import require_store
from app.config import settings
from app.db import get_supabase
from app.services import canvas_describe, prompt_builder
from app.storage import generate_signed_url, media_url, upload_asset
from app.models.canvas import CanvasFinalizeRequest, CreateCanvasSessionRequest
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
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime

router = APIRouter(tags=["sessions"])

_VALID_FACES = {"front", "back", "left", "right"}


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


@router.post("/sessions/canvas", response_model=SessionResponse)
async def create_canvas_session(
    body: CreateCanvasSessionRequest, store: dict = Depends(require_store)
) -> SessionResponse:
    collected: dict = {"flow_mode": "canvas"}
    if body.product_id:
        product = get_product(body.product_id, store_id=store["id"])
        if not product:
            raise HTTPException(status_code=404, detail="Unknown product_id for this store")
        product_ref = {
            "product_id": product["id"], "style": product["style"], "colour": product["colour"],
            "name": product["name"], "reference_image_url": product["reference_image_url"],
            "view_images": product.get("view_images") or {},
        }
    elif body.hat_type_id:
        hat = hat_types_service.get_hat_type(body.hat_type_id, store_id=store["id"])
        if not hat:
            raise HTTPException(status_code=404, detail="Unknown hat_type_id for this store")
        colour = None
        if body.colour:
            colour = body.colour if isinstance(body.colour, dict) else {"name": body.colour, "hex": body.colour}
        blanks = hat.get("blank_view_images") or {}
        product_ref = {
            "product_id": hat["id"], "style": hat.get("style", ""),
            "colour": (colour.get("name") or colour.get("hex")) if colour else "",
            "name": hat["name"], "reference_image_url": blanks.get("front", ""),
            "view_images": blanks,
        }
        collected["hat_type_id"] = hat["id"]
        collected["canvas_blank"] = True
        if colour:
            collected["hat_colour"] = colour
    else:
        raise HTTPException(status_code=400, detail="product_id or hat_type_id required")

    share_token = secrets.token_urlsafe(16)
    sb = get_supabase()
    res = sb.table("design_sessions").insert({
        "store_id": store["id"], "share_token": share_token, "state": "greeting",
        "channel": body.channel, "entry_path": body.entry_path, "flow_mode": "canvas",
        "product_ref": product_ref, "collected": collected, "status": "draft",
    }).execute()
    row = res.data[0]
    return SessionResponse(session_id=row["id"], share_token=share_token, state=row["state"])


@router.post("/sessions/{session_id}/canvas-layouts")
async def upload_canvas_layouts(
    session_id: str,
    faces: list[str] = Form(...),
    files: list[UploadFile] = File(...),
    kind: str = Form("layout"),
    store: dict = Depends(require_store),
) -> dict:
    # "layout" = decorations-only guide the image model consumes (canvas_layouts);
    # "preview" = full WYSIWYG canvas export emailed to the customer as their own
    # design (canvas_previews). Same validation + storage, different collected slot.
    slot = "canvas_previews" if kind == "preview" else "canvas_layouts"
    sb = get_supabase()
    sess = sb.table("design_sessions").select("id, collected").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    if len(faces) != len(files):
        raise HTTPException(status_code=400, detail="faces/files count mismatch")
    layouts: dict[str, str] = {}
    signed: dict[str, str] = {}
    for face, upload in zip(faces, files):
        if face not in _VALID_FACES:
            raise HTTPException(status_code=400, detail=f"invalid face: {face}")
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"Empty file for {face}")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
        mime = sniff_image_mime(data)
        if mime is None:
            raise HTTPException(status_code=415, detail="Unsupported file type")
        path = upload_asset(data, f"canvas_{face}_{uuid.uuid4().hex}.png", mime)
        layouts[face] = path
        signed[face] = generate_signed_url(path)
    collected = (sess.data[0].get("collected") or {})
    collected[slot] = {**(collected.get(slot) or {}), **layouts}
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()
    return {"views": signed}


@router.post("/sessions/{session_id}/canvas-finalize")
async def finalize_canvas(
    session_id: str, body: CanvasFinalizeRequest, store: dict = Depends(require_store)
) -> dict:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sess.data[0]
    collected = session.get("collected") or {}

    elements, description = canvas_describe.canvas_to_elements(body.canvas_design)
    collected["elements"] = elements
    collected["design_description"] = {"summary": description} if description else None
    collected["flow_mode"] = "canvas"
    if body.name:
        collected["name"] = body.name

    colourway = (body.canvas_design or {}).get("colourway")
    if isinstance(colourway, dict) and (colourway.get("name") or colourway.get("hex")):
        collected["hat_colour"] = colourway

    # The design is done — advance the chat from CANVAS_DESIGN into the outro
    # (decoration → notes → generate). Name + email were captured in chat during
    # the intro, so no lead capture here.
    collected["canvas_finalized"] = True

    from app.services import decoration_types as deco_svc
    from app.services.conversation import intent_extractor as ie
    from app.services.conversation.state_machine import ConversationState as S
    from app.services.conversation.state_machine import progress as sm_progress

    persona = store.get("persona_name") or settings.chatbot_persona_name

    # A REWORK ("Rework on the canvas" from the refine step) skips the outro
    # questions (decoration/notes already answered) and re-renders straight away
    # via the regeneration (edit) pipeline. refine_views is cleared so every
    # decorated face re-renders from the updated canvas.
    if collected.get("reworking"):
        collected.pop("reworking", None)
        collected["refine_views"] = []
        new_state = S.REGENERATING
        reply = await ie.generate_reply(new_state.value, collected, persona)
        sb.table("design_sessions").update(
            {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
        ).eq("id", session_id).execute()
        return {
            "reply": reply,
            "state": new_state.value,
            "data": {"trigger_regeneration": True, "progress": sm_progress(new_state, collected)},
        }

    # v2 step-by-step orchestrator: the design phase already happened in chat and
    # the customer explicitly requested a quote (REQUEST_QUOTE) before this. This
    # is a QUOTE-GATED flow: we do NOT AI-render or email the design to the
    # customer. Persist the canvas so the render can be produced on-demand from
    # the admin later (C4), surface the tracking reference on-screen, and end the
    # customer journey at the reference confirmation. Sales is notified + the
    # customer emailed the reference via the verification-track converge (C2/C3).
    if settings.canvas_orchestrator_v2:
        from app.services.conversation.state_machine_v2 import progress_v2

        reference = collected.get("reference_code")
        new_state = S.QUOTE_REQUESTED
        if reference:
            reply = (
                f"All done — your request is in! Your reference is {reference}. "
                "Our team will be in touch with a quote soon. We've also emailed "
                "it to you once you confirm your address."
            )
        else:
            reply = (
                "All done — your request is in! Our team will be in touch with a "
                "quote soon."
            )
        sb.table("design_sessions").update(
            {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
        ).eq("id", session_id).execute()
        return {
            "reply": reply,
            "state": new_state.value,
            "data": {"reference_code": reference, "progress": progress_v2(new_state, collected)},
        }

    active = deco_svc.list_types(store["id"], active_only=True)
    collected["decoration_options"] = [t["name"] for t in active]

    new_state = S.ASK_DECORATION
    reply = await ie.generate_reply(new_state.value, collected, persona)

    sb.table("design_sessions").update(
        {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
    ).eq("id", session_id).execute()

    return {
        "reply": reply,
        "state": new_state.value,
        "data": {
            "options": collected["decoration_options"],
            "multiselect": True,
            "selected": [],
            "progress": sm_progress(new_state, collected),
        },
    }


def _displayable_product_ref(product_ref: dict | None, base_url: str) -> dict | None:
    """Rewrite a persisted product_ref's image paths to client-fetchable URLs.

    Blank-hat sessions persist their reference/view images as RAW storage paths
    (``uploads/…``) which a browser can't load directly — so a resumed blank
    session lost its hat angles and colour overlay. Proxy them through
    ``/media/{token}`` (external http URLs pass through unchanged) so resume shows
    the chosen hat's four angles exactly as the live session did."""
    if not product_ref:
        return product_ref
    ref = dict(product_ref)
    imgs = ref.get("view_images") or {}
    ref["view_images"] = {v: (media_url(p, base_url) or p) for v, p in imgs.items() if p}
    reference = ref.get("reference_image_url")
    if reference:
        ref["reference_image_url"] = media_url(reference, base_url) or reference
    return ref


@router.get("/sessions/{token}", response_model=SessionDetail)
async def get_session(token: str, request: Request) -> SessionDetail:
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
        product_ref=_displayable_product_ref(session.get("product_ref"), str(request.base_url)),
        collected=collected,
        status=session["status"],
        messages=messages,
        data=data,
        designs=_released_designs(sb, session["id"], collected),
        canvas_design=session.get("canvas_design"),
    )


def _sign_design(path: str | None) -> str:
    if not path:
        return ""
    return path if path.startswith("http") else generate_signed_url(path)


def _released_designs(sb, session_id: str, collected: dict) -> list[str]:
    """Signed design URLs for the latest completed generation, front→back→…

    Gated on email verification (same reveal rule as the chat + email); returns
    []
    until then so a resumed session never leaks the design early. Multi-view
    designs return every rendered angle; single-view fall back to the hero.
    """
    if not collected.get("email_verified"):
        return []
    gen = (
        sb.table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not gen.data:
        return []
    row = gen.data[0]
    raw_views = row.get("view_images") or {}
    urls: list[str] = []
    for view in prompt_builder.RENDER_VIEW_ORDER:
        entry = raw_views.get(view)
        if entry:
            signed = _sign_design(entry.get("watermarked_url") or entry.get("image_url"))
            if signed:
                urls.append(signed)
    if not urls:
        signed = _sign_design(row.get("watermarked_url") or row.get("image_url"))
        if signed:
            urls.append(signed)
    return urls
