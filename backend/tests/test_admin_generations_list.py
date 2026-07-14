"""GET /admin/generations — list recent generation jobs + status for the admin
Ops panel. Admin-gated, no customer PII in the response.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

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

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, name):
        return _Query(list(self._rows if name == "generations" else []))


def _iso(dt):
    return dt.isoformat()


def _rows():
    now = datetime.now(timezone.utc)
    return [
        {
            "job_id": "job-stuck", "session_id": "sess-1", "store_id": "store-1",
            "tier": "preview", "status": "pending", "model": "pending",
            "error": None, "attempts": 0,
            "created_at": _iso(now - timedelta(minutes=20)),
            # PII-ish fields that must NOT leak into the response:
            "prompt": "SECRET PROMPT", "watermarked_url": "x",
        },
        {
            "job_id": "job-fresh", "session_id": "sess-2", "store_id": "store-1",
            "tier": "preview", "status": "pending", "model": "pending",
            "error": None, "attempts": 0,
            "created_at": _iso(now - timedelta(seconds=30)),
        },
        {
            "job_id": "job-failed", "session_id": "sess-3", "store_id": "store-1",
            "tier": "edit", "status": "failed", "model": "pending",
            "error": "stalled: no response within 8 min", "attempts": 3,
            "created_at": _iso(now - timedelta(minutes=40)),
        },
        {
            "job_id": "job-done", "session_id": "sess-4", "store_id": "store-1",
            "tier": "preview", "status": "complete", "model": "gemini-3-pro-image",
            "error": None, "attempts": 1,
            "created_at": _iso(now - timedelta(minutes=5)),
        },
    ]


@pytest.fixture()
def admin_client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "test-secret-123")
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _patch_sb(monkeypatch, rows):
    from app.api.routes import admin_generations

    monkeypatch.setattr(admin_generations, "get_supabase", lambda: _FakeSB(rows))


_HDR = {"X-Admin-Secret": "test-secret-123"}


def test_rejects_missing_secret(admin_client):
    resp = admin_client.get("/admin/generations")
    assert resp.status_code in (401, 403)


def test_lists_jobs_newest_first_with_summary(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _rows())
    resp = admin_client.get("/admin/generations", headers=_HDR)
    assert resp.status_code == 200
    body = resp.json()

    # newest-first
    ages = [it["age_seconds"] for it in body["items"]]
    assert ages == sorted(ages)  # smallest age (newest) first
    # summary counts over the window
    assert body["summary"] == {"pending": 2, "stalled": 1, "failed": 1, "complete": 1}
    assert body["stuck_minutes"] == 8


def test_stalled_flag(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _rows())
    resp = admin_client.get("/admin/generations?stuck_minutes=8", headers=_HDR)
    items = {it["job_id"]: it for it in resp.json()["items"]}
    assert items["job-stuck"]["stalled"] is True     # pending, 20 min old
    assert items["job-fresh"]["stalled"] is False    # pending, 30s old
    assert items["job-failed"]["stalled"] is False   # not pending
    assert items["job-done"]["stalled"] is False


def test_status_filter(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _rows())
    resp = admin_client.get("/admin/generations?status=pending", headers=_HDR)
    body = resp.json()
    assert {it["status"] for it in body["items"]} == {"pending"}
    assert len(body["items"]) == 2


def test_no_pii_in_response(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _rows())
    resp = admin_client.get("/admin/generations", headers=_HDR)
    raw = resp.text
    assert "SECRET PROMPT" not in raw
    for it in resp.json()["items"]:
        assert "prompt" not in it
        assert "collected" not in it
