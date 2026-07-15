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
