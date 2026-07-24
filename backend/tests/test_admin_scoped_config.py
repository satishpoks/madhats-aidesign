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


def _bearer(monkeypatch, allowed, is_super=False):
    row = {"id": "u1", "email": "a@x.com", "is_super": is_super, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_blocked_from_settings(client, monkeypatch):
    hdr = _bearer(monkeypatch, {"s1"})
    resp = client.get("/admin/settings", headers=hdr)
    assert resp.status_code == 403


def test_store_admin_blocked_from_backfill(client, monkeypatch):
    hdr = _bearer(monkeypatch, {"s1"})
    resp = client.post("/admin/deliveries/backfill", headers=hdr)
    assert resp.status_code == 403
