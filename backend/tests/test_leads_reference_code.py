"""MH-XXXXXX tracking reference generation + collision-checked assignment."""
from __future__ import annotations

import re

from app.services import leads as leads_service


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
            self._sink.append(self._pending_update)
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows
        self.sink: list = []

    def table(self, name):
        return _Query(name, self._rows, self.sink)


def test_generate_reference_code_shape():
    for _ in range(200):
        code = leads_service.generate_reference_code()
        assert re.fullmatch(r"MH-[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{6}", code), code
        # ambiguous glyphs never appear
        assert not (set("O0I1") & set(code[3:]))


def test_assign_reference_code_avoids_collision(monkeypatch):
    fake = _FakeSB([{"id": "lead-1", "reference_code": None},
                    {"id": "other", "reference_code": "MH-AAAAAA"}])
    # First candidate collides with the existing row; second is free.
    seq = iter(["MH-AAAAAA", "MH-BCDFGH"])
    monkeypatch.setattr(leads_service, "generate_reference_code", lambda: next(seq))
    code = leads_service.assign_reference_code(fake, "lead-1")
    assert code == "MH-BCDFGH"
    assert fake.sink == [{"reference_code": "MH-BCDFGH"}]


def test_record_quote_request_marks_lead_and_returns_code(monkeypatch):
    rows = [{"id": "lead-1", "session_id": "sess-1", "reference_code": None,
             "created_at": "2026-07-24T00:00:00Z"}]
    fake = _FakeSB(rows)
    monkeypatch.setattr(leads_service, "get_supabase", lambda: fake)
    monkeypatch.setattr(leads_service, "generate_reference_code", lambda: "MH-BCDFGH")
    # Converge call is best-effort; stub it so this test stays about recording.
    calls = []
    import app.services.delivery as delivery
    monkeypatch.setattr(delivery, "maybe_send_quote_confirmation",
                        lambda sid: calls.append(sid), raising=False)

    code = leads_service.record_quote_request({"id": "sess-1"}, {})
    assert code == "MH-BCDFGH"
    assert rows[0]["reference_code"] == "MH-BCDFGH"
    assert rows[0]["quote_requested"] is True
    assert rows[0]["quote_requested_at"]
    assert calls == ["sess-1"]


def test_record_quote_request_no_lead_returns_none(monkeypatch):
    fake = _FakeSB([])
    monkeypatch.setattr(leads_service, "get_supabase", lambda: fake)
    assert leads_service.record_quote_request({"id": "missing"}, {}) is None
