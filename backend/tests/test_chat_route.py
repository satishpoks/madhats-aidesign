"""Regression test for POST /chat/{session_id}.

slowapi's @limiter.limit uses functools.wraps, which copies __annotations__
but not __globals__. If chat.py has `from __future__ import annotations`,
FastAPI resolves the handler's string annotations against slowapi's module
globals (where ChatRequest doesn't exist), so it can't bind `body` and every
real HTTP POST to this route returns 422. This test drives the route through
the actual FastAPI app + TestClient (not a direct function call) so it
reproduces the bug the way a real client would hit it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _FakeResult:
    data: list = []


class _FakeTable:
    def __init__(self, name):
        self.name = name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return _FakeResult()


class _FakeSupabase:
    def table(self, name):
        return _FakeTable(name)


@pytest.fixture()
def client(monkeypatch):
    from app.main import app
    from app.services.conversation import orchestrator

    # Avoid a real DB round-trip: session lookup returns no rows, which the
    # orchestrator turns into SessionNotFound -> 404. This isolates the test
    # to the thing we're actually regression-testing (param resolution),
    # not Supabase/network availability.
    monkeypatch.setattr(orchestrator, "get_supabase", lambda: _FakeSupabase())

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_chat_post_resolves_body_not_422(client):
    """A POST with a valid JSON body must not 422 on param resolution.

    The session id is bogus, so the handler should run and then raise
    SessionNotFound -> 404. A 422 here means FastAPI failed to bind `body`
    (the annotation-resolution bug), not that our payload was invalid.
    """
    resp = client.post("/chat/nonexistent-session-id", json={"message": "hi"})

    assert resp.status_code == 404
