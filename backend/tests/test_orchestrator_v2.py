import pytest

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import checkpoints as cp
from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S
from tests.canvas_fake_supabase import FakeSB as _FakeSB


def _new_store():
    return {
        "session": {
            "id": "s1",
            "state": S.GREETING.value,
            "collected": {"flow_mode": "canvas"},
            "upsell_count": 0,
        }
    }


def _ckpt(**kw) -> dict:
    """A `session_checkpoints` row fixture for `store["checkpoints"]`.

    `session_id` defaults to "s1" (the fake filters on it — see
    `canvas_fake_supabase.FakeQuery._matches` — same as the real client), and
    every other optional column defaults to its usual empty value, so a test
    only spells out what it cares about."""
    row = {"session_id": "s1", "canvas_design": None, "chat_watermark": None,
           "superseded_at": None}
    row.update(kw)
    return row


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


# --- handle_back: restore a checkpoint by seq (Task 5 rewrite of Task C2) -----
#
# The single-step "undo the last answer" model (`handle_back(session_id)`,
# `_back_used`, `back_clears`, `back_removes_element`) is retired wholesale in
# favour of checkpoint restore: `handle_back(session_id, seq)` rolls `collected`
# back to the exact snapshot taken on ENTRY to an earlier checkpoint-opening
# step (`checkpoints.capture`/`restore`, Task 4; offerability via
# `state_machine_v2.back_targets`, Task 3). The tests below are rewrites of the
# pre-Task-5 suite pinning the OLD single-step model — each docstring says what
# it used to assert and why the new behaviour differs.

@pytest.mark.asyncio
async def test_back_restores_the_snapshot_taken_before_the_answer(monkeypatch):
    """Was `test_back_clears_the_last_answer_and_re_asks`: clearing the current
    step's own slots in place. Now: restoring the `quantity` checkpoint (opened
    on ENTRY to ASK_QUANTITY, before it was answered) drops the answer because
    it was never in that snapshot — not because anything is cleared."""
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
    })
    store["checkpoints"] = [
        _ckpt(seq=1, kind="quantity", label="Quantity — not set",
              step_id=S.ASK_QUANTITY.value,
              collected={"name": "Sam", "intro_ack": True, "has_logo": False,
                         "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True,
                         "email_captured": True, "email_verified": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_QUANTITY.value          # re-asked
    assert "quantity" not in store["session"]["collected"]  # answer absent


@pytest.mark.asyncio
async def test_back_with_no_checkpoints_raises_checkpoint_unavailable(monkeypatch):
    """Was `test_back_at_the_start_is_a_no_op`: Back at the very first step
    silently re-rendered it. Now there is no seq to ask for at all — no
    checkpoint has ever been captured — so any seq is unoffered and the call
    raises rather than silently no-opping."""
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    with pytest.raises(cp.CheckpointUnavailable):
        await o2.handle_back("s1", 1)


@pytest.mark.asyncio
async def test_back_at_greeting_with_no_checkpoints_raises_checkpoint_unavailable(monkeypatch):
    """Was `test_back_at_greeting_does_not_crash`, pinning a dedicated GREETING
    guard in the old single-step `handle_back` (which had no `seq` and no
    session_checkpoints table to consult). The new `handle_back` needs no such
    guard: GREETING is still in V2_OWNED so it passes that check, but no
    checkpoint can exist before the very first turn, so `back_targets` is
    empty and any seq is unoffered — CheckpointUnavailable, not a crash."""
    store = _new_store()
    assert store["session"]["state"] == S.GREETING.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    with pytest.raises(cp.CheckpointUnavailable):
        await o2.handle_back("s1", 1)


def test_public_forwards_back_targets_verbatim_and_defaults_to_empty():
    """Was `test_public_data_carries_can_go_back` (`can_go_back` computed
    inside `_public` from `last_answered_step`, now deleted) plus
    `test_public_flags_back_removes_element_only_mid_element` and
    `test_public_can_go_back_is_suppressed_while_back_used` (the
    `back_removes_element`/`_back_used` machinery, also deleted). `_public`
    now does none of that routing itself — it just carries whatever `targets`
    list the caller (which owns the checkpoint read) hands it, defaulting to
    an empty list when none is given."""
    d_default = o2._public(cs.by_id(S.ASK_NAME), {})
    assert d_default["back_targets"] == []

    given = [{"seq": 2, "kind": "logo", "label": "Logo 1"},
             {"seq": 1, "kind": "name", "label": "Your name — Sam"}]
    d_given = o2._public(cs.by_id(S.ASK_QUANTITY), {}, targets=given)
    assert d_given["back_targets"] == given


@pytest.mark.asyncio
async def test_back_restoring_the_decoration_checkpoint_clears_derived_flags_but_keeps_loaded_options(monkeypatch):
    """Was `test_back_from_post_decoration_state_undoes_the_decoration_method`
    (via `Step.back_clears`, now deleted). The decoration checkpoint is
    captured on ENTRY to ASK_DECORATION — AFTER `_prepare_decoration` has
    already loaded `decoration_options` (capture sits after the `prepare`
    re-resolution in `handle_message`) — so restoring to it keeps the loaded
    chips but drops the answer derived from them, with no `back_clears`
    concept needed at all."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
        "decoration_options": ["Embroidery", "Screen Print"],
        "decoration_types": ["Embroidery"], "decoration_done": True,
        "decoration_type": "embroidery",
    })
    store["checkpoints"] = [
        _ckpt(seq=1, kind="decoration", label="Decoration — not set",
              step_id=S.ASK_DECORATION.value,
              collected={"name": "Sam", "intro_ack": True, "has_logo": False,
                         "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True, "quantity": 50,
                         "email_captured": True, "email_verified": True,
                         "decoration_options": ["Embroidery", "Screen Print"]}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_DECORATION.value
    collected = store["session"]["collected"]
    assert "decoration_done" not in collected
    assert "decoration_types" not in collected
    assert "decoration_type" not in collected
    assert collected["decoration_options"] == ["Embroidery", "Screen Print"]
    # Terminal flags carry forward regardless of the snapshot's own contents.
    assert collected.get("email_captured") is True


@pytest.mark.asyncio
async def test_handle_back_after_quote_requested_raises_checkpoint_unavailable(monkeypatch):
    """Was `test_handle_back_at_finalize_is_a_no_op_and_keeps_quote_requested`
    (a silent no-op via `_TERMINAL_FLAGS`, now deleted). Regression (C-1): a
    committed quote must not be re-submittable via Back — `back_targets`
    returns `[]` outright once `quote_requested` is set (state_machine_v2),
    independent of any checkpoint's own `frozen_when`.

    Fix round 1 (Minor 3): a `seed_for(REGISTRY[-1])` fixture walks the WHOLE
    registry forward, which also sets `design_confirmed`/`decor_done`/
    `email_verified` — every other freeze predicate in the registry — so a
    seeded `name` row (frozen on `email_verified`) stayed frozen even with the
    `quote_requested` guard deleted, and the test passed for the wrong reason.
    This seeds a `quantity` row (frozen only on `design_confirmed`, which is
    deliberately NOT set here) so the ONLY thing blocking it is the
    `quote_requested` guard itself — deleting that guard makes this test fail,
    which is what "discriminating" means."""
    store = _new_store()
    store["session"]["state"] = S.FINALIZE_CANVAS.value
    store["session"]["collected"] = {"flow_mode": "canvas", "quote_requested": True}
    store["checkpoints"] = [
        _ckpt(seq=1, kind="quantity", label="Quantity — not set",
              step_id=S.ASK_QUANTITY.value, collected={"flow_mode": "canvas"}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    with pytest.raises(cp.CheckpointUnavailable):
        await o2.handle_back("s1", 1)
    assert store["session"]["collected"]["quote_requested"] is True


@pytest.mark.asyncio
async def test_forward_turn_captures_a_checkpoint_for_the_step_it_enters(monkeypatch):
    """Was `test_forward_turn_clears_the_back_lock`, pinning the per-Back
    `_back_used` lock (now deleted entirely — there is no more "one step per
    Back" restriction, since each checkpoint is independently offerable).
    What a forward turn does now: `handle_message`'s capture hook writes a
    session_checkpoints row for the step it advances INTO, when that step
    opens one."""
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)                        # chip tap needs no model
    res = await o2.handle_message("s1", "Yes, another logo")
    assert res["state"] == S.ASK_LOGO_PLACEMENT.value
    rows = [r for r in store.get("checkpoints", [])
            if r["step_id"] == S.ASK_LOGO_PLACEMENT.value]
    assert len(rows) == 1
    assert rows[0]["kind"] == "logo"


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


# --- Task 2 (rewritten): checkpoint restore for the logo/decor loops ---------
#
# The old model emitted a `remove` canvas_op to delete the in-progress element
# and reset its loop slots in place. The new model restores the checkpoint
# captured on ENTRY to the loop's opener step — the customer lands back on
# that question with the canvas/collected exactly as they stood before this
# pass through the loop began, via `canvas_restore` (Step1's dedicated tests
# cover that field directly) rather than a `remove` op.

@pytest.mark.asyncio
async def test_back_at_logo_bg_restores_the_snapshot_before_this_logo_was_started(monkeypatch):
    """Was `test_back_at_logo_bg_removes_the_logo_and_restarts_placement`."""
    store = _new_store()
    store["session"]["state"] = S.ASK_LOGO_BG.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "left", "placed": True},
    }
    store["checkpoints"] = [
        _ckpt(seq=1, kind="logo", label="Logo 1",
              step_id=S.ASK_LOGO_PLACEMENT.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_LOGO_PLACEMENT.value
    assert "pending_logo" not in store["session"]["collected"]


@pytest.mark.asyncio
async def test_back_at_decor_adjust_restores_the_snapshot_before_this_decoration_was_started(monkeypatch):
    """Was `test_back_at_decor_adjust_removes_the_decor_and_restarts`."""
    store = _new_store()
    store["session"]["state"] = S.DECOR_ADJUST.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": False,
        "logos_done": True, "pending_logo": None, "email_captured": True, "email_verified": True,
        "decor_choice": "text", "decor_face": "back", "decor_placed": True,
    }
    store["checkpoints"] = [
        _ckpt(seq=1, kind="decor", label="Text or graphic",
              step_id=S.ASK_ADD_DECOR.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": False, "logos_done": True, "pending_logo": None,
                         "email_captured": True, "email_verified": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_ADD_DECOR.value
    collected = store["session"]["collected"]
    assert "decor_choice" not in collected
    assert "decor_face" not in collected
    assert "decor_placed" not in collected


@pytest.mark.asyncio
async def test_non_element_back_restores_with_no_canvas_restore_when_the_snapshot_has_none(monkeypatch):
    """Was `test_non_element_back_sets_the_lock_and_carries_no_canvas_op`."""
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True, "email_verified": True,
    })
    store["checkpoints"] = [
        _ckpt(seq=1, kind="quantity", label="Quantity — not set",
              step_id=S.ASK_QUANTITY.value,
              collected={"name": "Sam", "intro_ack": True, "has_logo": False,
                         "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True,
                         "email_captured": True, "email_verified": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_QUANTITY.value                # normal rewind
    assert "canvas_restore" not in out["data"]


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


@pytest.mark.asyncio
async def test_verification_poll_captures_a_checkpoint_for_the_step_it_lands_on(monkeypatch):
    """Fix round 1 (Important 1): the ONLY exit from AWAIT_EMAIL_VERIFY is
    this poll (the emailed link click), and it can land the session on a
    checkpoint-opening step exactly like a normal chat turn can.

    A text-only customer (has_logo=False, logos_done=True) never touches
    ASK_ANOTHER_LOGO on the way out — it self-satisfies once the logo loop is
    closed — and lands straight on ASK_ADD_DECOR (kind="decor") from here.
    `handle_message` never runs for this transition at all, so without a
    capture hook in `check_verification` itself that customer's first
    decoration is unreachable via Back, while every later loop pass (captured
    through a normal `handle_message` turn) is offerable — an inconsistent
    menu within a single session."""
    store = _new_store()
    store["session"]["state"] = S.AWAIT_EMAIL_VERIFY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": False, "logos_done": True, "pending_logo": None,
        "email_captured": True, "email_verified": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    res = await o2.check_verification("s1")

    assert res["state"] == S.ASK_ADD_DECOR.value
    rows = [r for r in store.get("checkpoints", [])
            if r["step_id"] == S.ASK_ADD_DECOR.value]
    assert len(rows) == 1
    assert rows[0]["kind"] == "decor"


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
    is whitespace-pre-wrap, so the separation has to come from the copy.

    Pinned on a synthetic step, not a real registry one: ASK_LOGO_PLACEMENT used
    to be the step this covered, but its tip was dropped (2026-08-01) — the
    canvas callout (directive_for) already shows V2_TOOL_TIPS["upload"], so
    repeating it in the chat bubble duplicated it on screen. No registry step
    still relies on reply_for's tip-append path, so this test constructs one
    directly to keep the join behaviour covered independent of any step's copy.
    """
    from app.services.conversation import state_machine_v2 as v2
    step = cs.Step(id=S.ASK_LOGO_PLACEMENT, ask="Where should it go?",
                   done_when=lambda c: True, tip="Select the highlighted button.")
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i")
    assert step.tip in body
    assert "\n\n" + step.tip in body


def test_reply_for_separates_the_ack_from_the_question_with_a_blank_line():
    from app.services.conversation import state_machine_v2 as v2
    step = cs.by_id(S.ASK_QUANTITY)
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i", ack="Understood.")
    assert body.startswith("Understood.\n\n")


# --- Task 5: structured Back — capture on entry, restore by seq --------------

@pytest.mark.asyncio
async def test_every_v2_turn_ships_the_back_menu(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    await o2.handle_message("s1", "")            # GREETING kickoff -> ASK_NAME
    res = await o2.handle_message("s1", "Satish")
    assert isinstance(res["data"]["back_targets"], list)


@pytest.mark.asyncio
async def test_entering_a_checkpoint_step_captures_exactly_one_row(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    await o2.handle_message("s1", "")            # GREETING kickoff -> ASK_NAME
    rows = store.get("checkpoints", [])
    assert len([r for r in rows if r["step_id"] == S.ASK_NAME.value]) == 1


@pytest.mark.asyncio
async def test_back_restores_collected_and_supersedes_later_rows(monkeypatch):
    """Seed three checkpoints, restore the middle one, assert `collected` is
    that snapshot and the row after it is superseded (not deleted) while the
    earlier row is left alone. Restoring to `name` (seq 1) can't be used here:
    its checkpoint freezes on `email_verified`, which this session already has
    set — so seq 2 (`quantity`, frozen only on `design_confirmed`) is the one
    exercised, matching the controller's own note on this exact trap."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": False, "logos_done": True, "pending_logo": None,
        "decor_done": True, "decor_placed": True, "quantity": 50,
        "email_captured": True, "email_verified": True,
    }
    store["checkpoints"] = [
        _ckpt(seq=1, kind="name", label="Your name — Sam",
              step_id=S.ASK_NAME.value, collected={"flow_mode": "canvas"}),
        _ckpt(seq=2, kind="quantity", label="Quantity — not set",
              step_id=S.ASK_QUANTITY.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": False, "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True,
                         "email_captured": True, "email_verified": True}),
        _ckpt(seq=3, kind="purpose", label="What it's for — not set",
              step_id=S.ASK_PURPOSE.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": False, "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True, "quantity": 50,
                         "email_captured": True, "email_verified": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 2)
    assert out["state"] == S.ASK_QUANTITY.value
    assert "quantity" not in store["session"]["collected"]
    assert store["session"]["collected"]["name"] == "Sam"       # part of seq2's own snapshot
    checkpoints = {r["seq"]: r for r in store["checkpoints"]}
    assert checkpoints[1]["superseded_at"] is None              # earlier row untouched
    assert checkpoints[2]["superseded_at"] is None              # the restored row itself
    assert checkpoints[3]["superseded_at"] is not None          # later row superseded


@pytest.mark.asyncio
async def test_back_returns_the_canvas_snapshot_when_there_is_one(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos": [{"face": "front", "placed": True}],
        "pending_logo": {"face": "back", "placed": True},
        "decor_done": False,
    }
    design_snapshot = {"colourway": "navy", "faces": {"front": [{"id": "e1"}]}}
    store["checkpoints"] = [
        _ckpt(seq=1, kind="logo", label="Logo 1",
              step_id=S.ASK_LOGO_PLACEMENT.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": True},
              canvas_design=design_snapshot),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_LOGO_PLACEMENT.value
    assert out["data"]["canvas_restore"] == design_snapshot


@pytest.mark.asyncio
async def test_back_omits_canvas_restore_when_the_snapshot_has_none(monkeypatch):
    """The `name` checkpoint is captured before any canvas exists."""
    store = _new_store()
    store["session"]["state"] = S.SHOW_INTRO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam"}
    store["checkpoints"] = [
        _ckpt(seq=1, kind="name", label="Your name — not set",
              step_id=S.ASK_NAME.value, collected={"flow_mode": "canvas"}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_NAME.value
    assert "canvas_restore" not in out["data"]


@pytest.mark.asyncio
async def test_back_on_an_unknown_seq_raises_checkpoint_unavailable(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_QUANTITY.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    with pytest.raises(cp.CheckpointUnavailable):
        await o2.handle_back("s1", 99)


@pytest.mark.asyncio
async def test_back_carries_forward_a_verified_email(monkeypatch):
    """Restoring to a checkpoint taken before the email step must not
    un-verify the customer."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": False,
        "logos_done": True, "pending_logo": None, "decor_done": True,
        "decor_placed": True, "quantity": 50, "email_captured": True,
        "email_verified": True, "lead_id": "L1",
    }
    store["checkpoints"] = [
        # snapshot predates the email step entirely
        _ckpt(seq=1, kind="quantity", label="Quantity — not set",
              step_id=S.ASK_QUANTITY.value,
              collected={"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                         "has_logo": False, "logos_done": True, "pending_logo": None,
                         "decor_done": True, "decor_placed": True}),
    ]
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1", 1)
    assert out["state"] == S.ASK_QUANTITY.value
    collected = store["session"]["collected"]
    assert collected["email_verified"] is True
    assert collected["email_captured"] is True
    assert collected["lead_id"] == "L1"


def test_the_old_back_machinery_is_gone():
    assert not hasattr(o2, "_restart_element")
    src = __import__("inspect").getsource(o2)
    assert "_back_used" not in src
    assert "back_removes_element" not in src
