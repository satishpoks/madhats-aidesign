"""Graphics library routes (customer + admin). Service/storage are monkeypatched
so the tests exercise route logic (mapping, validation, gating) without a DB."""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import AdminContext, require_admin, require_admin_ctx, require_store
from app.main import app

_STORE = {"id": "s1"}
_SUPER_CTX = AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)


@pytest.fixture
def client():
    app.dependency_overrides[require_store] = lambda: _STORE
    app.dependency_overrides[require_admin] = lambda: None
    app.dependency_overrides[require_admin_ctx] = lambda: _SUPER_CTX
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_customer_graphics_maps_rows_to_media_urls(client, monkeypatch):
    monkeypatch.setattr(
        "app.services.graphics.list_graphics",
        lambda store_id, category=None, active_only=False: [
            {"id": "g1", "category": "clipart", "name": "Star", "storage_path": "uploads/s.png"},
        ],
    )
    monkeypatch.setattr("app.api.routes.graphics.media_url", lambda p, base: f"http://x/media/{p}")
    r = client.get("/graphics?category=clipart", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    assert r.json() == [
        {"id": "g1", "category": "clipart", "name": "Star", "url": "http://x/media/uploads/s.png"}
    ]


def test_customer_graphics_ignores_unknown_category(client, monkeypatch):
    captured = {}

    def fake_list(store_id, category=None, active_only=False):
        captured["category"] = category
        return []

    monkeypatch.setattr("app.services.graphics.list_graphics", fake_list)
    r = client.get("/graphics?category=bogus", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    assert captured["category"] is None  # unknown category is not forwarded


def test_admin_create_rejects_bad_category(client):
    r = client.post(
        "/admin/graphics",
        data={"category": "nope", "name": "x"},
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n", "image/png")},
        headers={"X-Store-Key": "k", "X-Admin-Secret": "z"},
    )
    assert r.status_code == 400


def test_admin_create_rejects_non_image(client):
    r = client.post(
        "/admin/graphics",
        data={"category": "company", "name": "x"},
        files={"file": ("x.txt", b"not an image", "text/plain")},
        headers={"X-Store-Key": "k", "X-Admin-Secret": "z"},
    )
    assert r.status_code == 415


def test_admin_create_happy_path(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin_graphics.sniff_image_mime", lambda data: "image/png")
    monkeypatch.setattr("app.api.routes.admin_graphics.upload_asset", lambda data, name, mime: "uploads/new.png")
    monkeypatch.setattr("app.api.routes.admin_graphics.media_url", lambda p, base: f"http://x/media/{p}")
    monkeypatch.setattr(
        "app.services.graphics.create_graphic",
        lambda store_id, category, name, storage_path: {
            "id": "g9", "category": category, "name": name, "storage_path": storage_path,
            "active": True, "sort_order": 0,
        },
    )
    r = client.post(
        "/admin/graphics",
        data={"category": "company", "name": "Logo"},
        files={"file": ("logo.png", io.BytesIO(b"anybytes"), "image/png")},
        headers={"X-Store-Key": "k", "X-Admin-Secret": "z"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["category"] == "company"
    assert body["name"] == "Logo"
    assert body["url"] == "http://x/media/uploads/new.png"
