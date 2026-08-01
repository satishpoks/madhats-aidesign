import pytest

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        self.store.setdefault("rows", []).extend(rows)
        return self


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store, name)


def _new_store():
    return {
        "session": {
            "id": "s1",
            "state": S.GREETING.value,
            "collected": {"flow_mode": "canvas"},
            "upsell_count": 0,
        }
    }


def _no_llm(monkeypatch):
    async def _boom(*a, **k):
        raise ie.LLMUnavailable("no key")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


def _llm_returns(monkeypatch, fields):
    async def _ok(*a, **k):
        return dict(fields)
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _ok)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


@pytest.mark.asyncio
async def test_kickoff_greets_and_advances_to_ask_name(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "")
    assert res["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_the_live_bug_yes_another_logo_reopens_the_logo_loop(monkeypatch):
    """Regression: the customer tapped the chip three times and was marched to
    the email question, because "another" contains "no"."""
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "front", "placed": True},
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)                       # a chip must not need the LLM
    res = await o2.handle_message("s1", "Yes, another logo")
    assert res["state"] == S.ASK_LOGO_PLACEMENT.value
    assert store["session"]["collected"]["logos"] == [{"face": "front", "placed": True}]


@pytest.mark.asyncio
async def test_a_chip_tap_makes_zero_llm_calls(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_QUANTITY.value
    # `logos` carries first-element evidence: email now rides the design phase
    # (earlier in the registry) and gates on it, so without this the router
    # would skip the email step entirely and this turn would land on
    # needed_by instead of proving the chip-tap-advances-to-email claim below.
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "logos_done": True,
                                     "logos": [{"face": "front", "placed": True}],
                                     "decor_done": True}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    calls = []

    async def _spy(*a, **k):
        calls.append(1)
        raise AssertionError("chip taps must not call the model")

    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _spy)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "50-99")
    assert calls == []
    assert store["session"]["collected"]["quantity"] == 50
    assert res["state"] == S.ASK_EMAIL.value


@pytest.mark.asyncio
async def test_free_text_stalls_when_the_model_is_unavailable(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "go on then")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value        # unchanged: nothing guessed
    assert res["reply"] == prompts.V2_STALL_REPLY
    assert store["session"]["collected"]["_fail_count"] == 1


@pytest.mark.asyncio
async def test_two_failures_nudge_toward_the_chips(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "_fail_count": 1,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "go on then")
    assert res["reply"] == prompts.V2_NUDGE_REPLY
    assert res["data"]["options"] == ["Yes, another logo", "No, that's all"]


@pytest.mark.asyncio
async def test_a_successful_turn_clears_the_fail_count(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "_fail_count": 1,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"another_logo": False})
    await o2.handle_message("s1", "nah I'm good")
    assert store["session"]["collected"].get("_fail_count", 0) == 0


@pytest.mark.asyncio
async def test_a_volunteered_answer_is_banked_and_its_step_skipped(monkeypatch):
    """Reordering: filling a later slot early means the router never asks it."""
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "decor_done": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"another_logo": False, "quantity": 50})
    res = await o2.handle_message("s1", "no thanks, and I need 50 caps")
    assert store["session"]["collected"]["quantity"] == 50
    assert res["state"] == S.ASK_EMAIL.value        # ask_quantity skipped
    assert res["data"]["progress"]["total"] == 8    # email left the counted path


@pytest.mark.asyncio
async def test_ask_email_tells_the_customer_a_verification_link_was_sent(monkeypatch):
    """Regression (session 69902f52): after giving their email the customer was
    marched straight to the purpose question with no word that a verification
    link had been sent or why. The reply must name the link and the address."""
    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "logos_done": True,
                                     "decor_done": True, "quantity": 50,
                                     "decoration_type": "embroidery"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    # _apply_email calls capture_lead_and_verify (which sends the double opt-in
    # email); stub it to report a successful capture.
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, email: ("lead-1", True))
    _llm_returns(monkeypatch, {"email": "sam@example.com"})
    res = await o2.handle_message("s1", "sam@example.com")
    # The flow now PARKS on the verification gate rather than walking on to the
    # next question — but the notice itself is unchanged and still names both.
    assert res["state"] == S.AWAIT_EMAIL_VERIFY.value
    assert "verification link" in res["reply"]
    assert "sam@example.com" in res["reply"]


@pytest.mark.asyncio
async def test_ask_email_notice_absent_when_capture_fails(monkeypatch):
    """If the address couldn't be captured, email_captured stays unset, the step
    re-asks itself, and no false 'link sent' claim is made."""
    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    # `logos` carries first-element evidence: without it, ask_email's own
    # done_when short-circuits True (nothing placed yet) regardless of
    # email_captured, so a failed capture would be masked as "step satisfied"
    # instead of re-asking — the exact behaviour under test here.
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "logos_done": True,
                                     "logos": [{"face": "front", "placed": True}],
                                     "decor_done": True, "quantity": 50}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, email: (None, False))
    _llm_returns(monkeypatch, {"email": "sam@example.com"})
    res = await o2.handle_message("s1", "sam@example.com")
    assert res["state"] == S.ASK_EMAIL.value            # re-asks itself
    assert "verification link" not in res["reply"]


@pytest.mark.asyncio
async def test_a_shared_tail_state_delegates_to_v1(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.OFFER_REFINE.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    called = {}

    async def _v1(sid, msg):
        called["hit"] = (sid, msg)
        return {"reply": "v1", "state": S.OFFER_REFINE.value, "data": {}}

    monkeypatch.setattr(o2._v1, "handle_message", _v1)
    res = await o2.handle_message("s1", "tweak it")
    assert called["hit"] == ("s1", "tweak it")
    assert res["reply"] == "v1"


@pytest.mark.asyncio
async def test_daily_cap_reroutes_to_the_quote_ask(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_PURPOSE.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_done": True, "quantity": 50,
        "needed_by": "ASAP", "email_captured": True, "email_verified": True, "design_confirmed": True,
        "final_notes_done": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: False)
    monkeypatch.setattr(cs.leads_service, "record_quote_request", lambda s, c: "MH-BCDFGH")
    _llm_returns(monkeypatch, {"purpose": "team caps"})
    # Quote-gated flow (C1): answering purpose now lands on the explicit
    # REQUEST_QUOTE submit step (design_confirmed is pre-seeded so the review
    # step, workstream B, is already settled and doesn't intercept); the
    # honesty gate fires on the turn that would otherwise reach
    # FINALIZE_CANVAS, i.e. after the submit chip.
    res = await o2.handle_message("s1", "for the team")
    assert res["state"] == S.REQUEST_QUOTE.value
    res = await o2.handle_message("s1", "Request a quote")
    assert res["state"] == S.QUOTE_REQUESTED.value
    assert res["data"]["options"] == ["Yes, request a quote", "No, I'm all set"]


@pytest.mark.asyncio
async def test_daily_cap_reply_separates_the_aside_from_the_quote_ask(monkeypatch):
    """The honesty-gate reply joins two separate customer-facing sentences —
    the run-on defect every other join site in this file was fixed for."""
    store = _new_store()
    store["session"]["state"] = S.ASK_PURPOSE.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_done": True, "quantity": 50,
        "needed_by": "ASAP", "email_captured": True, "email_verified": True, "design_confirmed": True,
        "final_notes_done": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: False)
    monkeypatch.setattr(cs.leads_service, "record_quote_request", lambda s, c: "MH-BCDFGH")
    _llm_returns(monkeypatch, {"purpose": "team caps"})
    await o2.handle_message("s1", "for the team")
    res = await o2.handle_message("s1", "Request a quote")
    assert res["reply"] == f"{prompts.GENERATION_BLOCKED_ASIDE}\n\n{prompts.CANVAS_QUOTE_ASK}"


@pytest.mark.asyncio
async def test_filler_is_never_stored_as_a_name(monkeypatch):
    """Pins the load-bearing update-then-apply order in handle_message.

    _apply_name POPS an implausible name that collected.update(fields) already
    wrote. If apply ever runs before the merge, the pop is a no-op and "ok"
    becomes the customer's name (the bug fixed in 44e8eda).
    """
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    store["session"]["collected"] = {"flow_mode": "canvas"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"name": "ok"})
    res = await o2.handle_message("s1", "ok")
    assert store["session"]["collected"].get("name") is None
    assert res["state"] == S.ASK_NAME.value          # re-asks


@pytest.mark.asyncio
async def test_a_real_name_is_accepted(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    store["session"]["collected"] = {"flow_mode": "canvas"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"name": "Sam"})
    res = await o2.handle_message("s1", "Sam")
    assert store["session"]["collected"]["name"] == "Sam"
    assert res["state"] == S.SHOW_INTRO.value


@pytest.mark.asyncio
async def test_ask_name_survives_an_outage_via_direct_answer(monkeypatch):
    # The whole funnel dies at step 1 without this: ask_name has no chips, so the
    # nudge cannot fire, and every session would stall forever.
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    store["session"]["collected"] = {"flow_mode": "canvas"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "Sam")
    assert store["session"]["collected"]["name"] == "Sam"
    assert res["state"] == S.SHOW_INTRO.value


@pytest.mark.asyncio
async def test_direct_answer_still_rejects_filler_in_an_outage(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    store["session"]["collected"] = {"flow_mode": "canvas"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "ok")
    assert store["session"]["collected"].get("name") is None
    assert res["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_ask_email_survives_an_outage_via_regex(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_done": True, "quantity": 50,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: ("lead-1", True))
    res = await o2.handle_message("s1", "sam@example.com")
    assert store["session"]["collected"]["email_captured"] is True
    assert res["state"] == S.AWAIT_EMAIL_VERIFY.value


@pytest.mark.asyncio
async def test_a_chip_bearing_step_still_stalls_in_an_outage(monkeypatch):
    # Unchanged behaviour: no direct_answer -> stall, guess nothing.
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "front", "placed": True},
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "go on then")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value
    assert res["reply"] == prompts.V2_STALL_REPLY


@pytest.mark.asyncio
async def test_typed_no_more_decor_advances_past_the_decor_loop(monkeypatch):
    """Finding 1 (final review), interpreter path end to end: a typed decline
    must not re-ask ASK_ANYTHING_ELSE forever.

    The message deliberately does NOT match either chip label verbatim (chip
    matching is case/whitespace-insensitive on the exact label, so a message
    that happens to equal "No, that's everything" would take the chip path
    and mask this bug, same as the model-free e2e did).

    The seed's `decor_placed: True` is the customer's first placed element, so
    once the decor loop closes the router lands on ASK_EMAIL (which now rides
    the design phase) before ASK_QUANTITY — not on ASK_QUANTITY directly.
    """
    store = _new_store()
    store["session"]["state"] = S.ASK_ANYTHING_ELSE.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_choice": "text", "decor_face": "front", "decor_placed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"more_decor": False})
    res = await o2.handle_message("s1", "nah, nothing more thanks")
    assert res["state"] == S.ASK_EMAIL.value      # must NOT re-ask ASK_ANYTHING_ELSE


@pytest.mark.asyncio
async def test_dynamic_chips_from_nudge_after_two_interpreter_failures(monkeypatch):
    """Regression: a step with chips_from must nudge to chips after _NUDGE_AFTER
    failures, not stall forever because step.chips is empty.

    The fix routes the nudge check through cs.chips_of(step, collected) instead
    of reading step.chips directly, so dynamic chips are visible to the nudge.
    """
    # Create a test step with chips_from that derives options from collected.
    # We'll use a fictional "ask_colour" step that offers colour options from
    # a store-scoped palette.
    def _colours_from_collected(c: dict) -> tuple[cs.Chip, ...]:
        colours = c.get("available_colours", ["Red", "Blue", "Green"])
        return tuple(cs.Chip(colour, {"chosen_colour": colour}) for colour in colours)

    test_step = cs.Step(
        # ASK_QUANTITY is a real registry state (not unused) — this only works
        # because `cs.by_id` is monkeypatched below to return `test_step` for it.
        id=S.ASK_QUANTITY,
        ask="Pick a colour:",
        chips=(),  # empty: chips come from chips_from
        chips_from=_colours_from_collected,
        slots=("chosen_colour",),
        done_when=lambda c: bool(c.get("chosen_colour")),
    )

    store = _new_store()
    store["session"]["state"] = S.ASK_QUANTITY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "available_colours": ["Red", "Blue", "Green"],
        "_fail_count": 1,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    monkeypatch.setattr(cs, "by_id", lambda state: test_step if state == S.ASK_QUANTITY else None)

    # First failure (after one already): should nudge because fails >= 2
    res = await o2.handle_message("s1", "something unmatchable")

    # After the fix, nudge should appear
    assert res["reply"] == prompts.V2_NUDGE_REPLY
    # The data should contain the options derived from chips_from
    assert res["data"]["options"] == ["Red", "Blue", "Green"]
    assert store["session"]["collected"]["_fail_count"] == 2


# --- handle_back: undo the last answer and re-ask it (Task C2) ----------------

@pytest.mark.asyncio
async def test_back_clears_the_last_answer_and_re_asks(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_QUANTITY.value          # re-asked
    assert "quantity" not in store["session"]["collected"]  # answer cleared


@pytest.mark.asyncio
async def test_back_at_the_start_is_a_no_op(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_back_at_greeting_does_not_crash(monkeypatch):
    """`GREETING` has no registry Step (`cs.by_id` returns None), so the
    no-target branch's `v2.reply_for(None, ...)` would raise AttributeError on
    `None.id` without a dedicated guard. `_new_store()` defaults to GREETING,
    mirroring a Back tap on the very first turn (before any message at all)."""
    store = _new_store()
    assert store["session"]["state"] == S.GREETING.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_NAME.value          # re-renders the kickoff
    assert out["data"]                                 # a real, non-empty data blob


def test_public_data_carries_can_go_back():
    # A mid-flow step can go back; the very first cannot.
    from app.services.conversation import state_machine_v2 as v2

    d_mid = o2._public(cs.by_id(S.ASK_QUANTITY),
                       {"name": "Sam", "intro_ack": True, "decor_placed": True,
                        "logos_done": True, "pending_logo": None,
                        "decor_done": True, "email_captured": True, "email_verified": True})
    assert d_mid["can_go_back"] is True

    d_start = o2._public(cs.by_id(S.ASK_NAME), {})
    assert d_start["can_go_back"] is False


@pytest.mark.asyncio
async def test_back_from_post_decoration_state_undoes_the_decoration_method(monkeypatch):
    """Amendment: Back must also be able to undo the decoration-method choice
    (a derived-flag step, not a plain writable-slot step) via back_clears."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
        # decoration_options mirrors what `_prepare_decoration` would already
        # have loaded on the original forward pass — Back does not (and must
        # not) clear it, only the answer flags derived from it.
        "decoration_options": ["Embroidery", "Screen Print"],
        "decoration_types": ["Embroidery"], "decoration_done": True,
        "decoration_type": "embroidery",
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_DECORATION.value
    collected = store["session"]["collected"]
    assert "decoration_done" not in collected
    assert "decoration_types" not in collected
    assert "decoration_type" not in collected
    assert collected["decoration_options"] == ["Embroidery", "Screen Print"]
    # Terminal flags are never touched by Back.
    assert collected.get("email_captured") is True


@pytest.mark.asyncio
async def test_handle_back_at_finalize_is_a_no_op_and_keeps_quote_requested(monkeypatch):
    """Regression (C-1): a committed quote must not be re-submittable via Back.
    quote_requested is REQUEST_QUOTE's writable done_when slot, so Back must
    not be able to clear it and re-ask REQUEST_QUOTE."""
    from tests.canvas_step_helpers import seed_for

    store = _new_store()
    store["session"]["state"] = S.FINALIZE_CANVAS.value
    store["session"]["collected"].update(seed_for(cs.REGISTRY[-1]))
    assert store["session"]["collected"]["quote_requested"] is True
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.FINALIZE_CANVAS.value           # no-op
    assert store["session"]["collected"]["quote_requested"] is True


# --- Task 1: element-adjust set + back lock -----------------------------------

def test_public_flags_back_removes_element_only_mid_element():
    from app.services.conversation import state_machine_v2 as v2
    base = {"name": "Sam", "intro_ack": True, "has_logo": True,
            "pending_logo": {"face": "front", "placed": True}, "email_captured": True, "email_verified": True}
    d_adjust = o2._public(cs.by_id(S.ASK_LOGO_BG), dict(base))
    assert d_adjust["can_go_back"] is True
    assert d_adjust["back_removes_element"] is True

    # A non-element step that can still go back keeps the flag false.
    d_plain = o2._public(cs.by_id(S.ASK_QUANTITY),
                         {"name": "Sam", "intro_ack": True, "decor_placed": True,
                          "logos_done": True, "pending_logo": None,
                          "decor_done": True, "email_captured": True, "email_verified": True})
    assert d_plain["can_go_back"] is True
    assert d_plain["back_removes_element"] is False


def test_public_can_go_back_is_suppressed_while_back_used():
    base = {"name": "Sam", "intro_ack": True, "has_logo": True,
            "pending_logo": {"face": "front", "placed": True}, "email_captured": True, "email_verified": True,
            "_back_used": True}
    d = o2._public(cs.by_id(S.ASK_LOGO_BG), dict(base))
    assert d["can_go_back"] is False
    assert d["back_removes_element"] is False   # gated on can_go_back too


@pytest.mark.asyncio
async def test_forward_turn_clears_the_back_lock(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True,
                                     "_back_used": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)                        # chip tap needs no model
    await o2.handle_message("s1", "Yes, another logo")
    assert "_back_used" not in store["session"]["collected"]


@pytest.mark.asyncio
async def test_final_notes_renders_disclaimer_and_captures_verbatim(monkeypatch):
    # Seed a session parked at ASK_FINAL_NOTES with the design confirmed.
    store = _new_store()
    store["session"]["state"] = S.ASK_FINAL_NOTES.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": True, "logos_done": True, "pending_logo": None,
        "email_captured": True, "email_verified": True, "lead_id": "L1", "decor_done": True,
        "quantity": 12, "decoration_done": True, "needed_by": "2-4 weeks",
        "purpose": "team caps", "design_confirmed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "get_store", lambda _id: None)
    # Interpreter MUST NOT be called for a direct_capture step.
    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run for direct_capture")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    out = await o2.handle_message("s1", "Text in Pantone 186 C please")

    assert "Customer final notes: Text in Pantone 186 C please" in \
        store["session"]["collected"]["brief_notes"]
    assert store["session"]["collected"]["final_notes_done"] is True
    assert store["session"]["state"] == S.REQUEST_QUOTE.value


@pytest.mark.asyncio
async def test_final_notes_whitespace_only_reasks_rather_than_advancing(monkeypatch):
    """A blank/whitespace turn is never a real answer (the empty-turn guard
    fires before the direct_capture branch): it must re-render ASK_FINAL_NOTES
    rather than banking an empty note and advancing to REQUEST_QUOTE."""
    store = _new_store()
    store["session"]["state"] = S.ASK_FINAL_NOTES.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": True, "logos_done": True, "pending_logo": None,
        "email_captured": True, "email_verified": True, "lead_id": "L1", "decor_done": True,
        "quantity": 12, "decoration_done": True, "needed_by": "2-4 weeks",
        "purpose": "team caps", "design_confirmed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "get_store", lambda _id: None)
    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run on a blank turn")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    out = await o2.handle_message("s1", "   ")

    assert store["session"]["state"] == S.ASK_FINAL_NOTES.value
    assert "final_notes_done" not in store["session"]["collected"]
    assert "brief_notes" not in store["session"]["collected"]


@pytest.mark.asyncio
async def test_final_notes_ask_shows_disclaimer_links(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.REVIEW_DESIGN.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": True, "logos_done": True, "pending_logo": None,
        "email_captured": True, "email_verified": True, "decor_done": True, "quantity": 12,
        "decoration_done": True, "needed_by": "2-4 weeks", "purpose": "team caps",
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "get_store", lambda _id: None)

    out = await o2.handle_message("s1", "Looks great, send it")

    assert store["session"]["state"] == S.ASK_FINAL_NOTES.value
    assert prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL in out["reply"]
    assert "we'll use it" in out["reply"]
    assert out["data"]["options"] == ["Nothing to add"]


@pytest.mark.asyncio
async def test_empty_turn_is_a_noop_and_never_reaches_the_interpreter(monkeypatch):
    """Regression: the live dead-loop. An empty/whitespace "" turn at an
    advanced non-greeting step was fed to interpret_turn_v2, which — given no
    real input but the full slot list — hallucinated well-typed slot values.
    first-unmet routing then walked the conversation BACKWARD, twice all the
    way to ask_name (with `name` wiped), making the flow unfinishable.

    Only the GREETING kickoff legitimately sends "". At every other owned step
    an empty turn must be a no-op: state unchanged, nothing cleared, and the
    interpreter must never run (feeding it "" is the whole bug).
    """
    store = _new_store()
    store["session"]["state"] = S.ASK_ADD_DECOR.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Satish", "has_logo": True,
        "logo_face": "front", "logo_placed": True, "logo_bg": "removed",
        "logos_done": True, "email_captured": True, "email_verified": True,
        "_asked": ["ask_name", "show_intro", "ask_has_logo",
                   "ask_logo_placement", "logo_adjust", "ask_logo_bg",
                   "ask_email", "ask_another_logo"],
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run on an empty turn")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "   ")   # whitespace-only

    assert res["state"] == S.ASK_ADD_DECOR.value               # stayed put
    assert store["session"]["collected"]["name"] == "Satish"   # nothing cleared


# --- Task 2: element-restart Back --------------------------------------------

@pytest.mark.asyncio
async def test_back_at_logo_bg_removes_the_logo_and_restarts_placement(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_LOGO_BG.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "left", "placed": True},
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_LOGO_PLACEMENT.value          # restart the element
    assert store["session"]["collected"]["pending_logo"] == {} # face/placed/bg cleared
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "left"}, "remove": True}]
    assert store["session"]["collected"]["_back_used"] is True # lock set
    assert out["data"]["can_go_back"] is False                 # can't back again yet


@pytest.mark.asyncio
async def test_back_at_decor_adjust_removes_the_decor_and_restarts(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.DECOR_ADJUST.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": False,
        "logos_done": True, "pending_logo": None, "email_captured": True, "email_verified": True,
        "decor_choice": "text", "decor_face": "back", "decor_placed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_ADD_DECOR.value               # re-pick text/shape
    collected = store["session"]["collected"]
    assert "decor_choice" not in collected
    assert "decor_face" not in collected
    assert "decor_placed" not in collected
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "back"}, "remove": True}]


@pytest.mark.asyncio
async def test_non_element_back_sets_the_lock_and_carries_no_canvas_op(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_QUANTITY.value                # normal rewind
    assert "canvas_ops" not in out["data"]
    assert store["session"]["collected"]["_back_used"] is True


# --- the email-verification gate ---------------------------------------------
# Answering ASK_EMAIL fires a double opt-in verification link. Until the
# customer opens it the flow must not move on: the gate step
# AWAIT_EMAIL_VERIFY is unmet, so first-unmet returns it every turn.


def _at_email_store():
    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "front", "placed": True, "bg": "none"},
    }
    return store


@pytest.mark.asyncio
async def test_giving_the_email_parks_the_flow_at_the_verification_gate(monkeypatch):
    store = _at_email_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: ("lead-1", True))
    _no_llm(monkeypatch)                       # direct_answer resolves the address

    res = await o2.handle_message("s1", "sam@example.com")

    assert res["state"] == S.AWAIT_EMAIL_VERIFY.value
    assert store["session"]["collected"]["email_captured"] is True
    # The address is echoed once, in the notice prepended to the gate's copy.
    assert "sam@example.com" in res["reply"]
    # Nothing to answer and no tool: the customer cannot act their way past it.
    assert res["data"].get("options") is None
    assert res["data"]["canvas"]["allowed_tools"] == []


@pytest.mark.asyncio
async def test_typing_at_the_gate_never_advances_and_never_calls_the_llm(monkeypatch):
    store = _at_email_store()
    store["session"]["state"] = S.AWAIT_EMAIL_VERIFY.value
    store["session"]["collected"]["email_captured"] = True
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    calls = []

    async def _spy(*a, **k):
        calls.append(a)
        return {}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _spy)

    for msg in ("yes I've verified it", "next please", "skip"):
        res = await o2.handle_message("s1", msg)
        assert res["state"] == S.AWAIT_EMAIL_VERIFY.value, msg
    # The gate declares no slots, so there is nothing to interpret — a customer
    # cannot talk their way past it, and idling here costs no model calls.
    assert calls == []
    # The retry copy is what a typed reply gets (the first render already said
    # a link was sent).
    assert res["reply"] == prompts.V2_AWAIT_VERIFY_RETRY


@pytest.mark.asyncio
async def test_the_gate_is_skipped_before_the_email_is_captured():
    """LOAD-BEARING: ask_email is deliberately SATISFIED early in the design
    (nothing placed yet), so a gate that only read `email_verified` would become
    first-unmet at the very start of the design phase and block it."""
    step = cs.by_id(S.AWAIT_EMAIL_VERIFY)
    assert step.done_when({"flow_mode": "canvas"})               # no email yet
    assert not step.done_when({"email_captured": True})          # sent, unconfirmed
    assert step.done_when({"email_captured": True, "email_verified": True})


@pytest.mark.asyncio
async def test_verification_poll_advances_the_flow_once_the_link_is_opened(monkeypatch):
    store = _at_email_store()
    store["session"]["state"] = S.AWAIT_EMAIL_VERIFY.value
    store["session"]["collected"]["email_captured"] = True
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    # Not verified yet: a no-op poll (reply=None) that leaves the state alone.
    res = await o2.check_verification("s1")
    assert res["reply"] is None
    assert res["state"] == S.AWAIT_EMAIL_VERIFY.value
    assert store["session"]["state"] == S.AWAIT_EMAIL_VERIFY.value

    # The customer opens the emailed link (leads.py flips this out-of-band).
    store["session"]["collected"]["email_verified"] = True
    res = await o2.check_verification("s1")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value
    assert store["session"]["state"] == S.ASK_ANOTHER_LOGO.value
    assert prompts.V2_EMAIL_VERIFIED_ACK in res["reply"]


# --- the verified turn is two messages (2026-08-01) ---------------------------

@pytest.mark.asyncio
async def test_verification_ack_and_the_next_question_are_two_separate_messages(monkeypatch):
    """A confirmation and a new question are two unrelated things. Merged into
    one bubble the customer reads past the confirmation into the question."""
    store = _at_email_store()
    store["session"]["state"] = S.AWAIT_EMAIL_VERIFY.value
    store["session"]["collected"]["email_captured"] = True
    store["session"]["collected"]["email_verified"] = True
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    res = await o2.check_verification("s1")

    assert res["reply"] == prompts.V2_EMAIL_VERIFIED_ACK
    extras = res["data"]["extra_replies"]
    assert len(extras) == 1
    assert prompts.V2_EMAIL_VERIFIED_ACK not in extras[0]     # not duplicated

    # Both are persisted, in order, as assistant rows — and no phantom user row.
    assistant = [r for r in store["rows"] if r["role"] == "assistant"]
    assert [r["content"] for r in assistant] == [res["reply"], extras[0]]
    assert not [r for r in store["rows"] if r["role"] == "user"]


@pytest.mark.asyncio
async def test_an_ordinary_turn_carries_no_extra_replies(monkeypatch):
    """`extra_replies` is absent on every other path, so nothing else changes."""
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "")
    assert "extra_replies" not in res["data"]


@pytest.mark.asyncio
async def test_the_verification_poll_delegates_a_non_gate_state_to_v1(monkeypatch):
    """The shared tail (post-generation VERIFY_EMAIL) is v1's, and the frontend
    polls the same endpoint there — so a v2 canvas session must not swallow it."""
    store = _at_email_store()
    store["session"]["state"] = S.VERIFY_EMAIL.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    seen = []

    async def _v1_check(sid):
        seen.append(sid)
        return {"reply": None, "state": S.VERIFY_EMAIL.value, "data": {}}
    monkeypatch.setattr(o2._v1, "check_verification", _v1_check)

    await o2.check_verification("s1")
    assert seen == ["s1"]


# --- Task 4: chat-side lenient guard (abuse decline) --------------------------

def _mid_flow_store():
    store = _new_store()
    store["session"]["state"] = S.ASK_QUANTITY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "logos": [{"face": "front", "placed": True}],
        "decor_done": True,
    }
    return store


@pytest.mark.asyncio
async def test_severe_abuse_re_renders_the_step_and_ingests_nothing(monkeypatch):
    """A slur must not advance the flow, and must not reach the interpreter."""
    from app.services import profanity

    store = _mid_flow_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run on a declined turn")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    res = await o2.handle_message("s1", "you are a <slur>")

    assert res["state"] == S.ASK_QUANTITY.value
    assert prompts.V2_ABUSE_DECLINE in res["reply"]
    assert "quantity" not in store["session"]["collected"]


@pytest.mark.asyncio
async def test_mild_profanity_does_not_block_the_funnel(monkeypatch):
    """Venting must not dead-end a sale — a mild turn is processed normally."""
    from app.services import profanity

    store = _mid_flow_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "mild")
    _llm_returns(monkeypatch, {"quantity": 50})

    res = await o2.handle_message("s1", "50 of the bloody things")

    assert prompts.V2_ABUSE_DECLINE not in res["reply"]
    assert res["state"] != S.ASK_QUANTITY.value


@pytest.mark.asyncio
async def test_the_decline_is_a_normal_reply_not_an_error(monkeypatch):
    """A 422 renders as an error banner and reads as a broken app."""
    from app.services import profanity

    store = _mid_flow_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    res = await o2.handle_message("s1", "abuse")
    assert isinstance(res.get("reply"), str) and res["reply"]


# --- I5: the identity steps are exempt from the severe decline ----------------
#
# OWNER RULING: "paki" and "heeb" stay in SEVERE_TERMS — they are kept for the
# cap path — but ASK_NAME and ASK_EMAIL are exempted, because both are also real
# surnames and the decline never advances: a customer called Paki, or one whose
# address contains their Heeb surname, would be permanently stuck on the FIRST
# question of the flow with no chip to escape via. These tests use the REAL
# scanner (no monkeypatched scan) — that is the point.

@pytest.mark.asyncio
async def test_a_real_surname_that_scans_severe_still_answers_ask_name(monkeypatch):
    from app.services import profanity

    assert profanity.scan("Paki") == "severe"      # the trap being exempted

    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)          # direct_answer resolves the name deterministically

    res = await o2.handle_message("s1", "Paki")

    assert prompts.V2_ABUSE_DECLINE not in res["reply"]
    assert store["session"]["collected"]["name"] == "Paki"
    assert res["state"] != S.ASK_NAME.value        # the flow advanced


@pytest.mark.asyncio
async def test_an_address_containing_a_surname_still_answers_ask_email(monkeypatch):
    from app.services import profanity

    assert profanity.scan("s.heeb@example.com") == "severe"

    store = _new_store()
    store["session"]["state"] = S.ASK_EMAIL.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "logos_done": True,
                                     "logos": [{"face": "front", "placed": True}],
                                     "decor_done": True, "quantity": 50,
                                     "decoration_type": "embroidery"}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, email: ("lead-1", True))
    _no_llm(monkeypatch)          # direct_answer extracts the address itself

    res = await o2.handle_message("s1", "s.heeb@example.com")

    assert prompts.V2_ABUSE_DECLINE not in res["reply"]
    assert store["session"]["collected"]["email_captured"] is True
    assert res["state"] == S.AWAIT_EMAIL_VERIFY.value


@pytest.mark.asyncio
async def test_the_same_severe_term_still_declines_at_every_other_step(monkeypatch):
    """The exemption is scoped to the identity steps and nothing else."""
    store = _mid_flow_store()                      # rests at ASK_QUANTITY
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run on a declined turn")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    res = await o2.handle_message("s1", "Paki")

    assert prompts.V2_ABUSE_DECLINE in res["reply"]
    assert res["state"] == S.ASK_QUANTITY.value
    assert "quantity" not in store["session"]["collected"]


# --- ASK_PURPOSE accepts anything (2026-08-01) --------------------------------

def _at_purpose_store():
    """A session parked at ASK_PURPOSE, built by walking the registry."""
    from tests.canvas_step_helpers import seed_for
    collected = seed_for(cs.by_id(S.ASK_PURPOSE))
    collected["flow_mode"] = "canvas"
    return {"session": {"id": "s1", "state": S.ASK_PURPOSE.value,
                        "collected": collected, "upsell_count": 0}}


@pytest.mark.asyncio
async def test_purpose_banks_a_refusal_verbatim_when_the_interpreter_reads_nothing(monkeypatch):
    """A refusal is a valid answer. The interpreter declines to fill `purpose`
    for "rather not say", which left done_when unmet and re-asked forever — and
    ASK_PURPOSE ships no chips, so there was no way out."""
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {})            # interpreter reads nothing
    res = await o2.handle_message("s1", "rather not say")
    assert store["session"]["collected"]["purpose"] == "rather not say"
    assert res["state"] != S.ASK_PURPOSE.value


@pytest.mark.asyncio
async def test_purpose_banks_a_misspelled_answer_verbatim(monkeypatch):
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {})
    await o2.handle_message("s1", "stff uniforsm for the shp")
    assert store["session"]["collected"]["purpose"] == "stff uniforsm for the shp"


@pytest.mark.asyncio
async def test_a_parsed_purpose_still_wins_over_the_verbatim_fallback(monkeypatch):
    """The fallback fires ONLY when the interpreter read nothing into the slot."""
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"purpose": "staff uniforms"})
    await o2.handle_message("s1", "umm stff uniforsm i guess")
    assert store["session"]["collected"]["purpose"] == "staff uniforms"


# --- paragraph layout (2026-08-01) -------------------------------------------

def test_reply_for_separates_the_question_from_its_tool_tip_with_a_blank_line():
    """One run-on paragraph is what made these replies hard to read. The bubble
    is whitespace-pre-wrap, so the separation has to come from the copy."""
    from app.services.conversation import state_machine_v2 as v2
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)          # has a tip
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i")
    assert step.tip in body
    assert "\n\n" + step.tip in body


def test_reply_for_separates_the_ack_from_the_question_with_a_blank_line():
    from app.services.conversation import state_machine_v2 as v2
    step = cs.by_id(S.ASK_QUANTITY)
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i", ack="Understood.")
    assert body.startswith("Understood.\n\n")
