"""C1 — the REQUEST_QUOTE registry step records the request via its apply hook."""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as sm2
from app.services.conversation.state_machine import ConversationState as S


def _step(state):
    return cs.by_id(state)


def test_request_quote_step_exists_between_purpose_and_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert S.REQUEST_QUOTE in ids
    assert ids.index(S.ASK_PURPOSE) < ids.index(S.REQUEST_QUOTE) < ids.index(S.FINALIZE_CANVAS)


def test_request_quote_chip_records_and_stores_reference(monkeypatch):
    step = _step(S.REQUEST_QUOTE)
    fields = sm2.resolve_chip(step, "Request a quote", {})
    assert fields == {"quote_requested": True}

    calls = {}

    def _record(session, collected):
        calls["session"] = session
        return "MH-BCDFGH"

    from app.services import leads as leads_service
    monkeypatch.setattr(leads_service, "record_quote_request", _record)

    collected: dict = {}
    step.apply(collected, fields, {"id": "sess-1"})
    assert collected["quote_requested"] is True
    assert collected["reference_code"] == "MH-BCDFGH"
    assert calls["session"] == {"id": "sess-1"}


def test_request_quote_gates_finalize_until_requested():
    # With everything before it satisfied but no quote_requested, first-unmet
    # rests on REQUEST_QUOTE — never FINALIZE_CANVAS. (needed_by and
    # design_confirmed are included so this stays correct once Workstream B's
    # needed_by and pre-submit review steps are merged before REQUEST_QUOTE —
    # an unused key is harmless if a step isn't present yet.)
    done = {"name": "Ann", "intro_ack": True, "logos_done": True, "decor_done": True,
            "quantity": 1, "decoration_done": True, "email_captured": True,
            "needed_by": "ASAP", "purpose": "team", "design_confirmed": True}
    assert sm2.next_step(done).id is S.REQUEST_QUOTE
    done["quote_requested"] = True
    assert sm2.next_step(done).id is S.FINALIZE_CANVAS
