"""GET /admin/prompt-preview/{session_id} — returns the exact assembled image
prompt for a session without generating an image. Admin-gated.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, sessions):
        self._sessions = sessions

    def table(self, name):
        return _Query(list(self._sessions if name == "design_sessions" else []))


_SESSION = {
    "id": "sess-1",
    "store_id": "store-1",
    "product_ref": {
        "reference_image_url": "https://cdn/ref.png",
        "style": "6-panel snapback",
        "colour": "black",
    },
    "collected": {
        "decoration_type": "embroidery",
        "elements": [
            {
                "type": "text",
                "content": "bold mountain crest",
                "placement_zone": "front_panel",
                "placement_position": "centre",
                "deferred": [],
            }
        ],
    },
}


@pytest.fixture()
def admin_client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "test-secret-123")
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _patch_sb(monkeypatch, sessions):
    from app.api.routes import admin_prompt

    monkeypatch.setattr(admin_prompt, "get_supabase", lambda: _FakeSB(sessions))


def test_rejects_missing_secret(admin_client):
    resp = admin_client.get("/admin/prompt-preview/sess-1")
    assert resp.status_code in (401, 403)


def test_returns_prompt_with_secret(admin_client, monkeypatch):
    _patch_sb(monkeypatch, [_SESSION])
    resp = admin_client.get(
        "/admin/prompt-preview/sess-1", headers={"X-Admin-Secret": "test-secret-123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"] == "sess-1"
    assert body["tier"] == "preview"
    assert body["reference_image_url"] == "https://cdn/ref.png"
    assert body["has_uploaded_asset"] is False
    assert "REPRODUCE THE CAP EXACTLY" in body["prompt"]
    assert "bold mountain crest" in body["prompt"]


def test_unknown_session_returns_404(admin_client, monkeypatch):
    _patch_sb(monkeypatch, [])
    resp = admin_client.get(
        "/admin/prompt-preview/nope", headers={"X-Admin-Secret": "test-secret-123"}
    )
    assert resp.status_code == 404
