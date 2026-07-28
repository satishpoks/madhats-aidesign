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
    check_verification as check_verification_v2,
    handle_back as handle_back_v2,
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
    rehydrate the EDITED canvas. Scoped hard to DESCRIBE_CHANGES and
    REWORK_CANVAS (the v2 unlock-all rework turn) on a canvas session so a
    stray/hostile design on any other turn can't overwrite the work.
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
    if row.get("state") in ("describe_changes", "rework_canvas") and flow == "canvas":
        (sb.table("design_sessions").update({"canvas_design": canvas_design})
         .eq("id", session_id).execute())


def _is_v2_canvas(session_id: str) -> bool:
    """Whether this session is routed by v2 — the flag on AND a canvas flow."""
    if not settings.canvas_orchestrator_v2:
        return False
    sb = get_supabase()
    res = sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
    if not res.data:
        return False
    return ((res.data[0].get("collected") or {}).get("flow_mode") == "canvas")


async def _dispatch(session_id: str, message: str,
                    canvas_design: dict | None = None) -> dict:
    """Route a chat turn to v2 (canvas sessions, flag on) or v1 (everything else).

    `canvas_design` reaches v2 ONLY. v1's handle_message takes no blob and its
    signature is deliberately untouched — v1 is the retained backup path.
    """
    if _is_v2_canvas(session_id):
        return await handle_message_v2(session_id, message, canvas_design)
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
        result = await _dispatch(session_id, body.message, body.canvas_design)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc

    return ChatResponse(**result)


@router.post("/chat/{session_id}/back", response_model=ChatResponse)
async def chat_back(session_id: str) -> ChatResponse:
    try:
        result = await handle_back_v2(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return ChatResponse(**result)


@router.get("/chat/{session_id}/verification", response_model=VerificationPollResponse)
async def poll_verification(session_id: str) -> VerificationPollResponse:
    """Cheap poll used by the chat while it waits for the emailed link.

    Not rate-limited (the client polls every few seconds) — it only reads and,
    at most once, advances the conversation past verification.

    Dispatched like a chat turn: a v2 canvas session waits MID-design at
    AWAIT_EMAIL_VERIFY, which v1 knows nothing about. v2's own check delegates
    any other state back to v1, so the shared post-generation VERIFY_EMAIL wait
    still works for canvas sessions that reach it.
    """
    try:
        if _is_v2_canvas(session_id):
            result = await check_verification_v2(session_id)
        else:
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
