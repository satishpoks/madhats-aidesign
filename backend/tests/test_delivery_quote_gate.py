"""Quote-gated sessions never receive the design by email (C2)."""
from __future__ import annotations

from app.services import delivery


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink = table, rows, sink
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
            self._sink.append((self._table, self._pending_update))
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: list = []

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


def test_maybe_send_preview_skips_quote_gated(monkeypatch):
    sent = []
    from app.services import email as email_service
    monkeypatch.setattr(email_service, "send_preview_email", lambda *a, **k: sent.append(a))
    fake = _FakeSB({
        "design_sessions": [{"id": "sess-1", "collected": {"quote_requested": True}}],
        "leads": [{"id": "lead-1", "session_id": "sess-1", "email_verified": True,
                   "preview_email_sent": False, "email": "a@b.com", "name": "Ann",
                   "created_at": "2026-07-24T00:00:00Z"}],
        "generations": [{"id": "g", "session_id": "sess-1", "status": "complete",
                         "image_url": "generations/clean.png", "created_at": "2026-07-24T00:00:00Z"}],
    })
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    assert delivery.maybe_send_preview("sess-1") is False
    assert sent == []


def test_send_final_design_skips_quote_gated(monkeypatch):
    # Everything a normal final-design send needs is present — a verified lead
    # with an address and two completed generations — so the ONLY reason this
    # can return False is the quote gate. Without the guard this test fails.
    fake = _FakeSB({
        "design_sessions": [{"id": "sess-1", "collected": {"quote_requested": True}}],
        "leads": [{"id": "lead-1", "session_id": "sess-1", "email": "a@b.com",
                   "email_verified": True, "final_email_sent": False,
                   "created_at": "2026-07-24T00:00:00Z"}],
    })
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "_completed_generations",
                        lambda sid: [{"image_url": "a"}, {"image_url": "b"}])
    delivered = []
    monkeypatch.setattr(delivery, "_deliver_final",
                        lambda lead, path: delivered.append(path) or True)
    assert delivery.send_final_design("sess-1") is False
    assert delivered == []


def test_send_final_design_still_sends_for_a_normal_session(monkeypatch):
    """The guard must not break the ordinary (non-quote-gated) flow."""
    fake = _FakeSB({
        "design_sessions": [{"id": "sess-1", "collected": {}}],
        "leads": [{"id": "lead-1", "session_id": "sess-1", "email": "a@b.com",
                   "email_verified": True, "final_email_sent": False,
                   "created_at": "2026-07-24T00:00:00Z"}],
    })
    monkeypatch.setattr(delivery, "get_supabase", lambda: fake)
    monkeypatch.setattr(delivery, "_completed_generations",
                        lambda sid: [{"image_url": "a"}, {"image_url": "b"}])
    delivered = []
    monkeypatch.setattr(delivery, "_deliver_final",
                        lambda lead, path: delivered.append(path) or True)
    assert delivery.send_final_design("sess-1") is True
    assert delivered == ["b"]
