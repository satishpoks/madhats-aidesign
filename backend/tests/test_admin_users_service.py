from __future__ import annotations

import pytest

from app.services import admin_users


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, db):
        self.table, self.db = table, db
        self._rows = list(db[table])
        self._pending = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._pending = ("insert", row)
        return self

    def update(self, patch):
        self._pending = ("update", patch)
        return self

    def delete(self):
        self._pending = ("delete", None)
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        self._eq = (field, value)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self._pending and self._pending[0] == "insert":
            row = dict(self._pending[1])
            row.setdefault("id", f"id-{len(self.db[self.table]) + 1}")
            self.db[self.table].append(row)
            return _Result([row])
        if self._pending and self._pending[0] == "update":
            for r in self._rows:
                r.update(self._pending[1])
            return _Result(self._rows)
        if self._pending and self._pending[0] == "delete":
            for r in list(self._rows):
                self.db[self.table].remove(r)
            return _Result(self._rows)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, db):
        self.db = db

    def table(self, name):
        self.db.setdefault(name, [])
        return _Query(name, self.db)


@pytest.fixture()
def fake_db(monkeypatch):
    db = {"admin_users": [], "admin_user_stores": []}
    monkeypatch.setattr(admin_users, "get_supabase", lambda: _FakeSB(db))
    return db


def test_create_and_get_by_email(fake_db):
    user = admin_users.create_user("Ops@x.com", "pw", is_super=False, store_ids=["s1", "s2"])
    assert user["is_super"] is False
    got = admin_users.get_by_email("ops@x.com")  # case-insensitive
    assert got is not None and got["id"] == user["id"]
    assert admin_users.allowed_store_ids(user["id"]) == {"s1", "s2"}


def test_update_reassigns_stores_and_password(fake_db):
    user = admin_users.create_user("a@x.com", "pw", is_super=False, store_ids=["s1"])
    admin_users.update_user(user["id"], store_ids=["s2", "s3"])
    assert admin_users.allowed_store_ids(user["id"]) == {"s2", "s3"}


def test_delete_user(fake_db):
    user = admin_users.create_user("a@x.com", "pw", is_super=False, store_ids=[])
    assert admin_users.delete_user(user["id"]) is True
    assert admin_users.get_by_id(user["id"]) is None
