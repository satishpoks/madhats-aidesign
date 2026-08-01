# backend/tests/test_storefront.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_store
from app.main import app
from app.services import settings_service

_STORE = {
    "id": "s1", "name": "Acme Caps", "persona_name": "Rex",
    "sales_notification_email": "secret@acme.example",  # must NOT leak
    "brand": {
        "primary_colour": "#123456",
        "logo_url": "uploads/logo.png",
        "menu_items": [{"label": "Shop", "url": "https://acme.example/shop"}],
        # Internal field (services/branding.py's watermark_asset_url) — must
        # never reach the customer widget, even after watermark_text is added
        # top-level. Present here so the leak test actually pins something.
        "watermark_asset_url": "https://internal.example/secret-watermark.png",
    },
}


@pytest.fixture
def client():
    app.dependency_overrides[require_store] = lambda: _STORE
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def store_headers():
    return {"X-Store-Key": "k"}


@pytest.fixture(autouse=True)
def _no_real_app_settings_call(monkeypatch):
    # The route now also reads settings_service.get_settings().watermark_text.
    # Without this, a test that doesn't care about the watermark (e.g.
    # test_storefront_returns_public_brand below) would make a real Supabase
    # round-trip via the module-level TTL cache's first fill — flaky/slow and
    # an unrelated network dependency. Tests that DO care override this again.
    monkeypatch.setattr(settings_service, "_read_row", lambda: {})
    settings_service.invalidate_cache()
    yield
    settings_service.invalidate_cache()


def test_storefront_returns_public_brand(client, monkeypatch):
    # public_brand (in app.services.branding) binds media_url at import, so patch
    # it THERE, not on the route module.
    monkeypatch.setattr(
        "app.services.branding.media_url", lambda p, base: f"http://api/media/{p}"
    )
    r = client.get("/storefront", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Acme Caps"
    assert body["persona_name"] == "Rex"
    assert body["brand"]["primary_colour"] == "#123456"
    assert body["brand"]["logo_url"] == "http://api/media/uploads/logo.png"
    assert body["brand"]["menu_items"][0]["label"] == "Shop"
    # secrets never surface
    assert "sales_notification_email" not in str(body)


def test_storefront_requires_store_key():
    # No override -> require_store enforces the header.
    r = TestClient(app).get("/storefront")
    assert r.status_code == 401


def test_storefront_returns_the_watermark_text(client, store_headers, monkeypatch):
    # Isolate from the real app_settings table / the module-level TTL cache
    # shared across the test session.
    monkeypatch.setattr(settings_service, "_read_row", lambda: {"watermark_text": "ACME PREVIEW"})
    settings_service.invalidate_cache()

    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    assert isinstance(res.json()["watermark_text"], str)
    assert res.json()["watermark_text"]        # never empty — the overlay needs something to draw


def test_storefront_never_leaks_the_watermark_asset(client, store_headers, monkeypatch):
    """public_brand's allow-list must still hold: the internal asset URL is not
    a customer-facing field, and adding a watermark key must not smuggle it out."""
    monkeypatch.setattr(settings_service, "_read_row", lambda: {"watermark_text": "ACME PREVIEW"})
    settings_service.invalidate_cache()

    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    assert "watermark_asset_url" not in res.text
