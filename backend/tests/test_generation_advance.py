"""advance_after_generation() — moves GENERATING forward after generation settles.

Email is captured earlier now (SAVE_PROGRESS_EMAIL), so GENERATING has no user
email turn to advance it. The frontend calls this once, after startGeneration
settles, and it advances GENERATING -> VERIFY_EMAIL (or collapses to
OFFER_REFINE if already verified, or -> ASK_EMAIL if no email was captured).
"""
from __future__ import annotations

import asyncio

from app.services.conversation import orchestrator


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
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

    async def _reply(state, collected, persona, aside=None):
        return f"[{state}] aside={aside}"

    monkeypatch.setattr(orchestrator.ie, "generate_reply", _reply)
    return fake


def test_advances_to_verify_when_captured_not_verified(monkeypatch):
    session = {"id": "s1", "state": "generating",
               "collected": {"email_captured": True}, "store_id": None}
    fake = _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s1"))
    assert result["state"] == "verify_email"
    assert result["reply"].startswith("[verify_email]")
    inserts = fake.sink.get("inserts", [])
    assert len(inserts) == 1 and inserts[0]["role"] == "assistant"


def test_collapses_to_offer_refine_when_already_verified(monkeypatch):
    session = {"id": "s2", "state": "generating",
               "collected": {"email_captured": True, "email_verified": True}, "store_id": None}
    _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s2"))
    assert result["state"] == "offer_refine"
    assert "verified" in result["reply"].lower()
    assert result["data"]["options"] == ["Request changes", "Looks good"]


def test_falls_back_to_ask_email_when_no_email(monkeypatch):
    session = {"id": "s3", "state": "generating", "collected": {}, "store_id": None}
    _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s3"))
    assert result["state"] == "ask_email"


def test_noop_when_not_generating(monkeypatch):
    session = {"id": "s4", "state": "offer_refine",
               "collected": {"email_captured": True}, "store_id": None}
    fake = _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s4"))
    assert result["reply"] is None
    assert result["state"] == "offer_refine"
    assert fake.sink.get("inserts") is None
