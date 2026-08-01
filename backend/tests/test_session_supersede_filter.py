"""Regression: the customer-facing GET /sessions/{token} reader must filter
chat_messages rows a checkpoint restore has marked superseded_at — the admin
reader (admin_diagnostics.py) deliberately keeps seeing everything, so this
test asserts the filter is applied specifically on the customer path.

Rows are never deleted on restore (append-only, audit trail), so this filter
is the only thing standing between the customer and a resurrected discarded
branch of the conversation.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

import app.api.routes.sessions as sessions_mod

_SESSION_ROW = {
    "id": "s1",
    "share_token": "tok",
    "state": "ask_name",
    "channel": "web",
    "entry_path": "pick_first",
    "product_ref": None,
    "collected": {},
    "status": "draft",
    "flow_mode": "canvas",
}


class _Result:
    def __init__(self, data):
        self.data = data


class _RecordingTable:
    """Fake supabase-py table that records every ``is_`` filter call.

    Modelled on the ``_FakeTable``/``_FakeSB`` pattern used across
    ``tests/test_orchestrator_v2.py`` and ``tests/test_canvas_routes.py``,
    extended only with the ``is_`` recorder this test needs.
    """

    def __init__(self, name, rows, calls):
        self.name = name
        self.rows = rows
        self.calls = calls

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def is_(self, col, val):
        self.calls.append((self.name, col, val))
        return self

    def execute(self):
        return _Result(self.rows)


class _FakeSB:
    def __init__(self, calls):
        self.calls = calls

    def table(self, name):
        rows = [_SESSION_ROW] if name == "design_sessions" else []
        return _RecordingTable(name, rows, self.calls)


def test_customer_session_reader_filters_superseded_chat_rows(monkeypatch):
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(sessions_mod, "get_supabase", lambda: _FakeSB(calls))

    from app.main import create_app

    client = TestClient(create_app())
    resp = client.get("/sessions/tok")

    assert resp.status_code == 200
    assert ("chat_messages", "superseded_at", "null") in calls
