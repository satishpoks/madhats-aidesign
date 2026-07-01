"""generation_logger — per-call audit trail writes.

Best-effort: a DB error must be swallowed and never propagate into the
generation worker.
"""
from __future__ import annotations

from app.services import generation_logger


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, sink):
        self._table = table
        self._sink = sink
        self._pending_insert = None
        self._pending_update = None
        self._filters: dict = {}

    def insert(self, payload):
        self._pending_insert = payload
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def eq(self, field, value):
        self._filters[field] = value
        return self

    def execute(self):
        if self._pending_insert is not None:
            row = dict(self._pending_insert)
            row.setdefault("id", "log-1")
            self._sink.setdefault(self._table, []).append(("insert", row))
            return _Result([row])
        if self._pending_update is not None:
            self._sink.setdefault(self._table, []).append(
                ("update", dict(self._filters), dict(self._pending_update))
            )
            return _Result([])
        return _Result([])


class _FakeSB:
    def __init__(self):
        self.sink: dict = {}

    def table(self, name):
        return _Query(name, self.sink)


class _BoomSB:
    def table(self, name):
        raise RuntimeError("db down")


def _patch(monkeypatch, sb):
    monkeypatch.setattr(generation_logger, "get_supabase", lambda: sb)


def test_log_request_inserts_and_returns_id(monkeypatch):
    sb = _FakeSB()
    _patch(monkeypatch, sb)

    log_id = generation_logger.log_request(
        generation_id="gen-1",
        job_id="job-1",
        session_id="sess-1",
        attempt=1,
        tier="preview",
        reference_image_url="https://cdn/ref.png",
        uploaded_asset_url="uploads/logo.png",
        full_prompt="REPRODUCE THE CAP EXACTLY ...",
        params={"placement_zone": "front_panel"},
    )

    assert log_id == "log-1"
    kind, row = sb.sink["generation_logs"][0]
    assert kind == "insert"
    assert row["status"] == "requested"
    assert row["attempt"] == 1
    assert row["full_prompt"].startswith("REPRODUCE")
    assert row["reference_image_url"] == "https://cdn/ref.png"
    assert row["uploaded_asset_url"] == "uploads/logo.png"


def test_log_response_updates_matching_row(monkeypatch):
    sb = _FakeSB()
    _patch(monkeypatch, sb)

    generation_logger.log_response(
        "log-1",
        status="complete",
        model="gemini-2.5-flash-image",
        output_image_url="generated/preview/x.png",
        response_meta={"image_returned": True},
        raw_response={"candidates": []},
        latency_ms=1234,
    )

    kind, filters, payload = sb.sink["generation_logs"][0]
    assert kind == "update"
    assert filters == {"id": "log-1"}
    assert payload["status"] == "complete"
    assert payload["model"] == "gemini-2.5-flash-image"
    assert payload["output_image_url"] == "generated/preview/x.png"
    assert payload["response_meta"] == {"image_returned": True}
    assert payload["raw_response"] == {"candidates": []}
    assert payload["latency_ms"] == 1234
    assert payload["response_at"]  # set to a timestamp


def test_log_response_noop_when_log_id_none(monkeypatch):
    sb = _FakeSB()
    _patch(monkeypatch, sb)
    generation_logger.log_response(None, status="complete")
    assert sb.sink == {}


def test_log_request_swallows_db_error(monkeypatch):
    _patch(monkeypatch, _BoomSB())
    # must NOT raise, returns None
    assert generation_logger.log_request(
        generation_id="g",
        job_id="j",
        session_id="s",
        attempt=1,
        tier="preview",
        reference_image_url="r",
        uploaded_asset_url=None,
        full_prompt="p",
        params={},
    ) is None


def test_log_response_swallows_db_error(monkeypatch):
    _patch(monkeypatch, _BoomSB())
    # must NOT raise
    generation_logger.log_response("log-1", status="failed", error="boom")


def test_log_cache_hit_writes_row(monkeypatch):
    sb = _FakeSB()
    _patch(monkeypatch, sb)

    generation_logger.log_cache_hit(
        generation_id="gen-1",
        job_id="job-1",
        session_id="sess-1",
        tier="preview",
        reference_image_url="https://cdn/ref.png",
        uploaded_asset_url=None,
        full_prompt="prompt",
        params={},
        model="stub",
        output_image_url="generated/preview/cached.png",
    )

    kind, row = sb.sink["generation_logs"][0]
    assert kind == "insert"
    assert row["status"] == "cache_hit"
    assert row["output_image_url"] == "generated/preview/cached.png"
