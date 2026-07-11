from app.services.conversation.state_machine import (
    ConversationState as S,
    advance_and_skip,
    progress,
)


def test_progress_describe_branch_total():
    # has_logo False -> describe branch (no upload/remove-bg steps).
    # position is defaulted (never its own turn), so it is not counted.
    collected = {"has_logo": False}
    p = progress(S.ASK_NAME, collected)
    assert p["step"] == 1
    assert p["total"] == 8  # name,purpose,qty,decoration,has_logo,describe,zone,email


def test_progress_upload_branch_is_longer():
    collected = {"has_logo": True}
    p = progress(S.ASK_PLACEMENT_ZONE, collected)
    assert p["total"] == 9  # upload branch adds remove-bg
    assert p["step"] == 8


def test_progress_post_design_is_complete():
    p = progress(S.SHOW_DESIGN, {"has_logo": False})
    assert p["step"] == p["total"]


def test_advance_and_skip_skips_already_answered_question():
    # Placement zone already known -> after position question we should not
    # re-ask a filled question; verify a filled zone is skipped when advancing
    # from a state whose next is ask_placement_zone. describe_design now funnels
    # through the (unanswered) additional-elements gather question first, so the
    # walk stops there rather than skipping all the way to placement position.
    collected = {"has_logo": False, "placement_zone": "front_panel"}
    nxt = advance_and_skip(S.DESCRIBE_DESIGN, collected)
    assert nxt == S.ASK_MORE_ELEMENTS

    # Once the gather question is answered (no more elements wanted), the
    # already-filled zone is skipped straight to placement position.
    collected["wants_more_elements"] = False
    nxt = advance_and_skip(S.ASK_MORE_ELEMENTS, collected)
    assert nxt == S.ASK_PLACEMENT_POSITION  # zone skipped because already filled


def test_progress_pin_annotation_does_not_reset():
    # Every session passes through pin-annotation after placement-position;
    # it must not drop back to step 1 — it's post-questionnaire (step == total).
    for st in (S.ASK_PIN_ANNOTATION, S.PIN_ANNOTATE_MODE):
        p = progress(st, {"has_logo": False})
        assert p["step"] == p["total"], st
