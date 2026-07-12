import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "list_hat_types", lambda s, active_only=False: [{
        "id": "h1", "slug": "5p", "name": "5-Panel", "style": "",
        "blank_view_images": {"front": "generated/blank/front.png"},
        "colours": [{"name": "Black", "hex": "#000000"}],
        "placement_zones": ["front_panel"], "decoration_types": ["print"], "active": True,
    }])
    from app.main import create_app
    return TestClient(create_app())


def test_requires_store_key(client):
    assert client.get("/hat-types").status_code == 401


def test_lists_active_with_proxied_urls(client):
    r = client.get("/hat-types", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["name"] == "5-Panel"
    # a private storage path becomes a /media/ proxy URL
    assert "/media/" in body[0]["view_images"]["front"]
