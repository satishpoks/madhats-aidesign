"""GET /admin/quote-requests — confirmed quote leads for the admin center."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Query(list(self._tables.get(name, [])))


def _tables():
    confirmed = {"id": "lead-1", "session_id": "sess-1", "name": "Ann",
                 "email": "ann@example.com", "phone": "0400000000",
                 "notify_by_phone": True, "quote_note": "asap",
                 "quote_confirmed": True, "quote_confirmed_at": "2026-07-02T10:00:00Z"}
    not_confirmed = {"id": "lead-2", "session_id": "sess-2", "name": "Ben",
                     "email": "ben@example.com", "quote_confirmed": False}
    session = {"id": "sess-1", "share_token": "share-tok",
               "product_ref": {"product_id": "prod-1", "name": "Snapback"},
               "collected": {"decoration_type": "embroidery",
                             "placement_zone": "front_panel", "quantity": 60}}
    return {"leads": [confirmed, not_confirmed], "design_sessions": [session]}


@pytest.fixture()
def admin_client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "test-secret-123")
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _patch_sb(monkeypatch, tables):
    from app.api.routes import admin_leads

    monkeypatch.setattr(admin_leads, "get_supabase", lambda: _FakeSB(tables))


def test_rejects_missing_secret(admin_client):
    resp = admin_client.get("/admin/quote-requests")
    assert resp.status_code in (401, 403)


def test_returns_only_confirmed_with_summary(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _tables())
    resp = admin_client.get(
        "/admin/quote-requests", headers={"X-Admin-Secret": "test-secret-123"}
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["lead_id"] == "lead-1"
    assert row["notify_by_phone"] is True
    assert row["quote_note"] == "asap"
    assert row["product"] == "Snapback"
    assert row["decoration_type"] == "embroidery"
    assert row["quantity"] == 60
    assert row["share_token"] == "share-tok"
