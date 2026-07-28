"""The chat notices a background tick the customer made themselves.

End-to-end through orchestrator_v2: a "Done" turn at LOGO_ADJUST carrying the
live canvas skips ASK_LOGO_BG and says so, instead of asking a question the
customer has already answered on screen.
"""
from __future__ import annotations

import pytest

from app import prompts
from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
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


def _at_logo_adjust():
    # email_captured + email_verified: the 2026-07-26 hard verification gate
    # (ASK_EMAIL -> AWAIT_EMAIL_VERIFY) sits between ASK_LOGO_BG and
    # ASK_ANOTHER_LOGO in the registry. Without both flags, completing this
    # first logo would correctly route to ASK_EMAIL (unrelated to background
    # auto-detection) rather than ASK_ANOTHER_LOGO — this fixture models a
    # session where the customer already verified earlier in the loop, per the
    # documented "past the email step" fixture convention.
    return {"session": {
        "id": "s1",
        "state": S.LOGO_ADJUST.value,
        "collected": {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                      "has_logo": True, "pending_logo": {"face": "front"},
                      "email_captured": True, "email_verified": True},
        "upsell_count": 0,
    }}


def _no_llm(monkeypatch):
    """A chip tap must need no model at all."""
    async def _boom(*a, **k):
        raise ie.LLMUnavailable("no key")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


def _design(remove_bg: bool):
    return {"colourway": None,
            "faces": {"front": [{"type": "image", "locked": False,
                                 "removeBg": remove_bg}],
                      "back": [], "left": [], "right": []}}


@pytest.mark.asyncio
async def test_a_ticked_logo_skips_the_background_question(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(True))

    assert res["state"] == S.ASK_ANOTHER_LOGO.value
    assert store["session"]["collected"]["pending_logo"]["bg"] == "removed"


@pytest.mark.asyncio
async def test_the_skip_is_acknowledged_in_the_reply(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(True))

    assert prompts.V2_BG_ALREADY_REMOVED in res["reply"]


@pytest.mark.asyncio
async def test_an_unticked_logo_still_gets_asked(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(False))

    assert res["state"] == S.ASK_LOGO_BG.value
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]


@pytest.mark.asyncio
async def test_no_canvas_blob_behaves_exactly_as_before(monkeypatch):
    """Every other turn in the flow sends no blob; none of them may change."""
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done")

    assert res["state"] == S.ASK_LOGO_BG.value
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]


@pytest.mark.asyncio
async def test_the_ack_is_not_prepended_on_an_unrelated_turn(monkeypatch):
    """A blob arriving at a step with no pending logo must be inert.

    Note this drives the FULL turn (interpreter returns a real field) rather
    than letting it stall — a stalled turn returns before observe_canvas is
    ever reached, which would make this pass for the wrong reason.
    """
    store = _at_logo_adjust()
    store["session"]["state"] = S.ASK_QUANTITY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos": [{"face": "front", "placed": True, "bg": "none"}],
        "logos_done": True, "pending_logo": None, "decor_done": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _ok(*a, **k):
        return {"quantity": 50}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _ok)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "50", canvas_design=_design(True))

    assert store["session"]["collected"]["quantity"] == 50   # the turn advanced
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]
