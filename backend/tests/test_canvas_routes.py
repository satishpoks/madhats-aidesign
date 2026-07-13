"""Tests for canvas session routes: create / layouts / finalize.

TDD: written before the routes exist — expected to fail with 404s until
POST /sessions/canvas, POST /sessions/{id}/canvas-layouts and
POST /sessions/{id}/canvas-finalize are implemented in
app/api/routes/sessions.py.
"""
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.data.stub_catalogue import STUB_PRODUCTS
from app.services.canvas_describe import canvas_to_elements

_STORE = {"id": "s1", "name": "Test Store"}
_STORE_HEADERS = {"X-Store-Key": "mh_pk_test"}
_PRODUCT_ID = STUB_PRODUCTS[0]["id"]


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeSessionsStore:
    """In-memory stand-in for the design_sessions table."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self._next_id = 1


class _Query:
    def __init__(self, store: _FakeSessionsStore, op: str, payload: dict | None = None):
        self.store = store
        self.op = op
        self.payload = payload
        self.filters: dict = {}

    def eq(self, field, value):
        self.filters[field] = value
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def select(self, *_a, **_k):
        return self

    def _matches(self):
        return [
            row
            for row in self.store.rows.values()
            if all(row.get(k) == v for k, v in self.filters.items())
        ]

    def execute(self):
        if self.op == "insert":
            row = dict(self.payload)
            row_id = f"sess-{self.store._next_id}"
            self.store._next_id += 1
            row["id"] = row_id
            self.store.rows[row_id] = row
            return _Result([row])
        if self.op == "select":
            return _Result(self._matches())
        if self.op == "update":
            matches = self._matches()
            for row in matches:
                row.update(self.payload)
            return _Result(matches)
        raise AssertionError(f"unexpected op {self.op}")


class _FakeTable:
    def __init__(self, store: _FakeSessionsStore):
        self.store = store

    def insert(self, payload):
        return _Query(self.store, "insert", payload)

    def select(self, *_a, **_k):
        return _Query(self.store, "select")

    def update(self, payload):
        return _Query(self.store, "update", payload)


class _FakeSB:
    def __init__(self):
        self.design_sessions = _FakeSessionsStore()

    def table(self, name):
        if name == "design_sessions":
            return _FakeTable(self.design_sessions)
        raise AssertionError(f"unexpected table {name}")


def _fake_get_product(product_id, store_id=None):
    return STUB_PRODUCTS[0] if product_id == _PRODUCT_ID else None


@pytest.fixture()
def client(monkeypatch):
    from app.api.deps import require_store
    from app.main import create_app

    fake_sb = _FakeSB()
    monkeypatch.setattr("app.api.routes.sessions.get_supabase", lambda: fake_sb)
    monkeypatch.setattr("app.api.routes.sessions.get_product", _fake_get_product)
    monkeypatch.setattr(
        "app.services.leads.capture_lead_and_verify", lambda session, collected, email: "lead-1"
    )

    app = create_app()
    app.dependency_overrides[require_store] = lambda: _STORE
    c = TestClient(app)
    c._fake = fake_sb
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_store_headers():
    return _STORE_HEADERS


@pytest.fixture()
def canvas_session_id(client, seeded_store_headers):
    r = client.post(
        "/sessions/canvas",
        json={"product_id": _PRODUCT_ID},
        headers=seeded_store_headers,
    )
    assert r.status_code == 200
    return r.json()["session_id"]


def test_create_canvas_session_sets_state_and_flow_mode(client, seeded_store_headers):
    r = client.post(
        "/sessions/canvas",
        json={"product_id": _PRODUCT_ID},
        headers=seeded_store_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "canvas_design"
    row = client._fake.design_sessions.rows[body["session_id"]]
    assert row["flow_mode"] == "canvas"
    assert row["collected"]["flow_mode"] == "canvas"
    assert row["product_ref"]["product_id"] == _PRODUCT_ID


def test_create_canvas_session_from_hat_type(client, seeded_store_headers, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.sessions.hat_types_service.get_hat_type",
        lambda hid, store_id=None: {
            "id": hid, "slug": "5p", "name": "5-Panel", "style": "flat",
            "blank_view_images": {"front": "b/front.png", "back": "b/back.png",
                                  "left": "b/left.png", "right": "b/right.png"},
            "placement_zones": ["front_panel", "back"], "decoration_types": ["print"],
        },
    )
    r = client.post(
        "/sessions/canvas",
        json={"hat_type_id": "h1", "colour": {"name": "Navy", "hex": "#1a2b5c"}},
        headers=seeded_store_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "canvas_design"
    row = client._fake.design_sessions.rows[body["session_id"]]
    assert row["flow_mode"] == "canvas"
    assert row["collected"]["flow_mode"] == "canvas"
    assert row["collected"]["hat_type_id"] == "h1"
    assert row["collected"]["hat_colour"]["hex"] == "#1a2b5c"
    assert row["product_ref"]["reference_image_url"] == "b/front.png"


def test_create_canvas_session_requires_product_or_hat_type(client, seeded_store_headers):
    r = client.post(
        "/sessions/canvas",
        json={},
        headers=seeded_store_headers,
    )
    assert r.status_code == 400


def test_upload_canvas_layouts_stores_signed_urls(client, seeded_store_headers, canvas_session_id, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.upload_asset", lambda data, filename, content_type: f"uploads/{filename}")
    monkeypatch.setattr("app.api.routes.sessions.generate_signed_url", lambda path: f"signed://{path}")

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post(
        f"/sessions/{canvas_session_id}/canvas-layouts",
        data={"faces": ["front"]},
        files={"files": ("front.png", io.BytesIO(png_bytes), "image/png")},
        headers=seeded_store_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["views"]["front"].startswith("signed://uploads/")
    row = client._fake.design_sessions.rows[canvas_session_id]
    assert row["collected"]["canvas_layouts"]["front"].startswith("uploads/")


def test_upload_canvas_layouts_rejects_oversized_file(client, seeded_store_headers, canvas_session_id, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.upload_asset", lambda data, filename, content_type: f"uploads/{filename}")
    monkeypatch.setattr("app.api.routes.sessions.generate_signed_url", lambda path: f"signed://{path}")

    from app.services.upload_validation import MAX_UPLOAD_BYTES

    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * MAX_UPLOAD_BYTES
    r = client.post(
        f"/sessions/{canvas_session_id}/canvas-layouts",
        data={"faces": ["front"]},
        files={"files": ("front.png", io.BytesIO(oversized), "image/png")},
        headers=seeded_store_headers,
    )
    assert r.status_code == 413


def test_upload_canvas_layouts_rejects_unsupported_mime(client, seeded_store_headers, canvas_session_id, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.upload_asset", lambda data, filename, content_type: f"uploads/{filename}")
    monkeypatch.setattr("app.api.routes.sessions.generate_signed_url", lambda path: f"signed://{path}")

    r = client.post(
        f"/sessions/{canvas_session_id}/canvas-layouts",
        data={"faces": ["front"]},
        files={"files": ("front.txt", io.BytesIO(b"not an image"), "text/plain")},
        headers=seeded_store_headers,
    )
    assert r.status_code == 415


def test_upload_canvas_layouts_rejects_faces_files_mismatch(client, seeded_store_headers, canvas_session_id, monkeypatch):
    monkeypatch.setattr("app.api.routes.sessions.upload_asset", lambda data, filename, content_type: f"uploads/{filename}")
    monkeypatch.setattr("app.api.routes.sessions.generate_signed_url", lambda path: f"signed://{path}")

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = client.post(
        f"/sessions/{canvas_session_id}/canvas-layouts",
        data={"faces": ["front", "back"]},
        files={"files": ("front.png", io.BytesIO(png_bytes), "image/png")},
        headers=seeded_store_headers,
    )
    assert r.status_code == 400


def test_finalize_writes_elements_and_moves_to_generating(client, seeded_store_headers, canvas_session_id):
    design = {"colourway": {"name": "Navy", "hex": "#1e3a8a"},
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                    "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                    "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design, "email": "a@b.com", "name": "Al"},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "generating"
    elements, _ = canvas_to_elements(design)
    assert elements[0]["content"] == "HI"

    row = client._fake.design_sessions.rows[canvas_session_id]
    assert row["state"] == "generating"
    assert row["collected"]["elements"][0]["content"] == "HI"
    assert row["collected"]["email_captured"] is True
    assert row["canvas_design"] == design


def test_canvas_request_entry_path_defaults_non_null():
    """Regression: design_sessions.entry_path is NOT NULL, so the create request
    must default entry_path to a non-null marker (the mocked-supabase route tests
    never hit the real constraint — a live E2E returned 503 when this was None)."""
    from app.models.canvas import CreateCanvasSessionRequest

    req = CreateCanvasSessionRequest(product_id="p1")
    assert req.entry_path == "canvas_first"
    assert req.entry_path is not None
