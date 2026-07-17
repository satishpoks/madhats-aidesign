"""v2 canvas routing — a generic engine over the canvas_steps registry.

Routing is first-unmet resolution: return the first step whose done_when(collected)
is False. That is a pure function of `collected`, so it is exhaustively testable
with plain dicts and needs no LLM, no mocking and no Supabase.

Flexibility comes from slot-filling, not from anyone choosing a route: if the
interpreter banks a volunteered answer ("logo on the back and 50 caps"), the
step that asks for it is already done, so the router simply doesn't return it.

Order is enforced inherently — the router never returns any step positioned
after an unmet one — which is why there is no separate "gate" concept. The
load-bearing invariant (no FINALIZE_CANVAS without email_captured) holds because
ask_email precedes finalize_canvas and its done_when reads `email_captured`,
which only _apply_email sets and the interpreter cannot write.
"""
from __future__ import annotations

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation.canvas_steps import MAX_LOGOS, Step  # noqa: F401 re-export
from app.services.conversation.state_machine import ConversationState as S

# Every state a v2 turn may rest on. GREETING is the kickoff (no registry step:
# it greets and advances without ingesting the turn). Anything NOT here is a
# shared tail state v1 owns — orchestrator_v2 delegates those turns to v1.
V2_OWNED: frozenset[S] = frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}


def next_step(collected: dict) -> Step:
    """The first step whose done_when is False. FINALIZE_CANVAS is terminal
    (done_when is always False), so this always returns a Step."""
    for step in cs.REGISTRY:
        if not step.done_when(collected):
            return step
    return cs.REGISTRY[-1]


# The customer-facing question steps, in order — the loop/adjust steps collapse
# onto their loop's anchor so "Step X of N" stays steady during a deep-dive.
_PROGRESS_ANCHORS: dict[S, S] = {
    S.LOGO_ADJUST: S.ASK_LOGO_PLACEMENT,
    S.ASK_ANOTHER_LOGO: S.ASK_LOGO_PLACEMENT,
    S.DECOR_ADJUST: S.ASK_ADD_DECOR,
    S.ASK_ANYTHING_ELSE: S.ASK_ADD_DECOR,
}
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE,
]


def progress_for(step: Step) -> dict:
    total = len(_PROGRESS_PATH)
    anchor = _PROGRESS_ANCHORS.get(step.id, step.id)
    if anchor in _PROGRESS_PATH:
        return {"step": _PROGRESS_PATH.index(anchor) + 1, "total": total}
    return {"step": total, "total": total}      # finalize + tail -> complete


def progress_v2(state: S, collected: dict | None = None) -> dict:
    """State-keyed wrapper, kept at its original signature for
    `sessions.py`'s canvas-finalize route — which calls it with GENERATING, a
    shared-tail state that has no registry step (-> "complete")."""
    step = cs.by_id(state)
    if step is None:
        total = len(_PROGRESS_PATH)
        return {"step": total, "total": total}
    return progress_for(step)


def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def _face(collected: dict) -> str:
    face = (collected.get("pending_logo") or {}).get("face")
    return face if face in cs.FACES else "front"


def _decor_tool(collected: dict) -> str:
    return "shape" if collected.get("decor_choice") == "shape" else "text"


def directive_for(step: Step, collected: dict) -> dict:
    """The canvas-control blob for a step. EVERY owned step returns one: the
    tool steps hand over their single tool, every other step locks all tools
    explicitly. A null directive means "not a v2 turn" and makes the frontend
    fall back to v1's whole-rail gating + status strip — which showed "Design
    locked in — finishing up" mid-design."""
    if step.tool is None:
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False}
    tool = _decor_tool(collected) if step.id is S.DECOR_ADJUST else step.tool
    return {
        "allowed_tools": [tool],
        "target_face": _face(collected) if step.face_target else None,
        "auto_open": tool if step.auto_open else None,
        "instructions": prompts.V2_TOOL_TIPS[tool],
        "show_done": step.show_done,
    }


def canvas_directive(state: S, collected: dict) -> dict | None:
    """State-keyed wrapper: None for a shared-tail state v2 doesn't own."""
    step = cs.by_id(state)
    return directive_for(step, collected) if step else None


def public_data_for(step: Step, collected: dict) -> dict:
    data: dict = {}
    if step.chips:
        data["options"] = [c.label for c in step.chips]
    if step.continuable:
        data["continuable"] = True
    if step.id is S.FINALIZE_CANVAS:
        data["trigger_finalize"] = True
    data["canvas"] = directive_for(step, collected)
    data["progress"] = progress_for(step)
    return data


def reply_for(step: Step, collected: dict, *, persona: str, intro: str,
              ack: str = "") -> str:
    """ack (LLM, best-effort) + the step's copy + its tool tip (verbatim).

    The tip is concatenated from the registry and never passes through a model,
    so a warm paraphrase cannot drop "tap the highlighted button" and leave the
    customer stuck. Without an ack the reply is simply the scripted copy."""
    if step.id is S.DECOR_ADJUST:
        # The tip is resolved at runtime (text vs shape), so it is PREPENDED to
        # this step's copy rather than appended like every other step. `step.ask`
        # is used rather than a re-typed literal so the two cannot drift.
        body = f"{prompts.V2_TOOL_TIPS[_decor_tool(collected)]} {step.ask}"
    else:
        asked = step.ask_retry and step.id.value in (collected.get("_asked") or [])
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
        )
        if step.tip and step.id is not S.LOGO_ADJUST:
            body = f"{body} {step.tip}"
    return f"{ack} {body}".strip() if ack else body


def resolve_chip(step: Step, message: str) -> dict | None:
    """The fields for an offered chip, or None if `message` isn't one of them.

    A chip tap is not natural language: we generated the label in this registry
    and shipped it to the browser, which sent it straight back. Matching it is an
    identity lookup on a closed set we own — no model, no latency, no failure
    mode. Only the CURRENT step's chips match; a stale chip tapped on an older
    message falls through to the interpreter, which reads it in context.
    """
    target = _norm(message)
    for chip in step.chips:
        if _norm(chip.label) == target:
            return dict(chip.fields)
    return None
