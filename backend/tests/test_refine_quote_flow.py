"""Canvas refine → change-method → quote handoff routing."""
from __future__ import annotations

from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation.state_machine import advance_state


def test_offer_refine_wants_changes_goes_to_change_method_for_canvas():
    c = {"flow_mode": "canvas", "wants_changes": True}
    assert advance_state(S.OFFER_REFINE, c) is S.ASK_CHANGE_METHOD


def test_offer_refine_happy_goes_to_quote_for_canvas():
    c = {"flow_mode": "canvas", "wants_changes": False}
    assert advance_state(S.OFFER_REFINE, c) is S.QUOTE_REQUESTED


def test_change_method_rework_goes_back_to_canvas():
    c = {"flow_mode": "canvas", "rework_on_canvas": True}
    assert advance_state(S.ASK_CHANGE_METHOD, c) is S.CANVAS_DESIGN


def test_change_method_describe_goes_to_describe_changes():
    c = {"flow_mode": "canvas", "rework_on_canvas": False}
    assert advance_state(S.ASK_CHANGE_METHOD, c) is S.DESCRIBE_CHANGES


def test_quote_requested_ends_session_for_canvas():
    c = {"flow_mode": "canvas"}
    assert advance_state(S.QUOTE_REQUESTED, c) is S.SESSION_END


def test_non_canvas_quote_requested_still_upsells():
    # The legacy chat flow is untouched.
    c = {}
    assert advance_state(S.QUOTE_REQUESTED, c) is S.UPSELL_PROMPT


# --- Orchestrator wiring: the in-chat quote handoff ------------------------
import pytest

from app.services.conversation import orchestrator as orch
from tests.test_conversation_smart import (
    _FakeSB, _fake_settings, _fixed_interpret, _fixed_reply,
)


@pytest.mark.asyncio
async def test_quote_yes_ends_session_and_surfaces_quote_link(monkeypatch):
    store = {"session": {"id": "s1", "state": S.QUOTE_REQUESTED.value,
                         "collected": {"flow_mode": "canvas"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer"}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    monkeypatch.setattr(orch, "_session_quote_url", lambda sid: "http://x/quote/tok")

    res = await orch.handle_message("s1", "Yes, request a quote")
    assert res["state"] == S.SESSION_END.value
    assert res["data"]["quote_url"] == "http://x/quote/tok"
    assert store["session"]["collected"]["wants_quote"] is True


@pytest.mark.asyncio
async def test_quote_no_ends_session_without_link(monkeypatch):
    store = {"session": {"id": "s1", "state": S.QUOTE_REQUESTED.value,
                         "collected": {"flow_mode": "canvas"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer"}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))

    res = await orch.handle_message("s1", "No, I'm all set")
    assert res["state"] == S.SESSION_END.value
    assert "quote_url" not in res["data"]
