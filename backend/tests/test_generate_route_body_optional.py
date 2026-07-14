"""POST /generate/{preview,final,regenerate} must not require a JSON request body.

Regression: the endpoints declared `body: GenerateRequest` but never read it —
the tier comes from the route path (`_start_generation(session_id, "preview")`).
A client that POSTed without a `Content-Type: application/json` header (or with
no body at all) got a 422, so no generation was ever enqueued — yet the chat
state machine still marched the session past GENERATING to OFFER_REFINE ("your
design is ready" with nothing rendered). This is exactly what stranded the
latest canvas session (0 generation rows at state=offer_refine). The unused body
param is removed so these calls succeed regardless of content-type.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import generate as generate_routes
    from app.main import app
    from app.models.generation import JobResponse

    async def _fake_start(session_id, tier, background):
        return JobResponse(job_id=f"job-{tier}")

    # Isolate the test to route param-binding: no DB, no provider.
    monkeypatch.setattr(generate_routes, "_start_generation", _fake_start)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.mark.parametrize(
    "path,tier",
    [
        ("/generate/preview/s1", "preview"),
        ("/generate/final/s1", "final"),
        ("/generate/regenerate/s1", "edit"),
    ],
)
def test_generate_no_body_no_content_type_does_not_422(client, path, tier):
    # No json=, no Content-Type header — exactly what the frontend sent when the
    # design API "didn't even trigger".
    resp = client.post(path)

    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] == f"job-{tier}"
