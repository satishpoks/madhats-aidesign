"""Tests for POST /chat/{session_id}/back.

Task 6: the route takes a `seq` (the checkpoint the customer tapped in the
Back menu) and delegates to `orchestrator_v2.handle_back(session_id, seq)`
(Task 5), which re-checks offerability server-side. This file only exercises
the route's request-model binding and its exception -> HTTP status mapping —
`handle_back`'s own behaviour (which seqs are offerable, carry-forward keys,
etc.) is covered in test_orchestrator_v2.py / test_checkpoints.py.

Uses the same `client` fixture shape as test_chat_route.py: a real
TestClient(app) so slowapi/FastAPI param binding runs for real, with
`handle_back_v2` monkeypatched directly so no Supabase round-trip is needed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import chat as chat_mod
from app.services.conversation import checkpoints as ck
from app.services.conversation.orchestrator import SessionNotFound


@pytest.fixture()
def client():
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_back_requires_a_seq(client):
    assert client.post("/chat/s1/back", json={}).status_code == 422


def test_back_returns_409_when_the_checkpoint_is_unavailable(client, monkeypatch):
    async def _boom(_sid, _seq):
        raise ck.CheckpointUnavailable("gone")
    monkeypatch.setattr(chat_mod, "handle_back_v2", _boom)
    assert client.post("/chat/s1/back", json={"seq": 3}).status_code == 409


def test_back_returns_404_for_an_unknown_session(client, monkeypatch):
    async def _missing(_sid, _seq):
        raise SessionNotFound("s1")
    monkeypatch.setattr(chat_mod, "handle_back_v2", _missing)
    assert client.post("/chat/s1/back", json={"seq": 1}).status_code == 404


def test_back_returns_200_and_the_restored_chat_response_on_success(client, monkeypatch):
    async def _ok(sid, seq):
        assert sid == "s1"
        assert seq == 2
        return {"reply": "Where should Logo 1 go?", "state": "logo_adjust", "data": {}}
    monkeypatch.setattr(chat_mod, "handle_back_v2", _ok)

    resp = client.post("/chat/s1/back", json={"seq": 2})

    assert resp.status_code == 200
    body = resp.json()
    assert body["reply"] == "Where should Logo 1 go?"
    assert body["state"] == "logo_adjust"
