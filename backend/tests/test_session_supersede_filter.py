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


class _MissingColumnTable(_RecordingTable):
    """A database that has not had 20260801000001 applied yet: postgrest raises
    `42703` (undefined column) the moment the `superseded_at` filter executes."""

    def __init__(self, name, rows, calls):
        super().__init__(name, rows, calls)
        self._filtered = False

    def is_(self, col, val):
        self._filtered = True
        return super().is_(col, val)

    def execute(self):
        if self._filtered:
            raise RuntimeError("column chat_messages.superseded_at does not exist")
        return _Result(self.rows)


class _MissingColumnSB(_FakeSB):
    def table(self, name):
        if name == "design_sessions":
            return _RecordingTable(name, [_SESSION_ROW], self.calls)
        return _MissingColumnTable(name, [], self.calls)


def test_customer_session_reader_survives_a_database_without_the_column(monkeypatch):
    """Deploy-order independence, not defensiveness: this reader backs every
    emailed resume/edit link for EVERY flow. Raising here would 500 them all on
    a database that predates the checkpoints migration — a far worse failure
    than briefly showing a superseded row, which cannot even exist until the
    migration is applied."""
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(sessions_mod, "get_supabase", lambda: _MissingColumnSB(calls))

    from app.main import create_app

    resp = TestClient(create_app()).get("/sessions/tok")

    assert resp.status_code == 200
    assert resp.json()["messages"] == []
    # It still TRIED the filtered read first — the fallback is a fallback.
    assert ("chat_messages", "superseded_at", "null") in calls
