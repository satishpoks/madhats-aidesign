"""Daily-design-cap gate: never route to GENERATING (and let the frontend
falsely announce success) when a fresh design can't be started.

Regression for the bug where a customer past their per-day design cap got a 429
from /generate/preview that the frontend swallowed, then saw "your design's in
your inbox and on-screen now" with nothing generated.
"""
from __future__ import annotations

from app import prompts
from app.services.conversation.orchestrator import _apply_generation_gate
from app.services.conversation.state_machine import ConversationState as S


def test_blocked_reroutes_generating_to_quote_with_honest_aside():
    collected: dict = {}
    state, aside = _apply_generation_gate(S.GENERATING, collected, can_start_design=False)
    assert state is S.QUOTE_REQUESTED
    assert aside == prompts.GENERATION_BLOCKED_ASIDE
    assert collected["generation_blocked"] == "daily_limit"


def test_allowed_generating_passes_through_untouched():
    collected: dict = {}
    state, aside = _apply_generation_gate(S.GENERATING, collected, can_start_design=True)
    assert state is S.GENERATING
    assert aside is None
    assert "generation_blocked" not in collected


def test_non_generating_states_are_never_gated():
    # Even when the cap is hit, states other than GENERATING are untouched.
    collected: dict = {}
    state, aside = _apply_generation_gate(S.VERIFY_EMAIL, collected, can_start_design=False)
    assert state is S.VERIFY_EMAIL
    assert aside is None
    assert "generation_blocked" not in collected
