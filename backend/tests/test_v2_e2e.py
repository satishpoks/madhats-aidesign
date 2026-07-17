"""End-to-end walk of the v2 canvas orchestrator's front half.

Drives `orchestrator_v2.handle_message` one turn at a time through the full
name -> intro -> logo loop -> text/shape loop -> quantity -> email -> purpose
-> FINALIZE_CANVAS sequence, asserting the resulting state after every turn.

Reuses the `_FakeSB`/`_FakeTable` fake-Supabase pattern from
`test_orchestrator_v2.py` (there is no conftest.py / pytest fixture registry
in this test suite — each test file wires its own fakes).
"""
import pytest

from app.services.conversation import canvas_steps as cs
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


def test_v2_no_longer_uses_the_shared_keyword_matchers():
    """v1 keeps is_affirmative/is_negative (it still routes on them); v2 must
    not import them. `is_negative` matches by substring, so "another" reads as
    "no" — that is what broke the logo loop. Task 8's rewrite also moved the
    name/done-word/face helpers out of orchestrator_v2 entirely: they either
    became registry data (canvas_steps.py) or were replaced by the generic
    first-unmet router (state_machine_v2.py)."""
    with open(o2.__file__, encoding="utf-8") as fh:
        text = fh.read()
    for banned in (
        "is_affirmative", "is_negative", "_apply_v2_fields", "_is_done",
        "_face_from", "_plausible_name", "_NAME_FILLER",
    ):
        assert banned not in text, f"{banned} still referenced in orchestrator_v2"


@pytest.mark.asyncio
async def test_full_v2_walk_using_the_exact_chip_labels(monkeypatch):
    """Drives the exact strings the UI ships. The old e2e hand-picked "yes" to
    dodge the broken "another" chip and stayed green over the bug; this walk
    drives "Yes, another logo" for real.

    The interpreter raises LLMUnavailable for the ENTIRE walk (no mid-walk
    swap) — proving something stronger than a plain e2e: chips resolve by
    deterministic label match, and the three free-text steps (name/email/
    purpose) resolve via `Step.direct_answer`, so the whole v2 front half
    completes with NO model at all.
    """
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: True)
    monkeypatch.setattr(
        cs.leads_service, "capture_lead_and_verify",
        lambda s, c, e: ("lead-1", True),
    )

    async def _boom(*a, **k):
        raise o2.ie.LLMUnavailable("chips and direct-answer steps need no model")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    walk = [
        ("",                        S.ASK_NAME),
        ("Sam",                     S.SHOW_INTRO),
        ("ok",                      S.ASK_LOGO_PLACEMENT),   # intro ack (no slots)
        ("Front",                   S.LOGO_ADJUST),
        ("Done",                    S.ASK_ANOTHER_LOGO),
        ("Yes, another logo",       S.ASK_LOGO_PLACEMENT),   # THE bug
        ("Back",                    S.LOGO_ADJUST),
        ("Done",                    S.ASK_ANOTHER_LOGO),
        ("No, that's it",           S.ASK_ADD_DECOR),
        ("Add text",                S.DECOR_ADJUST),
        ("Done",                    S.ASK_ANYTHING_ELSE),
        ("No, that's everything",   S.ASK_QUANTITY),
        ("50-99",                   S.ASK_EMAIL),
        ("sam@example.com",         S.ASK_PURPOSE),
        ("for the team",            S.FINALIZE_CANVAS),
    ]

    res = None
    for msg, expected in walk:
        res = await o2.handle_message("s1", msg)
        assert res["state"] == expected.value, f"{msg!r} -> {res['state']}"

    # The finalize state tells the frontend to flatten + finalize.
    assert res["data"]["trigger_finalize"] is True

    c = store["session"]["collected"]
    assert len(c["logos"]) == 2
    assert [l["face"] for l in c["logos"]] == ["front", "back"]
    assert c["quantity"] == 50
