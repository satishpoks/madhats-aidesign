"""generation_cache.lookup() — cache-hit selection.

The cache key is derived only from product/colour/prompt/asset, NOT the active
provider. A stub result (placehold.co placeholder) written while the provider
was `stub` must never be served as a cache hit after switching to a real
provider, otherwise the real generation never runs and every email ships the
placeholder. lookup() therefore excludes model='stub' rows.
"""
from __future__ import annotations

from app.services import generation_cache


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable supabase-py table stand-in supporting eq/neq/order/limit."""

    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def neq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) != value]
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
        return _Query(list(self._rows))


def test_lookup_ignores_stub_placeholder(monkeypatch):
    key = "cache-key-1"
    rows = [
        {
            "prompt_hash": key,
            "status": "complete",
            "model": "stub",
            "image_url": "https://placehold.co/800x600/png",
            "created_at": "2026-07-01T00:00:00Z",
        }
    ]
    monkeypatch.setattr(generation_cache, "get_supabase", lambda: _FakeSB(rows))
    assert generation_cache.lookup(key) is None


def test_lookup_returns_real_generation(monkeypatch):
    key = "cache-key-2"
    rows = [
        {
            "prompt_hash": key,
            "status": "complete",
            "model": "gemini-2.5-flash-image",
            "image_url": "generated/preview/abc.png",
            "created_at": "2026-07-01T01:00:00Z",
        }
    ]
    monkeypatch.setattr(generation_cache, "get_supabase", lambda: _FakeSB(rows))
    hit = generation_cache.lookup(key)
    assert hit is not None
    assert hit["image_url"] == "generated/preview/abc.png"


def test_lookup_prefers_real_over_stub_for_same_key(monkeypatch):
    key = "cache-key-3"
    rows = [
        {
            "prompt_hash": key,
            "status": "complete",
            "model": "stub",
            "image_url": "https://placehold.co/800x600/png",
            "created_at": "2026-07-01T02:00:00Z",  # newer, but a placeholder
        },
        {
            "prompt_hash": key,
            "status": "complete",
            "model": "gemini-2.5-flash-image",
            "image_url": "generated/preview/real.png",
            "created_at": "2026-07-01T00:00:00Z",
        },
    ]
    monkeypatch.setattr(generation_cache, "get_supabase", lambda: _FakeSB(rows))
    hit = generation_cache.lookup(key)
    assert hit is not None
    assert hit["model"] == "gemini-2.5-flash-image"
