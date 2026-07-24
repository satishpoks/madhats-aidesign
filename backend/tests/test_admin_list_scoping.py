from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _bearer_store_admin(monkeypatch, allowed):
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_blocked_from_global_diagnostics(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.get("/admin/diagnostics", headers=hdr)
    assert resp.status_code == 403


def test_store_admin_blocked_from_reap_stuck(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.post("/admin/generations/reap-stuck", headers=hdr)
    assert resp.status_code == 403


# --- Finding 1: GET /admin/generation-logs/{log_id} cross-store leak -------


class _LogResult:
    def __init__(self, data):
        self.data = data


class _LogQuery:
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
        return _LogResult(self._rows)


class _FakeLogSB:
    """generation_logs row(s) + the design_sessions row its session_id maps to."""

    def __init__(self, logs, sessions):
        self._logs = logs
        self._sessions = sessions

    def table(self, name):
        if name == "generation_logs":
            return _LogQuery(list(self._logs))
        if name == "design_sessions":
            return _LogQuery(list(self._sessions))
        return _LogQuery([])


def _patch_diagnostics_sb(monkeypatch, logs, sessions):
    from app.api.routes import admin_diagnostics

    monkeypatch.setattr(admin_diagnostics, "get_supabase", lambda: _FakeLogSB(logs, sessions))


def test_get_generation_log_blocks_cross_store_admin(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"store-1"})
    logs = [{"id": "log-1", "session_id": "sess-2", "full_prompt": "secret"}]
    sessions = [{"id": "sess-2", "store_id": "store-2"}]
    _patch_diagnostics_sb(monkeypatch, logs, sessions)
    resp = client.get("/admin/generation-logs/log-1", headers=hdr)
    assert resp.status_code == 403


def test_get_generation_log_allows_own_store_admin(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"store-1"})
    logs = [{"id": "log-1", "session_id": "sess-1", "full_prompt": "hello"}]
    sessions = [{"id": "sess-1", "store_id": "store-1"}]
    _patch_diagnostics_sb(monkeypatch, logs, sessions)
    resp = client.get("/admin/generation-logs/log-1", headers=hdr)
    assert resp.status_code == 200
    assert resp.json()["id"] == "log-1"


def test_get_generation_log_super_admin_bypasses_store_check(client, monkeypatch):
    logs = [{"id": "log-1", "session_id": "sess-2", "full_prompt": "secret"}]
    sessions = [{"id": "sess-2", "store_id": "store-2"}]
    _patch_diagnostics_sb(monkeypatch, logs, sessions)
    resp = client.get("/admin/generation-logs/log-1", headers={"X-Admin-Secret": "envsecret"})
    assert resp.status_code == 200


# --- Finding 2: GET /admin/generations filters BEFORE .limit() -------------


class _GenResult:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count if count is not None else len(data)


class _GenQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def in_(self, field, values):
        values = set(values)
        self._rows = [r for r in self._rows if r.get(field) in values]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _GenResult(self._rows)


class _FakeGenSB:
    def __init__(self, generations, sessions):
        self._generations = generations
        self._sessions = sessions

    def table(self, name):
        if name == "generations":
            return _GenQuery(list(self._generations))
        if name == "design_sessions":
            return _GenQuery(list(self._sessions))
        return _GenQuery([])


def _patch_generations_sb(monkeypatch, generations, sessions):
    from app.api.routes import admin_generations

    monkeypatch.setattr(admin_generations, "get_supabase", lambda: _FakeGenSB(generations, sessions))


def test_list_generations_scopes_before_limit_no_starvation(client, monkeypatch):
    # store-1 has one OLDER job; store-2 has many NEWER jobs. With limit=1 and
    # filtering applied after .limit() (the bug), a store-1 admin would see
    # zero jobs — store-2's newer jobs would fill the only slot.
    sessions = [
        {"id": "sess-1", "store_id": "store-1"},
        {"id": "sess-2", "store_id": "store-2"},
        {"id": "sess-3", "store_id": "store-2"},
    ]
    generations = [
        {"job_id": "job-store1-old", "session_id": "sess-1", "tier": "preview",
         "status": "complete", "model": "m", "error": None, "attempts": 1,
         "created_at": "2026-01-01T00:00:00+00:00"},
        {"job_id": "job-store2-new-a", "session_id": "sess-2", "tier": "preview",
         "status": "complete", "model": "m", "error": None, "attempts": 1,
         "created_at": "2026-07-01T00:00:00+00:00"},
        {"job_id": "job-store2-new-b", "session_id": "sess-3", "tier": "preview",
         "status": "complete", "model": "m", "error": None, "attempts": 1,
         "created_at": "2026-07-02T00:00:00+00:00"},
    ]
    _patch_generations_sb(monkeypatch, generations, sessions)
    hdr = _bearer_store_admin(monkeypatch, {"store-1"})
    resp = client.get("/admin/generations?limit=1", headers=hdr)
    assert resp.status_code == 200
    job_ids = {it["job_id"] for it in resp.json()["items"]}
    assert job_ids == {"job-store1-old"}
    assert "job-store2-new-a" not in job_ids
    assert "job-store2-new-b" not in job_ids


def test_list_generations_super_admin_sees_all_stores(client, monkeypatch):
    sessions = [
        {"id": "sess-1", "store_id": "store-1"},
        {"id": "sess-2", "store_id": "store-2"},
    ]
    generations = [
        {"job_id": "job-a", "session_id": "sess-1", "tier": "preview",
         "status": "complete", "model": "m", "error": None, "attempts": 1,
         "created_at": "2026-01-01T00:00:00+00:00"},
        {"job_id": "job-b", "session_id": "sess-2", "tier": "preview",
         "status": "complete", "model": "m", "error": None, "attempts": 1,
         "created_at": "2026-01-02T00:00:00+00:00"},
    ]
    _patch_generations_sb(monkeypatch, generations, sessions)
    resp = client.get("/admin/generations", headers={"X-Admin-Secret": "envsecret"})
    assert resp.status_code == 200
    job_ids = {it["job_id"] for it in resp.json()["items"]}
    assert job_ids == {"job-a", "job-b"}
