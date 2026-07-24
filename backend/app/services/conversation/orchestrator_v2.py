"""v2 step-by-step canvas orchestrator (parallel to orchestrator.py).

Per turn: resolve a chip deterministically OR interpret free text with Haiku,
validate into declared slots, run the step's effect, ask the router for the
first unmet step, assemble the reply, persist.

The LLM reads the customer; it never routes. Chips never reach the LLM: we
generated the label in canvas_steps and shipped it to the browser, so matching
it back is an identity lookup on a closed set we own.

Selected only when settings.canvas_orchestrator_v2 and flow_mode == "canvas".
Any state outside V2_OWNED is a shared tail state v1 owns — delegated, so a
canvas session is never stranded post-design.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services.branding import canvas_intro_text
from app.services.stores import get_store
from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation import orchestrator as _v1
from app.services.conversation.orchestrator import SessionNotFound, _can_start_design
from app.services.conversation.state_machine import ConversationState as S

_NUDGE_AFTER = 2


def _public(step: cs.Step, collected: dict, config: dict | None = None) -> dict:
    """`v2.public_data_for` plus `can_go_back` — whether `Back` currently has
    anywhere to go. Used everywhere a v2 turn's `data` is built, so the
    frontend always knows whether to offer the affordance. `config` is the
    store's canvas_flow (if any) — threaded through so can_go_back is
    computed over the SAME config-composed registry `next_step` just routed
    on, not silently the default registry."""
    data = v2.public_data_for(step, collected)
    data["can_go_back"] = v2.last_answered_step(collected, config) is not None
    return data


async def handle_message(session_id: str, message: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    current = S(session["state"])

    if current not in v2.V2_OWNED:
        return await _v1.handle_message(session_id, message)

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)
    # The store's admin-configured step order/on-off for the safe subset (V3).
    # None for an unconfigured store, which makes the router walk cs.REGISTRY
    # unchanged. Validated on the way in by branding._validate_canvas_flow.
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")
    state_before = current.value

    if current is S.GREETING:
        # Kickoff: greet and advance without ingesting the opening turn.
        # Deliberately does NOT mark ask_name as asked — this turn must get the
        # FULL greeting; only a re-ask gets the shorter retry copy. The main loop
        # below marks it when the customer actually answers.
        step = cs.by_id(S.ASK_NAME)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro)
        return await _persist(sb, session_id, collected, step, reply,
                              state_before, S.ASK_NAME, user_message="")

    step = cs.by_id(current)
    ack = ""

    fields = v2.resolve_chip(step, message, collected)
    if fields is None and step.slots:
        # Free text on a step that asks for something: the model reads it, or we
        # stall. No keyword fallback — a wrong field corrupts the design.
        # The `try` wraps ONLY the interpretation. write_ack must stay outside it:
        # it swallows its own failures today, but if it ever raised
        # LLMUnavailable, catching it here would silently discard a SUCCESSFUL
        # interpretation and overwrite it with direct_answer (or stall).
        try:
            fields = await ie.interpret_turn_v2(step, message, collected)
        except ie.LLMUnavailable:
            if step.direct_answer is None:
                return await _stall(sb, session_id, collected, step, state_before,
                                    message)
            # The answer IS the message for this step — resolve it deterministically
            # rather than stranding the session. Still validated, still guarded by
            # the step's apply. No ack: the model is down.
            fields = ie.validate_fields(step.direct_answer(message))
        else:
            ack = await ie.write_ack(persona, fields)
    elif fields is None:
        fields = {}                       # ack-only step (show_intro)

    collected.pop("_fail_count", None)
    # Filter BEFORE apply, so an effect never sees a field the router rejected.
    fields = v2.merge_fields(step, collected, fields)
    collected.update(fields)
    if step.apply:
        step.apply(collected, fields, session)
    # Canvas mutations this answer implies. Computed from the step just
    # ANSWERED (not the next one), so it must be read before next_step
    # re-resolves.
    canvas_ops = step.ops(collected, fields) if step.ops else []

    asked = collected.setdefault("_asked", [])
    if step.id.value not in asked:
        asked.append(step.id.value)

    next_ = v2.next_step(collected, flow_config)
    if next_.prepare:
        # Load whatever the step needs to render (store-scoped chips). prepare
        # may SATISFY its own step — a store with no decoration methods
        # configured — so re-resolve under the SAME config. One pass is enough:
        # only one step declares prepare, and a satisfied step routes forward to
        # steps that don't.
        next_.prepare(collected, store)
        next_ = v2.next_step(collected, flow_config)

    if next_.id is S.FINALIZE_CANVAS and not _can_start_design(session_id):
        # Honesty gate: the customer is capped, so pose the quote ask instead of
        # promising a render. QUOTE_REQUESTED is a shared tail state, so the NEXT
        # turn delegates to v1 — but THIS turn must speak, and v2 has no copy
        # for it.
        collected["generation_blocked"] = "daily_limit"
        reply = f"{prompts.GENERATION_BLOCKED_ASIDE} {prompts.CANVAS_QUOTE_ASK}"
        data = {"options": ["Yes, request a quote", "No, I'm all set"],
                "progress": v2.progress_for(cs.by_id(S.FINALIZE_CANVAS))}
        return await _persist(sb, session_id, collected, None, reply, state_before,
                              S.QUOTE_REQUESTED, user_message=message, data=data)

    reply = v2.reply_for(next_, collected, persona=persona, intro=intro, ack=ack)
    if step.id is S.ASK_EMAIL and collected.get("email_captured"):
        # The double opt-in verification email just went out (from _apply_email).
        # Prepend a notice so the customer knows to expect it and why — without
        # this the link arrives unexplained. `fields` still carries the address
        # (_apply_email pops it from `collected`, not `fields`).
        addr = fields.get("email") or "your inbox"
        reply = f"{prompts.V2_EMAIL_VERIFY_NOTICE.format(email=addr)} {reply}".strip()
    data = _public(next_, collected, flow_config)
    if canvas_ops:
        data["canvas_ops"] = canvas_ops
    return await _persist(sb, session_id, collected, next_, reply, state_before,
                          next_.id, user_message=message, data=data)


async def handle_back(session_id: str) -> dict:
    """Undo the last answer: clear the last-answered step's writable slots
    (plus its own `back_clears`) and re-ask it. One level per call; the
    frontend can call it repeatedly. No interpreter — this is the single
    legitimate slot-clearing gesture."""
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    current = S(session["state"])
    if current not in v2.V2_OWNED:
        return await _v1.handle_message(session_id, "")   # not a v2 turn; no-op-ish
    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)

    target = v2.last_answered_step(collected)
    if target is None:
        step = cs.by_id(current)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro)
        return await _persist(sb, session_id, collected, step, reply,
                              current.value, current, user_message="",
                              data=_public(step, collected))
    for key in (set(target.slots) & cs.WRITABLE_SLOTS) | set(target.back_clears):
        collected.pop(key, None)
    nxt = v2.next_step(collected)
    reply = v2.reply_for(nxt, collected, persona=persona, intro=intro)
    return await _persist(sb, session_id, collected, nxt, reply,
                          current.value, nxt.id, user_message="",
                          data=_public(nxt, collected))


async def _stall(sb, session_id, collected, step, state_before, message) -> dict:
    """Retry exhausted: leave the state untouched and guess nothing.

    Only reached by steps with NO `direct_answer` (see canvas_steps.Step) — those
    (ask_name, ask_email, ask_purpose) resolve the message directly during an
    outage instead of ever landing here. For the remaining chip-bearing steps,
    after `_NUDGE_AFTER` consecutive failures we re-render the chips and nudge —
    chips are deterministic, so this degrades the bot to a tap-through wizard.
    Nothing is guessed; a closed question is asked.
    """
    fails = int(collected.get("_fail_count") or 0) + 1
    collected["_fail_count"] = fails
    nudge = fails >= _NUDGE_AFTER and cs.chips_of(step, collected)
    reply = prompts.V2_NUDGE_REPLY if nudge else prompts.V2_STALL_REPLY
    return await _persist(sb, session_id, collected, step, reply, state_before,
                          step.id, user_message=message)


async def _persist(sb, session_id, collected, step, reply, state_before, new_state,
                   *, user_message: str = "", data: dict | None = None) -> dict:
    """Write the state + both chat rows, and shape the response.

    `step` is the step the session now RESTS on (None only for the capped
    QUOTE_REQUESTED handoff, which supplies its own `data`).
    """
    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()
    sb.table("chat_messages").insert([
        {"session_id": session_id, "role": "user", "content": user_message,
         "state_before": state_before, "state_after": state_before},
        {"session_id": session_id, "role": "assistant", "content": reply,
         "state_before": state_before, "state_after": new_state.value},
    ]).execute()
    if data is None:
        data = _public(step, collected) if step else {}
    return {"reply": reply, "state": new_state.value, "data": data}
