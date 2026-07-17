import pytest

from app.services.conversation import orchestrator as orch
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


def _fake_settings():
    def _f():
        return type("S", (), {"faq_knowledge": ""})()
    return _f


def _fixed_reply(text):
    async def _f(*a, **k):
        return text
    return _f


@pytest.mark.asyncio
async def test_advance_after_regeneration_moves_to_offer_refine(monkeypatch):
    store = {
        "session": {
            "id": "s1",
            "state": S.REGENERATING.value,
            "collected": {"name": "Al", "wants_changes": True, "last_change": "make it bigger"},
            "upsell_count": 0,
        }
    }
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("Happy with it now?"))

    res = await orch.advance_after_regeneration("s1")

    assert res["reply"] == "Happy with it now?"
    assert res["state"] == S.OFFER_REFINE.value
    assert res["data"].get("options")
    # session persisted the new state and cleared the stale flag
    assert store["session"]["state"] == S.OFFER_REFINE.value
    assert store["session"]["collected"]["wants_changes"] is False


@pytest.mark.asyncio
async def test_advance_after_regeneration_clears_canvas_edit_scratch(monkeypatch):
    # The clear-list comment says "so the NEXT edit starts fresh" but omitted
    # the canvas_edit_* flags and the new edit_confirm_stalled/edit_confirmed
    # pair -- safe today only because _apply_canvas_edit/_apply_edit_confirm
    # pop their own flags, but the one clear list should be honest about all
    # of them so a future canvas edit doesn't start from stale scratch.
    store = {
        "session": {
            "id": "s1",
            "state": S.REGENERATING.value,
            "collected": {
                "name": "Al", "flow_mode": "canvas", "wants_changes": True,
                "canvas_edit_ops": True, "canvas_edit_refused": True,
                "canvas_edit_stalled": True, "edit_confirm_stalled": True,
                "edit_confirmed": True,
            },
            "upsell_count": 0,
        }
    }
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("Happy with it now?"))

    await orch.advance_after_regeneration("s1")

    collected = store["session"]["collected"]
    for key in ("canvas_edit_ops", "canvas_edit_refused", "canvas_edit_stalled",
                "edit_confirm_stalled", "edit_confirmed"):
        assert key not in collected


@pytest.mark.asyncio
async def test_advance_after_regeneration_noop_when_not_regenerating(monkeypatch):
    store = {
        "session": {
            "id": "s1",
            "state": S.OFFER_REFINE.value,
            "collected": {"name": "Al"},
            "upsell_count": 0,
        }
    }
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("should not be called"))

    res = await orch.advance_after_regeneration("s1")

    assert res["reply"] is None
    assert res["state"] == S.OFFER_REFINE.value
    # session untouched
    assert store["session"]["state"] == S.OFFER_REFINE.value


@pytest.mark.asyncio
async def test_advance_after_regeneration_raises_for_missing_session(monkeypatch):
    store = {"session": {"id": "s1", "state": S.REGENERATING.value, "collected": {}, "upsell_count": 0}}

    class _EmptySB:
        def table(self, name):
            class _T:
                def select(self, *a, **k):
                    return self

                def eq(self, *a, **k):
                    return self

                def limit(self, *_):
                    return self

                def execute(self):
                    return type("R", (), {"data": []})()

            return _T()

    monkeypatch.setattr(orch, "get_supabase", lambda: _EmptySB())
    with pytest.raises(orch.SessionNotFound):
        await orch.advance_after_regeneration("missing")
