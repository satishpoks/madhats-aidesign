"""Unit tests for the decoration_types service (supabase-py mocked)."""
from __future__ import annotations

from app.services import decoration_types as svc


class _FakeQuery:
    def __init__(self, store):
        self._store = store
        self._filters = {}
    def select(self, *_a):
        return self
    def eq(self, col, val):
        self._filters[col] = val
        return self
    def order(self, *_a, **_k):
        return self
    def execute(self):
        rows = [r for r in self._store if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": rows})()
    def insert(self, row):
        row = {"id": "d1", "sort_order": 0, "active": True, **row}
        self._store.append(row)
        self._pending = [row]
        return self
    def delete(self):
        self._delete = True
        return self


class _FakeSB:
    def __init__(self, store):
        self._store = store
    def table(self, _name):
        return _FakeQuery(self._store)


def test_list_active_only(monkeypatch):
    store = [
        {"id": "a", "store_id": "s1", "name": "Embroidery", "active": True},
        {"id": "b", "store_id": "s1", "name": "Old", "active": False},
    ]
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSB(store))
    rows = svc.list_types("s1", active_only=True)
    assert [r["name"] for r in rows] == ["Embroidery"]


def test_list_all(monkeypatch):
    store = [
        {"id": "a", "store_id": "s1", "name": "Embroidery", "active": True},
        {"id": "b", "store_id": "s1", "name": "Old", "active": False},
    ]
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSB(store))
    assert len(svc.list_types("s1")) == 2
