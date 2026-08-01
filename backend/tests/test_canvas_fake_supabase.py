"""Regression guard for `tests/canvas_fake_supabase.py`'s own shape.

`test_checkpoints.py::test_fake_table_rejects_filters_before_a_verb` guards
THAT file's own (separate) fake — it says nothing about this shared module,
which four test files now import (`test_orchestrator_v2.py`, `test_v2_e2e.py`,
`test_v2_bg_autodetect.py`, `test_chat_route.py`). Without a guard here, a
future contributor "fixing" a test by adding `.eq(...)` directly to
`FakeTable` (rather than chaining it off the verb's return value) would
silently restore the exact Task 4 regression — a call order
(`.eq(...).gt(...).update(...)`) that raises `AttributeError` against the
real postgrest client — except now with 4x the blast radius, since every
importer would inherit the same permissive shape without a single failing
test anywhere.
"""
import pytest

from tests.canvas_fake_supabase import FakeSB


def test_fake_table_rejects_filters_before_a_verb():
    table = FakeSB({"session": {"id": "s1"}}).table("session_checkpoints")
    with pytest.raises(AttributeError):
        table.eq("session_id", "s1")
    with pytest.raises(AttributeError):
        table.gt("seq", 1)
    with pytest.raises(AttributeError):
        table.execute()
