"""check_verification() — the chat's poll while it waits at VERIFY_EMAIL.

Verification lands out-of-band (the customer clicks the emailed link, which
flips collected.email_verified). The poll must then advance the thread to
EMAIL_VERIFIED and return Ricardo's confirmation — and do nothing until then.
"""
from __future__ import annotations

import asyncio

from app.services.conversation import orchestrator


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable stand-in for a supabase-py table query."""

    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self._sink.setdefault("updates", []).append(payload)
        return self

    def insert(self, payload):
        self._sink.setdefault("inserts", []).append(payload)
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, session_row):
        self._session_row = session_row
        self.sink: dict = {}

    def table(self, name):
        rows = [self._session_row] if name == "design_sessions" else []
        return _Query(rows, self.sink)


def _patch(monkeypatch, session_row):
    fake = _FakeSB(session_row)
    monkeypatch.setattr(orchestrator, "get_supabase", lambda: fake)
    monkeypatch.setattr(orchestrator, "get_store", lambda _sid: None)

    async def _reply(state, collected, persona):
        return f"[{state}] confirmed"

    monkeypatch.setattr(orchestrator.ie, "generate_reply", _reply)
    return fake


def test_poll_advances_once_verified(monkeypatch):
    session = {
        "id": "sess-1",
        "state": "verify_email",
        "collected": {"email_captured": True, "email_verified": True},
        "store_id": None,
    }
    fake = _patch(monkeypatch, session)

    result = asyncio.run(orchestrator.check_verification("sess-1"))

    assert result["state"] == "email_verified"
    assert result["reply"] == "[email_verified] confirmed"
    # email_verified is a statement-only state the user taps through; every
    # turn also carries the step/total progress payload.
    assert result["data"]["continuable"] is True
    assert "progress" in result["data"]
    # Exactly one assistant line was appended — no phantom user turn.
    inserts = fake.sink.get("inserts", [])
    assert len(inserts) == 1
    assert inserts[0]["role"] == "assistant"
    assert inserts[0]["state_before"] == "verify_email"
    assert inserts[0]["state_after"] == "email_verified"


def test_poll_noops_until_verified(monkeypatch):
    session = {
        "id": "sess-2",
        "state": "verify_email",
        "collected": {"email_captured": True},  # not verified yet
        "store_id": None,
    }
    fake = _patch(monkeypatch, session)

    result = asyncio.run(orchestrator.check_verification("sess-2"))

    assert result["reply"] is None
    assert result["state"] == "verify_email"
    # Nothing persisted while we wait.
    assert fake.sink.get("inserts") is None
    assert fake.sink.get("updates") is None
