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


def test_confirm_stalls_in_place_when_the_interpreter_is_down():
    # An outage must never fall through to either branch of edit_confirmed —
    # it has to re-ask the chips, guessing nothing and spending nothing.
    c = {"flow_mode": "canvas", "edit_confirm_stalled": True}
    assert advance_state(S.CONFIRM_CANVAS_EDIT, c) is S.CONFIRM_CANVAS_EDIT


# --- IMPORTANT 1: a canvas edit must never become a change_request ---------


def test_canvas_describe_changes_never_sets_last_change(monkeypatch):
    """orchestrator.py used to set collected['last_change'] for EVERY
    DESCRIBE_CHANGES turn, ungated by flow_mode. For canvas sessions that
    value is picked up as a `change_request` fallback at regeneration
    (generate.py) and folded into the image prompt -- double-applying the
    edit the canvas already made for free."""
    c = {"flow_mode": "canvas"}
    o._apply_fields(S.DESCRIBE_CHANGES, {}, c, "make the logo smaller")
    assert "last_change" not in c


def test_non_canvas_describe_changes_still_sets_last_change():
    # session/blank flows are untouched -- last_change is their only signal.
    c = {"flow_mode": "session"}
    o._apply_fields(S.DESCRIBE_CHANGES, {}, c, "make the logo smaller")
    assert c["last_change"] == "make the logo smaller"


# --- IMPORTANT 2: the confirm gate must not read free text as approval -----


@pytest.mark.asyncio
async def test_confirm_chip_looks_right_confirms_with_zero_model_calls(monkeypatch):
    calls = []

    async def spy(_msg):
        calls.append(_msg)
        return False  # if this is ever reached, the test below catches it

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", spy)
    c = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c, "Looks right")
    assert c["edit_confirmed"] is True
    assert calls == []


@pytest.mark.asyncio
async def test_confirm_chip_not_quite_declines_with_zero_model_calls(monkeypatch):
    calls = []

    async def spy(_msg):
        calls.append(_msg)
        return True

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", spy)
    c = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c, "Not quite")
    assert c["edit_confirmed"] is False
    assert calls == []


@pytest.mark.asyncio
async def test_confirm_free_text_goes_to_the_interpreter_both_ways(monkeypatch):
    async def yes(_msg):
        return True

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", yes)
    c = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c, "yeah that's great")
    assert c["edit_confirmed"] is True

    async def no(_msg):
        return False

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", no)
    c2 = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c2, "hmm can you nudge it more")
    assert c2["edit_confirmed"] is False


@pytest.mark.asyncio
async def test_confirm_that_looks_wrong_does_not_confirm(monkeypatch):
    """The regression that motivated the fix: is_affirmative/substring matching
    read 'that looks wrong' as approval because 'lo-ok-s' contains 'ok'."""
    async def reads_it_correctly(_msg):
        assert "wrong" in _msg
        return False

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", reads_it_correctly)
    c = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c, "that looks wrong")
    assert c["edit_confirmed"] is False


@pytest.mark.asyncio
async def test_confirm_outage_stalls_and_never_reaches_regenerating(monkeypatch):
    async def boom(_msg):
        raise o.ie.LLMUnavailable("down")

    monkeypatch.setattr(o.ie, "interpret_edit_confirm", boom)
    c = {"flow_mode": "canvas"}
    await o._apply_edit_confirm(c, "yeah that's great")
    assert c.get("edit_confirmed") is None
    assert c["edit_confirm_stalled"] is True
    assert advance_state(S.CONFIRM_CANVAS_EDIT, c) is S.CONFIRM_CANVAS_EDIT


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
