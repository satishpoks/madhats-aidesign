import pytest

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S
from tests.canvas_step_helpers import satisfy


def _seed(**over):
    c = {"flow_mode": "canvas"}
    c.update(over)
    return c


def test_empty_session_asks_name():
    assert v2.next_step(_seed()).id is S.ASK_NAME


def test_name_then_intro_then_logo_face():
    assert v2.next_step(_seed(name="Sam")).id is S.SHOW_INTRO
    assert v2.next_step(_seed(name="Sam", intro_ack=True)).id is S.ASK_LOGO_PLACEMENT


def test_face_answered_moves_to_adjust():
    c = _seed(name="Sam", intro_ack=True, pending_logo={"face": "back"})
    assert v2.next_step(c).id is S.LOGO_ADJUST


def test_placed_moves_to_another_logo():
    c = _seed(name="Sam", intro_ack=True, pending_logo={"face": "back", "placed": True})
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_loop_reopens_placement_when_another_wanted():
    # "yes" clears another_logo and re-seeds pending_logo (Task 4's apply);
    # the router must walk BACK to the face question on its own.
    c = _seed(name="Sam", intro_ack=True, logos=[{"face": "back", "placed": True}],
              pending_logo={})
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_logos_done_falls_through_to_decor():
    c = _seed(name="Sam", intro_ack=True, logos=[{"face": "back", "placed": True}],
              pending_logo=None, logos_done=True)
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_quantity_zero_counts_as_answered():
    # "Not sure" -> 0 is a real answer; presence, not truthiness.
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True, quantity=0)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_missing_quantity_re_asks():
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True)
    assert v2.next_step(c).id is S.ASK_QUANTITY


def test_finalize_unreachable_without_email_captured():
    # The load-bearing invariant. Every earlier slot filled, email not captured.
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True,
              quantity=50, purpose="team caps", email="sam@example.com")
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_finalize_reached_when_everything_done():
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True,
              quantity=50, email_captured=True, purpose="team caps")
    assert v2.next_step(c).id is S.FINALIZE_CANVAS


def test_router_walks_every_step_in_declared_order():
    # Exhaustive order guarantee: satisfying each step in turn must yield the
    # next one, and never a step positioned after an unmet one.
    c = _seed()
    for step in cs.REGISTRY:
        assert v2.next_step(c).id is step.id, f"expected {step.id}"
        satisfy(c, step)


def test_v2_owned_is_the_registry_plus_greeting():
    assert v2.V2_OWNED == frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}
    assert S.OFFER_REFINE not in v2.V2_OWNED     # shared tail stays v1's


def test_progress_collapses_loop_steps_onto_their_anchor():
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    for sid in (S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 3, "total": total}
    for sid in (S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 4, "total": total}
    assert v2.progress_for(cs.by_id(S.FINALIZE_CANVAS)) == {"step": total, "total": total}


def test_progress_v2_is_state_keyed_and_survives_a_tail_state():
    # sessions.py's canvas-finalize route calls this with GENERATING, which has
    # NO registry step. It must report "complete", not explode.
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    assert v2.progress_v2(S.GENERATING, {}) == {"step": total, "total": total}
    assert v2.progress_v2(S.ASK_QUANTITY, {}) == {"step": 5, "total": total}


def test_tool_steps_hand_over_exactly_one_tool():
    d = v2.directive_for(cs.by_id(S.LOGO_ADJUST), {"pending_logo": {"face": "back"}})
    assert d["allowed_tools"] == ["upload"]
    assert d["target_face"] == "back"
    assert d["auto_open"] == "upload"
    assert d["show_done"] is True


def test_face_question_enables_upload_but_does_not_auto_open_it():
    # Conflating these was a shipped bug: the file dialog opened before the face
    # was answered, so the logo landed on whatever face was already active.
    d = v2.directive_for(cs.by_id(S.ASK_LOGO_PLACEMENT), {})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] is None
    assert d["target_face"] == "front"          # default until answered


def test_every_other_owned_step_locks_all_tools():
    # A null directive means "not a v2 turn" and makes the frontend fall back to
    # v1's whole-rail gating + status strip, which showed "Design locked in —
    # finishing up" MID-design. Every owned step must emit a directive.
    for step in cs.REGISTRY:
        d = v2.directive_for(step, {})
        assert d is not None, step.id
        if step.tool is None:
            assert d["allowed_tools"] == [], step.id


def test_decor_directive_follows_the_chosen_tool():
    assert v2.directive_for(cs.by_id(S.DECOR_ADJUST), {"decor_choice": "shape"})["allowed_tools"] == ["shape"]
    assert v2.directive_for(cs.by_id(S.DECOR_ADJUST), {"decor_choice": "text"})["allowed_tools"] == ["text"]


def test_canvas_directive_is_none_for_a_shared_tail_state():
    assert v2.canvas_directive(S.OFFER_REFINE, {}) is None


def test_public_data_chips_come_from_the_registry():
    d = v2.public_data_for(cs.by_id(S.ASK_ANOTHER_LOGO), {})
    assert d["options"] == ["Yes, another logo", "No, that's it"]


def test_public_data_marks_the_intro_continuable_and_finalize_triggering():
    assert v2.public_data_for(cs.by_id(S.SHOW_INTRO), {})["continuable"] is True
    assert v2.public_data_for(cs.by_id(S.FINALIZE_CANVAS), {})["trigger_finalize"] is True


def test_public_data_carries_progress():
    # progress_for itself is covered in Task 2; this asserts it is wired in.
    assert v2.public_data_for(cs.by_id(S.ASK_QUANTITY), {})["progress"]["step"] == 5


def _reply(step_id, collected=None, **kw):
    kw.setdefault("persona", "Ricardo")
    kw.setdefault("intro", "Welcome!")
    return v2.reply_for(cs.by_id(step_id), collected or {}, **kw)


def test_reply_appends_the_tool_tip_verbatim():
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"})
    assert prompts.V2_TOOL_TIPS["upload"] in out


def test_the_ack_can_never_paraphrase_the_tip_away():
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"},
                 ack="Nice — the back's a great spot.")
    assert out.startswith("Nice — the back's a great spot.")
    assert prompts.V2_TOOL_TIPS["upload"] in out       # concatenated, not generated


def test_reply_falls_back_to_bare_copy_without_an_ack():
    out = _reply(S.ASK_QUANTITY)
    assert out == "How many caps are you after?"


def test_reply_interpolates_name_persona_and_intro():
    assert "Sam" in _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"})
    assert "Ricardo" in _reply(S.ASK_NAME, persona="Ricardo")
    assert "Welcome!" in _reply(S.SHOW_INTRO, intro="Welcome!")


def test_reply_uses_retry_copy_once_the_step_has_been_asked():
    first = _reply(S.ASK_NAME)
    again = _reply(S.ASK_NAME, {"_asked": ["ask_name"]})
    assert first != again
    assert again == prompts.V2_ASK_NAME_RETRY


def test_decor_adjust_reply_uses_the_chosen_tool_tip():
    out = _reply(S.DECOR_ADJUST, {"decor_choice": "shape"})
    assert prompts.V2_TOOL_TIPS["shape"] in out
    assert prompts.V2_TOOL_TIPS["text"] not in out


def test_reply_defaults_the_name_when_unknown():
    assert "there" in _reply(S.ASK_LOGO_PLACEMENT, {})


def test_logo_adjust_does_not_duplicate_its_tip():
    # LOGO_ADJUST is the one step excluded from the tip append: its `ask` copy
    # already carries the drag/resize/rotate instructions inline, so appending
    # V2_TOOL_TIPS["upload"] would say it all twice. (The customer still gets the
    # "tap the button" instruction implicitly — this step auto-opens the picker.)
    out = _reply(S.LOGO_ADJUST, {"name": "Sam"})
    assert prompts.V2_TOOL_TIPS["upload"] not in out
    assert "drag to move" in out and "Done" in out


def test_decor_adjust_reply_matches_its_registry_copy():
    # Guards the DRY fix: the step's copy is read from the registry, not re-typed
    # in reply_for, so the two can never silently diverge.
    step = cs.by_id(S.DECOR_ADJUST)
    out = _reply(S.DECOR_ADJUST, {"decor_choice": "shape"})
    assert out == f"{prompts.V2_TOOL_TIPS['shape']} {step.ask}"
