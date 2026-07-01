"""_run_generation() — the background generation worker.

Covers the retry loop added in Task 2 (spec §4.3): transient provider errors
are retried up to 3x with backoff, permanent errors fail fast, a successful
completion triggers the gated delivery primitive (guarded so a delivery error
can never flip the generation back to failed), and a final failure records
attempts/error and sends an ops alert — never a customer-facing failure.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.api.routes import generate as generate_routes
from app.services.image.image_provider import GenerationParams, GenerationResult


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Minimal chainable stand-in for a supabase-py table query (see
    test_delivery.py / test_verification_poll.py for the same pattern)."""

    def __init__(self, table, rows, sink):
        self._table = table
        self._rows = rows
        self._sink = sink
        self._pending_update = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.setdefault(self._table, []).append(self._pending_update)
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables: dict):
        self._tables = tables
        self.sink: dict = {}

    def table(self, name):
        rows = list(self._tables.get(name, []))
        return _Query(name, rows, self.sink)


def _generation_row(**overrides):
    row = {
        "job_id": "job-1",
        "session_id": "sess-1",
        "tier": "preview",
        "model": "pending",
        "status": "pending",
        "attempts": 0,
        "created_at": "2026-07-01T00:00:00Z",
    }
    row.update(overrides)
    return row


def _base_kwargs(**overrides):
    kwargs = dict(
        job_id="job-1",
        session_id="sess-1",
        store_id="store-1",
        tier="preview",
        prompt="a design prompt",
        product_ref={"product_id": "prod-1", "colour": "black", "reference_image_url": "http://x/ref.png", "name": "Snapback"},
        collected={"design_description": {"summary": "bold logo front and centre"}},
        params=GenerationParams(tier="preview"),
    )
    kwargs.update(overrides)
    return kwargs


def _patch_common(monkeypatch, fake, *, provider, sleeps=None, alerts=None, previews=None):
    monkeypatch.setattr(generate_routes, "get_supabase", lambda: fake)
    monkeypatch.setattr(generate_routes.generation_cache, "lookup", lambda key: None)
    monkeypatch.setattr(generate_routes, "get_provider", lambda tier: provider)
    monkeypatch.setattr(generate_routes, "generate_signed_url", lambda path: f"signed:{path}")
    monkeypatch.setattr(generate_routes, "_make_watermarked", lambda clean_path: "watermarked/path.png")
    monkeypatch.setattr(generate_routes, "get_store", lambda store_id: None)

    if sleeps is not None:
        async def _fake_sleep(seconds):
            sleeps.append(seconds)

        monkeypatch.setattr(generate_routes.asyncio, "sleep", _fake_sleep)

    if previews is not None:
        def _fake_maybe_send(session_id):
            previews.append(session_id)
            return True

        monkeypatch.setattr(generate_routes.delivery, "maybe_send_preview", _fake_maybe_send)

    if alerts is not None:
        def _fake_alert(to, session_id, product, brief, error):
            alerts.append((to, session_id, product, brief, error))
            return True

        monkeypatch.setattr(generate_routes.email_service, "send_generation_alert", _fake_alert)


class _FlakyProvider:
    """Raises the given exceptions in sequence, then returns `result` (or keeps raising)."""

    def __init__(self, exceptions, result=None):
        self._exceptions = list(exceptions)
        self._result = result
        self.calls = 0

    async def generate(self, **kwargs):
        self.calls += 1
        if self._exceptions:
            raise self._exceptions.pop(0)
        return self._result


def _ok_result(model="stub-model"):
    return GenerationResult(
        image_url="generations/clean.png",
        cost_usd=0.01,
        latency_ms=100,
        model=model,
        raw_response={"candidates": ["..."]},
        response_meta={"image_returned": True},
    )


def _capture_logs(monkeypatch):
    """Record generation_logger calls made by the worker."""
    calls: dict = {"request": [], "response": [], "cache_hit": []}

    def _req(**kw):
        calls["request"].append(kw)
        return f"log-{len(calls['request'])}"

    def _resp(log_id, **kw):
        calls["response"].append((log_id, kw))

    def _cache(**kw):
        calls["cache_hit"].append(kw)

    monkeypatch.setattr(generate_routes.generation_logger, "log_request", _req)
    monkeypatch.setattr(generate_routes.generation_logger, "log_response", _resp)
    monkeypatch.setattr(generate_routes.generation_logger, "log_cache_hit", _cache)
    return calls


def test_logs_request_and_response_on_success(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([], result=_ok_result())
    _patch_common(monkeypatch, fake, provider=provider, sleeps=[], previews=[])
    logs = _capture_logs(monkeypatch)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert len(logs["request"]) == 1
    req = logs["request"][0]
    assert req["attempt"] == 1
    assert req["reference_image_url"] == "http://x/ref.png"
    assert req["full_prompt"] == "a design prompt"
    assert len(logs["response"]) == 1
    log_id, resp = logs["response"][0]
    assert log_id == "log-1"
    assert resp["status"] == "complete"
    assert resp["raw_response"] == {"candidates": ["..."]}
    assert resp["output_image_url"] == "generations/clean.png"


def test_logs_failure_with_error(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([ValueError("bad input")])
    _patch_common(monkeypatch, fake, provider=provider, sleeps=[], alerts=[], previews=[])
    logs = _capture_logs(monkeypatch)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert len(logs["request"]) == 1
    log_id, resp = logs["response"][0]
    assert resp["status"] == "failed"
    assert "bad input" in resp["error"]


def test_logs_one_row_per_attempt(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([httpx.TimeoutException("t")], result=_ok_result())
    _patch_common(monkeypatch, fake, provider=provider, sleeps=[], previews=[])
    logs = _capture_logs(monkeypatch)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert [r["attempt"] for r in logs["request"]] == [1, 2]
    assert [resp["status"] for _, resp in logs["response"]] == ["failed", "complete"]


def test_cache_hit_logs_cache_hit_row(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([], result=_ok_result())
    _patch_common(monkeypatch, fake, provider=provider, sleeps=[], previews=[])
    monkeypatch.setattr(
        generate_routes.generation_cache,
        "lookup",
        lambda key: {
            "model": "stub",
            "image_url": "generated/preview/cached.png",
            "watermarked_url": "watermarked/x.png",
        },
    )
    logs = _capture_logs(monkeypatch)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert provider.calls == 0
    assert len(logs["cache_hit"]) == 1
    assert logs["cache_hit"][0]["output_image_url"] == "generated/preview/cached.png"


def test_success_first_attempt_marks_complete_and_sends_preview(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([], result=_ok_result())
    sleeps: list = []
    previews: list = []
    _patch_common(monkeypatch, fake, provider=provider, sleeps=sleeps, previews=previews)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert row["status"] == "complete"
    assert row["attempts"] == 1
    assert provider.calls == 1
    assert sleeps == []
    assert previews == ["sess-1"]


def test_transient_error_retried_then_succeeds(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([httpx.TimeoutException("timeout")], result=_ok_result())
    sleeps: list = []
    previews: list = []
    _patch_common(monkeypatch, fake, provider=provider, sleeps=sleeps, previews=previews)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert row["status"] == "complete"
    assert row["attempts"] == 2
    assert provider.calls == 2
    assert sleeps == [2]  # one backoff between attempt 1 and 2
    assert previews == ["sess-1"]


def test_transient_error_exhausts_retries_marks_failed_and_alerts(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    exc = httpx.TimeoutException("still timing out")
    provider = _FlakyProvider([exc, exc, exc])  # fails all 3 attempts
    sleeps: list = []
    alerts: list = []
    previews: list = []
    _patch_common(monkeypatch, fake, provider=provider, sleeps=sleeps, alerts=alerts, previews=previews)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert row["status"] == "failed"
    assert row["attempts"] == 3
    assert "still timing out" in row["error"]
    assert provider.calls == 3
    assert sleeps == [2, 8]  # backoff before attempt 2 and attempt 3, none after final failure
    assert previews == []  # generation never succeeded — no delivery trigger
    assert len(alerts) == 1
    to, session_id, product, brief, error = alerts[0]
    assert session_id == "sess-1"
    assert product == "Snapback"
    assert "bold logo" in brief
    assert "still timing out" in error


def test_permanent_error_fails_fast_no_retry(monkeypatch):
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([ValueError("missing reference image")])
    sleeps: list = []
    alerts: list = []
    previews: list = []
    _patch_common(monkeypatch, fake, provider=provider, sleeps=sleeps, alerts=alerts, previews=previews)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert row["status"] == "failed"
    assert row["attempts"] == 1  # no retry attempted
    assert provider.calls == 1
    assert sleeps == []
    assert len(alerts) == 1


def test_delivery_error_on_success_does_not_flip_to_failed(monkeypatch):
    """A raising maybe_send_preview must never turn a completed generation
    back into a failed one — the call is guarded in its own try/except."""
    row = _generation_row()
    fake = _FakeSB({"generations": [row]})
    provider = _FlakyProvider([], result=_ok_result())
    sleeps: list = []
    _patch_common(monkeypatch, fake, provider=provider, sleeps=sleeps)

    def _raise(session_id):
        raise RuntimeError("delivery blew up")

    monkeypatch.setattr(generate_routes.delivery, "maybe_send_preview", _raise)

    asyncio.run(generate_routes._run_generation(**_base_kwargs()))

    assert row["status"] == "complete"
    assert row["attempts"] == 1


def test_is_transient_classification():
    assert generate_routes._is_transient(httpx.TimeoutException("t")) is True
    assert generate_routes._is_transient(ValueError("bad input")) is False

    class _FakeServerError(Exception):
        status_code = 503

    class _FakeClientError(Exception):
        status_code = 400

    assert generate_routes._is_transient(_FakeServerError()) is True
    assert generate_routes._is_transient(_FakeClientError()) is False

    # Test with real google.api_core exceptions (regression test for quota/503 handling)
    from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InvalidArgument

    # ResourceExhausted (429 quota) — must be transient to retry
    assert generate_routes._is_transient(ResourceExhausted("quota exceeded")) is True

    # ServiceUnavailable (503) — must be transient to retry
    assert generate_routes._is_transient(ServiceUnavailable("service unavailable")) is True

    # InvalidArgument (400) — must be permanent (fail fast, no retry)
    assert generate_routes._is_transient(InvalidArgument("invalid request")) is False
