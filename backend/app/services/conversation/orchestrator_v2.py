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
from app.services.conversation import checkpoints as ck
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


def _public(step: cs.Step, collected: dict, config: dict | None = None,
            *, targets: list[dict] | None = None) -> dict:
    """`v2.public_data_for` plus `back_targets` — the Back destinations
    offerable right now, newest first, already labelled and already filtered.

    Shipped on EVERY turn so the menu opens with no round trip and can never be
    stale. An empty list is how "no going back" is expressed: the frontend
    renders no Back button at all, so there is no separate disable flag to keep
    in sync.
    """
    data = v2.public_data_for(step, collected)
    data["back_targets"] = targets or []
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
        # The kickoff is itself a transition (GREETING -> ASK_NAME), so it
        # captures ASK_NAME's own checkpoint exactly like any other entry —
        # there is nothing GREETING-specific about the capture hook.
        ck.capture(sb, session_id, step, current, collected, canvas_design)
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
                              data=_public(step, collected, flow_config,
                                          targets=v2.back_targets(
                                              collected, ck.live_rows(sb, session_id))))

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
        reply = f"{prompts.V2_ABUSE_DECLINE}\n\n" + v2.reply_for(
            step, collected, persona=persona, intro=intro, colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply.strip(),
                              state_before, current, user_message=message,
                              data=_public(step, collected, flow_config,
                                          targets=v2.back_targets(
                                              collected, ck.live_rows(sb, session_id))))

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
    # observe_canvas is self-guarding; no step check belongs here. The return
    # value is intentionally unused: the customer-facing announcement was
    # removed by owner request, but the call must stay — its side effect
    # (writing pending_logo["bg"]="removed" when the customer ticked the
    # toggle themselves) is what makes first-unmet routing skip ASK_LOGO_BG.
    cs.observe_canvas(collected, canvas_design)
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

    # Snapshot on ENTRY to a checkpoint opener — correct by construction: this
    # turn carries `collected` and the canvas as they stood at the END of the
    # previous checkpoint. `current` is the state being LEFT, which is what
    # makes this idempotent: every re-render path (stall, retry, blank turn,
    # abuse decline) has current == next_ and writes nothing.
    ck.capture(sb, session_id, next_, current, collected, canvas_design)

    if next_.id is S.FINALIZE_CANVAS and not _can_start_design(session_id):
        # Honesty gate: the customer is capped, so pose the quote ask instead of
        # promising a render. QUOTE_REQUESTED is a shared tail state, so the NEXT
        # turn delegates to v1 — but THIS turn must speak, and v2 has no copy
        # for it.
        collected["generation_blocked"] = "daily_limit"
        reply = f"{prompts.GENERATION_BLOCKED_ASIDE}\n\n{prompts.CANVAS_QUOTE_ASK}"
        data = {"options": ["Yes, request a quote", "No, I'm all set"],
                "progress": v2.progress_for(cs.by_id(S.FINALIZE_CANVAS)),
                "back_targets": v2.back_targets(collected, ck.live_rows(sb, session_id))}
        return await _persist(sb, session_id, collected, None, reply, state_before,
                              S.QUOTE_REQUESTED, user_message=message, data=data)

    reply = v2.reply_for(next_, collected, persona=persona, intro=intro, ack=ack,
                        colour_note=colour_note)
    if step.id is S.ASK_EMAIL and collected.get("email_captured"):
        # The double opt-in verification email just went out (from _apply_email).
        # Prepend a notice so the customer knows to expect it and why — without
        # this the link arrives unexplained. `fields` still carries the address
        # (_apply_email pops it from `collected`, not `fields`).
        addr = fields.get("email") or "your inbox"
        reply = f"{prompts.V2_EMAIL_VERIFY_NOTICE.format(email=addr)}\n\n{reply}".strip()
    data = _public(next_, collected, flow_config,
                   targets=v2.back_targets(collected, ck.live_rows(sb, session_id)))
    if canvas_ops:
        data["canvas_ops"] = canvas_ops
    return await _persist(sb, session_id, collected, next_, reply, state_before,
                          next_.id, user_message=message, data=data)


async def handle_back(session_id: str, seq: int) -> dict:
    """Restore the session to checkpoint `seq`.

    The router needs no special casing: `collected` genuinely becomes what it
    was, so first-unmet lands on the opener step by itself. `state` is written
    explicitly so a mid-restore reload is consistent.

    Raises CheckpointUnavailable for an unknown, superseded or frozen seq — the
    double-tap and stale-tab case, which the route turns into a 409.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    if S(session["state"]) not in v2.V2_OWNED:
        raise ck.CheckpointUnavailable("not a v2 turn")

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")

    # Offerability is re-checked server-side: the button the customer tapped
    # was rendered from an earlier turn's data and may since have frozen.
    offerable = {t["seq"] for t in v2.back_targets(
        collected, ck.live_rows(sb, session_id))}
    if seq not in offerable:
        raise ck.CheckpointUnavailable(f"seq {seq} is not offerable")

    row = ck.restore(sb, session_id, seq, collected)
    if row is None:
        raise ck.CheckpointUnavailable(f"seq {seq} is unavailable")

    restored = row["collected"]
    step = cs.by_id_value(row["step_id"]) or cs.by_id(S.ASK_NAME)
    reply = v2.reply_for(step, restored, persona=persona, intro=intro,
                         colour_note=colour_note)
    data = _public(step, restored, flow_config,
                   targets=v2.back_targets(
                       restored, ck.live_rows(sb, session_id)))
    if row.get("canvas_design"):
        data["canvas_restore"] = row["canvas_design"]
    return await _persist(sb, session_id, restored, step, reply,
                          session["state"], step.id, user_message=None, data=data)


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
                "data": _public(step, collected, flow_config,
                                targets=v2.back_targets(
                                    collected, ck.live_rows(sb, session_id)))}

    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    next_ = v2.next_step(collected, flow_config)
    if next_.prepare:
        next_.prepare(collected, store)
        next_ = v2.next_step(collected, flow_config)
    # Two messages, not one: the confirmation is its own bubble so it can't be
    # read past on the way to the question. `ack=` is deliberately NOT passed —
    # that is what would merge them back together.
    next_question = v2.reply_for(next_, collected, persona=persona,
                                 intro=canvas_intro_text(store),
                                 colour_note=colour_disclaimer_text(
                                     store, collected.get("name") or "there"))
    return await _persist(sb, session_id, collected, next_,
                          prompts.V2_EMAIL_VERIFIED_ACK, current.value,
                          next_.id, user_message=None, config=flow_config,
                          extra_replies=[next_question])


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
                   config: dict | None = None,
                   extra_replies: list[str] | None = None) -> dict:
    """Write the state + the chat rows, and shape the response.

    `step` is the step the session now RESTS on (None only for the capped
    QUOTE_REQUESTED handoff, which supplies its own `data`). `config` is the
    store's canvas_flow, threaded through to the `_public` fallback below (an
    explicit `data=` always wins) purely for parity with its other callers —
    `back_targets` itself takes no config (Task 3: offerability is a pure
    function of each checkpoint's own `frozen_when`, not the composed registry).

    `user_message=None` writes the assistant row ONLY, for a turn the customer
    didn't take (check_verification, which advances off an out-of-band email
    click). `""` is different and still writes an empty user row — that's the
    GREETING kickoff's existing shape.

    `extra_replies` are FURTHER assistant messages, shown after `reply`. Each
    becomes its own persisted row and its own chat bubble, so two unrelated
    things (a confirmation and the next question) don't arrive merged. They are
    surfaced on `data`, not as a new top-level response key, so the response
    shape stays `{reply, state, data}` for every existing caller.
    """
    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()
    rows = [] if user_message is None else [
        {"session_id": session_id, "role": "user", "content": user_message,
         "state_before": state_before, "state_after": state_before},
    ]
    for content in [reply, *(extra_replies or [])]:
        rows.append(
            {"session_id": session_id, "role": "assistant", "content": content,
             "state_before": state_before, "state_after": new_state.value})
    sb.table("chat_messages").insert(rows).execute()
    if data is None:
        data = _public(step, collected, config,
                       targets=v2.back_targets(
                           collected, ck.live_rows(sb, session_id))) if step else {}
    if extra_replies:
        data["extra_replies"] = list(extra_replies)
    return {"reply": reply, "state": new_state.value, "data": data}
