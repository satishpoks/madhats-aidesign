from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation import state_machine_v2 as v2


def test_intro_then_first_logo_placement():
    # ASK_NAME only advances once a name is captured (see
    # test_ask_name_does_not_advance_until_a_name_is_captured).
    assert v2.advance_state_v2(S.ASK_NAME, {"name": "Sam"}) is S.SHOW_INTRO
    assert v2.advance_state_v2(S.SHOW_INTRO, {}) is S.ASK_LOGO_PLACEMENT


def test_placement_to_adjust_then_another():
    c = {"logo_face": "front"}
    assert v2.advance_state_v2(S.ASK_LOGO_PLACEMENT, c) is S.LOGO_ADJUST
    c["logo_done"] = True
    assert v2.advance_state_v2(S.LOGO_ADJUST, c) is S.ASK_ANOTHER_LOGO


def test_another_logo_yes_loops_until_cap():
    c = {"logo_count": 1, "wants_another_logo": True}
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, c) is S.ASK_LOGO_PLACEMENT
    c = {"logo_count": 4, "wants_another_logo": True}
    # At the cap, no more logos — advance to the decor loop.
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, c) is S.ASK_ADD_DECOR


def test_another_logo_no_goes_to_decor():
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, {"wants_another_logo": False}) is S.ASK_ADD_DECOR


def test_decor_loop():
    assert v2.advance_state_v2(
        S.ASK_ADD_DECOR, {"decor_choice": "text", "decor_answered": True}
    ) is S.DECOR_ADJUST
    assert v2.advance_state_v2(
        S.ASK_ADD_DECOR, {"decor_choice": None, "decor_answered": True}
    ) is S.ASK_QUANTITY
    assert v2.advance_state_v2(S.DECOR_ADJUST, {"decor_done": True}) is S.ASK_ANYTHING_ELSE
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": True}) is S.ASK_ADD_DECOR
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": False}) is S.ASK_QUANTITY


def test_decor_ambiguous_reply_reasks_instead_of_skipping():
    # An unrecognised free-text reply (decor_answered False) must NOT silently
    # advance to quantity — it must re-ask.
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {}) is S.ASK_ADD_DECOR
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {"decor_answered": False}) is S.ASK_ADD_DECOR


def test_tail_reorder_quantity_email_purpose_then_finalize():
    assert v2.advance_state_v2(S.ASK_QUANTITY, {"quantity": 12}) is S.ASK_EMAIL
    assert v2.advance_state_v2(S.ASK_EMAIL, {"email_captured": True}) is S.ASK_PURPOSE
    assert v2.advance_state_v2(S.ASK_PURPOSE, {"purpose": "team"}) is S.FINALIZE_CANVAS


def test_progress_counts_v2_path():
    p = v2.progress_v2(S.ASK_NAME, {})
    assert p["step"] == 1
    assert p["total"] >= 6


def test_directive_logo_placement_unlocks_upload_only():
    # The face question comes FIRST — the upload tool is enabled/highlighted
    # but must not auto-open before the customer answers which face (Finding
    # CRITICAL 1: opening early caused addImage to land on the wrong face).
    d = v2.canvas_directive(S.ASK_LOGO_PLACEMENT, {})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] is None
    assert d["show_done"] is False


def test_directive_logo_adjust_shows_done_and_keeps_upload():
    # By LOGO_ADJUST the face is answered, so it's safe to switch the canvas
    # to that face and THEN open the picker.
    d = v2.canvas_directive(S.LOGO_ADJUST, {"logo_face": "back"})
    assert d["show_done"] is True
    assert d["target_face"] == "back"
    assert d["auto_open"] == "upload"


def test_directive_anything_else_locks_all_tools():
    d = v2.canvas_directive(S.ASK_ANYTHING_ELSE, {})
    assert d["allowed_tools"] == []


def test_directive_none_only_for_unowned_tail_states():
    # A state v2 doesn't own is driven by the v1 UI -> no directive.
    assert v2.canvas_directive(S.OFFER_REFINE, {}) is None
    assert v2.canvas_directive(S.QUOTE_REQUESTED, {}) is None


def test_directive_locks_tools_on_every_owned_non_tool_state():
    # Every v2-owned step that isn't a tool step must still emit a directive
    # (locking all tools). A None here makes the frontend fall back to the v1
    # UI mid-flow — showing "finishing up" during the design loop and leaving
    # tool locking to the legacy gate rather than this state machine.
    tool_states = {S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.DECOR_ADJUST}
    for state in v2.V2_OWNED - tool_states:
        d = v2.canvas_directive(state, {})
        assert d is not None, f"{state.value} emitted no directive"
        assert d["allowed_tools"] == [], f"{state.value} did not lock tools"


def test_directive_quantity_locks_all_tools():
    d = v2.canvas_directive(S.ASK_QUANTITY, {})
    assert d["allowed_tools"] == []


def test_public_data_finalize_triggers_finalize():
    data = v2.v2_public_data(S.FINALIZE_CANVAS, {})
    assert data["trigger_finalize"] is True


def test_reply_uses_intro_text():
    r = v2.v2_reply(S.SHOW_INTRO, {"name": "Sam"}, "Ricardo", "Welcome to MadHats!")
    assert "Welcome to MadHats!" in r


# --- regression: the ASK_NAME step must actually greet + ask for the name ---

def test_reply_ask_name_greets_and_asks_for_the_name():
    # v2_reply had no ASK_NAME branch, so the kickoff fell through to the
    # catch-all ("Let's keep going.") — the customer was never asked anything,
    # and whatever they typed next was stored as their name.
    reply = v2.v2_reply(S.ASK_NAME, {}, "Ricardo", "intro")

    assert reply != "Let's keep going."
    assert "name" in reply.lower()
    assert "Ricardo" in reply


def test_ask_name_does_not_advance_until_a_name_is_captured():
    # No name in `collected` -> stay on ASK_NAME (re-ask) rather than marching
    # on to the intro with an empty/filler name.
    assert v2.advance_state_v2(S.ASK_NAME, {}) is S.ASK_NAME
    assert v2.advance_state_v2(S.ASK_NAME, {"name": "Sam"}) is S.SHOW_INTRO
