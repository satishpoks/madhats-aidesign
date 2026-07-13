import pytest
from fastapi.testclient import TestClient

from app.services import decoration_types as svc


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "list_types", lambda s, active_only=False: [
        {"id": "d1", "name": "Embroidery", "active": True, "sort_order": 0},
        {"id": "d2", "name": "Print", "active": True, "sort_order": 1},
    ])
    monkeypatch.setattr(svc, "create_type", lambda s, name: {
        "id": "d9", "name": name, "active": True, "sort_order": 0})
    monkeypatch.setattr(svc, "delete_type", lambda i, s: None)
    from app.main import create_app
    return TestClient(create_app())


def test_customer_requires_store_key(client):
    assert client.get("/decoration-types").status_code == 401


def test_customer_lists_active(client):
    r = client.get("/decoration-types", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    assert [x["name"] for x in r.json()] == ["Embroidery", "Print"]
    # public shape has no active/sort_order
    assert set(r.json()[0].keys()) == {"id", "name"}


def test_admin_requires_secret(client):
    # store key present but no admin secret → gated
    r = client.get("/admin/decoration-types", headers={"X-Store-Key": "k"})
    assert r.status_code in (401, 403)


def test_admin_requires_store_key(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.admin_secret", "sekret")
    # admin secret present, but NO X-Store-Key → store gate rejects
    assert client.get("/admin/decoration-types",
                      headers={"X-Admin-Secret": "sekret"}).status_code in (401, 403)


def test_admin_crud(client, monkeypatch):
    monkeypatch.setattr("app.config.settings.admin_secret", "sekret")
    h = {"X-Admin-Secret": "sekret", "X-Store-Key": "k"}
    assert client.get("/admin/decoration-types", headers=h).status_code == 200
    r = client.post("/admin/decoration-types", json={"name": "Vinyl"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Vinyl"
    assert client.delete("/admin/decoration-types/d1", headers=h).json() == {"deleted": True}
