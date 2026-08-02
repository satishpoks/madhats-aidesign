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
        "app.services.leads.capture_lead_and_verify",
        lambda session, collected, email: ("lead-1", True),
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
    assert body["state"] == "greeting"
    row = client._fake.design_sessions.rows[body["session_id"]]
    assert row["flow_mode"] == "canvas"
    assert row["collected"]["flow_mode"] == "canvas"
    assert row["product_ref"]["product_id"] == _PRODUCT_ID
    assert "canvas_blank" not in row["collected"]


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
    assert body["state"] == "greeting"
    row = client._fake.design_sessions.rows[body["session_id"]]
    assert row["flow_mode"] == "canvas"
    assert row["collected"]["flow_mode"] == "canvas"
    assert row["collected"]["hat_type_id"] == "h1"
    assert row["collected"]["hat_colour"]["hex"] == "#1a2b5c"
    assert row["collected"]["canvas_blank"] is True
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


def test_finalize_routes_to_decoration(client, seeded_store_headers, canvas_session_id, monkeypatch):
    import app.services.decoration_types as deco_svc
    import app.services.conversation.intent_extractor as ie

    monkeypatch.setattr(
        deco_svc, "list_types",
        lambda s, active_only=False: [{"name": "Embroidery"}, {"name": "Print"}],
    )

    async def _reply(*a, **k):
        return "How would you like this decorated?"

    monkeypatch.setattr(ie, "generate_reply", _reply)

    design = {"colourway": {"name": "Navy", "hex": "#1e3a8a"},
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                    "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                    "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design, "name": "Al"},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ask_decoration"
    assert body["data"]["multiselect"] is True
    assert body["data"]["options"] == ["Embroidery", "Print"]
    # v1 canvas never watermarks (design_confirmed is a v2-only flag, never set
    # on this path) — this producer is a hand-built dict, not
    # `orchestrator._public_data`/`public_data_for`, so it has to be checked
    # separately for the same uniformity those two already guarantee.
    assert body["data"]["watermark"] is False
    elements, _ = canvas_to_elements(design)
    assert elements[0]["content"] == "HI"

    row = client._fake.design_sessions.rows[canvas_session_id]
    assert row["state"] == "ask_decoration"
    assert row["collected"]["elements"][0]["content"] == "HI"
    assert row["collected"]["canvas_finalized"] is True
    assert row["canvas_design"] == design
    assert row["collected"]["hat_colour"] == {"name": "Navy", "hex": "#1e3a8a"}


def test_rework_finalize_carries_the_watermark_flag(
        client, seeded_store_headers, canvas_session_id, monkeypatch):
    """The rework branch ("Rework on the canvas" from OFFER_REFINE) is the
    second of the three hand-built `data` dicts in this route — it also used
    to emit no `watermark` key at all. A confirmed design going through the
    old `reworking` re-render path must still report its watermark state
    explicitly, the same as the other two branches."""
    import app.services.conversation.intent_extractor as ie

    async def _reply(*a, **k):
        return "Putting your changes together…"

    monkeypatch.setattr(ie, "generate_reply", _reply)

    row = client._fake.design_sessions.rows[canvas_session_id]
    row["collected"] = {**(row.get("collected") or {}),
                        "reworking": True, "design_confirmed": True}

    design = {"colourway": None, "faces": {"front": [], "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design}, headers=seeded_store_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "regenerating"
    assert body["data"]["trigger_regeneration"] is True
    assert body["data"]["watermark"] is True
    # regenerating is never the terminal quote_requested state.
    assert body["data"]["session_ended"] is False

    row = client._fake.design_sessions.rows[canvas_session_id]
    assert row["state"] == "regenerating"
    assert "reworking" not in row["collected"]


def test_v2_finalize_is_quote_gated_and_never_generates(client, seeded_store_headers, canvas_session_id, monkeypatch):
    """Under the v2 orchestrator flag, canvas-finalize is QUOTE-GATED (C1/C4):
    it must skip the v1 decoration/notes outro AND never trigger a render or a
    design email. It lands on QUOTE_REQUESTED and echoes the tracking reference
    the REQUEST_QUOTE step already minted."""
    monkeypatch.setattr("app.api.routes.sessions.settings.canvas_orchestrator_v2", True)
    row = client._fake.design_sessions.rows[canvas_session_id]
    row["collected"] = {**(row.get("collected") or {}),
                        "quote_requested": True, "reference_code": "MH-BCDFGH",
                        # REVIEW_DESIGN's "Looks great, send it" precedes
                        # REQUEST_QUOTE in the registry, so a real session
                        # reaching here always carries this.
                        "design_confirmed": True}

    design = {"colourway": {"name": "Navy", "hex": "#1e3a8a"},
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                    "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                    "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design, "name": "Al"},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "quote_requested"
    assert body["data"]["reference_code"] == "MH-BCDFGH"
    assert "MH-BCDFGH" in body["reply"]
    # The quote-gated flow never renders from finalize and never offers options.
    assert "trigger_generation" not in body["data"]
    assert "options" not in body["data"]
    # This is the third hand-built `data` dict in this route — it used to be a
    # silent producer of both flags (Finding: a live turn here showed the
    # canvas unwatermarked while a reload of the exact same state, served by
    # `_public_data`, showed it watermarked; and the frontend had no signal to
    # lock the composer other than the state string, which v1 shares as an
    # answerable gate). The design was confirmed to get here at all (REVIEW_
    # DESIGN precedes REQUEST_QUOTE in the registry), so it must watermark;
    # and this IS the terminal state for v2, so it must end the session.
    assert body["data"]["watermark"] is True
    assert body["data"]["session_ended"] is True

    row = client._fake.design_sessions.rows[canvas_session_id]
    assert row["state"] == "quote_requested"
    assert row["collected"]["elements"][0]["content"] == "HI"
    assert row["collected"]["canvas_finalized"] is True
    assert row["canvas_design"] == design


def test_quote_reply_does_not_claim_the_email_is_unconfirmed(
        client, seeded_store_headers, canvas_session_id, monkeypatch):
    """v2 cannot reach finalize with an unconfirmed address — AWAIT_EMAIL_VERIFY
    gates it — so promising delivery 'once you confirm' is false."""
    monkeypatch.setattr("app.api.routes.sessions.settings.canvas_orchestrator_v2", True)
    row = client._fake.design_sessions.rows[canvas_session_id]
    row["collected"] = {**(row.get("collected") or {}),
                        "quote_requested": True, "reference_code": "MH-BCDFGH"}

    design = {"colourway": None,
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                   "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                   "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design}, headers=seeded_store_headers)

    assert r.status_code == 200
    reply = r.json()["reply"]
    assert "once you confirm" not in reply.lower()
    assert "We've also emailed it to you." in reply


def test_v2_finalize_converges_the_quote_confirmation(client, seeded_store_headers, canvas_session_id, monkeypatch):
    """Finalize is the THIRD convergence point for the quote confirmation
    (C2/C3). The canvas — elements, layout guides, previews — only exists as of
    this write, and the sales email attaches them; a customer who verified early
    must get their components-complete email from here, not from the earlier
    REQUEST_QUOTE converge."""
    monkeypatch.setattr("app.api.routes.sessions.settings.canvas_orchestrator_v2", True)
    calls = []
    from app.services import delivery
    monkeypatch.setattr(delivery, "maybe_send_quote_confirmation",
                        lambda sid: calls.append(sid) or True)

    design = {"faces": {"front": [], "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    assert calls == [canvas_session_id]


def test_canvas_request_entry_path_defaults_non_null():
    """Regression: design_sessions.entry_path is NOT NULL, so the create request
    must default entry_path to a non-null marker (the mocked-supabase route tests
    never hit the real constraint — a live E2E returned 503 when this was None)."""
    from app.models.canvas import CreateCanvasSessionRequest

    req = CreateCanvasSessionRequest(product_id="p1")
    assert req.entry_path == "canvas_first"
    assert req.entry_path is not None


def _design_with_text(content: str) -> dict:
    return {"colourway": None, "faces": {
        "front": [{"id": "e1", "type": "text", "content": content,
                   "x": 0.5, "y": 0.4, "width": 0.3, "height": 0.1,
                   "rotation": 0, "zIndex": 0}],
        "back": [], "left": [], "right": []}}


def test_finalize_rejects_obscene_cap_text(client, seeded_store_headers, canvas_session_id):
    """Cap text reaches the AI render and then physical production artwork."""
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": _design_with_text("SHIT HAPPENS")},
                    headers=seeded_store_headers)
    assert r.status_code == 422
    assert "SHIT HAPPENS" in r.json()["detail"]   # names it so it can be edited


def test_finalize_rejection_writes_nothing(client, seeded_store_headers, canvas_session_id):
    """The gate runs before the collected write and before the sales notify."""
    client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                json={"canvas_design": _design_with_text("SHIT HAPPENS")},
                headers=seeded_store_headers)
    row = client._fake.design_sessions.rows[canvas_session_id]
    assert not (row.get("collected") or {}).get("canvas_finalized")
    assert row.get("canvas_design") is None


def test_finalize_does_not_scan_internal_brief_notes(client, seeded_store_headers,
                                                     canvas_session_id, monkeypatch):
    """OWNER RULING: notes are internal and never printed, so finalize must not
    gate on them. Chat deliberately allows mild profanity through, and
    `_apply_final_notes` / `_apply_decoration_mix` write that text into
    `brief_notes` verbatim — so a note gate rejected the job AFTER the customer
    had their reference code, with no UI to reword it and no sales notification.
    """
    import app.services.decoration_types as deco_svc
    import app.services.conversation.intent_extractor as ie

    monkeypatch.setattr(deco_svc, "list_types", lambda s, active_only=False: [])

    async def _reply(*a, **k):
        return "Anything else?"

    monkeypatch.setattr(ie, "generate_reply", _reply)

    row = client._fake.design_sessions.rows[canvas_session_id]
    row["collected"] = {**(row.get("collected") or {}),
                        "brief_notes": ["Customer final notes: this shit better be quick"]}

    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": _design_with_text("MADHATS CREW")},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    assert client._fake.design_sessions.rows[canvas_session_id]["collected"]["canvas_finalized"]


def test_finalize_accepts_clean_cap_text(client, seeded_store_headers, canvas_session_id, monkeypatch):
    # Mirrors test_finalize_routes_to_decoration's mocking: finalize_canvas
    # continues past the profanity gate into the v1 decoration-outro routing,
    # which otherwise calls out to decoration_types.list_types (real Supabase).
    import app.services.decoration_types as deco_svc
    import app.services.conversation.intent_extractor as ie

    monkeypatch.setattr(deco_svc, "list_types", lambda s, active_only=False: [])

    async def _reply(*a, **k):
        return "Anything else?"

    monkeypatch.setattr(ie, "generate_reply", _reply)

    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": _design_with_text("MADHATS CREW")},
                    headers=seeded_store_headers)
    assert r.status_code == 200
