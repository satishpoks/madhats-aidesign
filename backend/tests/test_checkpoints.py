import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import checkpoints as cp
from app.services.conversation.state_machine import ConversationState as S


class _FakeSB:
    """Records inserts/updates so tests can assert on what was written.
    `rows` is the session_checkpoints table; `chat` the chat_messages table."""

    def __init__(self, rows=None, chat=None, session=None):
        self.rows = rows if rows is not None else []
        self.chat = chat if chat is not None else []
        self.session = session or {"id": "s1", "collected": {}}
        self.updates = []

    def table(self, name):
        return _FakeTable(self, name)


class _FakeTable:
    """Mirrors postgrest's two-stage builder shape: `sb.table(...)` alone
    exposes only verbs (select/insert/update) — no filter methods at all,
    matching the real `SyncRequestBuilder`. `.eq`/`.gt`/`.is_`/`.order`/
    `.limit`/`.execute` exist only on the builder a verb returns
    (`SyncFilterRequestBuilder`).

    This two-stage split is load-bearing, not decoration: an earlier version
    of this fake put every method on one object, so it silently ACCEPTED
    `.eq(...).gt(...).update(...)` — a call order that raises `AttributeError`
    against the real client, since `sb.table(...)` has no `.eq` to call in
    the first place. That bug shipped past every test in this file. See
    `test_fake_table_rejects_filters_before_a_verb` below, which pins the
    shape rather than any one call site.
    """

    def __init__(self, sb, name):
        self.sb, self.name = sb, name

    def select(self, *a, **k):
        return _FakeQuery(self.sb, self.name, verb="select")

    def update(self, patch):
        return _FakeQuery(self.sb, self.name, verb="update", payload=patch)

    def insert(self, rows):
        return _FakeQuery(self.sb, self.name, verb="insert", payload=rows)


class _FakeQuery:
    """The filter-capable builder returned once a verb has been chosen.

    Filters accumulate here and are resolved at `.execute()` time — not when
    the verb method was called — because the real call order chains filters
    AFTER the verb (`.update(patch).eq(...).gt(...)`). Applying the patch
    inside `update()` itself, before any filter has been chained on, would
    see an empty filter set; that mistake is what let the original
    verb-order bug slip through (see `_FakeTable`'s docstring).
    """

    def __init__(self, sb, name, verb, payload=None):
        self.sb, self.name, self.verb, self.payload = sb, name, verb, payload
        self.f = {}
        self._gt = None

    def eq(self, col, val):
        self.f[col] = val
        return self

    def is_(self, col, val):
        self.f[col] = val
        return self

    def gt(self, col, val):
        self._gt = (col, val)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self.verb == "insert":
            target = self.sb.rows if self.name == "session_checkpoints" else self.sb.chat
            rows = self.payload if isinstance(self.payload, list) else [self.payload]
            target.extend(rows)
            return type("R", (), {"data": rows})()

        if self.verb == "update":
            self.sb.updates.append((self.name, dict(self.f), self._gt, self.payload))
            if self.name == "session_checkpoints":
                for r in self.sb.rows:
                    if self._gt and r["seq"] > self._gt[1]:
                        r.update(self.payload)
                    elif not self._gt and "seq" in self.f and r["seq"] == self.f["seq"]:
                        r.update(self.payload)
            if self.name == "design_sessions":
                self.sb.session.update(self.payload)
            return type("R", (), {"data": []})()

        # select
        if self.name == "session_checkpoints":
            data = [r for r in self.sb.rows
                    if r.get("superseded_at") is None or "superseded_at" not in self.f]
            if "seq" in self.f:
                data = [r for r in data if r["seq"] == self.f["seq"]]
            return type("R", (), {"data": data})()
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.sb.session]})()
        return type("R", (), {"data": self.sb.chat})()


def test_capture_writes_one_row_with_the_rendered_label():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_NAME), S.GREETING, {"flow_mode": "canvas"}, None)
    assert len(sb.rows) == 1
    assert sb.rows[0]["kind"] == "name"
    assert sb.rows[0]["step_id"] == S.ASK_NAME.value
    assert sb.rows[0]["seq"] == 1


def test_re_rendering_the_same_step_captures_nothing():
    """A stall, a retry, a blank turn and an abuse decline all re-render the
    CURRENT step. Capture keys on ENTERING a step from a different one, so none
    of them writes a second row."""
    sb = _FakeSB()
    for _ in range(3):
        cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT),
                   S.ASK_LOGO_PLACEMENT, {"logos": []}, None)
    assert sb.rows == []


def test_a_second_loop_pass_captures_its_own_row():
    """Re-entering the same opener from elsewhere in the loop IS a new pass.
    This is why capture keys on the transition rather than on a loop index
    derived from `collected` — the decor loop banks no collection to count."""
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT), S.ASK_HAS_LOGO,
               {"logos": []}, None)
    cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT), S.ASK_ANOTHER_LOGO,
               {"logos": [{"face": "front"}]}, None)
    assert [r["seq"] for r in sb.rows] == [1, 2]


def test_a_second_decor_pass_captures_its_own_row():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_ADD_DECOR), S.ASK_ANOTHER_LOGO, {}, None)
    cp.capture(sb, "s1", cs.by_id(S.ASK_ADD_DECOR), S.ASK_ANYTHING_ELSE, {}, None)
    assert [r["seq"] for r in sb.rows] == [1, 2]


def test_a_step_with_no_checkpoint_captures_nothing():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.LOGO_ADJUST), S.ASK_LOGO_PLACEMENT, {}, None)
    assert sb.rows == []


def test_capture_stores_the_canvas_blob_verbatim():
    sb = _FakeSB()
    design = {"colourway": "navy", "faces": {"front": [{"id": "e1"}]}}
    cp.capture(sb, "s1", cs.by_id(S.ASK_QUANTITY), S.ASK_ANYTHING_ELSE, {}, design)
    assert sb.rows[0]["canvas_design"] == design


def test_restore_replaces_collected_rather_than_merging():
    snap = {"name": "Satish", "logos": []}
    sb = _FakeSB(rows=[{"seq": 1, "kind": "name", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": snap,
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": None}])
    row = cp.restore(sb, "s1", 1, {"name": "Satish", "logos": [{"face": "front"}],
                                   "quantity": 50})
    assert row["collected"]["logos"] == []
    assert "quantity" not in row["collected"]


def test_restore_carries_forward_the_out_of_band_commit_flags():
    """The single most important correctness rule: a snapshot taken BEFORE the
    email step predates verification, and email_verified is written out of band
    by an emailed link click. A plain replacement would un-verify the customer.
    """
    snap = {"name": "Satish"}
    sb = _FakeSB(rows=[{"seq": 1, "kind": "name", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": snap,
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": None}])
    live = {"name": "Satish", "email_captured": True, "email_verified": True,
            "lead_id": "L1"}
    row = cp.restore(sb, "s1", 1, live)
    for key in ("email_captured", "email_verified", "lead_id"):
        assert row["collected"][key] == live[key], key


def test_carry_forward_keys_cover_every_out_of_band_write():
    assert cp.CARRY_FORWARD_KEYS == frozenset({
        "email_captured", "email_verified", "lead_id",
        "quote_requested", "reference_code"})


def test_restore_supersedes_later_checkpoints_without_deleting_them():
    rows = [{"seq": n, "kind": "k", "label": "L", "step_id": S.ASK_NAME.value,
             "collected": {}, "canvas_design": None, "chat_watermark": None,
             "superseded_at": None} for n in (1, 2, 3)]
    sb = _FakeSB(rows=rows)
    cp.restore(sb, "s1", 1, {})
    assert len(sb.rows) == 3                       # nothing deleted
    assert sb.rows[0]["superseded_at"] is None
    assert sb.rows[1]["superseded_at"] is not None
    assert sb.rows[2]["superseded_at"] is not None


def test_restore_supersedes_chat_rows_after_the_watermark():
    sb = _FakeSB(rows=[{"seq": 1, "kind": "k", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": {},
                        "canvas_design": None, "chat_watermark": "m7",
                        "superseded_at": None}])
    cp.restore(sb, "s1", 1, {})
    chat_updates = [u for u in sb.updates if u[0] == "chat_messages"]
    assert chat_updates, "chat rows after the watermark must be superseded"
    assert chat_updates[0][3].get("superseded_at") is not None


def test_restoring_an_unknown_seq_returns_none():
    assert cp.restore(_FakeSB(), "s1", 99, {}) is None


def test_seq_never_reuses_a_superseded_number():
    """After a restore supersedes rows 2-3, the next capture must be seq 4, not
    seq 2 — the (session_id, seq) unique index covers superseded rows too."""
    rows = [{"seq": n, "kind": "k", "label": "L", "step_id": S.ASK_NAME.value,
             "collected": {}, "canvas_design": None, "chat_watermark": None,
             "superseded_at": None} for n in (1, 2, 3)]
    sb = _FakeSB(rows=rows)
    cp.restore(sb, "s1", 1, {})
    cp.capture(sb, "s1", cs.by_id(S.ASK_QUANTITY), S.ASK_ANYTHING_ELSE, {}, None)
    assert sb.rows[-1]["seq"] == 4


def test_restoring_an_already_superseded_seq_returns_none():
    sb = _FakeSB(rows=[{"seq": 1, "kind": "k", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": {},
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": "2026-08-01T00:00:00Z"}])
    assert cp.restore(sb, "s1", 1, {}) is None


def test_fake_table_rejects_filters_before_a_verb():
    """Regression guard for a real runtime break, not a style nit.

    `sb.table(...)` returns postgrest's `SyncRequestBuilder`, which has no
    filter methods at all — `.eq`/`.gt`/`.is_` only exist on the builder a
    verb (select/insert/update) returns. A production call like
    `.eq(...).gt(...).update(...)` type-checks against a permissive fake but
    raises `AttributeError` against the real client. This test pins the
    fake's shape so that mistake can't ship silently again: if `checkpoints.py`
    ever calls a filter directly on the bare table object, THIS is the test
    that fails, not a subtler one three asserts downstream.
    """
    sb = _FakeSB()
    table = sb.table("session_checkpoints")
    with pytest.raises(AttributeError):
        table.eq("session_id", "s1")
    with pytest.raises(AttributeError):
        table.gt("seq", 1)
    with pytest.raises(AttributeError):
        table.execute()
