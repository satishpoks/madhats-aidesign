"""The describe branch edits the canvas instead of paying for a render.
Canvas-only: session/blank flows keep change_request -> regenerate."""
import pytest

from app.services.conversation import orchestrator as o
from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation.state_machine import advance_state


def _design():
    return {"colourway": None, "faces": {
        "front": [{"id": "logo1", "type": "image", "x": 0.4, "y": 0.4,
                   "width": 0.2, "height": 0.2, "rotation": 0, "zIndex": 0}],
        "back": [], "left": [], "right": []}}


def _session(collected=None):
    return {"id": "s1", "flow_mode": "canvas", "canvas_design": _design(),
            "collected": collected or {"flow_mode": "canvas"}}


@pytest.mark.asyncio
async def test_an_expressible_change_produces_ops_and_asks_to_confirm(monkeypatch):
    async def fake(_msg, _inv):
        return [{"op": "resize", "element_id": "logo1", "direction": "smaller", "amount": "small"}]
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", fake)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "the logo's a bit big")
    assert ops and ops[0]["target"]["id"] == "logo1"
    assert c["canvas_edit_ops"] is True
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.CONFIRM_CANVAS_EDIT


@pytest.mark.asyncio
async def test_a_render_level_change_is_refused_and_noted_for_the_team(monkeypatch):
    async def fake(_msg, _inv):
        return []
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", fake)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "make the embroidery thicker")
    assert ops == []
    assert c["canvas_edit_refused"] is True
    assert any("embroidery thicker" in n for n in c["brief_notes"])
    # Refused changes never render: the customer stays where they were.
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.OFFER_REFINE


@pytest.mark.asyncio
async def test_an_outage_stalls_rather_than_guessing_geometry(monkeypatch):
    async def boom(_msg, _inv):
        raise o.ie.LLMUnavailable("down")
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", boom)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "move it up")
    assert ops == []
    assert c["canvas_edit_stalled"] is True
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.DESCRIBE_CHANGES


def test_confirm_routes_to_regeneration_or_back_to_describe():
    assert advance_state(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas", "edit_confirmed": True}) is S.REGENERATING
    assert advance_state(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas", "edit_confirmed": False}) is S.DESCRIBE_CHANGES


def test_a_non_canvas_session_still_uses_the_old_describe_route():
    # session/blank flows must be untouched: change_request -> regenerate.
    c = {"flow_mode": "session", "refine_followups": []}
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.REFINE_CONFIRM


def test_confirm_offers_the_two_chips():
    d = o._public_data(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas"})
    assert d["options"] == ["Looks right", "Not quite"]


def test_confirm_is_a_gate_state_so_the_goal_planner_cannot_hijack_it():
    """_route sends any non-GATE_STATE to goal_planner.next_goal, which for a
    finished canvas session answers GENERATING — a FRESH generation that burns
    the daily design cap. goal_planner.py:27-34 records this exact trap biting
    ASK_CHANGE_METHOD."""
    from app.services.conversation import goal_planner
    assert S.CONFIRM_CANVAS_EDIT in goal_planner.GATE_STATES


def test_route_sends_a_confirmed_edit_to_regeneration_not_generation():
    # The end-to-end guarantee the gate exists for, through the real router.
    c = {"flow_mode": "canvas", "edit_confirmed": True, "name": "Sam",
         "canvas_finalized": True, "decoration_done": True, "notes_done": True}
    assert o._route(S.CONFIRM_CANVAS_EDIT, c, 0) is S.REGENERATING
