from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _bearer_store_admin(monkeypatch, allowed):
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_blocked_from_global_diagnostics(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.get("/admin/diagnostics", headers=hdr)
    assert resp.status_code == 403


def test_store_admin_blocked_from_reap_stuck(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.post("/admin/generations/reap-stuck", headers=hdr)
    assert resp.status_code == 403
