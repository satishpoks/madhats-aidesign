import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


def test_registry_ids_are_unique_and_are_conversation_states():
    ids = [s.id for s in cs.REGISTRY]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, S) for i in ids)


def test_registry_declares_the_v2_flow_in_order():
    assert [s.id for s in cs.REGISTRY] == [
        S.ASK_NAME, S.SHOW_INTRO, S.ASK_HAS_LOGO,
        S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO,
        S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE,
        S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE, S.FINALIZE_CANVAS,
    ]


def test_ask_email_precedes_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert ids.index(S.ASK_EMAIL) < ids.index(S.FINALIZE_CANVAS)


def test_chips_may_set_slots_plus_trusted_flags_the_llm_cannot():
    # Chips are trusted (we authored the label AND its fields), so they may set
    # flags beyond the interpreter's writable set. decor_done is writable by
    # BOTH now (a typed "no more" is just as valid an answer as the chip); only
    # quantity_unsure stays chip-only — it's an annotation ("Not sure" tapped),
    # not something the model should ever infer from free text.
    allowed = cs.WRITABLE_SLOTS | {"quantity_unsure"}
    for step in cs.REGISTRY:
        for chip in step.chips:
            assert set(chip.fields) <= allowed, f"{step.id}: {chip.label}"


def test_terminal_flags_are_not_interpreter_writable():
    # email_captured is the sole gate on FINALIZE_CANVAS — it is set ONLY by
    # _apply_email after a real capture_lead_and_verify, so it must stay out
    # of WRITABLE_SLOTS or the interpreter could fake a lead into existence.
    assert "email_captured" not in cs.WRITABLE_SLOTS
    # quantity_unsure is an annotation ("Not sure" chip), not an answer the
    # customer types, so it stays chip-only too.
    assert "quantity_unsure" not in cs.WRITABLE_SLOTS
    # decor_done, by contrast, IS interpreter-writable (see below) — letting
    # the model record "the customer said no more decoration" is just reading
    # the customer, same as the already-writable another_logo: False.


def test_tool_steps_carry_a_tip_and_tipless_steps_carry_no_tool():
    for step in cs.REGISTRY:
        assert bool(step.tool) == bool(step.tip), step.id


def test_by_id_round_trips():
    assert cs.by_id(S.ASK_ANOTHER_LOGO).id is S.ASK_ANOTHER_LOGO
    assert cs.by_id(S.OFFER_REFINE) is None      # a shared-tail state v2 doesn't own


def _all_chips():
    return [(s, ch) for s in cs.REGISTRY for ch in s.chips]


@pytest.mark.parametrize(
    "step,chip", _all_chips(), ids=lambda v: getattr(v, "label", getattr(v, "id", ""))
)
def test_every_offered_chip_is_understood(step, chip):
    """THE regression test for the live bug.

    "Yes, another logo" is a string WE generated in the chip list and shipped to
    the browser, which handed it straight back — and the old code grepped it to
    find out what we had meant, reading "another" as "no". Enumerated from the
    registry, so a step added later is covered the moment it is declared.
    """
    fields = v2.resolve_chip(step, chip.label, {})
    assert fields == chip.fields, f"{step.id}: {chip.label!r} did not round-trip"


def test_the_exact_bug_yes_another_logo_is_not_a_decline():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "Yes, another logo", {}) == {"another_logo": True}
    assert v2.resolve_chip(step, "No, that's it", {}) == {"another_logo": False}


def test_chip_match_is_case_and_whitespace_insensitive():
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)
    assert v2.resolve_chip(step, "  front  ", {}) == {"logo_face": "front"}


def test_free_text_is_not_a_chip():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "yeah go on then", {}) is None


def test_a_stale_chip_from_another_step_does_not_match():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "Add text", {}) is None


def test_resolve_chip_returns_a_copy_not_the_registry_dict():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    got = v2.resolve_chip(step, "Yes, another logo", {})
    got["another_logo"] = "mutated"
    assert step.chips[0].fields == {"another_logo": True}


# Shared with test_state_machine_v2 — created in Task 2, do NOT re-declare here.
from tests.canvas_step_helpers import seed_for


@pytest.mark.parametrize(
    "step,chip", _all_chips(), ids=lambda v: getattr(v, "label", getattr(v, "id", ""))
)
def test_every_offered_chip_makes_progress(step, chip):
    """Understanding a chip is not enough — it must also move the flow. This is
    the half of the round-trip test that needs the apply hooks."""
    c = seed_for(step)
    assert v2.next_step(c).id is step.id          # precondition: we're on it
    fields = v2.resolve_chip(step, chip.label, c)
    c.update(fields)
    if step.apply:
        step.apply(c, dict(fields), {})
    assert v2.next_step(c).id is not step.id, f"{step.id}: {chip.label!r} did not advance"


@pytest.mark.parametrize("filler", ["ok", "Okay", "yes", "hi there", "sure", "!!", "done"])
def test_filler_never_becomes_a_name(filler):
    """Regression (44e8eda): "ok" became a customer's name in a live session.
    The interpreter proposes; this deterministic guard disposes."""
    c = {"name": filler}                      # as the pre-apply merge leaves it
    cs.by_id(S.ASK_NAME).apply(c, {"name": filler}, {})
    assert "name" not in c
    assert not cs.by_id(S.ASK_NAME).done_when(c)      # -> re-asks


@pytest.mark.parametrize("real", ["Sam", "satish", "Mary-Jane", "Jo Smith"])
def test_a_real_name_is_kept(real):
    c = {"name": real}
    cs.by_id(S.ASK_NAME).apply(c, {"name": real}, {})
    assert c["name"] == real
    assert cs.by_id(S.ASK_NAME).done_when(c)


def test_a_name_is_trimmed_to_first_line_and_60_chars():
    c = {}
    cs.by_id(S.ASK_NAME).apply(c, {"name": "Sam\nsecond line"}, {})
    assert c["name"] == "Sam"


def test_intro_ack_is_set_by_any_reply():
    c = {}
    cs.by_id(S.SHOW_INTRO).apply(c, {}, {})
    assert c["intro_ack"] is True


def test_logo_face_lands_on_the_pending_logo():
    c = {}
    cs.by_id(S.ASK_LOGO_PLACEMENT).apply(c, {"logo_face": "back"}, {})
    assert c["pending_logo"] == {"face": "back"}


def test_another_logo_yes_banks_the_logo_and_reopens_the_loop():
    c = {"pending_logo": {"face": "back", "placed": True}, "another_logo": True}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": True}, {})
    assert c["logos"] == [{"face": "back", "placed": True}]
    assert c["pending_logo"] == {}
    assert "another_logo" not in c            # cleared -> the loop re-asks
    assert not c.get("logos_done")
    assert v2.next_step(c | {"name": "Sam", "intro_ack": True, "has_logo": True}).id is S.ASK_LOGO_PLACEMENT


def test_another_logo_no_banks_the_logo_and_closes_the_loop():
    c = {"pending_logo": {"face": "back", "placed": True}, "another_logo": False}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": False}, {})
    assert c["logos"] == [{"face": "back", "placed": True}]
    assert c["pending_logo"] is None
    assert c["logos_done"] is True


def test_logo_loop_stops_at_max_logos_even_when_more_are_wanted():
    c = {"logos": [{"face": f} for f in ("front", "back", "left")],
         "pending_logo": {"face": "right", "placed": True}}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": True}, {})
    assert len(c["logos"]) == cs.MAX_LOGOS
    assert c["logos_done"] is True             # capped
    assert c["pending_logo"] is None


def test_anything_else_yes_clears_the_decor_slots():
    c = {"decor_choice": "text", "decor_placed": True, "more_decor": True}
    cs.by_id(S.ASK_ANYTHING_ELSE).apply(c, {"more_decor": True}, {})
    assert "decor_choice" not in c and "decor_placed" not in c and "more_decor" not in c


def test_email_apply_captures_the_lead(monkeypatch):
    seen = {}

    def _fake(session, collected, email):
        seen.update(session=session, email=email)
        return "lead-1", True

    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify", _fake)
    c = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "sam@example.com"}, {"id": "s1"})
    assert c["email_captured"] is True and c["lead_id"] == "lead-1"
    assert seen["email"] == "sam@example.com"


def test_email_apply_does_not_capture_when_verification_fails(monkeypatch):
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: (None, False))
    c = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "sam@example.com"}, {"id": "s1"})
    assert not c.get("email_captured")         # -> ask_email re-asks itself


# --- Finding 1 (final review): a free-text "no" re-asks FOREVER at the two
# decor steps. Tapping the chip already worked; only typed answers hit this
# path, which is why the model-free e2e never caught it.


def test_typed_no_ends_the_decor_loop():
    """Free-text decline must satisfy the step. Tapping the chip already worked;
    only typed answers hit this path, which is why the model-free e2e missed it."""
    step = cs.by_id(S.ASK_ANYTHING_ELSE)
    c = {"decor_choice": "text", "decor_placed": True, "more_decor": False}
    step.apply(c, {"more_decor": False}, {})
    assert step.done_when(c), "typed 'no, that's everything' must end the loop"


def test_typed_no_at_add_decor_is_expressible_and_ends_the_loop():
    step = cs.by_id(S.ASK_ADD_DECOR)
    assert "decor_done" in step.slots, "the model needs a way to say 'no decoration'"
    c = {"decor_done": True}
    assert step.done_when(c)
    assert cs.by_id(S.DECOR_ADJUST).done_when(c)
    assert cs.by_id(S.ASK_ANYTHING_ELSE).done_when(c)


def test_decor_done_is_interpreter_writable_but_email_captured_is_not():
    assert "decor_done" in cs.WRITABLE_SLOTS
    assert "email_captured" not in cs.WRITABLE_SLOTS   # sole gate on FINALIZE
    assert "quantity_unsure" not in cs.WRITABLE_SLOTS  # annotation, not an answer


# --- Finding 2 (final review): _SLOT_DOCS and _PROGRESS_PATH are silent third
# declaration sites. A slot/step missing from them fails silently — no error,
# no other failing test, just a step that re-asks forever or reports "complete"
# too early.


def test_every_writable_slot_is_documented_for_the_interpreter():
    """_SLOT_DOCS is a second declaration site. A slot missing from it is
    silently dropped from the interpreter prompt (`if s in _SLOT_DOCS`), so the
    model never learns the field exists and the step re-asks forever — with no
    error and no other failing test."""
    from app.services.conversation import intent_extractor as ie

    undocumented = cs.WRITABLE_SLOTS - set(ie._SLOT_DOCS)
    assert not undocumented, f"add these to _SLOT_DOCS: {sorted(undocumented)}"


def test_slot_docs_has_no_entries_for_slots_that_no_longer_exist():
    from app.services.conversation import intent_extractor as ie

    assert set(ie._SLOT_DOCS) <= cs.WRITABLE_SLOTS


def test_every_asking_step_has_a_progress_position():
    """_PROGRESS_PATH is a third declaration site: a step absent from both it
    and _PROGRESS_ANCHORS silently reports "complete" to the customer."""
    from app.services.conversation import state_machine_v2 as v2

    for step in cs.REGISTRY:
        if step.id is S.FINALIZE_CANVAS:
            continue          # terminal: deliberately reports complete
        # Resolve the anchor's TARGET: progress_for maps id -> anchor -> path.
        # Asserting mere membership in _PROGRESS_ANCHORS leaves a hole — an
        # anchor pointing at a state absent from _PROGRESS_PATH silently
        # reports "complete" and the guard would still pass.
        anchor = v2._PROGRESS_ANCHORS.get(step.id, step.id)
        placed = anchor in v2._PROGRESS_PATH
        assert placed, f"{step.id.value} has no progress position"


def test_no_logo_skips_the_entire_logo_branch():
    """has_logo=False sets logos_done, and every logo step's done_when already
    short-circuits on `not _logos_open(c)` — so first-unmet skips all four with
    no new routing."""
    c = {"name": "Sam", "intro_ack": True}
    step = cs.by_id(S.ASK_HAS_LOGO)
    fields = v2.resolve_chip(step, "No — text only", c)
    assert fields == {"has_logo": False}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_has_logo_routes_into_the_logo_loop():
    c = {"name": "Sam", "intro_ack": True}
    step = cs.by_id(S.ASK_HAS_LOGO)
    fields = v2.resolve_chip(step, "Yes, I have a logo", c)
    assert fields == {"has_logo": True}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_ask_has_logo_is_satisfied_by_a_false_answer():
    """Presence, not truthiness — bool(False) is False, which would re-ask
    forever (the bug already fixed on ASK_ANYTHING_ELSE and ASK_QUANTITY)."""
    assert cs.by_id(S.ASK_HAS_LOGO).done_when({"has_logo": False})
    assert not cs.by_id(S.ASK_HAS_LOGO).done_when({})
