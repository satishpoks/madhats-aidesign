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

from app.services.conversation.intent_extractor import (
    _detect_youth_heuristic,
    _parse_quantity_heuristic,
)
from app.services.conversation.orchestrator import _ingest
from app.services.conversation.state_machine import ConversationState


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
