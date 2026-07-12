import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"0" * 20


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

    def _get(hat_type_id, store_id=None):
        for row in store["hat_types"]:
            if row["id"] == hat_type_id and (store_id is None or row["store_id"] == store_id):
                return row
        return None

    def _update(hat_type_id, patch):
        for row in store["hat_types"]:
            if row["id"] == hat_type_id:
                row.update(patch)
                return row
        return None

    def _delete(hat_type_id):
        store["hat_types"] = [r for r in store["hat_types"] if r["id"] != hat_type_id]

    def _set_angle(hat_type_id, view, path):
        row = _get(hat_type_id)
        if row is None:
            raise ValueError("hat type not found")
        imgs = dict(row.get("blank_view_images") or {})
        imgs[view] = path
        row["blank_view_images"] = imgs
        return row

    monkeypatch.setattr(svc, "create_hat_type", _create)
    monkeypatch.setattr(svc, "list_hat_types", lambda s, active_only=False: store["hat_types"])
    monkeypatch.setattr(svc, "get_hat_type", _get)
    monkeypatch.setattr(svc, "update_hat_type", _update)
    monkeypatch.setattr(svc, "delete_hat_type", _delete)
    monkeypatch.setattr(svc, "set_angle", _set_angle)
    monkeypatch.setattr(
        "app.api.routes.admin_hat_types.upload_asset",
        lambda data, filename, mime: f"stub/{filename}",
    )
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


def test_angle_upload_success(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["blank_view_images"]["front"] == "stub/front.png"


def test_angle_upload_bad_view(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/top",
        headers=h,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    assert r.status_code == 400


def test_angle_upload_empty_file(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.png", b"", "image/png")},
    )
    assert r.status_code == 400


def test_angle_upload_too_large(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    big = PNG_MAGIC + b"0" * (10 * 1024 * 1024 + 1)
    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.png", big, "image/png")},
    )
    assert r.status_code == 413


def test_angle_upload_bad_magic(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.txt", b"not an image", "text/plain")},
    )
    assert r.status_code == 415


def test_angle_upload_unknown_id_404(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    r = client.post(
        "/admin/hat-types/nope/angle/front",
        headers=h,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    assert r.status_code == 404


def test_activate_requires_all_angles(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.patch(f"/admin/hat-types/{hat_id}", json={"active": True}, headers=h)
    assert r.status_code == 400


def test_activate_succeeds_with_all_angles(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    for view in ("front", "back", "left", "right"):
        client.post(
            f"/admin/hat-types/{hat_id}/angle/{view}",
            headers=h,
            files={"file": (f"{view}.png", PNG_MAGIC, "image/png")},
        )

    r = client.patch(f"/admin/hat-types/{hat_id}", json={"active": True}, headers=h)
    assert r.status_code == 200
    assert r.json()["active"] is True


def test_update_unknown_id_404(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    r = client.patch("/admin/hat-types/nope", json={"name": "x"}, headers=h)
    assert r.status_code == 404


def test_delete_unknown_id_404(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    r = client.delete("/admin/hat-types/nope", headers=h)
    assert r.status_code == 404


def test_delete_happy_path(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    r = client.delete(f"/admin/hat-types/{hat_id}", headers=h)
    assert r.status_code == 200
    assert r.json() == {"deleted": True}


def test_other_store_cannot_patch_delete_or_upload_angle(client, monkeypatch):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]

    # a different X-Store-Key resolves to a different store
    monkeypatch.setattr(
        "app.api.deps.resolve_store", lambda k: {"id": "store-2"} if k else None
    )
    h2 = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "other"}

    r_patch = client.patch(f"/admin/hat-types/{hat_id}", json={"name": "x"}, headers=h2)
    assert r_patch.status_code == 404

    r_delete = client.delete(f"/admin/hat-types/{hat_id}", headers=h2)
    assert r_delete.status_code == 404

    r_angle = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h2,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    assert r_angle.status_code == 404
