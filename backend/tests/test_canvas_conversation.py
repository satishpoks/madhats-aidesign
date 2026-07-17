"""Canvas decoration/notes capture in the orchestrator (pure helpers)."""
from __future__ import annotations

from app.services.conversation import orchestrator as orch
from app.services.conversation.state_machine import ConversationState as S


def test_public_data_ask_decoration_multiselect():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery", "Print"],
                 "decoration_types": ["Embroidery"]}
    data = orch._state_public_data(S.ASK_DECORATION, collected)
    assert data["options"] == ["Embroidery", "Print"]
    assert data["multiselect"] is True
    assert data["selected"] == ["Embroidery"]


def test_public_data_ask_notes_has_skip_chip():
    data = orch._state_public_data(S.ASK_NOTES, {"flow_mode": "canvas"})
    assert "No, generate" in data["options"]


def test_capture_decoration_matches_options_and_marks_done():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery", "Print", "Patch"]}
    orch._apply_canvas_outro(S.ASK_DECORATION, collected, "Embroidery, Print")
    assert collected["decoration_types"] == ["Embroidery", "Print"]
    assert collected["decoration_done"] is True
    # folded into the brief + style modifier chosen
    assert any("Embroidery" in n for n in collected["brief_notes"])
    assert collected["decoration_type"] == "embroidery"


def test_capture_decoration_none_still_advances():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery"]}
    orch._apply_canvas_outro(S.ASK_DECORATION, collected, "none")
    assert collected["decoration_types"] == []
    assert collected["decoration_done"] is True


def test_capture_decoration_preserves_user_order_and_exact_match():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery", "Print", "Screen Print"]}
    orch._apply_canvas_outro(S.ASK_DECORATION, collected, "Print, Embroidery")
    # user's order preserved (Print first) → style bucket derives from Print
    assert collected["decoration_types"] == ["Print", "Embroidery"]
    assert collected["decoration_type"] == "print"
    # exact-token match: "Print" must NOT also pull in "Screen Print"
    assert "Screen Print" not in collected["decoration_types"]


def test_capture_notes_records_and_skips():
    c1 = {"flow_mode": "canvas"}
    orch._apply_canvas_outro(S.ASK_NOTES, c1, "Match pantone 185C please")
    assert c1["notes_done"] is True
    assert "Match pantone" in " ".join(c1["brief_notes"])

    c2 = {"flow_mode": "canvas"}
    orch._apply_canvas_outro(S.ASK_NOTES, c2, "No, generate")
    assert c2["notes_done"] is True
    assert not c2.get("brief_notes")


# --- regression: "Rework on the canvas" must reopen the canvas ---

def _reworked_collected(**over) -> dict:
    """A canvas session that has been through a full design + generation and is
    now sitting on ASK_CHANGE_METHOD."""
    c = {
        "flow_mode": "canvas", "name": "Sam", "purpose": "uniform", "quantity": 12,
        "email_prompt_shown": True, "email_captured": True, "email_verified": True,
        "canvas_finalized": True, "decoration_done": True, "notes_done": True,
        "rework_on_canvas": True,
    }
    c.update(over)
    return c


def test_ask_change_method_rework_routes_back_to_the_canvas():
    # ASK_CHANGE_METHOD was missing from goal_planner.GATE_STATES, so _route
    # consulted the goal planner (which only knows the forward questionnaire)
    # instead of advance_state's ASK_CHANGE_METHOD branch. The planner saw a
    # finished questionnaire and returned GENERATING/SAVE_PROGRESS_EMAIL — the
    # canvas never reopened.
    assert orch._route(S.ASK_CHANGE_METHOD, _reworked_collected(), 0) is S.CANVAS_DESIGN


def test_ask_change_method_describe_routes_to_describe_changes():
    c = _reworked_collected(rework_on_canvas=False)
    assert orch._route(S.ASK_CHANGE_METHOD, c, 0) is S.DESCRIBE_CHANGES


def test_v2_session_on_ask_change_method_is_never_re_asked_for_its_email():
    # The v2 orchestrator never sets v1's `email_prompt_shown` sentinel. Routing
    # a v2 tail turn through the goal planner therefore re-asked for an email
    # that was already captured AND verified.
    c = _reworked_collected()
    c.pop("email_prompt_shown")          # v2 never writes this
    c.pop("decoration_done"); c.pop("notes_done")  # nor these
    assert orch._route(S.ASK_CHANGE_METHOD, c, 0) is S.CANVAS_DESIGN
