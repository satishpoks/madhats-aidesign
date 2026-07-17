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
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True, "logos_done": True,
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
    assert res["data"]["options"] == ["Yes, another logo", "No, that's it"]


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
    assert res["data"]["progress"]["total"] == 7


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
        "email_captured": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: False)
    _llm_returns(monkeypatch, {"purpose": "team caps"})
    res = await o2.handle_message("s1", "for the team")
    assert res["state"] == S.QUOTE_REQUESTED.value
    assert res["data"]["options"] == ["Yes, request a quote", "No, I'm all set"]


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
    assert res["state"] == S.ASK_PURPOSE.value


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
async def test_typed_no_more_decor_advances_to_quantity(monkeypatch):
    """Finding 1 (final review), interpreter path end to end: a typed decline
    must not re-ask ASK_ANYTHING_ELSE forever.

    The message deliberately does NOT match either chip label verbatim (chip
    matching is case/whitespace-insensitive on the exact label, so a message
    that happens to equal "No, that's everything" would take the chip path
    and mask this bug, same as the model-free e2e did).
    """
    store = _new_store()
    store["session"]["state"] = S.ASK_ANYTHING_ELSE.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_choice": "text", "decor_placed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"more_decor": False})
    res = await o2.handle_message("s1", "nah, nothing more thanks")
    assert res["state"] == S.ASK_QUANTITY.value      # must NOT re-ask itself


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
        id=S.ASK_QUANTITY,  # reuse an unused state for this test
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
