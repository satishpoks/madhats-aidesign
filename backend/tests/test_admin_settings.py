from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings as app_settings
from app.services import settings_service


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_get_settings_requires_admin(client):
    assert client.get("/admin/settings").status_code == 401


def test_get_and_patch_settings(client, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(settings_service, "_read_row", lambda: store)
    monkeypatch.setattr(
        settings_service, "update_settings", _fake_update(store)
    )
    settings_service.invalidate_cache()
    hdr = {"X-Admin-Secret": app_settings.admin_secret}

    got = client.get("/admin/settings", headers=hdr)
    assert got.status_code == 200
    assert got.json()["designs_per_customer_per_day"] == 2

    patched = client.patch(
        "/admin/settings", headers=hdr, json={"regen_edits_per_session": 4}
    )
    assert patched.status_code == 200
    assert patched.json()["regen_edits_per_session"] == 4


def test_patch_rejects_negative(client):
    hdr = {"X-Admin-Secret": app_settings.admin_secret}
    resp = client.patch("/admin/settings", headers=hdr, json={"regen_edits_per_session": -1})
    assert resp.status_code == 422


def _fake_update(store):
    def _update(**fields):
        store.update({k: v for k, v in fields.items() if v is not None})
        return settings_service._from_row(store)
    return _update
