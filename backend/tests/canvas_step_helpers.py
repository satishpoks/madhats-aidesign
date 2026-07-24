"""Shared test helpers for walking the v2 canvas_steps registry.

Imported by test_state_machine_v2.py and test_canvas_steps.py (Task 4) — the
registry walk is needed by both, so it lives here once instead of being
duplicated per test module (the backend has no conftest.py; a plain
importable helper module matches the existing inline-fake convention).
"""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs
from app.services.conversation.state_machine import ConversationState as S


def satisfy(c: dict, step) -> None:
    """Minimal mutation to make one step done, mirroring the apply hooks.

    Walks the LONGEST path (one logo, one decoration, a mixed decoration method)
    so that every step in the registry becomes first-unmet in turn — hence
    decor_choice/decor_placed here rather than the decor_done shortcut, which
    would skip DECOR_ADJUST and ASK_ANYTHING_ELSE entirely, and decoration_mix
    rather than decoration_done, which would skip ASK_DECORATION_MIX.
    """
    if step.id is S.ASK_NAME:
        c["name"] = "Sam"
    elif step.id is S.SHOW_INTRO:
        c["intro_ack"] = True
    elif step.id is S.ASK_HAS_LOGO:
        c["has_logo"] = True
    elif step.id is S.ASK_LOGO_PLACEMENT:
        c["pending_logo"] = {"face": "front"}
    elif step.id is S.LOGO_ADJUST:
        c.setdefault("pending_logo", {})["placed"] = True
    elif step.id is S.ASK_LOGO_BG:
        c.setdefault("pending_logo", {})["bg"] = "none"
    elif step.id is S.ASK_ANOTHER_LOGO:
        c["logos_done"] = True
        c["pending_logo"] = None
    elif step.id is S.ASK_ADD_DECOR:
        c["decor_choice"] = "text"
    elif step.id is S.ASK_DECOR_PLACEMENT:
        c["decor_face"] = "front"
    elif step.id is S.DECOR_ADJUST:
        c["decor_placed"] = True
    elif step.id is S.ASK_ANYTHING_ELSE:
        c["decor_done"] = True
    elif step.id is S.ASK_QUANTITY:
        c["quantity"] = 12
    elif step.id is S.ASK_DECORATION:
        c["decoration_mix"] = True          # longest path: a mix must be described
    elif step.id is S.ASK_DECORATION_MIX:
        c["decoration_mix_note"] = "embroidered logo, printed text"
    elif step.id is S.ASK_EMAIL:
        c["email_captured"] = True
    elif step.id is S.ASK_PURPOSE:
        c["purpose"] = "team caps"
    elif step.id is S.REQUEST_QUOTE:
        c["quote_requested"] = True


def seed_for(step) -> dict:
    """A collected where `step` is the first unmet step."""
    c = {"flow_mode": "canvas"}
    for s in cs.REGISTRY:
        if s.id is step.id:
            return c
        satisfy(c, s)
    raise AssertionError(f"unreachable step {step.id}")
