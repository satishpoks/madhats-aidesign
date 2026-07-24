from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, f, v):
        self._filters[f] = v
        return self

    def limit(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        rows = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        return _Result(rows)


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return _Query(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _FakeTable(self._tables.get(name, []))


@pytest.fixture()
def client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app) as c:
        yield c


def _patch_sb(monkeypatch, session_row):
    from app.api.routes import admin_diagnostics

    tables = {
        "design_sessions": [session_row],
        "chat_messages": [],
        "generations": [],
        "leads": [],
    }
    monkeypatch.setattr(admin_diagnostics, "get_supabase", lambda: _FakeSB(tables))


def test_canvas_session_returns_faces(client, monkeypatch):
    session_row = {
        "id": "sess-1", "store_id": None, "state": "complete",
        "collected": {
            "flow_mode": "canvas",
            "canvas_previews": {"front": "prev_front.png", "back": "prev_back.png"},
            "canvas_layouts": {"front": "lay_front.png", "back": "lay_back.png"},
        },
        "canvas_design": {"colourway": None, "faces": {
            "front": [
                {"type": "image", "assetPath": "canvas_front_A.png",
                 "assetUrl": "http://x/sign/madhats-assets/canvas_front_A.png?t=1", "zIndex": 0},
                {"type": "text", "content": "SATISH", "colour": "#ffffff", "font": "Arial", "zIndex": 1},
            ],
            "back": [
                {"type": "image", "assetPath": "canvas_back_B.png", "zIndex": 0},
            ],
            "left": [], "right": [],
        }},
    }
    _patch_sb(monkeypatch, session_row)
    res = client.get("/admin/sessions/sess-1", headers={"X-Admin-Secret": "envsecret"})
    assert res.status_code == 200
    body = res.json()
    faces = {f["face"]: f for f in body["canvas_faces"]}
    assert set(faces) == {"front", "back"}
    front = faces["front"]
    assert "/media/" in front["preview_url"] and "/media/" in front["layout_url"]
    imgs = [e for e in front["elements"] if e["kind"] == "image"]
    assert len(imgs) == 1
    assert "/media/" in imgs[0]["url"] and imgs[0]["download_name"].endswith(".png")
    text = next(e for e in front["elements"] if e["kind"] == "text")
    assert "SATISH" in text["text"]


def test_non_canvas_session_has_no_faces(client, monkeypatch):
    session_row = {"id": "sess-2", "store_id": None, "state": "complete",
                   "collected": {"flow_mode": "session"}}
    _patch_sb(monkeypatch, session_row)
    body = client.get("/admin/sessions/sess-2", headers={"X-Admin-Secret": "envsecret"}).json()
    assert body.get("canvas_design") is None
    assert body.get("canvas_faces") == []
