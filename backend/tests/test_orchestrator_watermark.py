"""`orchestrator._public_data` serves BOTH v1-delegated turns and every resume
(`sessions.get_session` imports this same function), so it is the producer that
has to carry the watermark flag through the shared tail. Before this it emitted
nothing, and `chatStore.parseData` fell back to `false` — the design lost its
watermark the moment the flow left finalize_canvas, and on any reload."""
from __future__ import annotations

import pytest

from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState as S


@pytest.mark.parametrize("state", [
    S.QUOTE_REQUESTED, S.GENERATING, S.VERIFY_EMAIL, S.OFFER_REFINE,
])
def test_tail_states_carry_the_watermark_for_a_confirmed_canvas_design(state):
    data = _public_data(state, {"flow_mode": "canvas", "design_confirmed": True})
    assert data["watermark"] is True


def test_a_canvas_session_still_designing_is_not_watermarked():
    data = _public_data(S.CANVAS_DESIGN, {"flow_mode": "canvas"})
    assert data["watermark"] is False


def test_a_non_canvas_session_is_never_watermarked():
    data = _public_data(S.QUOTE_REQUESTED, {"flow_mode": "session",
                                            "design_confirmed": True})
    assert data["watermark"] is False


def test_the_key_is_always_present_so_the_frontend_never_guesses():
    # chatStore.parseData reads `'watermark' in data` before falling back. The
    # key being unconditionally present is what retires that fallback.
    assert "watermark" in _public_data(S.GREETING, {})
