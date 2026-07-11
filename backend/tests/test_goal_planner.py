"""Pure-logic tests for the goal-oriented conversation planner."""
from __future__ import annotations

from app.services.conversation.goal_planner import next_goal
from app.services.conversation.state_machine import ConversationState as S


def _base():
    # A fully-answered questionnaire up to (not including) placement.
    return {
        "name": "Al",
        "purpose": "staff uniforms",
        "quantity": 50,
        "decoration_type": "embroidery",
        "has_logo": False,
        "design_description": {"summary": "logo"},
    }


def test_empty_returns_name():
    assert next_goal({}) is S.ASK_NAME


def test_name_present_moves_to_purpose():
    assert next_goal({"name": "Al"}) is S.ASK_PURPOSE


def test_name_never_reasked_once_set():
    # The double-name-ask regression, at the planner level.
    out = next_goal({"name": "Al"})
    assert out is not S.ASK_NAME


def test_soft_purpose_satisfied_once_asked():
    # purpose still empty, but we've already asked -> do not ask again.
    assert next_goal({"name": "Al", "purpose_asked": True}) is S.ASK_QUANTITY


def test_youth_referral_gate_shown_once():
    c = {"name": "Al", "purpose": "school team", "youth_flag": True}
    assert next_goal(c) is S.YOUTH_REFERRAL
    c["youth_referred"] = True
    assert next_goal(c) is S.ASK_QUANTITY


def test_quantity_presence_not_truthiness():
    # "not sure" -> quantity 0 still counts as answered.
    c = {"name": "Al", "purpose_asked": True, "quantity": 0}
    assert next_goal(c) is not S.ASK_QUANTITY


def test_decoration_by_quantity():
    c = {"name": "Al", "purpose_asked": True}
    assert next_goal({**c, "quantity": 1}) is S.WARN_PRINT_SETUP
    assert next_goal({**c, "quantity": 6}) is S.RECOMMEND_DECORATION
    assert next_goal({**c, "quantity": 24}) is S.RECOMMEND_EMBROIDERY


def test_logo_branch_upload_then_removebg_then_placement():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": True}
    assert next_goal(c) is S.UPLOAD_LOGO
    c["uploaded_asset_path"] = "uploads/logo.png"
    assert next_goal(c) is S.ASK_REMOVE_BG
    c["remove_bg"] = False
    c["elements_offered"] = True
    assert next_goal(c) is S.ASK_PLACEMENT_ZONE


def test_describe_branch_reaches_placement():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False,
         "design_description": {"summary": "x"}, "elements_offered": True}
    assert next_goal(c) is S.ASK_PLACEMENT_ZONE


def test_placement_zone_only_then_pin_offer_then_generating():
    c = _base()
    c["placement_zone"] = "front_panel"          # position intentionally absent
    c["elements_offered"] = True
    assert next_goal(c) is S.ASK_PIN_ANNOTATION   # placement satisfied by zone alone
    c["pin_offered"] = True
    assert next_goal(c) is S.GENERATING


def test_pin_offer_is_optional_never_blocks():
    c = _base()
    c["placement_zone"] = "side"
    c["elements_offered"] = True
    c["pin_offered"] = True
    assert next_goal(c) is S.GENERATING


def test_gather_goal_offered_once_before_placement():
    collected = _base()
    assert next_goal(collected) is S.ASK_MORE_ELEMENTS


def test_gather_goal_skipped_once_offered():
    collected = {**_base(), "elements_offered": True}
    assert next_goal(collected) is S.ASK_PLACEMENT_ZONE


def test_gather_states_are_gates():
    from app.services.conversation.goal_planner import GATE_STATES
    assert S.ASK_MORE_ELEMENTS in GATE_STATES
    assert S.ADD_ELEMENTS_MODE in GATE_STATES
