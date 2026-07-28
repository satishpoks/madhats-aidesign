"""The two owner-dictated copy strings render, and their format keys resolve.

`Step.ask` is `.format()`-ed at reply time (state_machine_v2.reply_for), so a
mistyped placeholder — `{Name}`, `{customer}` — raises KeyError in front of a
live customer rather than at import. These tests render the real strings
through the real code path.
"""
from __future__ import annotations

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


def _render(step, collected):
    return v2.reply_for(step, collected, persona="Ricardo", intro="", colour_note="")


def test_greeting_introduces_the_persona_by_name():
    out = _render(cs.by_id(S.ASK_NAME), {})
    assert "I'm Ricardo, your design assistant" in out
    assert "bring your cap design to life" in out
    assert "{" not in out            # every placeholder resolved


def test_email_step_greets_the_customer_by_name():
    out = _render(cs.by_id(S.ASK_EMAIL), {"name": "Sam"})
    assert out.startswith("Great job, Sam.")
    assert "reference code" in out
    assert "{" not in out


def test_email_step_falls_back_when_no_name_was_captured():
    """reply_for defaults `name` to "there" — the step must not render "{name}"
    or crash for a session that somehow reached it without a name."""
    out = _render(cs.by_id(S.ASK_EMAIL), {})
    assert out.startswith("Great job, there.")


def test_the_greeting_constant_is_the_one_the_step_uses():
    """Guards against the copy being edited in prompts.py while the step quietly
    holds a stale literal (or vice versa)."""
    assert cs.by_id(S.ASK_NAME).ask is prompts.V2_ASK_NAME
