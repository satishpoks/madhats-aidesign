from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows, op, payload=None):
        self.rows = rows
        self.op = op
        self.payload = payload
        self.filters = {}

    def eq(self, f, v):
        self.filters[f] = v
        return self

    def limit(self, *a, **k):
        return self

    def select(self, *a, **k):
        return self

    def _matches(self):
        return [r for r in self.rows.values() if all(r.get(k) == v for k, v in self.filters.items())]

    def execute(self):
        if self.op == "select":
            return _Result(self._matches())
        if self.op == "update":
            m = self._matches()
            for r in m:
                r.update(self.payload)
            return _Result(m)
        raise AssertionError(self.op)


class _FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a, **k):
        return _Query(self.rows, "select")

    def update(self, payload):
        return _Query(self.rows, "update", payload)


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        assert name == "design_sessions"
        return _FakeTable(self._rows)


_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture()
def client(monkeypatch):
    from app.main import create_app

    rows = {"sess-1": {"id": "sess-1", "collected": {}}}
    fake_sb = _FakeSB(rows)
    monkeypatch.setattr("app.api.routes.uploads.get_supabase", lambda: fake_sb)
    monkeypatch.setattr("app.api.routes.uploads.upload_asset", lambda data, filename, content_type: f"uploads/{filename}")
    monkeypatch.setattr("app.api.routes.uploads.generate_signed_url", lambda path: f"signed://{path}")
    monkeypatch.setattr("app.api.routes.uploads.sniff_image_mime", lambda data: "image/png")
    c = TestClient(create_app())
    c._rows = rows
    return c


def test_upload_logo_returns_asset_path(client):
    res = client.post("/uploads/logo/sess-1", files={"file": ("logo.png", _PNG, "image/png")})
    assert res.status_code == 200
    body = res.json()
    assert body["asset_path"] == "uploads/logo.png"
    assert body["asset_url"] == "signed://uploads/logo.png"
    assert "asset_hash" in body
    assert client._rows["sess-1"]["collected"]["uploaded_asset_path"] == "uploads/logo.png"
