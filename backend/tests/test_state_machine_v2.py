import pytest

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S
from tests.canvas_step_helpers import satisfy, seed_for


def _seed(**over):
    c = {"flow_mode": "canvas"}
    c.update(over)
    return c


def test_empty_session_asks_name():
    assert v2.next_step(_seed()).id is S.ASK_NAME


def test_name_then_intro_then_logo_face():
    assert v2.next_step(_seed(name="Sam")).id is S.SHOW_INTRO
    assert v2.next_step(_seed(name="Sam", intro_ack=True)).id is S.ASK_HAS_LOGO
    assert v2.next_step(_seed(name="Sam", intro_ack=True, has_logo=True)).id is S.ASK_LOGO_PLACEMENT


def test_face_answered_moves_to_adjust():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, pending_logo={"face": "back"})
    assert v2.next_step(c).id is S.LOGO_ADJUST


def test_placed_moves_to_logo_bg():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, pending_logo={"face": "back", "placed": True})
    assert v2.next_step(c).id is S.ASK_LOGO_BG


def test_logo_loop_reopens_placement_when_another_wanted():
    # "yes" clears another_logo and re-seeds pending_logo (Task 4's apply);
    # the router must walk BACK to the face question on its own.
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos=[{"face": "back", "placed": True}],
              pending_logo={})
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_logos_done_falls_through_to_decor():
    # email_captured=True: a placed logo now gates ASK_EMAIL between the logo
    # loop and the decor loop, so it must be resolved for this test to isolate
    # what it actually targets — that the logo steps themselves are skipped.
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos=[{"face": "back", "placed": True}],
              pending_logo=None, logos_done=True, email_captured=True)
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_quantity_zero_counts_as_answered():
    # "Not sure" -> 0 is a real answer; presence, not truthiness.
    # email_captured=True so ask_email (design phase closed, earlier in the
    # registry) is not the intercept — this must genuinely exercise "0 is a
    # real answer" by landing on the step that follows a satisfied quantity.
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True, decor_done=True,
              email_captured=True, quantity=0, decoration_done=True)
    assert v2.next_step(c).id is S.NEEDED_BY


def test_missing_quantity_re_asks():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True, decor_done=True,
              email_captured=True)
    assert v2.next_step(c).id is S.ASK_QUANTITY


def test_email_is_skipped_before_any_element_is_placed():
    # Right after the intro, no element yet: the email step must not fire.
    c = _seed(name="Sam", intro_ack=True, has_logo=True)
    assert v2.next_step(c).id is not S.ASK_EMAIL


def test_email_fires_right_after_the_first_logo_is_placed():
    # First logo placed (pending_logo.placed) + its bg answered -> email is next,
    # before "add another logo".
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"})
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_email_fires_right_after_the_first_text_element_on_the_text_only_path():
    # Text-only: logo loop closed, first decor placed -> email is next.
    c = _seed(name="Sam", intro_ack=True, has_logo=False, logos_done=True,
              pending_logo=None, decor_choice="text", decor_placed=True)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_email_step_is_satisfied_once_captured():
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"},
              email_captured=True)
    assert v2.next_step(c).id is not S.ASK_EMAIL


def test_finalize_unreachable_without_email_captured():
    # The load-bearing invariant. Every earlier slot filled, email not captured.
    # `logos` carries first-element evidence (the email gate rides the first
    # placement) — has_logo/logos_done alone describe a closed loop, not proof
    # anything was ever placed in it.
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True, decor_done=True,
              logos=[{"face": "front", "placed": True}],
              quantity=50, decoration_done=True, purpose="team caps", email="sam@example.com")
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_finalize_reached_when_everything_done():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True, decor_done=True,
              quantity=50, decoration_done=True, email_captured=True, needed_by="ASAP",
              purpose="team caps", design_confirmed=True, quote_requested=True)
    assert v2.next_step(c).id is S.FINALIZE_CANVAS


def test_email_fires_when_the_design_phase_closes_with_nothing_placed():
    # The decline-everything path: no logo, no decoration, nothing placed.
    # Email must still be asked before finalize — the invariant holds on EVERY path.
    c = _seed(name="Sam", intro_ack=True, has_logo=False, logos_done=True,
              pending_logo=None, decor_done=True, quantity=50,
              decoration_done=True, needed_by="ASAP", purpose="team caps")
    assert v2.next_step(c).id is S.ASK_EMAIL


def _seed_at_review(**over):
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"},
              logos_done=True, decor_done=True, quantity=50, decoration_done=True,
              email_captured=True, needed_by="ASAP", purpose="team caps")
    c.update(over)
    return c


def test_review_is_asked_after_purpose():
    assert v2.next_step(_seed_at_review()).id is S.REVIEW_DESIGN


def test_confirming_review_advances_to_request_quote():
    assert v2.next_step(_seed_at_review(design_confirmed=True)).id is S.REQUEST_QUOTE


def test_rework_routes_to_the_canvas_rework_step():
    assert v2.next_step(_seed_at_review(design_rework=True)).id is S.REWORK_CANVAS


def test_finishing_rework_returns_to_review():
    # design_rework cleared, not yet confirmed -> back to REVIEW_DESIGN.
    assert v2.next_step(_seed_at_review(design_rework=False)).id is S.REVIEW_DESIGN


def test_router_walks_every_step_in_declared_order():
    # Exhaustive order guarantee: satisfying each step in turn must yield the
    # next one, and never a step positioned after an unmet one.
    #
    # REWORK_CANVAS is the one loop-only step: it is reached solely via
    # design_rework=True at REVIEW_DESIGN, and its own "Done" answer loops BACK
    # to REVIEW_DESIGN rather than continuing forward — so on the straight-
    # through (confirm) path this walk takes, REVIEW_DESIGN's satisfy() already
    # leaves REWORK_CANVAS's own done_when trivially true and it is never the
    # current unmet step. The loop itself is covered by
    # test_rework_routes_to_the_canvas_rework_step and
    # test_finishing_rework_returns_to_review.
    c = _seed()
    for step in cs.REGISTRY:
        if step.id is S.REWORK_CANVAS:
            continue
        assert v2.next_step(c).id is step.id, f"expected {step.id}"
        satisfy(c, step)


def test_v2_owned_is_the_registry_plus_greeting():
    assert v2.V2_OWNED == frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}
    assert S.OFFER_REFINE not in v2.V2_OWNED     # shared tail stays v1's


def test_progress_collapses_loop_steps_onto_their_anchor():
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    # ASK_HAS_LOGO and ASK_LOGO_PLACEMENT both have progress step 3
    assert v2.progress_for(cs.by_id(S.ASK_HAS_LOGO)) == {"step": 3, "total": total}
    for sid in (S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 3, "total": total}
    for sid in (S.ASK_ADD_DECOR, S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 4, "total": total}
    assert v2.progress_for(cs.by_id(S.FINALIZE_CANVAS)) == {"step": total, "total": total}


def test_progress_v2_is_state_keyed_and_survives_a_tail_state():
    # sessions.py's canvas-finalize route calls this with GENERATING, which has
    # NO registry step. It must report "complete", not explode.
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    assert v2.progress_v2(S.GENERATING, {}) == {"step": total, "total": total}
    assert v2.progress_v2(S.ASK_QUANTITY, {}) == {"step": 5, "total": total}


def test_tool_steps_hand_over_exactly_one_tool():
    d = v2.directive_for(cs.by_id(S.LOGO_ADJUST), {"has_logo": True, "pending_logo": {"face": "back"}})
    assert d["allowed_tools"] == ["upload"]
    assert d["target_face"] == "back"
    assert d["auto_open"] == "upload"
    assert d["show_done"] is True


def test_face_question_enables_upload_but_does_not_auto_open_it():
    # Conflating these was a shipped bug: the file dialog opened before the face
    # was answered, so the logo landed on whatever face was already active.
    d = v2.directive_for(cs.by_id(S.ASK_LOGO_PLACEMENT), {"has_logo": True})
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


def test_rework_directive_unlocks_all_tools():
    d = v2.directive_for(cs.by_id(S.REWORK_CANVAS), {"design_rework": True})
    assert set(d["allowed_tools"]) == {"upload", "text", "shape"}
    assert d["show_done"] is True
    assert d["unlock_all"] is True


def test_non_rework_directive_does_not_unlock_all():
    d = v2.directive_for(cs.by_id(S.ASK_QUANTITY), {})
    assert d["unlock_all"] is False


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
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam", "has_logo": True})
    assert prompts.V2_TOOL_TIPS["upload"] in out


def test_the_ack_can_never_paraphrase_the_tip_away():
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam", "has_logo": True},
                 ack="Nice — the back's a great spot.")
    assert out.startswith("Nice — the back's a great spot.")
    assert prompts.V2_TOOL_TIPS["upload"] in out       # concatenated, not generated


def test_reply_falls_back_to_bare_copy_without_an_ack():
    out = _reply(S.ASK_QUANTITY)
    assert out == "How many caps are you after?"


def test_reply_interpolates_name_persona_and_intro():
    assert "Sam" in _reply(S.ASK_HAS_LOGO, {"name": "Sam"})
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


def test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable():
    """LOAD-BEARING. Surface.tsx:111-113 locks every unlocked element when the
    flow leaves an editing step (v2Editing = allowedTools.length > 0), and a
    locked layer can't be selected (canvasStore.ts:36). The "Remove background"
    toggle lives in SelectedToolbar, which only renders for a SELECTED element.
    Drop this tool and the customer is told to tick a toggle they cannot reach —
    a failure invisible from the backend. Do not "tidy" the tool away.
    """
    step = cs.by_id(S.ASK_LOGO_BG)
    d = v2.directive_for(step, {"pending_logo": {"face": "back", "placed": True}})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] is None          # or the file picker reopens
    assert d["target_face"] == "back"
    assert d["instructions"] == prompts.V2_BG_INSTRUCTIONS   # not the upload tip


def test_ask_logo_bg_copy_does_not_append_the_upload_tip():
    step = cs.by_id(S.ASK_LOGO_BG)
    reply = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="hi")
    assert "Upload image" not in reply
    assert "background" in reply.lower()


def test_reply_defaults_the_name_when_unknown():
    assert "there" in _reply(S.ASK_HAS_LOGO, {})


def test_logo_adjust_does_not_duplicate_its_tip():
    # LOGO_ADJUST is the one step excluded from the tip append: its `ask` copy
    # already carries the drag/resize/rotate instructions inline, so appending
    # V2_TOOL_TIPS["upload"] would say it all twice. (The customer still gets the
    # "tap the button" instruction implicitly — this step auto-opens the picker.)
    out = _reply(S.LOGO_ADJUST, {"name": "Sam", "has_logo": True, "pending_logo": {"face": "front"}})
    assert prompts.V2_TOOL_TIPS["upload"] not in out
    assert "drag to move" in out and "Done" in out


def test_decor_adjust_reply_matches_its_registry_copy():
    # Guards the DRY fix: the step's copy is read from the registry, not re-typed
    # in reply_for, so the two can never silently diverge.
    step = cs.by_id(S.DECOR_ADJUST)
    out = _reply(S.DECOR_ADJUST, {"has_logo": True, "logos_done": True, "decor_choice": "shape"})
    assert out == f"{prompts.V2_TOOL_TIPS['shape']} {step.ask}"


def _multi_step():
    """A throwaway registry record — the mechanism is tested without depending
    on Task 6's ASK_DECORATION."""
    return cs.Step(
        id=S.ASK_DECORATION,
        ask="pick some",
        chips_from=lambda c: tuple(
            cs.Chip(n, {"decoration_types": [n]})
            for n in (c.get("decoration_options") or [])
        ),
        multiselect=True,
        slots=("decoration_types",),
        done_when=lambda c: False,
    )


def test_chips_from_builds_chips_out_of_collected():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    labels = [ch.label for ch in cs.chips_of(_multi_step(), c)]
    assert labels == ["Embroidery", "Screen Print"]


def test_static_chips_are_unaffected_by_chips_of():
    step = cs.by_id(S.ASK_QUANTITY)
    assert cs.chips_of(step, {}) == step.chips


def test_multiselect_resolves_a_comma_joined_selection_in_order():
    """The UI ships `decoSel.join(', ')` (ChatColumn.submitDeco:274)."""
    c = {"decoration_options": ["Embroidery", "Screen Print", "Vinyl"]}
    fields = v2.resolve_chip(_multi_step(), "Screen Print, Embroidery", c)
    assert fields == {"decoration_types": ["Screen Print", "Embroidery"]}


def test_multiselect_drops_tokens_that_were_never_offered():
    c = {"decoration_options": ["Embroidery"]}
    fields = v2.resolve_chip(_multi_step(), "Embroidery, Sublimation", c)
    assert fields == {"decoration_types": ["Embroidery"]}


def test_multiselect_resolves_the_uis_empty_continue_sentinel():
    """Continue with nothing selected sends the literal 'none'. It is a string
    WE ship, so it must resolve deterministically — otherwise it falls through
    to the interpreter and stalls under LLMUnavailable."""
    c = {"decoration_options": ["Embroidery"]}
    assert v2.resolve_chip(_multi_step(), "none", c) == {"decoration_types": []}


def test_multiselect_free_text_falls_through_to_the_interpreter():
    c = {"decoration_options": ["Embroidery"]}
    assert v2.resolve_chip(_multi_step(), "whatever looks best", c) is None


def test_public_data_marks_a_multiselect_step_for_the_frontend():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    data = v2.public_data_for(_multi_step(), c)
    assert data["options"] == ["Embroidery", "Screen Print"]
    assert data["multiselect"] is True
    assert data["selected"] == []


def test_public_data_does_not_mark_a_single_select_step_as_multiselect():
    data = v2.public_data_for(cs.by_id(S.ASK_QUANTITY), {})
    assert "multiselect" not in data


def test_decor_adjust_targets_the_face_the_customer_named():
    """Regression: DECOR_ADJUST has always set face_target=True while _face()
    read pending_logo — which is None once the logo loop closes — so text
    silently always targeted "front"."""
    c = {"logos_done": True, "pending_logo": None,
         "decor_choice": "text", "decor_face": "left"}
    d = v2.directive_for(cs.by_id(S.DECOR_ADJUST), c)
    assert d["target_face"] == "left"
    assert d["allowed_tools"] == ["text"]


def test_decor_adjust_targets_the_named_face_for_a_shape_too():
    c = {"logos_done": True, "pending_logo": None,
         "decor_choice": "shape", "decor_face": "right"}
    d = v2.directive_for(cs.by_id(S.DECOR_ADJUST), c)
    assert d["target_face"] == "right"
    assert d["allowed_tools"] == ["shape"]


def test_logo_steps_still_read_the_logo_face():
    """_face is now step-aware; the logo branch must be unaffected."""
    c = {"pending_logo": {"face": "back"}, "decor_face": "left"}
    d = v2.directive_for(cs.by_id(S.LOGO_ADJUST), c)
    assert d["target_face"] == "back"


def test_the_second_logo_does_not_repeat_the_first_ask_verbatim():
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)
    first = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="hi")
    second = v2.reply_for(step, {"name": "Sam", "_asked": ["ask_logo_placement"]},
                          persona="Ricardo", intro="hi")
    assert first != second
    assert "this one" in second.lower()


def test_the_text_tip_puts_the_styling_instruction_on_its_own_line():
    """The tip already named font/size/colour, but as a trailing clause the
    customer read straight past it."""
    tip = prompts.V2_TOOL_TIPS["text"]
    lines = [l for l in tip.split("\n") if l.strip()]
    assert len(lines) == 2
    assert "size" in lines[1] and "colour" in lines[1]


# --- merge_fields: the interpreter must never un-answer an answered step -------
# Root cause of the live 12:24 session loop: the interpreter prompt exposes every
# WRITABLE_SLOT on every turn, and the orchestrator blanket-merged whatever came
# back. At ASK_DECORATION_MIX the answer "no - i just want embroydary" made Haiku
# fill decor_done:false and decoration_mix:false — flags answered turns earlier —
# so first-unmet walked BACKWARD and re-asked two settled questions.

def test_a_falsy_write_from_another_step_cannot_un_answer_a_settled_step():
    """The exact live regression: "no - i just want embroydary" at the mix step."""
    step = cs.by_id(S.ASK_DECORATION_MIX)
    c = seed_for(step)
    assert c["decor_done"] is True             # settled six steps earlier

    fields = v2.merge_fields(step, c, {"decor_done": False,
                                       "decoration_mix_note": "embroidery"})

    assert "decor_done" not in fields          # dropped: not this step's slot
    c.update(fields)
    assert v2.next_step(c).id is not S.ASK_ADD_DECOR


def test_a_step_may_clear_its_own_slot_so_the_mix_can_be_cancelled():
    """Backing out of a mix is the one legitimate falsy write here — the customer
    tapped "I want a mix" then said "actually just embroidery"."""
    step = cs.by_id(S.ASK_DECORATION_MIX)
    c = seed_for(step)

    fields = v2.merge_fields(step, c, {"decoration_mix": False})

    assert fields["decoration_mix"] is False
    c.update(fields)
    assert v2.next_step(c).id is S.ASK_DECORATION   # re-asks the method, not decor


def test_a_volunteered_answer_to_a_later_step_is_still_banked():
    """The guard must not cost v2 its slot-filling flexibility."""
    step = cs.by_id(S.ASK_ADD_DECOR)
    fields = v2.merge_fields(step, {"name": "Sam"}, {"decor_done": True,
                                                     "quantity": 50})
    assert fields == {"decor_done": True, "quantity": 50}


def test_a_truthy_correction_to_a_settled_slot_is_still_allowed():
    """Only truthy->falsy un-answers a step; 50 -> 100 keeps ask_quantity done."""
    step = cs.by_id(S.ASK_DECORATION)
    fields = v2.merge_fields(step, {"quantity": 50}, {"quantity": 100})
    assert fields == {"quantity": 100}


def test_needed_by_enum_member_exists():
    assert S.NEEDED_BY.value == "needed_by"


def test_needed_by_has_a_progress_slot_immediately_before_purpose():
    path = v2._PROGRESS_PATH
    assert S.NEEDED_BY in path
    assert path.index(S.NEEDED_BY) == path.index(S.ASK_PURPOSE) - 1
    assert len(path) == 8   # email left the path; it rides the design phase now


def test_needed_by_is_asked_after_email_and_before_purpose():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True,
              decor_done=True, quantity=50, decoration_done=True,
              email_captured=True)
    assert v2.next_step(c).id is S.NEEDED_BY
    c["needed_by"] = "ASAP"
    assert v2.next_step(c).id is S.ASK_PURPOSE


def test_needed_by_is_not_satisfied_by_an_empty_answer():
    """`done_when` must read truthiness, not presence. `quantity` uses presence
    deliberately because 0 is a real answer — `needed_by` has no such falsy-real
    value, so an interpreter write of "" on an EARLIER step would otherwise mark
    the step answered and silently skip the question, losing the timeframe sales
    needs. The step's own comment already claims "any non-empty answer"."""
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True,
              decor_done=True, quantity=50, decoration_done=True,
              email_captured=True, needed_by="")
    assert v2.next_step(c).id is S.NEEDED_BY
    c["needed_by"] = None
    assert v2.next_step(c).id is S.NEEDED_BY


# --- Workstream D: config-aware compose (pure, plain dicts) --------------------
# effective_registry is a pure function of (config, cs.REGISTRY) — no collected,
# no DB, no LLM — so every case below is a plain-dict unit test.

def _flow(*pairs):
    """A canvas_flow config from (id, enabled) pairs."""
    return {"steps": [{"id": i, "enabled": e} for i, e in pairs]}


def test_effective_registry_is_identity_without_config():
    assert v2.effective_registry(None) is cs.REGISTRY
    assert v2.effective_registry({}) is cs.REGISTRY
    # A config that names nothing composes back to the identical tuple.
    assert v2.effective_registry({"steps": []}) == cs.REGISTRY


def test_effective_registry_keeps_every_locked_step_in_place():
    # Reorder the configurable subset; every non-configurable step must keep its
    # exact relative position. Nothing crosses a locked step.
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_quantity", True)))
    locked_before = [s.id for s in cs.REGISTRY if s.id.value not in cs.CONFIGURABLE_STEP_IDS]
    locked_after = [s.id for s in eff if s.id.value not in cs.CONFIGURABLE_STEP_IDS]
    assert locked_after == locked_before


def test_effective_registry_keeps_locked_steps_at_their_exact_index():
    """Stronger than relative order: a locked step must keep its literal index,
    which is what guarantees no configurable step is ever spliced into a locked
    position (the entanglement the Complexity gate exists to catch)."""
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_quantity", True)))
    assert len(eff) == len(cs.REGISTRY)
    for i, (before, after) in enumerate(zip(cs.REGISTRY, eff)):
        if before.id.value not in cs.CONFIGURABLE_STEP_IDS:
            assert after is before, f"locked step moved at index {i}"


def test_effective_registry_reorders_only_the_configurable_slots():
    # ask_quantity naturally sits at an earlier index than ask_purpose. Asking
    # for purpose first must put purpose in the earliest configurable slot and
    # quantity in a later one — without moving any locked step.
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_quantity", True)))
    order = [s.id.value for s in eff if s.id.value in cs.CONFIGURABLE_STEP_IDS]
    assert order.index("ask_purpose") < order.index("ask_quantity")


def test_effective_registry_drops_a_disabled_step():
    eff = v2.effective_registry(_flow(("ask_purpose", False)))
    ids = [s.id.value for s in eff]
    assert "ask_purpose" not in ids
    assert "ask_quantity" in ids            # untouched configurable steps remain
    assert len(eff) == len(cs.REGISTRY) - 1     # exactly one step removed


def test_effective_registry_ignores_unmentioned_configurable_steps():
    # Only ask_purpose is named; the rest keep default order + enabled.
    eff = v2.effective_registry(_flow(("ask_purpose", True)))
    assert {s.id.value for s in eff} == {s.id.value for s in cs.REGISTRY}


def test_effective_registry_ignores_a_locked_or_unknown_id():
    """Defence in depth. `branding.validate_brand` rejects these at the admin
    door, but a hand-edited stores.brand row must not be able to move a locked
    step either — the compose only ever reads CONFIGURABLE_STEP_IDS."""
    eff = v2.effective_registry(_flow(("ask_email", False), ("not_a_step", True)))
    assert eff == cs.REGISTRY


def test_effective_registry_ignores_duplicate_ids():
    eff = v2.effective_registry(_flow(("ask_purpose", True), ("ask_purpose", True)))
    assert [s.id.value for s in eff].count("ask_purpose") == 1
    assert len(eff) == len(cs.REGISTRY)


def test_next_step_default_matches_the_bare_registry_walk():
    # The baseline guarantee: next_step(collected) with no config is unchanged.
    # REWORK_CANVAS is skipped here for the same reason as
    # test_router_walks_every_step_in_declared_order: it's loop-only, and
    # REVIEW_DESIGN's satisfy() (confirm, not rework) already leaves it
    # trivially done.
    c = {"flow_mode": "canvas"}
    for step in cs.REGISTRY:
        if step.id is S.REWORK_CANVAS:
            continue
        assert v2.next_step(c).id is step.id
        assert v2.next_step(c, None).id is step.id
        satisfy(c, step)


def test_next_step_honours_a_reordering_config():
    # With purpose-before-quantity, a session that has answered everything up to
    # the first configurable slot is asked purpose, not quantity.
    # email_captured=True: the design phase is already closed (logos_done +
    # decor_done), so ask_email (earlier in the registry) would otherwise
    # intercept before either configurable slot is reached.
    cfg = _flow(("ask_purpose", True), ("ask_quantity", True))
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "email_captured": True}
    assert v2.next_step(c).id is S.ASK_QUANTITY          # default order
    assert v2.next_step(c, cfg).id is S.ASK_PURPOSE      # configured order


def test_next_step_skips_a_disabled_step():
    cfg = _flow(("ask_purpose", False))
    # Everything answered except purpose; purpose disabled -> finalize (given
    # email captured). Locked steps still gate normally.
    # `needed_by` (workstream B) and `quote_requested` (workstream C) are seeded
    # because both are locked steps flanking ask_purpose — without them the walk
    # stops on one of THEM and the test would prove nothing about the disabled
    # step. Seeding keeps ask_purpose the only variable, which is the claim.
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "quantity": 12, "decoration_done": True, "email_captured": True,
         "needed_by": "ASAP", "design_confirmed": True, "quote_requested": True}
    assert v2.next_step(c).id is S.ASK_PURPOSE           # asked by default
    assert v2.next_step(c, cfg).id is S.FINALIZE_CANVAS  # skipped when disabled


def test_next_step_still_blocks_finalize_without_email_under_config():
    # The load-bearing invariant survives reordering: email is locked before
    # finalize, so no config can reach finalize without email_captured.
    # `logos` carries first-element evidence — without it the email step skips
    # itself (nothing placed yet) rather than blocking, proving nothing about
    # the config wiring this test targets.
    cfg = _flow(("ask_purpose", True), ("ask_quantity", True))
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "logos": [{"face": "front", "placed": True}],
         "quantity": 12, "decoration_done": True, "purpose": "team caps"}
    assert v2.next_step(c, cfg).id is S.ASK_EMAIL


def test_no_config_can_reach_finalize_without_email():
    """Exhaustive over every enable/disable+order permutation of the safe
    subset: FINALIZE_CANVAS is unreachable while email_captured is falsy."""
    import itertools

    ids = sorted(cs.CONFIGURABLE_STEP_IDS)
    # No fabricated `logos` here on purpose: this is the exhaustive proof, and
    # must exercise the zero-element (decline-everything) branch — the
    # design-phase backstop is what keeps email required on that branch, not
    # first-element evidence.
    c = {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
         "logos_done": True, "pending_logo": None, "decor_done": True,
         "quantity": 12, "decoration_done": True, "purpose": "team caps",
         "needed_by": "next month"}
    for order in itertools.permutations(ids):
        for flags in itertools.product([True, False], repeat=len(order)):
            cfg = _flow(*zip(order, flags))
            assert v2.next_step(c, cfg).id is S.ASK_EMAIL
