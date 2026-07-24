"""Tests for intent_extractor no-key fallback and orchestrator kickoff handshake.

These tests exercise:
  - _parse_quantity_heuristic: digit and word-based parsing (no LLM needed)
  - _detect_youth_heuristic: keyword detection (no LLM needed)
  - _ingest GREETING state: must NOT capture the user message as the name
  - _ingest ASK_NAME state: MUST capture the user message as the name

All tests are fully synchronous; no external services are required.
"""
from __future__ import annotations

import asyncio

import pytest

from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator as orch
from app.services.conversation.intent_extractor import (
    _detect_youth_heuristic,
    _parse_quantity_heuristic,
)
from app.services.conversation.state_machine import ConversationState


async def _ingest(state: ConversationState, message: str, collected: dict) -> None:
    """Test shim mirroring the retired orchestrator._ingest: run the no-LLM
    interpreter field extraction for `state`, then apply it as the orchestrator
    does. Kept so the kickoff-handshake assertions below still exercise the
    real capture path (interpret_turn fallback -> _apply_fields)."""
    fields = ie._extract_fields_for_state(state.value, message, collected)
    orch._apply_fields(state, fields, collected, message)


# ---------------------------------------------------------------------------
# parse_quantity — heuristic (sync helper, no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("a dozen", 12),
        ("dozen hats please", 12),
        ("twelve", 12),
        ("50-99", 50),
        ("I need about 50-99 units", 50),
        ("couple", 2),
        ("a few", 3),
        ("few hats", 3),
        ("single", 1),
        ("one", 1),
        ("not sure", 0),
        ("12", 12),
        ("25 hats", 25),
        ("100 units please", 100),
    ],
)
def test_parse_quantity_heuristic(msg: str, expected: int) -> None:
    result = _parse_quantity_heuristic(msg)
    assert result == expected, f"_parse_quantity_heuristic({msg!r}) expected {expected}, got {result}"


# ---------------------------------------------------------------------------
# detect_youth — keyword heuristic (sync helper, no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("they're for kids at school", True),
        ("youth team jerseys", True),
        ("children's program", True),
        ("junior league caps", True),
        ("school fundraiser", True),
        ("for adult staff uniforms", False),
        ("my team at work", False),
        ("corporate event giveaway", False),
        ("resale in my shop", False),
    ],
)
def test_detect_youth_heuristic(msg: str, expected: bool) -> None:
    result = _detect_youth_heuristic(msg)
    assert result == expected, f"_detect_youth_heuristic({msg!r}) expected {expected}, got {result}"


# ---------------------------------------------------------------------------
# Kickoff handshake — GREETING state must NOT capture name
# ---------------------------------------------------------------------------


def test_ingest_greeting_does_not_capture_name() -> None:
    """_ingest on GREETING state must not capture the message as a name.

    The kickoff turn arrives at GREETING state with the user's raw first message
    (may be empty or an intro). The name must NOT be captured here; only
    ASK_NAME should do that.
    """
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.GREETING, "Sam", collected))
    assert "name" not in collected, "GREETING _ingest must NOT set collected['name']"


def test_ingest_ask_name_captures_name() -> None:
    """_ingest on ASK_NAME state MUST capture the message as the customer name."""
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.ASK_NAME, "Sam", collected))
    assert collected.get("name") == "Sam", "ASK_NAME _ingest must set collected['name'] = 'Sam'"


def test_ingest_ask_name_trims_whitespace() -> None:
    """Name is trimmed and truncated to 60 chars."""
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.ASK_NAME, "  Jordan  ", collected))
    assert collected.get("name") == "Jordan"


# ---------------------------------------------------------------------------
# generate_reply — per-element deep-dive must give the model element context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_reply_deepdive_gives_model_element_context(monkeypatch):
    """Regression (session XejU8PSYL2n928oSJjw3_w): a TEXT element's deep-dive
    questions called it "your logo" and re-asked the cap colour, because the
    model was never told which element it was asking about. The prompt must
    carry the element type and its content."""
    monkeypatch.setattr(ie, "_has_llm", True)
    captured: dict = {}

    async def fake_complete(prompt, **kw):
        captured["prompt"] = prompt
        return "ok"

    monkeypatch.setattr(ie, "_complete", fake_complete)
    el = {"type": "text", "content": "satish"}
    await ie.generate_reply(
        "element_deepdive", {"name": "Al"}, "Ricardo",
        ask_for="placement_zone", element=el,
    )
    p = captured["prompt"].lower()
    assert "text" in p        # model told the element is text (not a logo)
    assert "satish" in p      # model told what the text says


# ---------------------------------------------------------------------------
# Fix #1 — the model's private reasoning must NEVER reach the customer
# Regression (session M7bd429P_q3zZCwYI5VK0g): Ricardo's reply was the raw
# Haiku output including its chain-of-thought and an internal field name
# ("purpose_asked"), because (a) internal bookkeeping flags were fed into the
# reply prompt and (b) the model's "Here's Ricardo's message:" preamble was
# never stripped.
# ---------------------------------------------------------------------------


def test_safe_collected_strips_internal_bookkeeping_flags() -> None:
    """Only real design data may reach an LLM context — never state-machine
    bookkeeping flags or ids (which the model reads and narrates about)."""
    collected = {
        "name": "Al",
        "purpose": "team caps",
        "design_description": {"summary": "blue logo"},
        "quantity": 25,
        # internal flags / ids that must be scrubbed:
        "purpose_asked": True,
        "email_captured": True,
        "email_verified": True,
        "email_prompt_shown": True,
        "resume_email_sent": True,
        "youth_flag": False,
        "flow_mode": "canvas",
        "lead_id": "495f409d-cc24-4d11-9ec6-24b22e42c37e",
    }
    safe = ie._safe_collected(collected)
    # real design data survives
    assert safe["name"] == "Al"
    assert safe["purpose"] == "team caps"
    assert safe["design_description"] == {"summary": "blue logo"}
    assert safe["quantity"] == 25
    # every internal flag / id is gone
    for leaked in (
        "purpose_asked", "email_captured", "email_verified", "email_prompt_shown",
        "resume_email_sent", "youth_flag", "flow_mode", "lead_id", "email", "phone",
    ):
        assert leaked not in safe, f"{leaked!r} leaked into the LLM context"


def test_strip_meta_preamble_removes_model_reasoning() -> None:
    raw = (
        "I notice the step instruction asks me to address the customer by name, "
        "but the known details show that `purpose_asked` is already true.\n\n"
        "Since we've already established the purpose, I'll move on.\n\n"
        "Here's Ricardo's message:\n\n"
        "So, what kind of style are you after?"
    )
    assert ie._strip_meta_preamble(raw) == "So, what kind of style are you after?"


def test_strip_meta_preamble_leaves_clean_reply_untouched() -> None:
    clean = "So, what kind of style are you after — bold or classic?"
    assert ie._strip_meta_preamble(clean) == clean


@pytest.mark.asyncio
async def test_generate_reply_strips_leaked_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return (
            "I notice `purpose_asked` is already true, so I'll skip that step.\n\n"
            "Here's Ricardo's message:\n\n"
            "So, what style are you after?"
        )

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.generate_reply("ask_purpose", {"name": "Al"}, "Ricardo")
    assert "purpose_asked" not in out
    assert "Here's" not in out
    assert out == "So, what style are you after?"


# ---------------------------------------------------------------------------
# Fix #2 — mojibake repair (UTF-8 bytes mis-decoded as CP1252)
# Regression (session M7bd429P_q3zZCwYI5VK0g): em-dashes were stored/shown as
# "â€"". Defensive repair so a mis-encoded reply self-heals before the customer
# ever sees it.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad,good",
    [
        ("address â€” could you", "address — could you"),
        ("afterâ€”something", "after—something"),
        ("itâ€™s ready", "it’s ready"),  # curly apostrophe
    ],
)
def test_repair_mojibake_fixes_double_encoded_punctuation(bad: str, good: str) -> None:
    assert ie.repair_mojibake(bad) == good


def test_repair_mojibake_idempotent_on_clean_text() -> None:
    clean = "what style are you after — bold or classic? café"
    assert ie.repair_mojibake(clean) == clean


@pytest.mark.asyncio
async def test_generate_reply_repairs_mojibake(monkeypatch) -> None:
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return "what style are you afterâ€”bold or classic?"

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.generate_reply("ask_purpose", {}, "Ricardo")
    assert "â€" not in out
    assert "—" in out


# ---------------------------------------------------------------------------
# Fix #3 — a bare greeting must not be captured as the customer's name
# Regression (session M7bd429P_q3zZCwYI5VK0g): the customer answered "What's
# your first name?" with "hi" and it became collected["name"] = "hi".
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Fix #4 — _normalize_interpretation must never crash on an unhashable field.
# Regression (session 69902f52 — "Yes, request a quote" showed a fetch error):
# Haiku returned placement_zone (and could return intent) as a LIST, and
# `value not in {a_set}` raises TypeError: unhashable type: 'list'. The whole
# chat turn 500'd. Any non-string/unhashable value must be dropped, not hashed.
# ---------------------------------------------------------------------------


def test_normalize_interpretation_drops_list_placement_zone() -> None:
    """A list placement_zone must be dropped, not hashed (which crashes)."""
    out = ie._normalize_interpretation(
        {"intent": "answer", "fields": {"placement_zone": ["front_panel", "back"]}},
        allowed_targets=[],
    )
    assert "placement_zone" not in out["fields"]


def test_normalize_interpretation_drops_list_intent() -> None:
    """A list (unhashable) intent must fall back to 'answer', not crash."""
    out = ie._normalize_interpretation(
        {"intent": ["answer", "revise"], "fields": {}},
        allowed_targets=[],
    )
    assert out["intent"] == "answer"


def test_normalize_interpretation_keeps_valid_placement_zone() -> None:
    out = ie._normalize_interpretation(
        {"intent": "answer", "fields": {"placement_zone": "front_panel"}},
        allowed_targets=[],
    )
    assert out["fields"]["placement_zone"] == "front_panel"


def test_normalize_interpretation_drops_invalid_string_placement_zone() -> None:
    out = ie._normalize_interpretation(
        {"intent": "answer", "fields": {"placement_zone": "nonsense"}},
        allowed_targets=[],
    )
    assert "placement_zone" not in out["fields"]


@pytest.mark.parametrize(
    "greeting", ["hi", "Hi", "hello", "Hey there", "good morning", "yo", "hiya"]
)
def test_ask_name_rejects_greeting(greeting: str) -> None:
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.ASK_NAME, greeting, collected))
    assert "name" not in collected, f"{greeting!r} must NOT be captured as a name"


def test_ask_name_still_captures_real_name() -> None:
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.ASK_NAME, "Sam", collected))
    assert collected.get("name") == "Sam"


def test_ask_name_captures_name_that_merely_starts_like_greeting() -> None:
    """A real name is not rejected just because it shares letters with a
    greeting (e.g. 'Henry' contains 'he')."""
    collected: dict = {}
    asyncio.run(_ingest(ConversationState.ASK_NAME, "Henry", collected))
    assert collected.get("name") == "Henry"
