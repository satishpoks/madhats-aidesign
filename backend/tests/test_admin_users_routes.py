from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import admin_users as users_route
from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_list_requires_super(client, monkeypatch):
    # A store admin (bearer, not super) must get 403.
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: {"s1"})
    token = admin_auth.create_token("u1")
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_super_can_create_and_list(client, monkeypatch):
    created = {"id": "u2", "email": "new@x.com", "is_super": False, "status": "active", "stores": []}
    monkeypatch.setattr(users_route.admin_users, "get_by_email", lambda e: None)
    monkeypatch.setattr(users_route.admin_users, "create_user", lambda **k: created)
    monkeypatch.setattr(users_route.admin_users, "list_users", lambda: [created])

    hdr = {"X-Admin-Secret": "envsecret"}
    resp = client.post("/admin/users", headers=hdr, json={
        "email": "new@x.com", "password": "pw", "is_super": False, "store_ids": ["s1"],
    })
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@x.com"

    listed = client.get("/admin/users", headers=hdr)
    assert listed.status_code == 200 and len(listed.json()) == 1


def test_super_can_patch_and_delete(client, monkeypatch):
    monkeypatch.setattr(users_route.admin_users, "get_by_id", lambda uid: {"id": uid})
    monkeypatch.setattr(users_route.admin_users, "update_user", lambda uid, **k: {"id": uid, "email": "a@x.com", "is_super": True, "status": "active", "stores": []})
    monkeypatch.setattr(users_route.admin_users, "delete_user", lambda uid: True)
    hdr = {"X-Admin-Secret": "envsecret"}
    patched = client.patch("/admin/users/u2", headers=hdr, json={"is_super": True})
    assert patched.status_code == 200 and patched.json()["is_super"] is True
    deleted = client.delete("/admin/users/u2", headers=hdr)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
