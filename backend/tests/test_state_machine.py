"""Pure-logic tests for the conversation state machine. No external services."""
from __future__ import annotations

from app.services.conversation.state_machine import (
    ConversationState as S,
)
from app.services.conversation.state_machine import (
    advance_state,
    allowed_backtracks,
    progress,
)


def test_youth_branch():
    assert advance_state(S.CHECK_YOUTH, {"youth_flag": True}) is S.YOUTH_REFERRAL
    assert advance_state(S.CHECK_YOUTH, {"youth_flag": False}) is S.ASK_QUANTITY


def test_decoration_engine_by_quantity():
    assert advance_state(S.DECORATION_ENGINE, {"quantity": 1}) is S.WARN_PRINT_SETUP
    assert advance_state(S.DECORATION_ENGINE, {"quantity": 6}) is S.RECOMMEND_DECORATION
    assert advance_state(S.DECORATION_ENGINE, {"quantity": 24}) is S.RECOMMEND_EMBROIDERY


def test_has_logo_branch():
    assert advance_state(S.ASK_HAS_LOGO, {"has_logo": True}) is S.UPLOAD_LOGO
    assert advance_state(S.ASK_HAS_LOGO, {"has_logo": False}) is S.DESCRIBE_DESIGN


def test_pin_branch():
    assert advance_state(S.ASK_PIN_ANNOTATION, {"wants_pins": True}) is S.PIN_ANNOTATE_MODE
    assert advance_state(S.ASK_PIN_ANNOTATION, {"wants_pins": False}) is S.GENERATING


def test_email_capture_branch():
    # The email is asked for in the GENERATING message and captured inline:
    # once we have it we move to the verification step (no separate form).
    assert advance_state(S.GENERATING, {"email_captured": True}) is S.VERIFY_EMAIL
    # No usable email yet → fall through to ASK_EMAIL to ask once more.
    assert advance_state(S.GENERATING, {}) is S.ASK_EMAIL
    # ASK_EMAIL behaves the same: captured → verify, otherwise re-ask.
    assert advance_state(S.ASK_EMAIL, {"email_captured": True}) is S.VERIFY_EMAIL
    assert advance_state(S.ASK_EMAIL, {}) is S.ASK_EMAIL


def test_email_verification_branch():
    # Verification completes out-of-band (emailed link), so the chat rests at
    # VERIFY_EMAIL until email_verified flips.
    assert advance_state(S.VERIFY_EMAIL, {"email_verified": True}) is S.EMAIL_VERIFIED
    assert advance_state(S.VERIFY_EMAIL, {}) is S.VERIFY_EMAIL


def test_upsell_caps_at_max():
    assert advance_state(S.UPSELL_PROMPT, {"wants_upsell": True}, upsell_count=0) is S.ASK_PLACEMENT_ZONE
    assert advance_state(S.UPSELL_PROMPT, {"wants_upsell": True}, upsell_count=2) is S.SESSION_END
    assert advance_state(S.UPSELL_PROMPT, {"wants_upsell": False}, upsell_count=0) is S.SESSION_END


def test_linear_progression():
    assert advance_state(S.GREETING, {}) is S.ASK_NAME
    assert advance_state(S.ASK_NAME, {}) is S.ASK_PURPOSE
    assert advance_state(S.CONFIRM_DECORATION, {}) is S.ASK_HAS_LOGO


def test_backtracks_never_past_name():
    for state in S:
        for target in allowed_backtracks(state):
            assert target not in (S.GREETING,)


def test_progress_path_excludes_defaulted_position():
    # describe branch: name, purpose, quantity, decoration, has_logo,
    # describe_design, placement_zone, email = 8 steps (position is defaulted).
    collected = {"has_logo": False}
    total = progress(S.ASK_NAME, collected)["total"]
    assert total == 8


def test_progress_counts_logo_branch():
    # logo branch adds upload + remove_bg, drops describe:
    # name, purpose, quantity, decoration, has_logo, upload, remove_bg,
    # placement_zone, email = 9 steps.
    collected = {"has_logo": True}
    assert progress(S.ASK_NAME, collected)["total"] == 9


def test_progress_position_backtrack_resolves_like_zone():
    # ASK_PLACEMENT_POSITION is a backtrack target; its progress must match its
    # merged sibling ASK_PLACEMENT_ZONE, not fall back to step 1.
    collected = {"has_logo": False}
    zone = progress(S.ASK_PLACEMENT_ZONE, collected)
    pos = progress(S.ASK_PLACEMENT_POSITION, collected)
    assert pos == zone
    assert pos["step"] != 1


def test_more_elements_branch():
    assert advance_state(S.ASK_MORE_ELEMENTS, {"wants_more_elements": True}) is S.ADD_ELEMENTS_MODE
    assert advance_state(S.ASK_MORE_ELEMENTS, {"wants_more_elements": False}) is S.ASK_PLACEMENT_ZONE


def test_add_elements_loops_then_exits():
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": True}) is S.ADD_ELEMENTS_MODE
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": False}) is S.ASK_PLACEMENT_ZONE


def test_design_source_paths_reach_more_elements():
    # Both the logo path (via remove-bg) and the describe path funnel into the
    # gather loop, not straight to placement.
    assert advance_state(S.ASK_REMOVE_BG, {}) is S.ASK_MORE_ELEMENTS
    assert advance_state(S.DESCRIBE_DESIGN, {}) is S.ASK_MORE_ELEMENTS


def test_post_verification_collapses_to_offer_refine():
    # After verification the chat must walk EMAIL_VERIFIED -> SEND_PREVIEW_EMAIL
    # -> SHOW_DESIGN without resting, landing on OFFER_REFINE.
    from app.services.conversation.state_machine import AUTO_ADVANCE_STATES
    state = advance_state(S.VERIFY_EMAIL, {"email_verified": True})  # EMAIL_VERIFIED
    for _ in range(10):
        if state in AUTO_ADVANCE_STATES:
            state = advance_state(state, {})
            continue
        break
    assert state is S.OFFER_REFINE
