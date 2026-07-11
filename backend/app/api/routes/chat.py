import structlog
from fastapi import APIRouter, HTTPException, Request

from app.api.deps import limiter
from app.config import settings
from app.models.message import ChatRequest, ChatResponse, VerificationPollResponse
from app.services.conversation.orchestrator import (
    SessionNotFound,
    check_verification,
    handle_message,
)
from app.services.moderation import ModerationError, check_text

router = APIRouter(tags=["chat"])
log = structlog.get_logger()


@router.post("/chat/{session_id}", response_model=ChatResponse)
@limiter.limit(settings.rate_limit_str)
async def chat(session_id: str, body: ChatRequest, request: Request) -> ChatResponse:
    try:
        await check_text(body.message)
    except ModerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        result = await handle_message(session_id, body.message)
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
