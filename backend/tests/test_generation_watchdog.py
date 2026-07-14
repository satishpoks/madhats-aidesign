"""reap_stuck_generations() — the stalled-generation watchdog.

A generation stuck at 'pending' past the threshold (a hung provider call with no
timeout) is marked failed and a fresh render is re-enqueued so the design still
gets produced + delivered — bounded per session so a persistently-hung provider
gives up and alerts ops instead of looping forever.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks

from app.api.routes import generate as gen


class _Query:
    """Chainable supabase-py stand-in that shares row dicts with the backing
    store (so .update mutates the stored rows) and supports .lt + .insert."""

    def __init__(self, store, table):
        self._store = store
        self._table = table
        self._rows = list(store.setdefault(table, []))
        self._update = None
        self._insert = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def lt(self, field, value):
        self._rows = [r for r in self._rows if str(r.get(field) or "") < value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._update = payload
        return self

    def insert(self, payload):
        self._insert = payload
        return self

    def execute(self):
        if self._update is not None:
            for row in self._rows:
                row.update(self._update)
            return _Res(self._rows)
        if self._insert is not None:
            new_id = f"gen-{len(self._store[self._table]) + 1}"
            row = {**self._insert, "id": new_id, "job_id": new_id}
            self._store[self._table].append(row)
            return _Res([row])
        return _Res(self._rows)


class _Res:
    def __init__(self, data):
        self.data = data


class _FakeSB:
    def __init__(self, store):
        self._store = store

    def table(self, name):
        return _Query(self._store, name)


def _session(sid="sess-1"):
    return {
        "id": sid,
        "store_id": "store-1",
        "product_ref": {
            "product_id": "p1", "colour": "black",
            "reference_image_url": "http://x/ref.png", "name": "Snapback",
        },
        "collected": {"design_description": {"summary": "bold logo"}},
    }


def _old(minutes=30):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _patch(monkeypatch, store, alerts=None):
    sb = _FakeSB(store)
    monkeypatch.setattr(gen, "get_supabase", lambda: sb)

    async def _noop_run(**kw):
        return None

    monkeypatch.setattr(gen, "_run_generation", _noop_run)
    if alerts is not None:
        monkeypatch.setattr(
            gen, "_send_ops_alert",
            lambda *a, **k: alerts.append(a),
        )
    return sb


def test_stuck_pending_is_reaped_and_retried(monkeypatch):
    store = {
        "generations": [
            {"job_id": "job-1", "session_id": "sess-1", "tier": "preview",
             "status": "pending", "created_at": _old(30)},
        ],
        "design_sessions": [_session()],
    }
    _patch(monkeypatch, store)
    bg = BackgroundTasks()

    tally = asyncio.run(gen.reap_stuck_generations(background=bg, stuck_minutes=5))

    assert tally == {"reaped": 1, "retried": 1, "gave_up": 0}
    # Original job marked failed with the stall marker.
    original = next(r for r in store["generations"] if r["job_id"] == "job-1")
    assert original["status"] == "failed"
    assert original["error"].startswith(gen._STALL_ERROR_PREFIX)
    # A fresh pending row was enqueued + the worker scheduled.
    pending = [r for r in store["generations"] if r["status"] == "pending"]
    assert len(pending) == 1 and pending[0]["job_id"] != "job-1"
    assert len(bg.tasks) == 1


def test_recent_pending_is_not_reaped(monkeypatch):
    store = {
        "generations": [
            {"job_id": "job-1", "session_id": "sess-1", "tier": "preview",
             "status": "pending", "created_at": datetime.now(timezone.utc).isoformat()},
        ],
        "design_sessions": [_session()],
    }
    _patch(monkeypatch, store)
    bg = BackgroundTasks()

    tally = asyncio.run(gen.reap_stuck_generations(background=bg, stuck_minutes=5))

    assert tally == {"reaped": 0, "retried": 0, "gave_up": 0}
    assert store["generations"][0]["status"] == "pending"
    assert len(bg.tasks) == 0


def test_gives_up_and_alerts_after_max_stall_retries(monkeypatch):
    # Already stalled MAX_STALL_RETRIES times; reaping one more tips it over.
    prior = [
        {"job_id": f"old-{i}", "session_id": "sess-1", "status": "failed",
         "error": f"{gen._STALL_ERROR_PREFIX} no response"}
        for i in range(gen.MAX_STALL_RETRIES)
    ]
    store = {
        "generations": prior + [
            {"job_id": "job-1", "session_id": "sess-1", "tier": "preview",
             "status": "pending", "created_at": _old(30)},
        ],
        "design_sessions": [_session()],
    }
    alerts: list = []
    _patch(monkeypatch, store, alerts=alerts)
    bg = BackgroundTasks()

    tally = asyncio.run(gen.reap_stuck_generations(background=bg, stuck_minutes=5))

    assert tally == {"reaped": 1, "retried": 0, "gave_up": 1}
    assert len(alerts) == 1  # ops alerted instead of looping
    assert len(bg.tasks) == 0  # no new render enqueued
    assert not [r for r in store["generations"] if r["status"] == "pending"]
