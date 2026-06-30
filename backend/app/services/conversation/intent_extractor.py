"""All Claude Haiku calls live here. Every prompt comes from app.prompts.

Haiku is used only to interpret freeform input into structured data and to word
Ricardo's scripted reply — never to make routing decisions.

When ``settings.anthropic_api_key`` is empty (local dev / CI without a key),
every function falls back to a deterministic heuristic or a canned reply from
``app.prompts.CANNED_REPLIES``.  The real Haiku path is unchanged when a key
is present.
"""
from __future__ import annotations

import json
import re

import structlog

from app import prompts
from app.config import settings

log = structlog.get_logger()

# Evaluated once at import time.  Every function checks this flag before
# touching the Anthropic SDK so we never even construct the client when the
# key is absent.
_has_llm: bool = bool(settings.anthropic_api_key)

# Lazy Anthropic client — only created when _has_llm is True.
_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic  # noqa: PLC0415 — intentional lazy import
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def _complete(
    prompt: str,
    *,
    system: str = prompts.RICARDO_SYSTEM_PROMPT,
    max_tokens: int = 400,
) -> str:
    resp = await _get_client().messages.create(
        model=settings.claude_haiku_model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    return "".join(parts).strip()


def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction from a model reply."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1:
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("json_parse_failed")
        return {}


# ---------------------------------------------------------------------------
# Deterministic / heuristic helpers (used when _has_llm is False)
# ---------------------------------------------------------------------------

# Longest phrases listed first so the scan short-circuits on the most specific
# match (e.g. "a dozen" before "dozen", "a few" before "few").
_WORD_TO_QTY: list[tuple[str, int]] = [
    ("not sure", 0),
    ("a dozen", 12),
    ("dozen", 12),
    ("twelve", 12),
    ("a few", 3),
    ("few", 3),
    ("couple", 2),
    ("single", 1),
    ("one", 1),
]

_YOUTH_KEYWORDS: frozenset[str] = frozenset(
    {"kid", "kids", "child", "children", "youth", "school", "junior"}
)


def _parse_quantity_heuristic(message: str) -> int:
    """Return a quantity integer from free-form text without calling an LLM.

    Priority:
      1. "not sure" → 0  (checked before digit scan to avoid matching "one")
      2. First digit run found, e.g. "25 hats" → 25, "50-99" → 50 (lower bound)
      3. Word map (longest match wins), e.g. "a dozen" → 12
      4. Fallback → 0
    """
    low = message.lower()
    if "not sure" in low:
        return 0
    # Digits win: for ranges like "50-99" the first integer is the lower bound.
    m = re.search(r"\b(\d+)(?:-\d+)?\b", low)
    if m:
        return int(m.group(1))
    # Word map: list is already sorted longest-first.
    for phrase, qty in _WORD_TO_QTY:
        if phrase in low:
            return qty
    return 0


def _detect_youth_heuristic(message: str) -> bool:
    """Return True if the message contains any youth/school keyword."""
    low = message.lower()
    return any(kw in low for kw in _YOUTH_KEYWORDS)


def _generate_reply_canned(state: str, collected: dict, persona_name: str) -> str:
    """Return a canned, user-facing reply for the given state.  No LLM call."""
    template = prompts.CANNED_REPLIES.get(
        state, "Let's keep going — what would you like to do next?"
    )
    try:
        return template.format(
            name=collected.get("name", "there"),
            quantity=collected.get("quantity", ""),
            decoration_type=collected.get("decoration_type", ""),
            placement_zone=collected.get("placement_zone", ""),
            persona=persona_name,
        )
    except (KeyError, IndexError):
        return template


def _safe_collected(collected: dict) -> dict:
    """Strip PII before it is ever placed into an LLM context for reply wording."""
    redacted = dict(collected)
    redacted.pop("email", None)
    redacted.pop("phone", None)
    return redacted


# ---------------------------------------------------------------------------
# Public API — each function has a fallback when _has_llm is False
# ---------------------------------------------------------------------------


async def detect_backtrack(
    message: str, current_state: str, allowed_targets: list[str]
) -> str | None:
    """Return a target state slug if the user wants to go back, else None.

    Without a key: acceptable degradation — backtrack detection is disabled.
    """
    if not allowed_targets:
        return None
    if not _has_llm:
        return None
    prompt = prompts.BACKTRACK_DETECTION_PROMPT.format(
        current_state=current_state,
        message=message,
        allowed_targets=", ".join(allowed_targets),
    )
    data = _parse_json(await _complete(prompt, max_tokens=120))
    if data.get("backtrack") and data.get("target") in allowed_targets:
        return data["target"]
    return None


async def parse_quantity(message: str) -> int:
    """Extract a hat quantity from free-form user text."""
    if not _has_llm:
        return _parse_quantity_heuristic(message)
    prompt = prompts.QUANTITY_EXTRACTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=60))
    try:
        return max(0, int(data.get("quantity", 0)))
    except (TypeError, ValueError):
        return 0


async def detect_youth(message: str) -> bool:
    """Return True if the message indicates the order is for children / youth."""
    if not _has_llm:
        return _detect_youth_heuristic(message)
    prompt = prompts.YOUTH_DETECTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=40))
    return bool(data.get("youth", False))


async def extract_design_description(message: str) -> dict:
    """Extract structured design context from the customer's description."""
    if not _has_llm:
        return {"summary": message.strip()}
    prompt = prompts.DESIGN_EXTRACTION_PROMPT.format(message=message)
    data = _parse_json(await _complete(prompt, max_tokens=400))
    return data or {"summary": message}


async def generate_reply(state: str, collected: dict, persona_name: str) -> str:
    """Word Ricardo's reply for the given state.

    Without a key: returns a canned reply from prompts.CANNED_REPLIES.
    With a key: calls Haiku with the STATE_PROMPTS instruction template.
    """
    if not _has_llm:
        return _generate_reply_canned(state, collected, persona_name)

    instruction = prompts.STATE_PROMPTS.get(state, "Continue the conversation politely.")
    try:
        instruction = instruction.format(
            name=collected.get("name", "there"),
            quantity=collected.get("quantity", ""),
            decoration_type=collected.get("decoration_type", ""),
            placement_zone=collected.get("placement_zone", ""),
        )
    except (KeyError, IndexError):
        pass

    system = prompts.RICARDO_SYSTEM_PROMPT.replace("Ricardo", persona_name)
    prompt = prompts.REPLY_GENERATION_PROMPT.format(
        state_instruction=instruction,
        collected=json.dumps(_safe_collected(collected)),
    )
    return await _complete(prompt, system=system, max_tokens=200)
