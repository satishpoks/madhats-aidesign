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


def test_public_data_colour_chips_from_colourways():
    collected = {"flow_mode": "blank", "hat_colours": [
        {"name": "Navy", "hex": "#1a2b5c"}, {"name": "Black", "hex": "#000000"}]}
    data = _public_data(S.ASK_HAT_COLOUR, collected)
    assert data["options"] == ["Navy", "Black"]
    assert data["colour_swatches"][0]["hex"] == "#1a2b5c"


def test_public_data_colour_detail_options():
    data = _public_data(S.ASK_COLOUR_DETAIL, {"flow_mode": "blank"})
    assert "Whole hat — one colour" in data["options"]


def test_apply_fields_colour_detail_whole_hat_sets_no_note():
    from app.services.conversation.orchestrator import _apply_fields
    collected = {"flow_mode": "blank", "hat_colour": {"name": "Navy", "hex": "#1a2b5c"}}
    _apply_fields(S.ASK_COLOUR_DETAIL, {}, collected, "Whole hat — one colour")
    assert collected["colour_detail_asked"] is True
    assert "colour_note" not in collected


def test_apply_fields_colour_detail_captures_section_note():
    from app.services.conversation.orchestrator import _apply_fields
    collected = {"flow_mode": "blank", "hat_colour": {"name": "Navy", "hex": "#1a2b5c"}}
    _apply_fields(S.ASK_COLOUR_DETAIL, {}, collected, "navy body, white stitching, red brim")
    assert collected["colour_detail_asked"] is True
    assert collected["colour_note"] == "navy body, white stitching, red brim"


def test_tint_ready_advertised_once_colour_chosen():
    # After a colour is chosen, EVERY subsequent state advertises tint_ready +
    # tint_hex so the left viewer can composite the tinted blank instantly.
    collected = {"flow_mode": "blank", "hat_colour": {"name": "Navy", "hex": "#1a2b5c"}}
    data = _public_data(S.RECOMMEND_EMBROIDERY, collected)
    assert data["tint_ready"] is True
    assert data["tint_hex"] == "#1a2b5c"


def test_no_tint_before_colour_or_for_customise():
    # Blank, no colour yet -> no tint signal.
    assert "tint_ready" not in _public_data(S.ASK_HAT_COLOUR, {"flow_mode": "blank"})
    # Customise flow -> never tinted.
    assert "tint_ready" not in _public_data(S.RECOMMEND_EMBROIDERY, {"decoration_type": "print"})
