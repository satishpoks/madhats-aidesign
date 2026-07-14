# backend/tests/test_storefront.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_store
from app.main import app

_STORE = {
    "id": "s1", "name": "Acme Caps", "persona_name": "Rex",
    "sales_notification_email": "secret@acme.example",  # must NOT leak
    "brand": {
        "primary_colour": "#123456",
        "logo_url": "uploads/logo.png",
        "menu_items": [{"label": "Shop", "url": "https://acme.example/shop"}],
    },
}


@pytest.fixture
def client():
    app.dependency_overrides[require_store] = lambda: _STORE
    yield TestClient(app)
    app.dependency_overrides.clear()


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
