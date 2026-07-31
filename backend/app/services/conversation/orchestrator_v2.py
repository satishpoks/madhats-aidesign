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

import structlog

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services import profanity
from app.services.branding import canvas_intro_text, colour_disclaimer_text
from app.services.stores import get_store
from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation import orchestrator as _v1
from app.services.conversation.orchestrator import SessionNotFound, _can_start_design
from app.services.conversation.state_machine import ConversationState as S

log = structlog.get_logger()

_NUDGE_AFTER = 2

#: The two steps where a REAL PERSON'S IDENTITY is the expected answer, so the
#: severe-abuse decline must not fire. `SEVERE_TERMS` carries terms that are also
#: genuine surnames ("Paki" is a well-known Māori surname; "Heeb" is Swiss/
#: German), and because the decline never advances, such a customer would be
#: permanently blocked at the FIRST question — or at the email step by their own
#: address ("s.heeb@example.com") — with no chip to escape via. The terms stay in
#: the list (owner ruling); the identity steps are exempted instead.
#:
#: Safe because these turns write only the `name`/`email` slot — each already
#: guarded by its own step's apply/direct-answer — never free text into
#: `brief_notes`. Knock-on: `find_terms` no longer logs a surname at these steps.
_ABUSE_EXEMPT_STEPS: frozenset[S] = frozenset({S.ASK_NAME, S.ASK_EMAIL})


def _public(step: cs.Step, collected: dict, config: dict | None = None) -> dict:
    """`v2.public_data_for` plus `can_go_back` (whether `Back` has anywhere to
    go) and `back_removes_element` (whether that Back removes the in-progress
    element rather than rewinding one slot). `_back_used` suppresses Back until
    the next forward turn — one step per Back, no two consecutive."""
    data = v2.public_data_for(step, collected)
    can_back = (not collected.get("_back_used")) and (
        v2.last_answered_step(collected, config) is not None)
    data["can_go_back"] = can_back
    data["back_removes_element"] = bool(
        can_back and step is not None and step.id in v2._ELEMENT_ADJUST_STEPS)
    return data


async def handle_message(session_id: str, message: str,
                         canvas_design: dict | None = None) -> dict:
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
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
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
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply,
                              state_before, S.ASK_NAME, user_message="",
                              config=flow_config)

    step = cs.by_id(current)

    if not (message or "").strip():
        # An empty/whitespace turn is never a real answer at a non-greeting step
        # — only the GREETING kickoff (handled above) legitimately sends "". A
        # blank message matches no chip, so without this guard it falls through
        # to interpret_turn_v2, and the model — handed no real input but the full
        # slot list — hallucinates well-typed slot values that walk first-unmet
        # routing BACKWARD (the live dead-loop that reset sessions to ask_name).
        # Re-render the current step, ingesting nothing.
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply, state_before,
                              current, user_message=message,
                              data=_public(step, collected, flow_config))

    # Severe abuse (slurs / hate terms) is declined WITHOUT advancing: re-render
    # the current step exactly as the blank-turn guard above does, ingesting
    # nothing, so no slot is written and first-unmet routing cannot move. Mild
    # profanity deliberately falls straight through — a frustrated customer
    # venting must not dead-end a sale.
    #
    # A normal reply, never a 422: an error banner reads as a broken app rather
    # than a boundary. `find_terms` logs the matched TERM only — never the
    # message, name or email (security rule 10).
    #
    # ASK_NAME / ASK_EMAIL are exempt (see _ABUSE_EXEMPT_STEPS): a real surname
    # would otherwise dead-end the first two questions of the flow.
    if step.id not in _ABUSE_EXEMPT_STEPS and profanity.scan(message) == "severe":
        log.info("v2_turn_declined_abuse", terms=profanity.find_terms(message))
        reply = f"{prompts.V2_ABUSE_DECLINE} " + v2.reply_for(
            step, collected, persona=persona, intro=intro, colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply.strip(),
                              state_before, current, user_message=message,
                              data=_public(step, collected, flow_config))

    # A real forward answer re-enables Back: the single-step lock is per-Back.
    # Popped AFTER the empty-turn guard so a blank kickoff turn never clears it,
    # and BEFORE the interpreter runs so `_back_used` never enters an LLM context.
    collected.pop("_back_used", None)

    ack = ""

    fields = v2.resolve_chip(step, message, collected)
    if fields is None and step.slots:
        if step.direct_capture:
            # The answer IS the message; interpreting it adds nothing and an LLM
            # could reshape a colour code. Verbatim, still validated + apply-guarded.
            fields = ie.validate_fields(step.direct_answer(message))
        else:
            # Free text on a step that asks for something: the model reads it, or
            # we stall. No keyword fallback — a wrong field corrupts the design.
            # The `try` wraps ONLY the interpretation. write_ack must stay outside
            # it: it swallows its own failures today, but if it ever raised
            # LLMUnavailable, catching it here would silently discard a SUCCESSFUL
            # interpretation and overwrite it with direct_answer (or stall).
            try:
                fields = await ie.interpret_turn_v2(step, message, collected)
            except ie.LLMUnavailable:
                if step.direct_answer is None:
                    return await _stall(sb, session_id, collected, step,
                                        state_before, message, config=flow_config)
                # The answer IS the message for this step — resolve it
                # deterministically rather than stranding the session. Still
                # validated, still guarded by the step's apply. No ack: the
                # model is down.
                fields = ie.validate_fields(step.direct_answer(message))
            else:
                ack = await ie.write_ack(persona, fields)
    elif fields is None:
        fields = {}                       # ack-only step (show_intro)

    if step.accept_verbatim and not any(fields.get(s) for s in step.slots):
        # The interpreter read nothing into this step's own slot — a misspelled
        # answer, or a refusal it declined to treat as an answer. For this step
        # the message IS the answer, so bank it rather than re-ask a question
        # the customer just answered. Still validated (so it can only land in a
        # declared slot) and still guarded by the step's own apply.
        fields = {**fields,
                  **ie.validate_fields({step.slots[0]: message.strip()})}

    collected.pop("_fail_count", None)
    # Filter BEFORE apply, so an effect never sees a field the router rejected.
    fields = v2.merge_fields(step, collected, fields)
    collected.update(fields)
    if step.apply:
        step.apply(collected, fields, session)
    # The customer may have ticked "Remove background" in the Adjust panel
    # themselves. That lives only in the frontend store until finalize, so the
    # live canvas blob (sent on this turn only) is the sole way to see it.
    # AFTER apply — on the Done turn it is _apply_logo_placed that marks the
    # logo placed — and BEFORE next_step, because the write satisfies
    # ASK_LOGO_BG.done_when and that is what makes first-unmet skip it.
    # observe_canvas is self-guarding; no step check belongs here.
    bg_auto_marked = cs.observe_canvas(collected, canvas_design)
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

    reply = v2.reply_for(next_, collected, persona=persona, intro=intro, ack=ack,
                        colour_note=colour_note)
    if bg_auto_marked:
        # Say what we noticed. Without this the background question simply
        # vanishes, which reads as the bot skipping a step at random.
        reply = f"{prompts.V2_BG_ALREADY_REMOVED} {reply}".strip()
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


def _restart_element(collected: dict, current: S) -> str:
    """Clear the in-progress element's slots so first-unmet re-asks it from the
    top, and return the face the (now-removed) canvas element sat on. Logo:
    reset pending_logo to {} (loop stays open) -> re-asks ASK_LOGO_PLACEMENT.
    Decor: drop the decor slots -> re-asks ASK_ADD_DECOR (re-pick text/shape)."""
    if current in (S.LOGO_ADJUST, S.ASK_LOGO_BG):
        face = cs._pending(collected).get("face") or "front"
        collected["pending_logo"] = {}
        return face
    # DECOR_ADJUST
    face = collected.get("decor_face") or "front"
    for key in ("decor_choice", "decor_face", "decor_placed"):
        collected.pop(key, None)
    return face


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
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
    # Same wiring as handle_message: thread the store's configurable-flow
    # config into the router so Back's routing (and the can_go_back it
    # reports) is computed over the SAME config-composed registry the forward
    # flow just used, not silently the default registry.
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")

    if current is S.GREETING:
        # Nothing before the very first step to undo — re-render the kickoff,
        # mirroring handle_message's own GREETING branch. Without this guard
        # cs.by_id(GREETING) is None (GREETING has no registry Step) and the
        # no-target branch below crashes on v2.reply_for(None, ...).
        step = cs.by_id(S.ASK_NAME)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply,
                              current.value, S.ASK_NAME, user_message="",
                              data=_public(step, collected, flow_config))

    if current in v2._ELEMENT_ADJUST_STEPS:
        face = _restart_element(collected, current)
        collected["_back_used"] = True
        nxt = v2.next_step(collected, flow_config)
        reply = v2.reply_for(nxt, collected, persona=persona, intro=intro,
                             ack=prompts.V2_BACK_RESTART_ACK, colour_note=colour_note)
        data = _public(nxt, collected, flow_config)
        data["canvas_ops"] = [
            {"target": {"kind": "pending_logo", "face": face}, "remove": True}]
        return await _persist(sb, session_id, collected, nxt, reply,
                              current.value, nxt.id, user_message="", data=data)

    target = v2.last_answered_step(collected, flow_config)
    if target is None:
        step = cs.by_id(current)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply,
                              current.value, current, user_message="",
                              data=_public(step, collected, flow_config))
    clear = ((set(target.slots) & cs.WRITABLE_SLOTS) | set(target.back_clears)) - v2._TERMINAL_FLAGS
    for key in clear:
        collected.pop(key, None)
    collected["_back_used"] = True
    nxt = v2.next_step(collected, flow_config)
    reply = v2.reply_for(nxt, collected, persona=persona, intro=intro,
                         colour_note=colour_note)
    return await _persist(sb, session_id, collected, nxt, reply,
                          current.value, nxt.id, user_message="",
                          data=_public(nxt, collected, flow_config))


async def check_verification(session_id: str) -> dict:
    """Poll target while a v2 canvas session waits at AWAIT_EMAIL_VERIFY.

    The gate is the one step no customer turn can satisfy: it clears only when
    the emailed link is opened, which flips ``collected.email_verified`` from the
    leads route. The still-open tab polls this every few seconds; once the flag
    lands we resolve the next unmet step and append ONLY the assistant's line —
    a phantom user turn would appear in the thread as something the customer
    never said.

    Returns ``reply=None`` (nothing changed) until verification lands. Any state
    outside the gate is delegated to v1, which owns the shared post-generation
    VERIFY_EMAIL wait the frontend polls with the same endpoint.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    current = S(session["state"])

    if current is not S.AWAIT_EMAIL_VERIFY:
        return await _v1.check_verification(session_id)

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")
    step = cs.by_id(current)

    if not collected.get("email_verified"):
        return {"reply": None, "state": current.value,
                "data": _public(step, collected, flow_config)}

    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    next_ = v2.next_step(collected, flow_config)
    if next_.prepare:
        next_.prepare(collected, store)
        next_ = v2.next_step(collected, flow_config)
    reply = v2.reply_for(next_, collected, persona=persona,
                         intro=canvas_intro_text(store),
                         ack=prompts.V2_EMAIL_VERIFIED_ACK,
                         colour_note=colour_disclaimer_text(
                             store, collected.get("name") or "there"))
    return await _persist(sb, session_id, collected, next_, reply, current.value,
                          next_.id, user_message=None, config=flow_config)


async def _stall(sb, session_id, collected, step, state_before, message,
                 *, config: dict | None = None) -> dict:
    """Retry exhausted: leave the state untouched and guess nothing.

    Only reached by steps with NO `direct_answer` (see canvas_steps.Step) — the
    direct-answer steps resolve the message directly during an outage instead
    of ever landing here (ASK_FINAL_NOTES never reaches this function either,
    for a different reason: its `direct_capture` short-circuits before the
    interpreter is ever called). For the remaining chip-bearing steps, after
    `_NUDGE_AFTER` consecutive failures we re-render the chips and nudge —
    chips are deterministic, so this degrades the bot to a tap-through wizard.
    Nothing is guessed; a closed question is asked.
    """
    fails = int(collected.get("_fail_count") or 0) + 1
    collected["_fail_count"] = fails
    nudge = fails >= _NUDGE_AFTER and cs.chips_of(step, collected)
    reply = prompts.V2_NUDGE_REPLY if nudge else prompts.V2_STALL_REPLY
    return await _persist(sb, session_id, collected, step, reply, state_before,
                          step.id, user_message=message, config=config)


async def _persist(sb, session_id, collected, step, reply, state_before, new_state,
                   *, user_message: str | None = "", data: dict | None = None,
                   config: dict | None = None) -> dict:
    """Write the state + the chat rows, and shape the response.

    `step` is the step the session now RESTS on (None only for the capped
    QUOTE_REQUESTED handoff, which supplies its own `data`). `config` is the
    store's canvas_flow — only consulted for the `_public` fallback below (an
    explicit `data=` always wins), so `can_go_back` in that fallback is scoped
    to the same config-composed registry as the turn that produced it.

    `user_message=None` writes the assistant row ONLY, for a turn the customer
    didn't take (check_verification, which advances off an out-of-band email
    click). `""` is different and still writes an empty user row — that's the
    GREETING kickoff's existing shape.
    """
    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()
    rows = [] if user_message is None else [
        {"session_id": session_id, "role": "user", "content": user_message,
         "state_before": state_before, "state_after": state_before},
    ]
    rows.append(
        {"session_id": session_id, "role": "assistant", "content": reply,
         "state_before": state_before, "state_after": new_state.value})
    sb.table("chat_messages").insert(rows).execute()
    if data is None:
        data = _public(step, collected, config) if step else {}
    return {"reply": reply, "state": new_state.value, "data": data}
