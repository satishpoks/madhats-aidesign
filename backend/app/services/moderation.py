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
    "You are a content-safety filter for a custom-headwear design chat. "
    "The message below is a single turn a customer typed in conversation — it may "
    "be anything: a name, an email address, a phone number, a quantity, a yes/no, "
    "a question, small talk, or a cap design idea.\n\n"
    "Mark it UNSAFE only if it actually contains hate symbols, explicit sexual "
    "content, graphic violence, or clearly illegal content. Ordinary, benign, "
    "empty, or off-topic messages — including personal contact details such as "
    "names, emails and phone numbers — are SAFE. Never flag a message merely "
    "because it is not a design request.\n\n"
    'Message: "{text}"\n\n'
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
