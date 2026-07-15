from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation import state_machine_v2 as v2


def test_intro_then_first_logo_placement():
    assert v2.advance_state_v2(S.ASK_NAME, {}) is S.SHOW_INTRO
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
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {"decor_choice": "text"}) is S.DECOR_ADJUST
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {"decor_choice": None}) is S.ASK_QUANTITY
    assert v2.advance_state_v2(S.DECOR_ADJUST, {"decor_done": True}) is S.ASK_ANYTHING_ELSE
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": True}) is S.ASK_ADD_DECOR
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": False}) is S.ASK_QUANTITY


def test_tail_reorder_quantity_email_purpose_then_finalize():
    assert v2.advance_state_v2(S.ASK_QUANTITY, {"quantity": 12}) is S.ASK_EMAIL
    assert v2.advance_state_v2(S.ASK_EMAIL, {"email_captured": True}) is S.ASK_PURPOSE
    assert v2.advance_state_v2(S.ASK_PURPOSE, {"purpose": "team"}) is S.FINALIZE_CANVAS


def test_progress_counts_v2_path():
    p = v2.progress_v2(S.ASK_NAME, {})
    assert p["step"] == 1
    assert p["total"] >= 6


def test_directive_logo_placement_unlocks_upload_only():
    d = v2.canvas_directive(S.ASK_LOGO_PLACEMENT, {})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] == "upload"
    assert d["show_done"] is False


def test_directive_logo_adjust_shows_done_and_keeps_upload():
    d = v2.canvas_directive(S.LOGO_ADJUST, {"logo_face": "back"})
    assert d["show_done"] is True
    assert d["target_face"] == "back"


def test_directive_anything_else_locks_all_tools():
    d = v2.canvas_directive(S.ASK_ANYTHING_ELSE, {})
    assert d["allowed_tools"] == []


def test_directive_none_for_tail_states():
    # Genuine tail states drive no canvas change.
    assert v2.canvas_directive(S.ASK_EMAIL, {}) is None
    assert v2.canvas_directive(S.ASK_PURPOSE, {}) is None


def test_directive_quantity_locks_all_tools():
    d = v2.canvas_directive(S.ASK_QUANTITY, {})
    assert d["allowed_tools"] == []


def test_public_data_finalize_triggers_finalize():
    data = v2.v2_public_data(S.FINALIZE_CANVAS, {})
    assert data["trigger_finalize"] is True


def test_reply_uses_intro_text():
    r = v2.v2_reply(S.SHOW_INTRO, {"name": "Sam"}, "Ricardo", "Welcome to MadHats!")
    assert "Welcome to MadHats!" in r
