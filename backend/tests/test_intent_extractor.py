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
