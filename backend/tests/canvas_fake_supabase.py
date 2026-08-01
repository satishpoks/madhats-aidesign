"""A minimal two-stage fake mirroring postgrest's real builder split, shared by
the v2 canvas orchestrator tests that need `design_sessions` + `chat_messages`
+ `session_checkpoints` behind one in-memory `store` dict.

Verb-first, deliberately: `sb.table(name)` returns an object exposing ONLY
verb methods (select/insert/update) — no filter methods at all — matching the
real postgrest `SyncRequestBuilder`. Filters (`eq`/`is_`/`gt`/`order`/`limit`)
chain off the verb's return value (`SyncFilterRequestBuilder`), which is where
they live in the real client. An earlier version of this fake (in
`test_orchestrator_v2.py`, before Task 5) put every method on one object, so it
silently ACCEPTED `.eq(...).gt(...).update(...)` — a call order that raises
`AttributeError` against the real client. See
`test_checkpoints.py::test_fake_table_rejects_filters_before_a_verb`, which
pins this shape against that exact regression (Task 4). This module is shared
(rather than duplicated per test file) so the shape can't drift between copies
— the drift itself was Task 4's cross-task warning to Task 5.

`store` shape: {"session": {...}, "rows": [...chat rows...],
"checkpoints": [...session_checkpoints rows...]}. "session" is a single dict
(one design session per test); the other two are lists, created lazily.
"""
from __future__ import annotations

import copy

_TABLE_KEYS = {"chat_messages": "rows", "session_checkpoints": "checkpoints"}


class FakeSB:
    def __init__(self, store: dict):
        self.store = store

    def table(self, name: str) -> "FakeTable":
        return FakeTable(self.store, name)


class FakeTable:
    """`sb.table(...)` — verbs only, no filters. See module docstring."""

    def __init__(self, store: dict, name: str):
        self.store, self.name = store, name

    def select(self, *_a, **_k) -> "FakeQuery":
        return FakeQuery(self.store, self.name, "select")

    def update(self, patch: dict) -> "FakeQuery":
        return FakeQuery(self.store, self.name, "update", patch)

    def insert(self, rows) -> "FakeQuery":
        return FakeQuery(self.store, self.name, "insert", rows)


class FakeQuery:
    """The filter-capable builder a verb returns. Filters accumulate here and
    are resolved at `.execute()` time, matching the real client's chaining
    order (`.update(patch).eq(...).gt(...)`)."""

    def __init__(self, store: dict, name: str, verb: str, payload=None):
        self.store, self.name, self.verb, self.payload = store, name, verb, payload
        self._eq: dict = {}
        self._gt = None
        self._is_null: set[str] = set()
        self._order = None
        self._limit = None

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def is_(self, col, val):
        if val in (None, "null"):
            self._is_null.add(col)
        else:
            self._eq[col] = val
        return self

    def gt(self, col, val):
        self._gt = (col, val)
        return self

    def order(self, col, desc: bool = False, **_k):
        self._order = (col, desc)
        return self

    def limit(self, n=None, *_a, **_k):
        self._limit = n
        return self

    def _matches(self, row: dict) -> bool:
        for col, val in self._eq.items():
            if row.get(col) != val:
                return False
        if self._gt is not None:
            col, val = self._gt
            cur = row.get(col)
            if cur is None or not (cur > val):
                return False
        for col in self._is_null:
            if row.get(col) is not None:
                return False
        return True

    def _list(self) -> list:
        key = _TABLE_KEYS.get(self.name, self.name)
        return self.store.setdefault(key, [])

    def execute(self):
        if self.name == "design_sessions":
            return self._execute_session()

        rows = self._list()
        if self.verb == "insert":
            # Deep-copy the payload: `checkpoints.capture` inserts the LIVE
            # session `collected` dict as a row's "collected" column. Without
            # this, the fake stores a reference rather than a snapshot, so a
            # later in-place mutation of the live session (every turn does
            # `collected.update(...)`) would retroactively change the
            # "captured" row too — the real Postgres round-trip never aliases
            # like this, and a capture/restore test could pass by accident
            # (`restored == live`) with nothing actually snapshotted.
            new_rows = [copy.deepcopy(r) for r in (
                self.payload if isinstance(self.payload, list) else [self.payload])]
            if self.name == "chat_messages":
                # Real chat rows carry a DB-assigned id + created_at, which the
                # checkpoint watermark (capture/restore) reads. Orchestrator
                # code never sets these itself, so synthesize monotonically
                # increasing values here — exact values don't matter, only
                # uniqueness and ordering.
                for r in new_rows:
                    n = self.store["_clock"] = self.store.get("_clock", 0) + 1
                    r.setdefault("id", f"m{n}")
                    r.setdefault("created_at", f"{n:06d}")
            rows.extend(new_rows)
            return _Result(new_rows)

        matched = [r for r in rows if self._matches(r)]
        if self.verb == "update":
            for r in matched:
                r.update(self.payload)
            return _Result(matched)

        # select
        if self._order:
            col, desc = self._order
            matched = sorted(matched, key=lambda r: r.get(col), reverse=desc)
        if self._limit is not None:
            matched = matched[: self._limit]
        return _Result(matched)

    def _execute_session(self):
        session = self.store["session"]
        if self.verb == "select":
            return _Result([session])
        if self.verb == "update":
            session.update(self.payload)
            return _Result([session])
        # insert: not used by any current caller, but handled for completeness.
        self.store["session"] = (
            self.payload if not isinstance(self.payload, list) else self.payload[0])
        return _Result([self.store["session"]])


class _Result:
    def __init__(self, data):
        self.data = data
