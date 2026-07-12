# backend/tests/test_hat_types_service.py
from app.services import hat_types


class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows, store):
        self._rows, self._store = rows, store
        self._insert = None
        self._update = None
    def select(self, *a, **k): return self
    def eq(self, f, v):
        self._rows = [r for r in self._rows if r.get(f) == v]; return self
    def order(self, *a, **k): return self
    def limit(self, n):
        self._rows = self._rows[:n]; return self
    def insert(self, row):
        self._insert = {**row, "id": "new-id"}; return self
    def update(self, patch):
        self._update = patch; return self
    def execute(self):
        if self._insert is not None: return _Result([self._insert])
        if self._update is not None:
            for r in self._rows: r.update(self._update)
            return _Result(self._rows)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows): self._rows = rows
    def table(self, name): return _Query(list(self._rows), None)


def test_all_angles_present():
    assert hat_types.all_angles_present({"blank_view_images": {
        "front": "a", "back": "b", "left": "c", "right": "d"}}) is True
    assert hat_types.all_angles_present({"blank_view_images": {"front": "a"}}) is False


def test_list_active_only_filters(monkeypatch):
    # NOTE: brief's fixture omitted "store_id" on the rows, which meant the
    # service's real (and correct) `.eq("store_id", ...)` scoping filter
    # zeroed out every row before `active_only` was ever applied — the test
    # could not actually exercise what it claims to. Rows are scoped to
    # "store-1" here so the active_only filter is the thing under test.
    rows = [
        {"id": "1", "active": True, "store_id": "store-1"},
        {"id": "2", "active": False, "store_id": "store-1"},
    ]
    monkeypatch.setattr(hat_types, "get_supabase", lambda: _FakeSB(rows))
    out = hat_types.list_hat_types("store-1", active_only=True)
    assert [r["id"] for r in out] == ["1"]
