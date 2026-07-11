"""POST /generate/regenerate/{session_id} — tier='edit' regeneration.

Reuses the preview pipeline but tags the generations row tier='edit' and folds
collected['last_change'] into the prompt as an explicit "requested change"
instruction (see prompt_builder.build_prompt / _start_generation). Cap
enforcement on repeated edits is Task 11 — not covered here.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


async def _noop_async(*a, **k):
    return None


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_regenerate_creates_edit_generation(client, monkeypatch):
    # Minimal happy-path: session exists with a product ref; regenerate returns a job.
    from app.api.routes import generate as gen

    session = {
        "id": "s1",
        "product_ref": {"reference_image_url": "ref.png", "product_id": "p1", "colour": "black"},
        "collected": {"design_description": {"summary": "logo"}, "last_change": "make it bigger"},
        "store_id": None,
    }

    captured = {}

    class _T:
        def __init__(self, name):
            self.name = name

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def order(self, *a, **k):
            return self

        def execute(self):
            if self.name == "design_sessions":
                return type("R", (), {"data": [session]})()
            if self.name == "leads":
                return type("R", (), {"data": []})()
            return type("R", (), {"data": [{"job_id": "j1", "id": "g1"}]})()

        def insert(self, rows):
            captured["tier"] = rows.get("tier")
            return self

    monkeypatch.setattr(gen, "get_supabase", lambda: type("SB", (), {"table": lambda self, n: _T(n)})())
    monkeypatch.setattr(gen, "check_text", _noop_async)
    monkeypatch.setattr(gen.BackgroundTasks, "add_task", lambda self, *a, **k: None)

    from app.services import limits

    monkeypatch.setattr(limits, "can_edit", lambda session_id: True)
    monkeypatch.setattr(limits, "can_start_design", lambda email: True)

    resp = client.post("/generate/regenerate/s1", json={"tier": "edit"})
    assert resp.status_code == 200
    assert captured["tier"] == "edit"


def test_regenerate_folds_last_change_into_prompt(monkeypatch):
    """build_prompt appends collected['change_request'] to the design block so
    the regenerated image reflects the customer's requested edit."""
    from app.services import prompt_builder

    collected = {
        "design_description": {"summary": "bold logo"},
        "change_request": "make the text bigger",
    }
    product_ref = {"reference_image_url": "ref.png"}
    params = prompt_builder.build_params(collected, "edit")

    prompt = prompt_builder.build_prompt(collected, product_ref, params)

    assert "make the text bigger" in prompt
    assert "Requested change from the customer" in prompt


def test_regenerate_uses_preview_provider_for_edit_tier(monkeypatch):
    """_run_generation must resolve the provider via provider_tier ('preview'
    for edit tier) since get_provider() has no 'edit' adapter — the
    generations row itself still records tier='edit'."""
    import asyncio

    from app.api.routes import generate as gen
    from app.services.image.image_provider import GenerationParams, GenerationResult

    class _Result:
        def __init__(self, data):
            self.data = data

    class _Query:
        def __init__(self, table, rows):
            self._table = table
            self._rows = rows
            self._pending_update = None

        def select(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def limit(self, *a, **k):
            return self

        def update(self, payload):
            self._pending_update = payload
            return self

        def execute(self):
            if self._pending_update is not None:
                for row in self._rows:
                    row.update(self._pending_update)
            return _Result(self._rows)

    class _FakeSB:
        def __init__(self, tables):
            self._tables = tables

        def table(self, name):
            return _Query(name, self._tables.get(name, []))

    row = {"job_id": "job-1", "session_id": "sess-1", "tier": "edit", "status": "pending", "attempts": 0}
    fake = _FakeSB({"generations": [row]})

    seen_tiers = []

    def _fake_get_provider(tier):
        seen_tiers.append(tier)

        class _Provider:
            async def generate(self, **kwargs):
                return GenerationResult(
                    image_url="generations/clean.png",
                    cost_usd=0.0,
                    latency_ms=10,
                    model="stub-model",
                    raw_response={},
                    response_meta={},
                )

        return _Provider()

    monkeypatch.setattr(gen, "get_supabase", lambda: fake)
    monkeypatch.setattr(gen.generation_cache, "lookup", lambda key: None)
    monkeypatch.setattr(gen, "get_provider", _fake_get_provider)
    monkeypatch.setattr(gen, "generate_signed_url", lambda path: f"signed:{path}")
    monkeypatch.setattr(gen, "_make_watermarked", lambda clean_path: "watermarked/path.png")
    monkeypatch.setattr(gen, "get_store", lambda store_id: None)
    monkeypatch.setattr(gen.delivery, "maybe_send_preview", lambda session_id: None)

    asyncio.run(
        gen._run_generation(
            job_id="job-1",
            session_id="sess-1",
            store_id=None,
            tier="edit",
            provider_tier="preview",
            prompt="a design prompt",
            product_ref={"product_id": "p1", "colour": "black", "reference_image_url": "ref.png"},
            collected={},
            params=GenerationParams(tier="edit"),
        )
    )

    assert seen_tiers == ["preview"]
    assert row["tier"] == "edit"
    assert row["status"] == "complete"
