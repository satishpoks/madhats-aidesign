from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import AdminContext, require_admin_ctx
from app.main import app

_ROW = {"id": "s1", "slug": "acme", "name": "Acme", "brand": {"primary_colour": "#111111"}}
_SUPER_CTX = AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)


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
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
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


def test_patch_preserves_logo_url_when_omitted(monkeypatch):
    """A PATCH that sends only a colour must not wipe brand.logo_url — the
    frontend BrandingView intentionally omits logo_url from the PATCH body
    and relies on the backend to merge, not replace, the brand column."""
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
    row = {
        "id": "s1",
        "slug": "acme",
        "name": "Acme",
        "brand": {"logo_url": "uploads/x.png", "primary_colour": "#111"},
    }
    fake = _FakeTable(row)
    monkeypatch.setattr(
        "app.api.routes.admin_stores.get_supabase",
        lambda: type("SB", (), {"table": lambda self, name: fake})(),
    )
    client = TestClient(app)
    try:
        r = client.patch(
            "/admin/stores/s1",
            json={"brand": {"primary_colour": "#00FF00"}},
            headers={"X-Admin-Secret": "z"},
        )
        assert r.status_code == 200
        brand = r.json()["brand"]
        assert brand["primary_colour"] == "#00FF00"
        assert brand["logo_url"] == "uploads/x.png"
    finally:
        app.dependency_overrides.clear()


def test_get_store_admin_returns_proxied_logo_url(monkeypatch):
    """GET /admin/stores/{id} must return a displayable /media proxy URL for
    brand.logo_url, not the raw storage path (which breaks <img src> on reload)."""
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
    row = {"id": "s1", "slug": "acme", "name": "Acme", "brand": {"logo_url": "uploads/x.png"}}
    fake = _FakeTable(row)
    monkeypatch.setattr(
        "app.api.routes.admin_stores.get_supabase",
        lambda: type("SB", (), {"table": lambda self, name: fake})(),
    )
    monkeypatch.setattr(
        "app.api.routes.admin_stores.media_url",
        lambda path, base: f"{base}media/{path}",
    )
    client = TestClient(app)
    try:
        r = client.get("/admin/stores/s1", headers={"X-Admin-Secret": "z"})
        assert r.status_code == 200
        assert r.json()["brand"]["logo_url"].endswith("media/uploads/x.png")
        # the underlying row must be untouched (display-only conversion)
        assert row["brand"]["logo_url"] == "uploads/x.png"
    finally:
        app.dependency_overrides.clear()


# --- Workstream D: canvas_flow rides the existing brand PATCH ------------------
# No route change is expected: validate_brand already validates canvas_flow and
# the PATCH already read-merges. These tests prove the composition, and are the
# alarm that fires if either half regresses.

def test_patch_accepts_and_merges_canvas_flow(monkeypatch):
    """A canvas_flow PATCH must validate, and must merge without wiping the
    existing logo_url (the same read-merge guarantee colours rely on)."""
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
    row = {"id": "s1", "slug": "acme", "name": "Acme",
           "brand": {"logo_url": "uploads/x.png", "primary_colour": "#111"}}
    fake = _FakeTable(row)
    monkeypatch.setattr(
        "app.api.routes.admin_stores.get_supabase",
        lambda: type("SB", (), {"table": lambda self, name: fake})(),
    )
    client = TestClient(app)
    try:
        r = client.patch(
            "/admin/stores/s1",
            json={"brand": {"canvas_flow": {"steps": [
                {"id": "ask_purpose", "enabled": False},
                {"id": "ask_quantity", "enabled": True},
            ]}}},
            headers={"X-Admin-Secret": "z"},
        )
        assert r.status_code == 200
        brand = r.json()["brand"]
        assert brand["canvas_flow"]["steps"] == [
            {"id": "ask_purpose", "enabled": False},
            {"id": "ask_quantity", "enabled": True},
        ]
        assert brand["logo_url"] == "uploads/x.png"      # merge, not clobber
        assert brand["primary_colour"] == "#111"
    finally:
        app.dependency_overrides.clear()


def test_patch_rejects_a_locked_step_in_canvas_flow(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"canvas_flow": {"steps": [{"id": "ask_email"}]}}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 400
