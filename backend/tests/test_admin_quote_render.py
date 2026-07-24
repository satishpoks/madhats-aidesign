"""POST /admin/quote-requests/{lead_id}/render triggers an on-demand render (C4)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink = table, rows, sink
        self._pending_insert = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def execute(self):
        if self._pending_insert is not None:
            row = {"job_id": "job-xyz", "id": "gen-row-1", **self._pending_insert}
            self._sink.append(row)
            return _Result([row])
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: list = []

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import admin_leads, generate
    from app.main import app

    fake = _FakeSB({
        "leads": [{"id": "lead-1", "session_id": "sess-1"}],
        "design_sessions": [{"id": "sess-1", "store_id": "store-1",
                             "product_ref": {"reference_image_url": "https://x/f.png"},
                             "collected": {"flow_mode": "canvas", "elements": []}}],
    })
    monkeypatch.setattr(admin_leads, "get_supabase", lambda: fake)
    monkeypatch.setattr(generate, "get_supabase", lambda: fake)
    # Resolve the store from the X-Store-Key header to store-1.
    from app.api import deps
    monkeypatch.setattr(deps, "resolve_store", lambda k: {"id": "store-1"})
    # Don't actually run the background render.
    monkeypatch.setattr(generate, "_run_generation", lambda **k: None)
    return TestClient(app)


def test_render_requires_admin(client):
    r = client.post("/admin/quote-requests/lead-1/render",
                    headers={"X-Store-Key": "mh_pk"})
    assert r.status_code == 401


def test_render_enqueues_and_returns_job(client):
    r = client.post(
        "/admin/quote-requests/lead-1/render",
        headers={"X-Admin-Secret": settings.admin_secret, "X-Store-Key": "mh_pk"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == "job-xyz"


def test_render_rejects_cross_store(client, monkeypatch):
    from app.api import deps
    monkeypatch.setattr(deps, "resolve_store", lambda k: {"id": "other-store"})
    r = client.post(
        "/admin/quote-requests/lead-1/render",
        headers={"X-Admin-Secret": settings.admin_secret, "X-Store-Key": "mh_pk"},
    )
    assert r.status_code == 404
