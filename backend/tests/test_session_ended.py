"""`orchestrator._public_data` serves BOTH v1-delegated turns and every resume
(`sessions.get_session` imports this same function), so it is the producer that
has to carry the `session_ended` lock through the shared tail — mirrors
`test_orchestrator_watermark.py` for the sibling flag.

The finding this closes: `ChatColumn.tsx` used to lock its composer (and
`RedirectCountdown` used to open its "back to the shop" dialog) on
`chatState === 'quote_requested'` alone. That state string is shared with v1,
where it's an answerable yes/no gate (state_machine.py's
QUOTE_REQUESTED -> SESSION_END transition, driven by a `wants_quote` reply) —
so a v1 canvas session at that state was wrongly locked and redirected over a
question it could still answer. Only a v2 canvas session is genuinely done
there, because its REQUEST_QUOTE step already captured the decision via its
one chip before `canvas-finalize` ever wrote the state.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState as S


def test_v2_canvas_session_is_locked_at_quote_requested(monkeypatch):
    monkeypatch.setattr(settings, "canvas_orchestrator_v2", True)
    data = _public_data(S.QUOTE_REQUESTED, {"flow_mode": "canvas"})
    assert data["session_ended"] is True


def test_v1_canvas_session_stays_answerable_at_the_same_state(monkeypatch):
    monkeypatch.setattr(settings, "canvas_orchestrator_v2", False)
    data = _public_data(S.QUOTE_REQUESTED, {"flow_mode": "canvas"})
    assert data["session_ended"] is False
    # And it must still be the answerable yes/no gate, not a statement.
    assert data["options"] == ["Yes, request a quote", "No, I'm all set"]


@pytest.mark.parametrize("state", [
    S.GENERATING, S.VERIFY_EMAIL, S.OFFER_REFINE, S.CANVAS_DESIGN, S.SESSION_END,
])
def test_no_other_state_ever_ends_the_session(monkeypatch, state):
    monkeypatch.setattr(settings, "canvas_orchestrator_v2", True)
    data = _public_data(state, {"flow_mode": "canvas"})
    assert data["session_ended"] is False


def test_a_non_canvas_session_is_never_ended_by_this_flag(monkeypatch):
    monkeypatch.setattr(settings, "canvas_orchestrator_v2", True)
    data = _public_data(S.QUOTE_REQUESTED, {"flow_mode": "session"})
    assert data["session_ended"] is False


def test_the_key_is_always_present_so_the_frontend_never_guesses(monkeypatch):
    monkeypatch.setattr(settings, "canvas_orchestrator_v2", True)
    assert "session_ended" in _public_data(S.GREETING, {})
