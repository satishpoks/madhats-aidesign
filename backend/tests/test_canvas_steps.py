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
        S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_LOGO_BG, S.ASK_EMAIL,
        # The verification gate sits IMMEDIATELY after ask_email: that adjacency
        # is what makes the double opt-in blocking. A step spliced between them
        # would be answerable before the address is confirmed.
        S.AWAIT_EMAIL_VERIFY,
        S.ASK_ANOTHER_LOGO,
        S.ASK_ADD_DECOR, S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE,
        S.ASK_QUANTITY, S.ASK_DECORATION, S.ASK_DECORATION_MIX,
        S.NEEDED_BY, S.ASK_PURPOSE, S.REVIEW_DESIGN, S.REWORK_CANVAS,
        S.ASK_FINAL_NOTES,
        S.REQUEST_QUOTE,
        S.FINALIZE_CANVAS,
    ]


def test_ask_email_precedes_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert ids.index(S.ASK_EMAIL) < ids.index(S.FINALIZE_CANVAS)


def test_chips_may_set_slots_plus_trusted_flags_the_llm_cannot():
    # Chips are trusted (we authored the label AND its fields), so they may set
    # flags beyond the interpreter's writable set. decor_done is writable by
    # BOTH now (a typed "no more" is just as valid an answer as the chip); only
    # quantity_unsure stays chip-only — it's an annotation ("Not sure" tapped),
    # not something the model should ever infer from free text. final_notes_done
    # is chip-only too: it must not be interpreter-writable (see
    # test_final_notes_done_is_not_interpreter_writable), but the "Nothing to
    # add" chip we authored is allowed to set it directly. change_email is the
    # same shape and matters MORE: it un-captures a verified-pending address, so
    # an interpreter that could write it would let free text anywhere in the flow
    # dismantle the double opt-in. Chip-only, and the gate declares no slots.
    allowed = cs.WRITABLE_SLOTS | {"quantity_unsure", "final_notes_done",
                                   "change_email"}
    for step in cs.REGISTRY:
        for chip in step.chips:
            assert set(chip.fields) <= allowed, f"{step.id}: {chip.label}"


def test_change_email_is_never_interpreter_writable():
    """The one field that can undo an email capture must reach `collected` only
    via the gate's own chip — never from free text the model interpreted."""
    assert "change_email" not in cs.WRITABLE_SLOTS
    assert cs.by_id(S.AWAIT_EMAIL_VERIFY).slots == ()


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
        # ASK_LOGO_BG, ASK_DECOR_PLACEMENT and REWORK_CANVAS have tools but use
        # instructions or runtime-resolved tips instead of step.tip.
        # ASK_LOGO_PLACEMENT also has a tool but no tip (2026-08-01): the tip
        # was dropped from the chat reply because directive_for's fallback
        # (`step.instructions or V2_TOOL_TIPS[tool]`) already surfaces
        # V2_TOOL_TIPS["upload"] as the canvas callout, so appending it to the
        # chat too duplicated the guidance on screen.
        if step.id in (S.ASK_LOGO_BG, S.ASK_DECOR_PLACEMENT, S.REWORK_CANVAS,
                       S.ASK_LOGO_PLACEMENT):
            assert step.tool and not step.tip
        else:
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
    assert v2.resolve_chip(step, "No, that's all", {}) == {"another_logo": False}


def test_chip_match_is_case_and_whitespace_insensitive():
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)
    assert v2.resolve_chip(step, "  front  ", {}) == {"logo_face": "front"}


def test_free_text_is_not_a_chip():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "yeah go on then", {}) is None


def _decor_seed() -> dict:
    return {"name": "Sam", "intro_ack": True, "has_logo": False,
            "logos_done": True, "pending_logo": None}


def test_decor_placement_is_asked_before_the_decor_tool_opens():
    c = _decor_seed()
    c["decor_choice"] = "text"
    assert v2.next_step(c).id is S.ASK_DECOR_PLACEMENT

    step = cs.by_id(S.ASK_DECOR_PLACEMENT)
    fields = v2.resolve_chip(step, "Back", c)
    assert fields == {"decor_face": "back"}
    c.update(fields)
    assert v2.next_step(c).id is S.DECOR_ADJUST


def test_adding_a_second_decoration_re_asks_the_face():
    """_apply_anything_else must clear decor_face too, or the second decoration
    silently reuses the first one's face."""
    c = _decor_seed()
    c.update({"decor_choice": "text", "decor_face": "back", "decor_placed": True})
    step = cs.by_id(S.ASK_ANYTHING_ELSE)
    fields = v2.resolve_chip(step, "Add something else", c)
    c.update(fields)
    step.apply(c, fields, {})
    assert "decor_face" not in c
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_decor_placement_is_skipped_when_no_decoration_is_wanted():
    assert cs.by_id(S.ASK_DECOR_PLACEMENT).done_when({"decor_done": True})


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
def test_every_offered_chip_makes_progress(step, chip, monkeypatch):
    """Understanding a chip is not enough — it must also move the flow. This is
    the half of the round-trip test that needs the apply hooks."""
    # REQUEST_QUOTE's apply writes to `leads` and converges delivery; this test
    # is about routing, so stub the recording (every other apply is pure).
    monkeypatch.setattr(
        cs.leads_service, "record_quote_request", lambda s, c: "MH-BCDFGH",
    )
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


def test_ask_has_logo_false_does_not_re_ask_once_its_apply_has_run():
    """Presence, not truthiness — a `False` answer that has actually gone
    through `apply` (so `logos_done` is set) must not re-ask forever (the bug
    already fixed on ASK_ANYTHING_ELSE and ASK_QUANTITY). Unlike the old
    contract, a bare `has_logo: False` with no `apply` having run does NOT
    satisfy the step on its own — see
    test_volunteered_has_logo_false_without_apply_still_asks_the_step for why:
    `apply` is what sets `logos_done`, the flag that actually skips the logo
    loop, so the step must stay unmet until that side effect has run."""
    c = {"has_logo": False}
    step = cs.by_id(S.ASK_HAS_LOGO)
    step.apply(c, {"has_logo": False}, {})
    assert step.done_when(c)
    assert not cs.by_id(S.ASK_HAS_LOGO).done_when({})


def test_volunteered_has_logo_false_without_apply_still_asks_the_step():
    """Regression: the interpreter can volunteer `has_logo=False` on an EARLIER
    turn than ASK_HAS_LOGO becomes current (e.g. "Hi I'm Sam, no logo, just
    text" fills {'name': 'Sam', 'has_logo': False} in one turn). The
    orchestrator runs ONLY the CURRENT step's `apply` each turn
    (orchestrator_v2.py:89-90) — so if `done_when` trusted the raw slot, the
    step would already read as done, would never become current, its apply
    would never run, and `logos_done` would never be set: a text-only customer
    gets marched into the logo loop anyway, the exact bug this step exists to
    prevent.

    Confirmed failing before the fix (routed to ASK_LOGO_PLACEMENT instead):
        next after name  : show_intro
        next after intro : ask_logo_placement     <- WRONG
        logos_done       : None
    """
    c = {"name": "Sam", "intro_ack": True, "has_logo": False}   # volunteered, no apply
    assert v2.next_step(c).id is S.ASK_HAS_LOGO, (
        "a volunteered False must still route to ASK_HAS_LOGO so its apply runs"
    )

    # Now let the step actually run, as the orchestrator would: resolve its
    # chip and apply it.
    step = cs.by_id(S.ASK_HAS_LOGO)
    fields = v2.resolve_chip(step, "No — text only", c)
    c.update(fields)
    step.apply(c, fields, {})
    assert c["logos_done"] is True
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_volunteered_has_logo_true_skips_straight_into_the_logo_loop():
    """`True` needs no side effect (there is nothing to skip), so it may
    legitimately short-circuit `done_when` on the raw slot alone — unlike
    `False`, which must wait for `apply` to set `logos_done`."""
    c = {"name": "Sam", "intro_ack": True, "has_logo": True}   # volunteered, no apply
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_logo_bg_is_asked_after_the_logo_is_placed_and_before_email():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    assert v2.next_step(c).id is S.ASK_LOGO_BG

    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "Yes, remove background", c)
    assert fields == {"logo_bg": "removed"}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["pending_logo"]["bg"] == "removed"
    # The first logo is now placed -> ASK_EMAIL rides right after it, before
    # ASK_ANOTHER_LOGO.
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_logo_bg_declined_still_satisfies_the_step():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "No, it's fine as it is", c)
    assert fields == {"logo_bg": "none"}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_logo_bg_is_skipped_when_there_is_no_logo():
    c = {"name": "Sam", "intro_ack": True, "has_logo": False,
         "logos_done": True, "pending_logo": None}
    assert cs.by_id(S.ASK_LOGO_BG).done_when(c)


def _quantity_done() -> dict:
    # email_captured=True: every test built on this seed targets a decoration/
    # mix step, all positioned AFTER ask_email in the registry. Without it,
    # ask_email (design phase closed, nothing placed) would legitimately
    # intercept first and the test would prove nothing about its real subject.
    return {"name": "Sam", "intro_ack": True, "has_logo": False,
            "logos_done": True, "pending_logo": None, "decor_done": True,
            "quantity": 50, "email_captured": True, "email_verified": True}


def test_decoration_is_asked_after_quantity_and_before_email():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    assert v2.next_step(c).id is S.ASK_DECORATION


def test_decoration_chips_are_the_stores_methods_plus_a_mix_escape_hatch():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    labels = [ch.label for ch in cs.chips_of(cs.by_id(S.ASK_DECORATION), c)]
    assert labels == ["Embroidery", "Screen Print", cs.MIX_CHIP_LABEL]


def test_decoration_is_single_select():
    """One method is the default answer. A mix is possible but deliberately
    costs an extra step, because it costs the customer more per hat."""
    assert cs.by_id(S.ASK_DECORATION).multiselect is False


def test_the_decoration_ask_warns_that_mixing_costs_more_per_hat():
    """The v1-only ChatColumn multi-select renders that caveat when 2+ chips are
    ticked; single-select never trips it, so the copy has to carry it."""
    ask = cs.by_id(S.ASK_DECORATION).ask.lower()
    assert "cost" in ask and "per hat" in ask


def test_choosing_one_decoration_sets_the_brief_and_the_render_style_bucket():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = v2.resolve_chip(step, "Embroidery", c)
    c.update(fields)
    step.apply(c, fields, {})

    assert c["decoration_types"] == ["Embroidery"]
    assert c["decoration_type"] == "embroidery"
    assert "Decoration method: Embroidery" in c["brief_notes"]
    # no mix -> no describe step; email_captured=True (seeded by _quantity_done)
    # already satisfies ask_email, which sits earlier in the registry, so this
    # resolves straight through to needed_by.
    assert v2.next_step(c).id is S.NEEDED_BY


def test_the_mix_chip_routes_to_the_describe_step_and_asks_nothing_else():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = v2.resolve_chip(step, cs.MIX_CHIP_LABEL, c)
    assert fields == {"decoration_mix": True}
    c.update(fields)
    step.apply(c, fields, {})

    assert step.done_when(c)                       # the mix IS an answer
    assert v2.next_step(c).id is S.ASK_DECORATION_MIX


def test_describing_the_mix_records_the_brief_and_a_style_bucket():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    c["decoration_mix"] = True
    step = cs.by_id(S.ASK_DECORATION_MIX)
    fields = {"decoration_mix_note": "Embroidery on the front, screen print on the back"}
    c.update(fields)
    step.apply(c, fields, {})

    assert step.done_when(c)
    assert "Embroidery on the front" in c["brief_notes"][-1]
    # No single method covers a mix, so the bucket comes from the customer's own
    # words via the same keyword table a single pick uses.
    assert c["decoration_type"] == "embroidery"
    # email_captured=True (seeded by _quantity_done) already satisfies
    # ask_email, which sits earlier in the registry, so this resolves straight
    # through to needed_by.
    assert v2.next_step(c).id is S.NEEDED_BY


def test_the_mix_describe_step_warns_about_cost_too():
    ask = cs.by_id(S.ASK_DECORATION_MIX).ask.lower()
    assert "cost" in ask and "per hat" in ask


def test_an_empty_mix_description_re_asks_rather_than_banking_nothing():
    c = _quantity_done()
    c["decoration_mix"] = True
    step = cs.by_id(S.ASK_DECORATION_MIX)
    step.apply(c, {"decoration_mix_note": "   "}, {})
    assert not step.done_when(c)
    assert v2.next_step(c).id is S.ASK_DECORATION_MIX


def test_the_mix_step_is_skipped_entirely_when_no_mix_was_asked_for():
    c = _quantity_done()
    c["decoration_done"] = True
    assert cs.by_id(S.ASK_DECORATION_MIX).done_when(c)


def test_the_mix_step_resolves_free_text_without_a_model():
    """It has no chips, so the stall-and-nudge escape hatch cannot fire — an
    interpreter outage would strand the session one step before the email."""
    step = cs.by_id(S.ASK_DECORATION_MIX)
    assert step.direct_answer is not None
    assert step.direct_answer("embroidered logo, printed text") == {
        "decoration_mix_note": "embroidered logo, printed text"
    }


def test_decoration_names_not_offered_by_the_store_never_reach_the_brief():
    """decoration_types is store-dynamic so it cannot go in SLOT_ENUMS — this
    filter IS the interpreter guard."""
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = {"decoration_types": ["Sublimation", "Embroidery"]}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["decoration_types"] == ["Embroidery"]


def test_a_decoration_answer_as_a_bare_string_is_still_filtered():
    """The interpreter may return a string rather than a list."""
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = {"decoration_types": "Screen Print"}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["decoration_types"] == ["Screen Print"]
    assert c["decoration_type"] == "print"


def test_prepare_loads_the_stores_active_methods_once(monkeypatch):
    calls = []

    def _fake(store_id, active_only=False):
        calls.append(store_id)
        return [{"name": "Embroidery"}, {"name": "Vinyl"}]

    monkeypatch.setattr("app.services.decoration_types.list_types", _fake)
    c = _quantity_done()
    step = cs.by_id(S.ASK_DECORATION)
    step.prepare(c, {"id": "store-1"})
    assert c["decoration_options"] == ["Embroidery", "Vinyl"]

    step.prepare(c, {"id": "store-1"})          # already loaded
    assert calls == ["store-1"]


def test_a_store_with_no_decoration_methods_skips_the_step(monkeypatch):
    """No options means no chips and no way to answer — that would dead-end the
    funnel just before needed_by (email_captured=True, email_verified=True, seeded by
    _quantity_done, already satisfies ask_email earlier in the registry)."""
    monkeypatch.setattr("app.services.decoration_types.list_types",
                        lambda *a, **k: [])
    c = _quantity_done()
    step = cs.by_id(S.ASK_DECORATION)
    step.prepare(c, {"id": "store-1"})
    assert step.done_when(c)
    assert v2.next_step(c).id is S.NEEDED_BY


def test_prepare_survives_a_missing_store():
    c = _quantity_done()
    cs.by_id(S.ASK_DECORATION).prepare(c, None)
    assert v2.next_step(c).id is S.NEEDED_BY


def test_decoration_bookkeeping_is_not_interpreter_writable():
    assert "decoration_types" in cs.WRITABLE_SLOTS
    assert "decoration_mix" in cs.WRITABLE_SLOTS        # "I'd like a mix" in free text
    assert "decoration_mix_note" in cs.WRITABLE_SLOTS
    assert "decoration_done" not in cs.WRITABLE_SLOTS
    assert "decoration_options" not in cs.WRITABLE_SLOTS
    assert "decoration_type" not in cs.WRITABLE_SLOTS   # the render-style bucket


def test_ask_logo_bg_chips_no_longer_ask_the_customer_to_tick():
    step = cs.by_id(S.ASK_LOGO_BG)
    labels = [c.label for c in step.chips]
    assert labels == ["Yes, remove background", "No, it's fine as it is"]
    assert "tick" not in step.ask.lower()


def test_yes_emits_an_op_that_flags_the_pending_logo():
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "back", "placed": True}}
    ops = step.ops(c, {"logo_bg": "removed"})
    assert ops == [{"target": {"kind": "pending_logo", "face": "back"},
                    "patch": {"removeBg": True}}]


def test_no_emits_no_op():
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert step.ops(c, {"logo_bg": "none"}) == []


def test_bg_copy_never_promises_processing_or_a_wait():
    # Standing rule: ticking is instant; nothing is matted client-side.
    step = cs.by_id(S.ASK_LOGO_BG)
    blob = (step.ask + " " + (step.instructions or "")).lower()
    for banned in ("wait", "processing", "hang on", "just a moment"):
        assert banned not in blob


def test_bg_still_marks_the_step_answered():
    # pending_logo["bg"] is the done_when marker — the op is an ADDITION to it.
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "front", "placed": True}}
    step.apply(c, {"logo_bg": "removed"}, {})
    assert step.done_when(c) is True


def test_needed_by_step_shape():
    step = cs.by_id(S.NEEDED_BY)
    assert step is not None
    assert step.slots == ("needed_by",)
    assert "needed_by" in cs.WRITABLE_SLOTS
    assert "needed_by" not in cs.SLOT_ENUMS      # free text: a bucket OR a date
    assert step.apply is None and step.direct_answer is None
    assert step.done_when({"needed_by": "ASAP"})
    assert not step.done_when({})
    labels = [ch.label for ch in step.chips]
    assert labels == ["ASAP", "2–4 weeks", "1–2 months", "Just exploring"]
    for ch in step.chips:
        assert set(ch.fields) == {"needed_by"}


def test_needed_by_sits_immediately_before_purpose_in_the_registry():
    ids = [s.id for s in cs.REGISTRY]
    assert ids[ids.index(S.NEEDED_BY) + 1] is S.ASK_PURPOSE


def test_a_defer_answer_still_satisfies_needed_by():
    """"Just exploring" (no firm date) is a valid answer — any non-empty value
    satisfies the step."""
    step = cs.by_id(S.NEEDED_BY)
    fields = v2.resolve_chip(step, "Just exploring", {})
    assert fields == {"needed_by": "Just exploring"}
    assert step.done_when(fields)


def test_apply_final_notes_appends_typed_note_to_brief():
    from app.services.conversation import canvas_steps as cs
    c = {}
    cs._apply_final_notes(c, {"final_notes": "Pantone 186 C for the text"}, {})
    assert c["final_notes_done"] is True
    assert any("Pantone 186 C" in n for n in c["brief_notes"])


def test_apply_final_notes_nothing_to_add_adds_no_brief_note():
    from app.services.conversation import canvas_steps as cs
    # The chip sets final_notes_done directly (merged before apply); apply sees
    # no final_notes and must not append a brief note.
    c = {"final_notes_done": True}
    cs._apply_final_notes(c, {}, {})
    assert "brief_notes" not in c


def test_apply_final_notes_folds_early_volunteered_note_on_nothing_to_add():
    from app.services.conversation import canvas_steps as cs
    # Customer volunteered a colour code at an earlier step (interpreter banked it),
    # then taps "Nothing to add" (chip fields carry no final_notes, only the done flag).
    c = {"final_notes": "Pantone 186 C for the text", "final_notes_done": True}
    cs._apply_final_notes(c, {}, {})
    assert any("Pantone 186 C" in n for n in c.get("brief_notes", []))


def test_apply_final_notes_typed_note_wins_over_pre_banked():
    from app.services.conversation import canvas_steps as cs
    c = {"final_notes": "stale early value"}
    cs._apply_final_notes(c, {"final_notes": "the real typed note"}, {})
    assert c["brief_notes"] == ["Customer final notes: the real typed note"]


def test_accept_verbatim_is_set_on_ask_purpose_only():
    """Banking a raw message verbatim is correct exactly where the answer IS
    the message. Globally it would write "umm the back one I think" into
    logo_face (an enum) or quantity (an int) and corrupt the design."""
    verbatim = {s.id for s in cs.REGISTRY if s.accept_verbatim}
    assert verbatim == {S.ASK_PURPOSE}


def test_exactly_these_steps_open_a_checkpoint():
    """Guard test: adding a registry step forces a deliberate decision about
    whether it is a Back destination. See the spec's section 5.1."""
    assert cs.CHECKPOINT_STEP_IDS == frozenset({
        S.ASK_NAME, S.ASK_HAS_LOGO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
        S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE,
    })


def test_name_checkpoint_freezes_only_on_email_verification():
    cp = cs.by_id(S.ASK_NAME).checkpoint
    assert cp.frozen_when({}) is False
    assert cp.frozen_when({"decor_done": True}) is False   # design done: still editable
    assert cp.frozen_when({"email_verified": True}) is True


def test_design_checkpoints_freeze_when_the_design_is_agreed():
    for sid in (S.ASK_HAS_LOGO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR):
        cp = cs.by_id(sid).checkpoint
        assert cp.frozen_when({}) is False, sid
        assert cp.frozen_when({"decor_done": True}) is True, sid


def test_brief_checkpoints_freeze_only_when_the_design_is_confirmed():
    for sid in (S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE):
        cp = cs.by_id(sid).checkpoint
        assert cp.frozen_when({"decor_done": True}) is False, sid
        assert cp.frozen_when({"design_confirmed": True}) is True, sid


def test_email_steps_are_never_checkpoints():
    # Verified email must not be re-askable; the verify gate freezes all input
    # anyway, so there is no window in which an unverified one is editable.
    assert cs.by_id(S.ASK_EMAIL).checkpoint is None
    assert cs.by_id(S.AWAIT_EMAIL_VERIFY).checkpoint is None


def test_labels_read_as_the_customer_s_own_answer():
    assert cs.by_id(S.ASK_NAME).checkpoint.label({"name": "Satish"}) == "Your name — Satish"
    assert cs.by_id(S.ASK_QUANTITY).checkpoint.label({"quantity": 50}) == "Quantity — 50"
    assert cs.by_id(S.ASK_HAS_LOGO).checkpoint.label({"has_logo": True}) == "Logo or image 1"
    assert cs.by_id(S.ASK_HAS_LOGO).checkpoint.label({"has_logo": False}) == "Logo or image — no"


def test_labels_never_crash_on_a_missing_or_partial_value():
    """Labels are rendered at CAPTURE time, i.e. BEFORE the step is answered —
    so every label function must cope with its own slot being absent."""
    for sid in cs.CHECKPOINT_STEP_IDS:
        text = cs.by_id(sid).checkpoint.label({})
        assert isinstance(text, str) and text


def test_logo_label_numbers_the_pass_from_the_banked_collection():
    logo = cs.by_id(S.ASK_LOGO_PLACEMENT).checkpoint
    assert logo.label({"logos": [{"face": "front"}]}) == "Logo or image 2"
    assert logo.label({"logos": [], "pending_logo": {"face": "front"}}) == "Logo or image 1 — front"


def test_one_logo_element_is_one_checkpoint_shared_by_both_openers():
    """ASK_HAS_LOGO opens logo 1 (so Back returns to "do you have a logo?");
    ASK_LOGO_PLACEMENT opens logo 2 onward. Both render the SAME label function
    so the menu reads as one numbered series, not two unrelated entries for the
    same element."""
    first = cs.by_id(S.ASK_HAS_LOGO).checkpoint
    later = cs.by_id(S.ASK_LOGO_PLACEMENT).checkpoint
    assert first.kind == later.kind == "logo"
    assert first.label is later.label
    # Logo 1 is opened by ASK_HAS_LOGO, so placement adds nothing on that pass.
    assert first.opens_when is None
    assert later.opens_when({"logos": []}) is False
    assert later.opens_when({"logos": [{"face": "front"}]}) is True


def test_decor_label_is_not_numbered():
    """There is NO `decor` collection — ASK_ANYTHING_ELSE's apply POPS
    decor_choice/decor_face/decor_placed on each new pass, so nothing
    accumulates and a pass index cannot be derived from `collected`. The label
    describes the decoration instead of counting it."""
    decor = cs.by_id(S.ASK_ADD_DECOR).checkpoint
    assert decor.label({"decor_choice": "text", "decor_face": "left"}) == "Text — left"
    assert decor.label({}) == "Text or graphic"


def test_back_clears_is_gone():
    """Replaced by snapshots — nothing may still declare it."""
    assert not hasattr(cs.REGISTRY[0], "back_clears")
