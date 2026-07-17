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
        S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_LOGO_BG, S.ASK_ANOTHER_LOGO,
        S.ASK_ADD_DECOR, S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE,
        S.ASK_QUANTITY, S.ASK_DECORATION, S.ASK_DECORATION_MIX,
        S.ASK_EMAIL, S.ASK_PURPOSE, S.FINALIZE_CANVAS,
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
        # ASK_LOGO_BG and ASK_DECOR_PLACEMENT have tools but use instructions or
        # runtime-resolved tips instead of step.tip.
        if step.id in (S.ASK_LOGO_BG, S.ASK_DECOR_PLACEMENT):
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
    assert v2.resolve_chip(step, "No, that's it", {}) == {"another_logo": False}


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


def test_logo_bg_is_asked_after_the_logo_is_placed_and_before_another_logo():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    assert v2.next_step(c).id is S.ASK_LOGO_BG

    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "Yes, I've ticked it", c)
    assert fields == {"logo_bg": "removed"}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["pending_logo"]["bg"] == "removed"
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_bg_declined_still_satisfies_the_step():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "No, it's fine as is", c)
    assert fields == {"logo_bg": "none"}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_bg_is_skipped_when_there_is_no_logo():
    c = {"name": "Sam", "intro_ack": True, "has_logo": False,
         "logos_done": True, "pending_logo": None}
    assert cs.by_id(S.ASK_LOGO_BG).done_when(c)


def _quantity_done() -> dict:
    return {"name": "Sam", "intro_ack": True, "has_logo": False,
            "logos_done": True, "pending_logo": None, "decor_done": True,
            "quantity": 50}


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
    assert v2.next_step(c).id is S.ASK_EMAIL       # no mix -> no describe step


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
    assert v2.next_step(c).id is S.ASK_EMAIL


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
    funnel just before the email step."""
    monkeypatch.setattr("app.services.decoration_types.list_types",
                        lambda *a, **k: [])
    c = _quantity_done()
    step = cs.by_id(S.ASK_DECORATION)
    step.prepare(c, {"id": "store-1"})
    assert step.done_when(c)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_prepare_survives_a_missing_store():
    c = _quantity_done()
    cs.by_id(S.ASK_DECORATION).prepare(c, None)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_decoration_bookkeeping_is_not_interpreter_writable():
    assert "decoration_types" in cs.WRITABLE_SLOTS
    assert "decoration_mix" in cs.WRITABLE_SLOTS        # "I'd like a mix" in free text
    assert "decoration_mix_note" in cs.WRITABLE_SLOTS
    assert "decoration_done" not in cs.WRITABLE_SLOTS
    assert "decoration_options" not in cs.WRITABLE_SLOTS
    assert "decoration_type" not in cs.WRITABLE_SLOTS   # the render-style bucket
