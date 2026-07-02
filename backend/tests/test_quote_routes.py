"""GET/POST /quote/{token} — the customer-facing Request-a-Quote page."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import leads as leads_service


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable supabase-py stand-in. Deferred update/insert mutate the shared
    row dicts on execute() so a second request in the same test sees the change."""

    def __init__(self, table, rows, sink):
        self._table = table
        self._rows = rows
        self._sink = sink
        self._pending_update = None

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

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.setdefault(self._table, []).append(self._pending_update)
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: dict = {}

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


def _tables(**overrides):
    lead = {"id": "lead-1", "session_id": "sess-1", "name": "Ann",
            "email": "ann@example.com", "phone": None, "quote_confirmed": False}
    session = {"id": "sess-1", "store_id": None, "share_token": "share-tok",
               "product_ref": {"product_id": "prod-1"},
               "collected": {"decoration_type": "embroidery",
                             "placement_zone": "front_panel",
                             "placement_position": "centre", "quantity": 24}}
    gen = {"id": "gen-1", "session_id": "sess-1", "status": "complete",
           "watermarked_url": "generations/wm.png", "image_url": "generations/clean.png",
           "created_at": "2026-07-02T00:00:00Z"}
    lead.update(overrides.get("lead", {}))
    return {"leads": [lead], "design_sessions": [session], "generations": [gen]}, lead, session


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import quote
    from app.main import app

    fake_holder = {}

    def _install(tables):
        fake = _FakeSB(tables)
        fake_holder["fake"] = fake
        monkeypatch.setattr(quote, "get_supabase", lambda: fake)
        monkeypatch.setattr(quote, "get_product", lambda *a, **k: {"name": "Snapback", "style": "6-panel", "colour": "black"})
        monkeypatch.setattr(quote, "generate_signed_url", lambda p: f"signed:{p}")
        return fake

    with TestClient(app, raise_server_exceptions=True) as c:
        c.install = _install  # type: ignore[attr-defined]
        c.holder = fake_holder  # type: ignore[attr-defined]
        yield c


def test_get_renders_confirm_page(client):
    tables, _lead, _session = _tables()
    client.install(tables)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.get(f"/quote/{token}")

    assert resp.status_code == 200
    body = resp.text
    assert "Snapback" in body
    assert "embroidery" in body
    assert 'name="quantity"' in body
    assert 'value="24"' in body
    assert 'name="notify_by_phone"' in body


def test_get_bad_token_renders_error(client):
    tables, _lead, _session = _tables()
    client.install(tables)

    resp = client.get("/quote/not-a-real-jwt")

    assert resp.status_code == 400
    assert "couldn't open that quote link" in resp.text.lower()


def test_get_missing_lead_renders_error(client):
    tables, _lead, _session = _tables()
    tables["leads"] = []  # token is valid but the lead is gone
    client.install(tables)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.get(f"/quote/{token}")

    assert resp.status_code == 400
