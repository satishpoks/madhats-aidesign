"""Orchestration wiring tests for blank-mode: composite-preview gate + colour picker."""
from __future__ import annotations

from app.services.conversation.goal_planner import GATE_STATES, next_goal
from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState as S


def test_composite_preview_is_a_gate():
    assert S.COMPOSITE_PREVIEW in GATE_STATES


def test_public_data_composite_preview():
    data = _public_data(S.COMPOSITE_PREVIEW, {"flow_mode": "blank"})
    assert data["composite_preview"] is True
    assert "Tweak something" in data["options"]


def test_public_data_colour_picker():
    assert _public_data(S.ASK_HAT_COLOUR, {"flow_mode": "blank"})["colour_picker"] is True
