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


def test_storefront_returns_public_brand(client, store_headers, monkeypatch):
    # public_brand (in app.services.branding) binds media_url at import, so patch
    # it THERE, not on the route module.
    monkeypatch.setattr(
        "app.services.branding.media_url", lambda p, base: f"http://api/media/{p}"
    )
    r = client.get("/storefront", headers=store_headers)
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
    # Proves the route actually reads settings_service rather than merely
    # returning some non-empty string (e.g. a hard-coded default would also
    # satisfy the two assertions above) — "ACME PREVIEW" is distinguishable
    # from the real default ("MADHATS PREVIEW"), so this pins the wiring.
    assert res.json()["watermark_text"] == "ACME PREVIEW"


def test_storefront_survives_an_unreadable_app_settings_row(client, store_headers, monkeypatch):
    """A settings-table failure must not 500 the customer widget's first call.

    `get_settings()` does not catch, so before this the route inherited a brand
    new hard dependency on `app_settings` being present and reachable — on a hot
    customer path, for a decorative string that already has a default.
    `brandStore.init` swallows the error, so the visible effect was a studio
    with no branding at all.
    """
    def _boom() -> dict:
        raise RuntimeError("app_settings unreachable")

    monkeypatch.setattr(settings_service, "_read_row", _boom)
    settings_service.invalidate_cache()

    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    # Falls back to the same literal services/watermark.py stamps into the
    # emailed previews, so canvas and email agree even with settings down.
    assert res.json()["watermark_text"] == "MADHATS PREVIEW"
    # The rest of the payload is unaffected — this is a graceful degrade of one
    # field, not a stubbed-out response.
    assert res.json()["name"] == "Acme Caps"


def test_storefront_never_leaks_the_watermark_asset(client, store_headers, monkeypatch):
    """public_brand's allow-list must still hold: the internal asset URL is not
    a customer-facing field, and adding a watermark key must not smuggle it out."""
    monkeypatch.setattr(settings_service, "_read_row", lambda: {"watermark_text": "ACME PREVIEW"})
    settings_service.invalidate_cache()

    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    assert "watermark_asset_url" not in res.text
