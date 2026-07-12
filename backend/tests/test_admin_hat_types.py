import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


@pytest.fixture()
def client(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "admin_secret", "s3cr3t")
    # store resolution for X-Store-Key
    monkeypatch.setattr(
        "app.api.deps.resolve_store", lambda k: {"id": "store-1"} if k else None
    )
    store = {"hat_types": []}

    def _create(store_id, body):
        row = {"id": "h1", "store_id": store_id, "blank_view_images": {}, "active": False, **body}
        store["hat_types"].append(row)
        return row

    monkeypatch.setattr(svc, "create_hat_type", _create)
    monkeypatch.setattr(svc, "list_hat_types", lambda s, active_only=False: store["hat_types"])
    from app.main import create_app
    return TestClient(create_app())


def test_create_requires_admin(client):
    r = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 401  # missing X-Admin-Secret


def test_create_and_list(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    r = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "5P"
    r2 = client.get("/admin/hat-types", headers=h)
    assert r2.status_code == 200 and len(r2.json()) == 1
