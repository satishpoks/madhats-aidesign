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


# --- Task 4 fix round 1: severe-abuse moderation short-circuit (route level) --
#
# `check_text` runs BEFORE `_dispatch` and raises a 422 on flagged content —
# for a v2 canvas session that pre-empts `handle_message_v2`'s own decline
# guard (tested at the orchestrator layer in test_orchestrator_v2.py), so a
# real slur never reaches it and the customer sees an error banner instead of
# the graceful decline. These tests drive the real POST /chat/{session_id}
# route (not handle_message directly) to prove the fix at the layer the
# customer actually hits.

class _StatefulTable:
    """A `_FakeTable` that persists writes back onto a shared `store` dict,
    mirroring the pattern in tests/test_orchestrator_v2.py so the real
    orchestrator_v2.handle_message can run end-to-end against it."""

    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        return self


class _StatefulSupabase:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _StatefulTable(self.store, name)


def _canvas_store():
    return {
        "session": {
            "id": "s1",
            "state": "ask_quantity",
            "collected": {
                "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                "has_logo": True, "logos_done": True,
                "logos": [{"face": "front", "placed": True}],
                "decor_done": True,
            },
        }
    }


def _tail_state_canvas_store():
    """A v2 canvas session resting in a SHARED TAIL state (post-design).

    `offer_refine` is not in V2_OWNED, so orchestrator_v2 delegates the turn to
    v1 before ever reaching its decline guard — which is why the moderation
    bypass must not fire here.
    """
    store = _canvas_store()
    store["session"]["state"] = "offer_refine"
    return store


def _v1_store():
    return {
        "session": {
            "id": "s1",
            "state": "ask_quantity",
            "collected": {"flow_mode": "session", "name": "Sam"},
        }
    }


@pytest.fixture()
def moderation_client(monkeypatch):
    from app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_v2_canvas_session_severe_message_bypasses_moderation(monkeypatch, moderation_client):
    """A v2 canvas session sending a severe message gets a normal 200 decline
    reply, not a 422 — and check_text is never called."""
    from app import prompts
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.conversation import orchestrator_v2 as o2

    store = _canvas_store()
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(o2, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    async def _boom(*_a, **_k):
        raise AssertionError("check_text must not be called on a v2 severe short-circuit")
    monkeypatch.setattr(chat_route, "check_text", _boom)

    resp = moderation_client.post("/chat/s1", json={"message": "you are a <slur>"})

    assert resp.status_code == 200
    body = resp.json()
    assert prompts.V2_ABUSE_DECLINE in body["reply"]
    assert body["state"] == "ask_quantity"
    assert "quantity" not in store["session"]["collected"]


def test_v1_session_severe_message_still_422(monkeypatch, moderation_client):
    """A non-canvas (v1) session with the same severe message must still go
    through check_text and still 422 — v1 has no decline guard."""
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.moderation import ModerationError

    store = _v1_store()
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    calls = []

    async def _flag(_text):
        calls.append(1)
        raise ModerationError("flagged by content safety filter")
    monkeypatch.setattr(chat_route, "check_text", _flag)

    resp = moderation_client.post("/chat/s1", json={"message": "you are a <slur>"})

    assert resp.status_code == 422
    assert calls == [1]


def test_v2_canvas_session_non_severe_content_still_moderated(monkeypatch, moderation_client):
    """The short-circuit is narrow: content our own scanner calls clean/mild
    (e.g. graphic violence, sexual content — outside our word list) must still
    reach check_text and still 422, even on a v2 canvas session."""
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.moderation import ModerationError

    store = _canvas_store()
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "clean")

    calls = []

    async def _flag(_text):
        calls.append(1)
        raise ModerationError("flagged by content safety filter")
    monkeypatch.setattr(chat_route, "check_text", _flag)

    resp = moderation_client.post("/chat/s1", json={"message": "graphic content"})

    assert resp.status_code == 422
    assert calls == [1]


def test_v2_canvas_session_in_a_shared_tail_state_is_still_moderated(monkeypatch, moderation_client):
    """C1 (security regression): the bypass was keyed on flow_mode alone.

    `orchestrator_v2.handle_message` delegates any state outside `V2_OWNED`
    straight to v1 BEFORE its decline guard, so at every post-design tail state
    (offer_refine, describe_changes, verify_email, generating, quote_requested)
    a severe message both skipped `check_text` AND got no decline — landing
    verbatim in `brief_notes`. Before this branch that request 422'd; it must
    422 again.
    """
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.moderation import ModerationError

    store = _tail_state_canvas_store()
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    calls = []

    async def _flag(_text):
        calls.append(1)
        raise ModerationError("flagged by content safety filter")
    monkeypatch.setattr(chat_route, "check_text", _flag)

    resp = moderation_client.post("/chat/s1", json={"message": "you are a <slur>"})

    assert resp.status_code == 422
    assert calls == [1]


# --- Security residual: the identity-step exemption removed BOTH gates --------
#
# `orchestrator_v2._ABUSE_EXEMPT_STEPS` skips v2's OWN severe-abuse decline at
# ASK_NAME / ASK_EMAIL, because `paki` and `heeb` are in SEVERE_TERMS and are
# also real surnames. Those two states ARE in V2_OWNED, so the route-level
# bypass fired too — leaving a severe message at the first two questions with no
# moderation of any kind, free to reach `interpret_turn_v2` (which is handed
# EVERY writable slot regardless of step) and bank e.g. `final_notes`, which
# `_apply_final_notes` later appends verbatim into `brief_notes` -> the sales
# email. The LLM gate must run at exactly the steps v2 declines to guard.

def _identity_step_canvas_store(state: str):
    """A v2 canvas session sitting on one of the two exempted identity steps."""
    return {
        "session": {
            "id": "s1",
            "state": state,
            "collected": {"flow_mode": "canvas"},
        }
    }


def test_exempt_step_set_is_imported_not_duplicated():
    """One definition, two consumers. A second copy in chat.py would drift from
    the orchestrator's the first time a step is added to (or removed from) the
    exemption, silently reopening this hole."""
    from app.api.routes import chat as chat_route
    from app.services.conversation import orchestrator_v2 as o2

    assert chat_route._ABUSE_EXEMPT_STEPS is o2._ABUSE_EXEMPT_STEPS


@pytest.mark.parametrize("state", ["ask_name", "ask_email"])
def test_v2_identity_steps_are_still_moderated(state, monkeypatch, moderation_client):
    """A severe message at ASK_NAME / ASK_EMAIL must reach `check_text`.

    v2 exempts these two steps from its own decline, so if the route bypassed
    them as well there would be no gate at all.
    """
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.moderation import ModerationError

    store = _identity_step_canvas_store(state)
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    calls = []

    async def _flag(_text):
        calls.append(1)
        raise ModerationError("flagged by content safety filter")
    monkeypatch.setattr(chat_route, "check_text", _flag)

    resp = moderation_client.post("/chat/s1", json={"message": "you are a <slur>"})

    assert resp.status_code == 422
    assert calls == [1]


@pytest.mark.parametrize("state", ["ask_name", "ask_email"])
def test_v2_identity_steps_owns_turn_is_false(state, monkeypatch):
    """The unit the route gate is built on: v2 does NOT own an exempt turn,
    because its handler deliberately declines to guard it."""
    from app.api.routes import chat as chat_route

    store = _identity_step_canvas_store(state)
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))

    assert chat_route._v2_canvas_owns_turn("s1") is False


def test_a_real_surname_at_ask_name_still_gets_through(monkeypatch, moderation_client):
    """The whole reason the exemption exists. `check_text` now runs — and
    moderation.py explicitly instructs the judge that names are SAFE — so a
    customer whose surname collides with a term in SEVERE_TERMS passes the gate
    and the flow advances, with no decline prepended."""
    from app import prompts
    from app.api.routes import chat as chat_route
    from app.services import profanity
    from app.services.conversation import intent_extractor as ie
    from app.services.conversation import orchestrator_v2 as o2

    store = _identity_step_canvas_store("ask_name")
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    monkeypatch.setattr(chat_route, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(o2, "get_supabase", lambda: _StatefulSupabase(store))
    monkeypatch.setattr(profanity, "scan", lambda t: "severe")

    calls = []

    async def _ok(_text):
        calls.append(1)
    monkeypatch.setattr(chat_route, "check_text", _ok)

    async def _interpret(_step, _msg, _collected):
        return {"name": "Paki"}
    monkeypatch.setattr(ie, "interpret_turn_v2", _interpret)

    async def _ack(*_a, **_k):
        return ""
    monkeypatch.setattr(ie, "write_ack", _ack)

    resp = moderation_client.post("/chat/s1", json={"message": "Paki"})

    assert resp.status_code == 200
    body = resp.json()
    assert calls == [1], "the LLM gate must run at the identity steps"
    assert prompts.V2_ABUSE_DECLINE not in body["reply"]
    assert store["session"]["collected"]["name"] == "Paki"
