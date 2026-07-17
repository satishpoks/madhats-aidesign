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
    # describe_design, email = 7 steps (position is defaulted; global
    # placement is retired from the forward path -- placement is per-element
    # now, inside the deep-dive).
    collected = {"has_logo": False}
    total = progress(S.ASK_NAME, collected)["total"]
    assert total == 7


def test_progress_counts_logo_branch():
    # logo branch adds upload + remove_bg, drops describe:
    # name, purpose, quantity, decoration, has_logo, upload, remove_bg,
    # email = 8 steps (global placement retired from the forward path).
    collected = {"has_logo": True}
    assert progress(S.ASK_NAME, collected)["total"] == 8


def test_progress_position_backtrack_resolves_like_zone():
    # ASK_PLACEMENT_POSITION is a backtrack target; its progress must match its
    # merged sibling ASK_PLACEMENT_ZONE, not fall back to step 1.
    collected = {"has_logo": False}
    zone = progress(S.ASK_PLACEMENT_ZONE, collected)
    pos = progress(S.ASK_PLACEMENT_POSITION, collected)
    assert pos == zone
    assert pos["step"] != 1


def test_progress_holds_steady_during_gather_loop():
    collected = {"has_logo": False}
    zone = progress(S.ASK_PLACEMENT_ZONE, collected)
    assert progress(S.ASK_MORE_ELEMENTS, collected) == zone
    assert progress(S.ADD_ELEMENTS_MODE, collected) == zone
    assert zone["step"] != 1


# NOTE: test_more_elements_branch (asserted ASK_MORE_ELEMENTS -> ADD_ELEMENTS_MODE
# / ASK_PLACEMENT_ZONE on wants_more_elements) is superseded by
# test_deepdive_entered_when_pending_element and
# test_more_elements_exit_offers_pins_then_generates below, which cover the new
# pending_element/pin_offered-driven routing.


def test_add_elements_mode_is_legacy_dead_end():
    # ADD_ELEMENTS_MODE is retired from the forward flow: the per-element
    # deep-dive (ELEMENT_DEEPDIVE) replaced it. No branch handles it anymore,
    # so it falls through to the default successor (its own first TRANSITIONS
    # entry), which is itself -- it is no longer reachable going forward.
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": True}) is S.ADD_ELEMENTS_MODE
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": False}) is S.ADD_ELEMENTS_MODE


def test_design_source_paths_reach_more_elements():
    # Both the logo path (via remove-bg) and the describe path funnel into the
    # per-element deep-dive now, not the retired ADD_ELEMENTS_MODE gather loop.
    assert advance_state(S.ASK_REMOVE_BG, {}) is S.ELEMENT_DEEPDIVE
    assert advance_state(S.DESCRIBE_DESIGN, {}) is S.ELEMENT_DEEPDIVE


def test_deepdive_entered_when_pending_element():
    assert advance_state(S.ASK_MORE_ELEMENTS, {"pending_element": {"type": "text"}}) is S.ELEMENT_DEEPDIVE


def test_deepdive_loops_until_element_complete():
    assert advance_state(S.ELEMENT_DEEPDIVE, {"pending_element": {"type": "text"}}) is S.ELEMENT_DEEPDIVE
    # pending cleared (element completed by orchestrator) -> back to the offer
    assert advance_state(S.ELEMENT_DEEPDIVE, {}) is S.ASK_MORE_ELEMENTS


def test_more_elements_exit_generates_pin_hidden():
    # Pin placement is hidden: no pending element -> straight to generation.
    assert advance_state(S.ASK_MORE_ELEMENTS, {}) is S.GENERATING
    assert advance_state(S.ASK_MORE_ELEMENTS, {"pin_offered": True}) is S.GENERATING


def test_design_sources_funnel_into_deepdive():
    assert advance_state(S.UPLOAD_LOGO, {}) is S.ELEMENT_DEEPDIVE
    assert advance_state(S.DESCRIBE_DESIGN, {}) is S.ELEMENT_DEEPDIVE


def test_progress_steady_during_deepdive_and_placement_retired():
    # Global placement is off the path; the deep-dive holds the counter at the
    # design-source step for both branches.
    describe = {"has_logo": False}
    assert progress(S.ELEMENT_DEEPDIVE, describe) == progress(S.DESCRIBE_DESIGN, describe)
    assert progress(S.ASK_MORE_ELEMENTS, describe) == progress(S.DESCRIBE_DESIGN, describe)
    logo = {"has_logo": True}
    assert progress(S.ELEMENT_DEEPDIVE, logo) == progress(S.ASK_REMOVE_BG, logo)
    # describe branch total drops by one now that ASK_PLACEMENT_ZONE is gone: 7
    assert progress(S.ASK_NAME, describe)["total"] == 7


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


def test_composite_preview_confirm_goes_to_generating():
    assert advance_state(S.COMPOSITE_PREVIEW, {"composite_confirmed": True}) is S.GENERATING


def test_composite_preview_tweak_goes_back_to_more_elements():
    assert advance_state(S.COMPOSITE_PREVIEW, {"composite_confirmed": False}) is S.ASK_MORE_ELEMENTS


def test_canvas_design_waits_until_finalized():
    assert advance_state(S.CANVAS_DESIGN, {}) is S.CANVAS_DESIGN
    assert advance_state(S.CANVAS_DESIGN, {"canvas_finalized": True}) is S.ASK_DECORATION


def test_decoration_then_notes_then_generating():
    assert advance_state(S.ASK_DECORATION, {}) is S.ASK_NOTES
    assert advance_state(S.ASK_NOTES, {}) is S.GENERATING


def test_canvas_progress_path():
    collected = {"flow_mode": "canvas"}
    p = progress(S.ASK_DECORATION, collected)
    assert p["total"] == 7          # name,email,purpose,quantity,design,decoration,notes
    assert 1 <= p["step"] <= p["total"]


def test_transitions_table_documents_the_canvas_edit_gate():
    # TRANSITIONS exists purely to document reachability (module docstring at
    # the top of the file). The canvas-edit branch added three new DESCRIBE_
    # CHANGES successors (CONFIRM_CANVAS_EDIT, OFFER_REFINE on refusal, and a
    # self-loop while stalled) and a brand new CONFIRM_CANVAS_EDIT state --
    # both must appear here, mirroring how ASK_CHANGE_METHOD is already listed.
    from app.services.conversation.state_machine import TRANSITIONS

    describe_changes_successors = TRANSITIONS[S.DESCRIBE_CHANGES]
    assert S.CONFIRM_CANVAS_EDIT in describe_changes_successors
    assert S.OFFER_REFINE in describe_changes_successors
    assert S.DESCRIBE_CHANGES in describe_changes_successors

    assert S.CONFIRM_CANVAS_EDIT in TRANSITIONS
    assert set(TRANSITIONS[S.CONFIRM_CANVAS_EDIT]) == {S.REGENERATING, S.DESCRIBE_CHANGES}
