"""End-to-end walk of the v2 canvas orchestrator's front half.

Drives `orchestrator_v2.handle_message` one turn at a time through the full
name -> intro -> logo loop -> text/shape loop -> quantity -> email -> purpose
-> FINALIZE_CANVAS sequence, asserting the resulting state after every turn.

Reuses the `_FakeSB`/`_FakeTable` fake-Supabase pattern from
`test_orchestrator_v2.py` (there is no conftest.py / pytest fixture registry
in this test suite — each test file wires its own fakes).
"""
import pytest

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
async def test_full_front_half_walk(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(
        o2.leads_service, "capture_lead_and_verify", lambda *a, **k: ("lead1", True)
    )
    monkeypatch.setattr(o2, "_can_start_design", lambda sid: True)

    turns = [
        ("", S.ASK_NAME),
        ("Sam", S.SHOW_INTRO),
        ("continue", S.ASK_LOGO_PLACEMENT),
        ("Back", S.LOGO_ADJUST),
        ("done", S.ASK_ANOTHER_LOGO),
        ("no", S.ASK_ADD_DECOR),
        ("Add text", S.DECOR_ADJUST),
        ("done", S.ASK_ANYTHING_ELSE),
        ("no", S.ASK_QUANTITY),
        ("50-99", S.ASK_EMAIL),
        ("sam@example.com", S.ASK_PURPOSE),
        ("Staff caps", S.FINALIZE_CANVAS),
    ]

    res = None
    for msg, expected in turns:
        res = await o2.handle_message("s1", msg)
        assert res["state"] == expected.value, (msg, res["state"])
        # Regression (CRITICAL 1): the face question must not auto-open the
        # upload dialog before it's answered …
        if expected is S.ASK_LOGO_PLACEMENT:
            assert res["data"]["canvas"]["auto_open"] is None
        # … and answering a non-front face must land the LOGO_ADJUST
        # directive on that face, not "front".
        if expected is S.LOGO_ADJUST:
            assert res["data"]["canvas"]["target_face"] == "back"
            assert res["data"]["canvas"]["auto_open"] == "upload"

    # The finalize state tells the frontend to flatten + finalize.
    assert res["data"]["trigger_finalize"] is True
