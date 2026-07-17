"""Test dispatch routing (v1 vs v2) in chat.py."""
from __future__ import annotations

import pytest
from app.api.routes import chat as chat_route
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    """Minimal fake table chain."""

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": [{"collected": {"flow_mode": "canvas"}}]})()


class _FakeSB:
    """Minimal fake Supabase client."""

    def table(self, name):
        return _FakeTable()


@pytest.mark.asyncio
async def test_dispatch_v2_when_flag_on_and_canvas(monkeypatch):
    """Route to v2 when flag is on and session's flow_mode is canvas."""
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _FakeSB())

    called = {}

    async def fake_v2(sid, msg):
        called["v2"] = True
        return {"reply": "hi", "state": S.ASK_NAME.value, "data": {}}

    monkeypatch.setattr(chat_route, "handle_message_v2", fake_v2)
    await chat_route._dispatch("session-id-1", "hello")
    assert called.get("v2") is True


@pytest.mark.asyncio
async def test_dispatch_v1_when_flag_off(monkeypatch):
    """Route to v1 when flag is off."""
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", False)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _FakeSB())

    called = {}

    async def fake_v1(sid, msg):
        called["v1"] = True
        return {"reply": "hi", "state": S.ASK_NAME.value, "data": {}}

    monkeypatch.setattr(chat_route, "handle_message", fake_v1)
    await chat_route._dispatch("session-id-2", "hello")
    assert called.get("v1") is True
