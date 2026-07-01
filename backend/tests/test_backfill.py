"""delivery.backfill_pending() + POST /admin/deliveries/backfill.

Self-heal sweep: re-attempts delivery for verified leads whose preview email
never sent (e.g. a Resend outage at the moment both async tracks — generation
completion and email verification — had already fired). Safe to run
repeatedly: maybe_send_preview is idempotent, so an already-delivered lead is
never re-sent.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services import delivery


# ---------------------------------------------------------------------------
# Fake supabase-py builder — adds `.gte()` on top of the eq/order/limit chain
# used elsewhere in this test suite (see tests/test_delivery.py).
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows, captured_filters):
        self._rows = rows
        self._captured = captured_filters

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._captured.append(("eq", field, value))
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def gte(self, field, value):
        self._captured.append(("gte", field, value))
        self._rows = [r for r in self._rows if (r.get(field) or "") >= value]
        return self

    def order(self, field, desc=False, **k):
        self._captured.append(("order", field, desc))
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._captured.append(("limit", n))
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows
        self.captured_filters: list = []

    def table(self, name):
        assert name == "leads"
        return _Query(list(self._rows), self.captured_filters)


def _lead(**overrides):
    row = {
        "id": "lead-1",
        "session_id": "sess-1",
        "email_verified": True,
        "preview_email_sent": False,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }
    row.update(overrides)
    return row


def test_backfill_calls_maybe_send_preview_for_pending_lead(monkeypatch):
    lead = _lead(session_id="sess-1")
    fake = _FakeSB([lead])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)

    calls = []

    def _fake_send(session_id):
        calls.append(session_id)
        return True

    monkeypatch.setattr(delivery, "maybe_send_preview", _fake_send)

    result = delivery.backfill_pending()

    assert calls == ["sess-1"]
    assert result == {"scanned": 1, "delivered": 1, "still_pending": 0}


def test_backfill_excludes_already_sent_lead(monkeypatch):
    """The query itself filters out preview_email_sent=true rows — the fake
    DB never returns them, so maybe_send_preview is never called for them."""
    sent_lead = _lead(session_id="sess-sent", preview_email_sent=True)
    pending_lead = _lead(session_id="sess-pending", preview_email_sent=False)
    fake = _FakeSB([sent_lead, pending_lead])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)

    calls = []
    monkeypatch.setattr(delivery, "maybe_send_preview", lambda sid: calls.append(sid) or True)

    delivery.backfill_pending()

    assert calls == ["sess-pending"]
    assert ("eq", "preview_email_sent", False) in fake.captured_filters


def test_backfill_excludes_over_age_lead(monkeypatch):
    """A lead verified more than max_age_hours ago must be excluded by the
    .gte('verified_at', cutoff) filter and therefore never processed."""
    now = datetime.now(timezone.utc)
    fresh = _lead(session_id="sess-fresh", verified_at=now.isoformat())
    stale = _lead(session_id="sess-stale", verified_at=(now - timedelta(hours=200)).isoformat())
    fake = _FakeSB([fresh, stale])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)

    calls = []
    monkeypatch.setattr(delivery, "maybe_send_preview", lambda sid: calls.append(sid) or True)

    delivery.backfill_pending(max_age_hours=72)

    assert calls == ["sess-fresh"]
    gte_calls = [f for f in fake.captured_filters if f[0] == "gte" and f[1] == "verified_at"]
    assert len(gte_calls) == 1


def test_backfill_counts_still_pending_when_send_returns_false(monkeypatch):
    lead = _lead(session_id="sess-1")
    fake = _FakeSB([lead])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "maybe_send_preview", lambda sid: False)

    result = delivery.backfill_pending()

    assert result == {"scanned": 1, "delivered": 0, "still_pending": 1}
    # backfill_pending itself never flips the flag — that's maybe_send_preview's job.
    assert lead["preview_email_sent"] is False


def test_backfill_one_failure_does_not_abort_sweep(monkeypatch):
    now = datetime.now(timezone.utc)
    lead_a = _lead(session_id="sess-a", verified_at=now.isoformat())
    lead_b = _lead(session_id="sess-b", verified_at=(now - timedelta(seconds=1)).isoformat())
    fake = _FakeSB([lead_a, lead_b])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)

    calls = []

    def _fake_send(session_id):
        calls.append(session_id)
        if session_id == "sess-a":
            raise RuntimeError("boom")
        return True

    monkeypatch.setattr(delivery, "maybe_send_preview", _fake_send)

    result = delivery.backfill_pending()

    # Order isn't the point here — both rows must be processed despite the
    # first one raising.
    assert set(calls) == {"sess-a", "sess-b"}
    assert result == {"scanned": 2, "delivered": 1, "still_pending": 1}


def test_backfill_respects_limit(monkeypatch):
    fake = _FakeSB([_lead(session_id="sess-1")])
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "maybe_send_preview", lambda sid: True)

    delivery.backfill_pending(limit=7)

    assert ("limit", 7) in fake.captured_filters


# ---------------------------------------------------------------------------
# Route: POST /admin/deliveries/backfill
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "test-secret-123")
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def test_backfill_route_rejects_missing_secret(admin_client):
    resp = admin_client.post("/admin/deliveries/backfill")
    assert resp.status_code in (401, 403)


def test_backfill_route_rejects_wrong_secret(admin_client):
    resp = admin_client.post(
        "/admin/deliveries/backfill", headers={"X-Admin-Secret": "nope"}
    )
    assert resp.status_code in (401, 403)


def test_backfill_route_returns_tally_with_correct_secret(admin_client, monkeypatch):
    from app.services import delivery as delivery_mod

    monkeypatch.setattr(
        delivery_mod,
        "backfill_pending",
        lambda limit=100, max_age_hours=72: {"scanned": 3, "delivered": 2, "still_pending": 1},
    )

    resp = admin_client.post(
        "/admin/deliveries/backfill",
        headers={"X-Admin-Secret": "test-secret-123"},
    )

    assert resp.status_code == 200
    assert resp.json() == {"scanned": 3, "delivered": 2, "still_pending": 1}


def test_backfill_route_passes_query_params(admin_client, monkeypatch):
    from app.api.routes import admin_deliveries

    captured = {}

    def _fake(limit=100, max_age_hours=72):
        captured["limit"] = limit
        captured["max_age_hours"] = max_age_hours
        return {"scanned": 0, "delivered": 0, "still_pending": 0}

    monkeypatch.setattr(admin_deliveries.delivery, "backfill_pending", _fake)

    resp = admin_client.post(
        "/admin/deliveries/backfill?limit=5&max_age_hours=24",
        headers={"X-Admin-Secret": "test-secret-123"},
    )

    assert resp.status_code == 200
    assert captured == {"limit": 5, "max_age_hours": 24}
