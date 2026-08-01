"""The chat notices a background tick the customer made themselves.

End-to-end through orchestrator_v2: a "Done" turn at LOGO_ADJUST carrying the
live canvas skips ASK_LOGO_BG silently, instead of asking a question the
customer has already answered on screen. (The customer-facing announcement
that used to accompany the skip was removed by owner request — the skip
itself, asserted here via the resulting state/reply, is unchanged.)
"""
from __future__ import annotations

import pytest

from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S
from tests.canvas_fake_supabase import FakeSB as _FakeSB


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
async def test_the_skip_moves_straight_to_the_next_question(monkeypatch):
    """No announcement is made (owner request, 2026-08-01) — the reply is
    simply ASK_ANOTHER_LOGO's own copy, not ASK_LOGO_BG's question repeated."""
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(True))

    assert "another logo" in res["reply"].lower()
    assert "background" not in res["reply"].lower()


@pytest.mark.asyncio
async def test_an_unticked_logo_still_gets_asked(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(False))

    assert res["state"] == S.ASK_LOGO_BG.value
    assert "background" in res["reply"].lower()


@pytest.mark.asyncio
async def test_no_canvas_blob_behaves_exactly_as_before(monkeypatch):
    """Every other turn in the flow sends no blob; none of them may change."""
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done")

    assert res["state"] == S.ASK_LOGO_BG.value
    assert "background" in res["reply"].lower()


@pytest.mark.asyncio
async def test_observe_canvas_is_inert_on_an_unrelated_turn(monkeypatch):
    """A blob arriving at a step with no pending logo must not disturb the turn.

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
    assert "background" not in res["reply"].lower()
