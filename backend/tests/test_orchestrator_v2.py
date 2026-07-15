import pytest

from app import prompts
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


@pytest.mark.asyncio
async def test_kickoff_greets_and_advances_to_ask_name(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    res = await o2.handle_message("s1", "")

    assert res["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_name_advances_to_intro_with_admin_text(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    await o2.handle_message("s1", "")          # greeting -> ask_name
    res = await o2.handle_message("s1", "Sam")  # name -> show_intro

    assert res["state"] == S.SHOW_INTRO.value
    # No store configured (store_id omitted from the fake session), so the
    # defensive Task-7 fallback returns the module default intro text.
    assert prompts.V2_DEFAULT_INTRO in res["reply"]
    assert res["data"]["continuable"] is True


@pytest.mark.asyncio
async def test_logo_placement_emits_upload_directive(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    await o2.handle_message("s1", "")
    await o2.handle_message("s1", "Sam")
    res = await o2.handle_message("s1", "continue")  # intro -> placement

    assert res["state"] == S.ASK_LOGO_PLACEMENT.value
    assert res["data"]["canvas"]["allowed_tools"] == ["upload"]


@pytest.mark.asyncio
async def test_done_locks_and_advances_to_another_logo(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    res = None
    for m in ("", "Sam", "continue", "Front"):
        res = await o2.handle_message("s1", m)
    assert res["state"] == S.LOGO_ADJUST.value

    res = await o2.handle_message("s1", "done")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value


@pytest.mark.asyncio
async def test_tail_state_delegates_to_v1(monkeypatch):
    # A shared tail state (not in v2's owned set) must hand the turn to v1.
    store = _new_store()
    store["session"]["state"] = S.OFFER_REFINE.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    sentinel = {"reply": "V1", "state": S.OFFER_REFINE.value, "data": {}}

    async def _fake_v1(session_id, message):
        return sentinel

    monkeypatch.setattr(o2._v1, "handle_message", _fake_v1)

    res = await o2.handle_message("s1", "tweak the logo")
    assert res is sentinel


@pytest.mark.asyncio
async def test_daily_cap_reroutes_to_quote_with_honest_copy(monkeypatch):
    # At the ASK_PURPOSE turn the flow tries to enter FINALIZE_CANVAS; a capped
    # customer is rerouted to QUOTE_REQUESTED with honest block copy this turn.
    store = _new_store()
    store["session"]["state"] = S.ASK_PURPOSE.value
    store["session"]["collected"] = {"flow_mode": "canvas", "email_captured": True}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda sid: False)

    res = await o2.handle_message("s1", "for our footy club")

    assert res["state"] == S.QUOTE_REQUESTED.value
    assert prompts.GENERATION_BLOCKED_ASIDE in res["reply"]
    assert res["data"]["options"] == ["Yes, request a quote", "No, I'm all set"]
