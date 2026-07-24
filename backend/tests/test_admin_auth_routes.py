from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import admin_auth as auth_route
from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _stub_user(monkeypatch, *, is_super=False, status="active", password="pw"):
    row = {
        "id": "u1", "email": "ops@x.com", "is_super": is_super, "status": status,
        "password_hash": admin_auth.hash_password(password),
    }
    monkeypatch.setattr(admin_users, "get_by_email", lambda e: row if e.strip().lower() == "ops@x.com" else None)
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row if uid == "u1" else None)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: {"s1"})
    monkeypatch.setattr(auth_route, "_stores_public", lambda ids: [{"id": "s1", "name": "Store 1", "public_key": "pk_1"}])
    return row


def test_login_success_returns_token_and_profile(client, monkeypatch):
    _stub_user(monkeypatch)
    resp = client.post("/admin/auth/login", json={"email": "Ops@x.com", "password": "pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["profile"]["is_super"] is False
    assert body["profile"]["stores"][0]["public_key"] == "pk_1"


def test_login_wrong_password(client, monkeypatch):
    _stub_user(monkeypatch)
    resp = client.post("/admin/auth/login", json={"email": "ops@x.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_disabled_user(client, monkeypatch):
    _stub_user(monkeypatch, status="disabled")
    resp = client.post("/admin/auth/login", json={"email": "ops@x.com", "password": "pw"})
    assert resp.status_code == 401


def test_me_with_env_secret_is_super(client):
    resp = client.get("/admin/auth/me", headers={"X-Admin-Secret": "envsecret"})
    assert resp.status_code == 200
    assert resp.json()["is_super"] is True


def test_change_password_env_super_rejected(client):
    resp = client.post(
        "/admin/auth/change-password",
        headers={"X-Admin-Secret": "envsecret"},
        json={"current_password": "x", "new_password": "y"},
    )
    assert resp.status_code == 400
