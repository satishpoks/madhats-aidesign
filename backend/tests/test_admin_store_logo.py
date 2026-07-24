# backend/tests/test_admin_store_logo.py
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import AdminContext, require_admin_ctx
from app.main import app

_SUPER_CTX = AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)


class _FakeTable:
    def __init__(self, row): self._row = row
    def select(self, *a, **k): return self
    def update(self, patch): self._row = {**self._row, **patch}; return self
    def eq(self, *a): return self
    def limit(self, n): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [self._row]; return r


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
    fake = _FakeTable({"id": "s1", "brand": {"primary_colour": "#111111"}})
    monkeypatch.setattr("app.api.routes.admin_stores.get_supabase", lambda: type("SB", (), {"table": lambda self, n: fake})())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_logo_rejects_non_image(client):
    r = client.post(
        "/admin/stores/s1/logo",
        files={"file": ("x.txt", b"not an image", "text/plain")},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 415


def test_logo_happy_path(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin_stores.sniff_image_mime", lambda d: "image/png")
    monkeypatch.setattr("app.api.routes.admin_stores.upload_asset", lambda d, n, m: "uploads/logo.png")
    monkeypatch.setattr("app.api.routes.admin_stores.media_url", lambda p, base: f"http://api/media/{p}")
    r = client.post(
        "/admin/stores/s1/logo",
        files={"file": ("logo.png", io.BytesIO(b"anybytes"), "image/png")},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 200
    assert r.json()["logo_url"] == "http://api/media/uploads/logo.png"
