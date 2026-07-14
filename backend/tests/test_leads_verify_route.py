"""POST /leads/verify/send — resend-verification route.

Regression test for a spec-coverage gap: the initial verification email (sent
via leads_service.capture_lead_and_verify) is store-branded, but the *resend*
route previously called leads_service.send_verification(lead) with no store,
so a resent verification email was always unbranded. The route must derive the
store from the lead's session (design_sessions.store_id -> stores.get_store)
and pass it through.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.routes import leads as leads_route
from app.main import app


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable stand-in for a supabase-py table query."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, lead_row, session_row):
        self._lead_row = lead_row
        self._session_row = session_row

    def table(self, name):
        if name == "leads":
            return _Query([self._lead_row] if self._lead_row else [])
        if name == "design_sessions":
            return _Query([self._session_row] if self._session_row else [])
        raise AssertionError(f"unexpected table {name}")


client = TestClient(app)


def test_resend_verification_passes_resolved_store(monkeypatch):
    lead_row = {"id": "lead-1", "session_id": "sess-1", "email": "c@x.example", "name": "Sam"}
    session_row = {"store_id": "store-1"}
    fake_sb = _FakeSB(lead_row, session_row)
    monkeypatch.setattr(leads_route, "get_supabase", lambda: fake_sb)

    fake_store = {"id": "store-1", "brand": {"store_name": "Acme Caps"}}
    monkeypatch.setattr("app.services.stores.get_store", lambda store_id: fake_store)

    captured = {}

    def _fake_send_verification(lead, store=None):
        captured["lead"] = lead
        captured["store"] = store
        return True

    monkeypatch.setattr(leads_route.leads_service, "send_verification", _fake_send_verification)

    resp = client.post("/leads/verify/send", json={"lead_id": "lead-1"})

    assert resp.status_code == 200
    assert captured["lead"]["id"] == "lead-1"
    assert captured["store"] == fake_store


def test_resend_verification_falls_back_when_no_store(monkeypatch):
    lead_row = {"id": "lead-2", "session_id": "sess-2", "email": "c@x.example", "name": "Sam"}
    session_row = {"store_id": None}
    fake_sb = _FakeSB(lead_row, session_row)
    monkeypatch.setattr(leads_route, "get_supabase", lambda: fake_sb)

    def _boom(store_id):
        raise AssertionError("get_store should not be called when session has no store_id")

    monkeypatch.setattr("app.services.stores.get_store", _boom)

    captured = {}

    def _fake_send_verification(lead, store=None):
        captured["store"] = store
        return True

    monkeypatch.setattr(leads_route.leads_service, "send_verification", _fake_send_verification)

    resp = client.post("/leads/verify/send", json={"lead_id": "lead-2"})

    assert resp.status_code == 200
    assert captured["store"] is None
