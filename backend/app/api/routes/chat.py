import structlog
from fastapi import APIRouter, HTTPException, Request

from app.api.deps import limiter
from app.config import settings
from app.db import get_supabase
from app.models.message import (
    ChatRequest,
    ChatResponse,
    RegenerationPollResponse,
    VerificationPollResponse,
)
from app.services.conversation.orchestrator import (
    SessionNotFound,
    advance_after_generation,
    advance_after_regeneration,
    check_verification,
    handle_message,
)
from app.services.conversation.orchestrator_v2 import (
    handle_message as handle_message_v2,
)
from app.services.moderation import ModerationError, check_text

router = APIRouter(tags=["chat"])
log = structlog.get_logger()


def _persist_live_canvas_design(session_id: str, canvas_design: dict | None) -> None:
    """Adopt the frontend's live design as the base for a canvas refine turn.

    `_apply_canvas_edit` resolves ops against the persisted `canvas_design`,
    which is only written at finalize — so without this, an iterate-again loop
    ("Not quite" -> "up more") recomputes every nudge from the ORIGINAL geometry
    and the second relative nudge no-ops. Also makes a mid-confirm reload
    rehydrate the EDITED canvas. Scoped hard to DESCRIBE_CHANGES on a canvas
    session so a stray/hostile design on any other turn can't overwrite the work.
    """
    if not isinstance(canvas_design, dict) or "faces" not in canvas_design:
        return
    sb = get_supabase()
    res = (sb.table("design_sessions").select("state, flow_mode, collected")
           .eq("id", session_id).limit(1).execute())
    if not res.data:
        return
    row = res.data[0]
    flow = row.get("flow_mode") or (row.get("collected") or {}).get("flow_mode")
    if row.get("state") == "describe_changes" and flow == "canvas":
        (sb.table("design_sessions").update({"canvas_design": canvas_design})
         .eq("id", session_id).execute())


async def _dispatch(session_id: str, message: str) -> dict:
    """Route a chat turn to v2 (canvas sessions, flag on) or v1 (everything else)."""
    if settings.canvas_orchestrator_v2:
        sb = get_supabase()
        res = sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
        if res.data:
            collected = res.data[0].get("collected") or {}
            if collected.get("flow_mode") == "canvas":
                return await handle_message_v2(session_id, message)
    return await handle_message(session_id, message)


@router.post("/chat/{session_id}", response_model=ChatResponse)
@limiter.limit(settings.rate_limit_str)
async def chat(session_id: str, body: ChatRequest, request: Request) -> ChatResponse:
    try:
        await check_text(body.message)
    except ModerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _persist_live_canvas_design(session_id, body.canvas_design)
    try:
        result = await _dispatch(session_id, body.message)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    return ChatResponse(**result)


@router.get("/chat/{session_id}/verification", response_model=VerificationPollResponse)
async def poll_verification(session_id: str) -> VerificationPollResponse:
    """Cheap poll used by the chat while it waits at VERIFY_EMAIL.

    Not rate-limited (the client polls every few seconds) — it only reads and,
    at most once, advances the conversation past verification.
    """
    try:
        result = await check_verification(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return VerificationPollResponse(**result)


@router.get("/chat/{session_id}/regeneration", response_model=RegenerationPollResponse)
async def poll_regeneration(session_id: str) -> RegenerationPollResponse:
    """One-shot advance used by the chat right after a regeneration settles.

    The frontend calls this exactly once, after startRegeneration(sessionId)
    resolves (success or failure) — not a timed poll — so there's no
    completion race. Advances REGENERATING -> OFFER_REFINE; a no-op if the
    session isn't at REGENERATING.
    """
    try:
        result = await advance_after_regeneration(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return RegenerationPollResponse(**result)


@router.get("/chat/{session_id}/generation-advance", response_model=RegenerationPollResponse)
async def poll_generation_advance(session_id: str) -> RegenerationPollResponse:
    """One-shot advance used by the chat right after preview generation settles.

    Called exactly once by the frontend after startGeneration(sessionId) resolves
    (success or failure). Advances GENERATING -> VERIFY_EMAIL (or collapses to
    OFFER_REFINE if already verified, or -> ASK_EMAIL if no email was captured);
    a no-op if the session isn't at GENERATING.
    """
    try:
        result = await advance_after_generation(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return RegenerationPollResponse(**result)
