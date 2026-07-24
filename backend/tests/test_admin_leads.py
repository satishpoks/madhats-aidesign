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

    def or_(self, expr):
        # minimal "col.eq.true,col2.eq.true" — keep rows truthy on ANY listed col
        cols = [clause.split(".")[0] for clause in expr.split(",")]
        self._rows = [r for r in self._rows if any(r.get(c) for c in cols)]
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


# --- C5/C7: reference + summary + downloadable components -------------------

def _quote_tables():
    """A confirmed lead with a reference + a fuller collected summary, plus a
    v2 quote-gated lead that is quote_requested but never quote_confirmed."""
    confirmed = {"id": "lead-1", "session_id": "sess-1", "name": "Ann",
                 "email": "ann@example.com", "reference_code": "MH-BCDFGH",
                 "quote_confirmed": True, "quote_requested": False,
                 "quote_confirmed_at": "2026-07-24T10:00:00Z",
                 "created_at": "2026-07-24T10:00:00Z"}
    requested = {"id": "lead-2", "session_id": "sess-2", "name": "Ben",
                 "email": "ben@example.com", "reference_code": "MH-REQ222",
                 "quote_confirmed": False, "quote_requested": True,
                 "created_at": "2026-07-24T09:00:00Z"}
    ignored = {"id": "lead-3", "session_id": "sess-3", "name": "Cal",
               "quote_confirmed": False, "quote_requested": False,
               "created_at": "2026-07-24T08:00:00Z"}
    sess1 = {"id": "sess-1", "share_token": "share-tok",
             "product_ref": {"product_id": "prod-1", "name": "Snapback"},
             "collected": {"decoration_type": "embroidery", "quantity": 60,
                           "needed_by": "2-4 weeks", "purpose": "team event",
                           "brief_notes": ["Decoration method: embroidery"],
                           "uploaded_asset_path": "uploads/logo.png"}}
    sess2 = {"id": "sess-2", "share_token": "tok-2", "product_ref": {},
             "collected": {"quantity": 12}}
    return {"leads": [confirmed, requested, ignored],
            "design_sessions": [sess1, sess2],
            "generations": []}


def test_quote_requests_include_reference_and_summary(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _quote_tables())
    r = admin_client.get("/admin/quote-requests",
                         headers={"X-Admin-Secret": "test-secret-123"})
    assert r.status_code == 200
    row = next(x for x in r.json() if x["lead_id"] == "lead-1")
    assert row["reference_code"] == "MH-BCDFGH"
    assert row["needed_by"] == "2-4 weeks"
    assert row["purpose"] == "team event"
    assert row["quantity"] == 60
    assert row["notes"] == "Decoration method: embroidery"


def test_v2_requested_leads_appear_without_quote_confirmed(admin_client, monkeypatch):
    """The quote-gated flow sets quote_requested=True and never quote_confirmed —
    the listing must still surface it (widened .or_ filter)."""
    _patch_sb(monkeypatch, _quote_tables())
    r = admin_client.get("/admin/quote-requests",
                         headers={"X-Admin-Secret": "test-secret-123"})
    assert r.status_code == 200
    refs = {row.get("reference_code") for row in r.json()}
    assert "MH-REQ222" in refs        # quote_requested-only lead is listed
    assert len(r.json()) == 2         # the neither-flag lead stays hidden


def test_components_endpoint_lists_download_urls(admin_client, monkeypatch):
    from app.api.routes import admin_leads

    _patch_sb(monkeypatch, _quote_tables())
    monkeypatch.setattr(admin_leads.storage, "media_url",
                        lambda path, base: f"/media/{path}")
    r = admin_client.get("/admin/quote-requests/lead-1/components",
                         headers={"X-Admin-Secret": "test-secret-123"})
    assert r.status_code == 200
    comps = r.json()["components"]
    assert any(c["label"].startswith("Uploaded") for c in comps)
    assert all(c["url"] for c in comps)


def test_components_endpoint_404_for_unknown_lead(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _quote_tables())
    r = admin_client.get("/admin/quote-requests/nope/components",
                         headers={"X-Admin-Secret": "test-secret-123"})
    assert r.status_code == 404
