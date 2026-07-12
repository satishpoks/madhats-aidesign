from app.services.conversation.state_machine import (
    ConversationState as S,
    advance_and_skip,
    progress,
)


def test_progress_describe_branch_total():
    # has_logo False -> describe branch (no upload/remove-bg steps).
    # position is defaulted (never its own turn), so it is not counted.
    # Global placement is retired from the forward path (placement is
    # per-element now), so the zone step is gone too.
    collected = {"has_logo": False}
    p = progress(S.ASK_NAME, collected)
    assert p["step"] == 1
    assert p["total"] == 7  # name,purpose,qty,decoration,has_logo,describe,email


def test_progress_upload_branch_is_longer():
    # ASK_PLACEMENT_ZONE is now a legacy/backtrack-only state; it still
    # normalizes to the branch's design-source step (ASK_REMOVE_BG here).
    collected = {"has_logo": True}
    p = progress(S.ASK_PLACEMENT_ZONE, collected)
    assert p["total"] == 8  # upload branch adds remove-bg; zone retired
    assert p["step"] == 7


def test_progress_post_design_is_complete():
    p = progress(S.SHOW_DESIGN, {"has_logo": False})
    assert p["step"] == p["total"]


def test_advance_and_skip_skips_already_answered_question():
    # describe_design now funnels directly into the per-element deep-dive
    # (global placement is retired from the forward path -- placement is
    # asked per element inside the deep-dive, owned by the orchestrator, not
    # by this gather-loop skip logic).
    collected = {"has_logo": False, "placement_zone": "front_panel"}
    nxt = advance_and_skip(S.DESCRIBE_DESIGN, collected)
    assert nxt == S.ELEMENT_DEEPDIVE


def test_progress_pin_annotation_still_post_question():
    # Pin states are hidden from the flow but remain post-questionnaire, so if
    # ever reached they read as complete (step == total), never step 1.
    for st in (S.ASK_PIN_ANNOTATION, S.PIN_ANNOTATE_MODE):
        p = progress(st, {"has_logo": False})
        assert p["step"] == p["total"], st


def test_progress_early_email_is_the_email_step():
    # SAVE_PROGRESS_EMAIL is the email step in both branches (last counted step).
    p = progress(S.SAVE_PROGRESS_EMAIL, {"has_logo": False})
    assert p["step"] == p["total"] == 7


def test_progress_terminal_ask_email_fallback_is_complete():
    # The rare terminal fallback ask must not drop back to step 1.
    p = progress(S.ASK_EMAIL, {"has_logo": False})
    assert p["step"] == p["total"]
