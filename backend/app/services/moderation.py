"""Input moderation — runs before every model call (text prompt + uploaded image).

Prototype implementation: a lightweight Haiku safety check on text; image check is
a stubbed pass that still gates the call site. Raises ModerationError on failure.
"""
from __future__ import annotations

import structlog

from app.config import settings
from app.services.conversation import intent_extractor as ie

log = structlog.get_logger()

_MODERATION_PROMPT = (
    "You are a content-safety filter for a custom-headwear design tool. "
    "Decide if the following design request is safe (no hate symbols, explicit "
    "sexual content, violence, or illegal content).\n\n"
    'Request: "{text}"\n\n'
    'Respond with ONLY a JSON object: {{"safe": true}} or {{"safe": false, "reason": "..."}}'
)


class ModerationError(Exception):
    pass


async def check_text(text: str) -> None:
    if not text or not text.strip():
        return
    if not settings.anthropic_api_key:
        return
    try:
        raw = await ie._complete(  # noqa: SLF001 — internal helper reuse
            _MODERATION_PROMPT.format(text=text[:2000]),
            system="You are a strict but fair content-safety filter.",
            max_tokens=80,
        )
        data = ie._parse_json(raw)  # noqa: SLF001
    except Exception:  # noqa: BLE001 — never let moderation infra crash a request silently
        log.warning("moderation_text_check_errored")
        return
    if data.get("safe") is False:
        log.info("moderation_blocked_text")
        raise ModerationError(data.get("reason", "Request flagged by content safety filter."))


async def check_image(image_bytes: bytes) -> None:
    # Prototype: structural pass-through. A real vision moderation call slots in here.
    if not image_bytes:
        raise ModerationError("Empty image.")
    return
