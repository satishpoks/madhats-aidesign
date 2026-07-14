from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_admin
from app.main import app

_ROW = {"id": "s1", "slug": "acme", "name": "Acme", "brand": {"primary_colour": "#111111"}}


class _FakeTable:
    def __init__(self, row): self._row = row; self._filter = None
    def select(self, *a, **k): return self
    def update(self, patch): self._row = {**self._row, **patch}; return self
    def eq(self, col, val): self._filter = (col, val); return self
    def limit(self, n): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [self._row]; return r


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: None
    fake = _FakeTable(dict(_ROW))
    monkeypatch.setattr("app.api.routes.admin_stores.get_supabase", lambda: type("SB", (), {"table": lambda self, name: fake})())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_one_returns_full_store(client):
    r = client.get("/admin/stores/s1", headers={"X-Admin-Secret": "z"})
    assert r.status_code == 200
    assert r.json()["brand"]["primary_colour"] == "#111111"


def test_patch_updates_valid_brand(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"primary_colour": "#00FF00", "menu_items": [{"label": "Shop", "url": "https://x.example"}]}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 200
    assert r.json()["brand"]["primary_colour"] == "#00FF00"


def test_patch_rejects_invalid_brand(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"primary_colour": "notacolour"}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 400
