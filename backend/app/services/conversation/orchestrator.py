"""Chat orchestrator — the main /chat handler.

Flow per message:
  1. load session
  2. KICKOFF guard: if state is GREETING, emit the greeting reply and advance
     to ASK_NAME without ingesting the message as data.
  3. otherwise detect back-track intent → rewind if requested
  4. interpret the message in the context of the CURRENT state
     (deterministic logic + optional LLM extraction), update collected
  5. advance_state() picks the next state; auto-advance through routing-only
     states (CHECK_YOUTH, DECORATION_ENGINE) that need no user input
  6. word Ricardo's reply
  7. persist the chat_message row
  8. return reply + new state
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.config import settings
from app.db import get_supabase
from app.services import leads as leads_service
from app.services import settings_service
from app.services.stores import get_store
from app.services.conversation import brief
from app.services.conversation import goal_planner
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import (
    AUTO_ADVANCE_STATES,
    ConversationState,
    advance_state,
    allowed_backtracks,
    is_affirmative,
    is_negative,
    progress,
)

log = structlog.get_logger()

# Phrases that end the element-gather loop ("that's everything").
_DONE_ELEMENTS = (
    "that's it", "thats it", "that's all", "thats all", "that's everything",
    "thats everything", "nothing else", "no more", "all set", "generate",
    "ready", "done",
)

# States where a (non-declining) message contributes a design element.
_ELEMENT_STATES = frozenset(
    {
        ConversationState.DESCRIBE_DESIGN,
        ConversationState.ASK_MORE_ELEMENTS,
        ConversationState.ADD_ELEMENTS_MODE,
        ConversationState.DESCRIBE_CHANGES,
    }
)
# Bare acknowledgements that carry no element to extract on their own.
_BARE_YES = frozenset(
    {"yes", "yeah", "yep", "sure", "ok", "okay", "add text", "add a graphic", "add graphic"}
)


class SessionNotFound(Exception):
    pass


async def handle_message(session_id: str, message: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}
    upsell_count: int = session.get("upsell_count") or 0

    # Per-tenant persona, falling back to the global default.
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name

    state_before = current.value

    # -----------------------------------------------------------------------
    # 2. KICKOFF: the very first call while still at GREETING
    # Do NOT ingest the (possibly empty) opening message as data.
    # Emit the greeting reply and advance to ASK_NAME.
    # -----------------------------------------------------------------------
    if current is ConversationState.GREETING:
        new_state = ConversationState.ASK_NAME
        reply = await ie.generate_reply(ConversationState.GREETING.value, collected, persona)
    else:
        # --- 3+4. interpret the turn (one call: intent + fields) ---
        faq = settings_service.get_settings().faq_knowledge
        targets = [s.value for s in allowed_backtracks(current)]
        interp = await ie.interpret_turn(current.value, message, collected, targets, faq)

        _apply_fields(current, interp.get("fields") or {}, collected, message)
        await _maybe_gather_element(current, interp.get("fields") or {}, collected, message)

        # --- 4b. email capture (inline, no separate form) ---
        # GENERATING and ASK_EMAIL ask for the email in the chat. We already
        # have the customer's name, so the moment a usable email arrives we
        # create the lead and send a verification email — no second form. The
        # preview itself is released when the customer clicks that link.
        if current in (ConversationState.GENERATING, ConversationState.ASK_EMAIL) and not collected.get(
            "email_captured"
        ):
            email = leads_service.extract_email(message)
            if email:
                lead_id = leads_service.capture_lead_and_verify(session, collected, email)
                collected["email_captured"] = True
                if lead_id:
                    collected["lead_id"] = lead_id

        intent = interp["intent"]
        # A tapped option chip (or a message exactly matching one) is a
        # DEFINITIVE answer — never a side-question. The interpreter occasionally
        # misclassifies a terse decision reply as ask_question/chitchat.
        _opts = _public_data(current, collected)
        _chip_values = [o.lower() for o in (_opts.get("options", []) + _opts.get("options2", []))]
        if message.strip().lower() in _chip_values and intent in ("ask_question", "chitchat"):
            intent = "answer"

        # Questions / chit-chat are answered INLINE (aside) and never freeze the
        # flow: routing still runs, so filled slots advance and only a genuinely
        # unmet slot "stays". This is what removes the old re-ask loop.
        aside = interp.get("question_answer") or None if intent in ("ask_question", "chitchat") else None

        if intent in ("revise", "backtrack"):
            target = interp.get("revise_target") or interp.get("backtrack_target")
            new_state = ConversationState(target) if target else _route(current, collected, upsell_count)
            if target:
                log.info("backtrack", session_id=session_id, frm=state_before, to=new_state.value)
        elif current is ConversationState.OFFER_REFINE and collected.get("wants_changes"):
            if _can_edit(session_id):
                new_state = ConversationState.DESCRIBE_CHANGES
            else:
                collected["edit_cap_reached"] = True
                new_state = ConversationState.QUOTE_REQUESTED
        else:
            new_state = _route(current, collected, upsell_count)

        if new_state is ConversationState.UPSELL_PROMPT and collected.get("wants_upsell"):
            upsell_count += 1
        # auto-advance through any routing-only states advance_state may return
        while new_state in AUTO_ADVANCE_STATES:
            new_state = advance_state(new_state, collected, upsell_count=upsell_count)

        # One-shot flags: mark soft/optional goals as offered so they are never
        # nagged on a later turn.
        if new_state is ConversationState.ASK_PURPOSE:
            collected["purpose_asked"] = True
        elif new_state is ConversationState.YOUTH_REFERRAL:
            collected["youth_referred"] = True
        elif new_state is ConversationState.ASK_MORE_ELEMENTS:
            collected["elements_offered"] = True
        elif new_state is ConversationState.ASK_PIN_ANNOTATION:
            collected["pin_offered"] = True

        reply = await ie.generate_reply(new_state.value, collected, persona, aside=aside)

    if new_state is ConversationState.QUOTE_REQUESTED:
        try:
            from app.services import delivery  # noqa: PLC0415

            delivery.send_final_design(session_id)
        except Exception:  # noqa: BLE001 — delivery is best-effort
            log.warning("final_design_send_failed", session_id=session_id)

    # --- 7. persist state + messages ---
    sb.table("design_sessions").update(
        {
            "state": new_state.value,
            "collected": collected,
            "upsell_count": upsell_count,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert(
        [
            {
                "session_id": session_id,
                "role": "user",
                "content": message,
                "state_before": state_before,
                "state_after": state_before,
            },
            {
                "session_id": session_id,
                "role": "assistant",
                "content": reply,
                "state_before": state_before,
                "state_after": new_state.value,
            },
        ]
    ).execute()

    data = _public_data(new_state, collected)
    data["progress"] = progress(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}


async def check_verification(session_id: str) -> dict:
    """Poll target for the chat while it rests at VERIFY_EMAIL.

    Email verification happens out-of-band (the customer clicks the emailed
    link, which flips ``collected.email_verified``). This lets the still-open
    chat tab detect that and advance the thread to EMAIL_VERIFIED — appending
    only Ricardo's confirmation line, with no phantom user turn.

    Returns ``reply=None`` (no change) until verification lands.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}

    if current is not ConversationState.VERIFY_EMAIL or not collected.get("email_verified"):
        data = _public_data(current, collected)
        data["progress"] = progress(current, collected)
        return {"reply": None, "state": current.value, "data": data}

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name

    new_state = advance_state(current, collected)
    while new_state in AUTO_ADVANCE_STATES:
        new_state = advance_state(new_state, collected)

    reply = await ie.generate_reply(new_state.value, collected, persona)

    sb.table("design_sessions").update(
        {"state": new_state.value, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert(
        {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
            "state_before": current.value,
            "state_after": new_state.value,
        }
    ).execute()

    data = _public_data(new_state, collected)
    data["progress"] = progress(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}


async def advance_after_regeneration(session_id: str) -> dict:
    """Poll target for the chat while it rests at REGENERATING.

    Regeneration runs out-of-band on the frontend (client-side poll of
    /generate/status), which appends the new design to the viewer but has no
    way to move the CONVERSATION forward on its own. The frontend calls this
    once, right after that regeneration promise settles (success or failure —
    the customer must never be stranded at REGENERATING), to advance the
    thread back to OFFER_REFINE.

    Returns ``reply=None`` (no-op) if the session isn't at REGENERATING.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}

    if current is not ConversationState.REGENERATING:
        data = _public_data(current, collected)
        data["progress"] = progress(current, collected)
        return {"reply": None, "state": current.value, "data": data}

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name

    new_state = advance_state(current, collected)
    collected["wants_changes"] = False

    reply = await ie.generate_reply(new_state.value, collected, persona)

    sb.table("design_sessions").update(
        {
            "state": new_state.value,
            "collected": collected,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert(
        {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
            "state_before": current.value,
            "state_after": new_state.value,
        }
    ).execute()

    data = _public_data(new_state, collected)
    data["progress"] = progress(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}


def _route(
    current: ConversationState, collected: dict, upsell_count: int
) -> ConversationState:
    """Forward routing: the goal planner owns the questionnaire; advance_state
    owns the downstream/branching gates."""
    if current in goal_planner.GATE_STATES:
        return advance_state(current, collected, upsell_count=upsell_count)
    return goal_planner.next_goal(collected, upsell_count=upsell_count)


def _apply_fields(state: ConversationState, fields: dict, collected: dict, message: str) -> None:
    """Merge validated interpreter fields into collected and derive the branch
    booleans the state machine reads. The interpreter does not emit the yes/no
    booleans for confirmation states, so we derive those from the raw message
    (works with and without an LLM key)."""
    S = ConversationState
    low = message.lower()

    # Deterministic name capture: a bare first name must fill `name` no matter
    # how the interpreter classified the turn (fixes the double name-ask). Skip
    # obvious non-answers (questions).
    if state is S.ASK_NAME and not collected.get("name"):
        candidate = message.strip().split("\n")[0][:60]
        if candidate and "?" not in candidate:
            collected["name"] = candidate

    for key in (
        "name", "purpose", "quantity", "decoration_type",
        "placement_zone", "placement_position", "remove_bg", "has_logo", "youth_flag",
    ):
        if key in fields and fields[key] is not None:
            collected[key] = fields[key]

    # Merged placement: a zone is enough. Default the position to centre so we
    # never spend a separate turn asking for it (the customer can fine-tune via
    # the pin tool). An explicitly-provided position is preserved.
    if collected.get("placement_zone") and not collected.get("placement_position"):
        collected["placement_position"] = "centre"

    # Decoration default: if the customer just accepted the recommendation,
    # neither the interpreter nor the heuristic set decoration_type — fall back
    # to the recommended type for the current state (mirrors the old _ingest).
    if state in (S.WARN_PRINT_SETUP, S.RECOMMEND_DECORATION, S.RECOMMEND_EMBROIDERY):
        if not collected.get("decoration_type"):
            collected["decoration_type"] = "embroidery" if state is S.RECOMMEND_EMBROIDERY else "print"

    # has_logo: derive from the raw message when the interpreter didn't set it,
    # so "Upload logo" / "I have a logo" reliably reaches the uploader dialog and
    # "describe" / "walk me through" goes to the describe path. Describe/negative
    # signals are checked first so "no logo, describe it" doesn't read as a yes.
    if state is S.ASK_HAS_LOGO and "has_logo" not in fields:
        _describe = ("describe", "walk me", "instead", "no logo", "don't have",
                     "dont have", "haven't", "havent", "without", "rather")
        _has = ("logo", "upload", "artwork", "art work", "file", "have", "got",
                "yes", "yep", "yeah")
        if any(w in low for w in _describe):
            collected["has_logo"] = False
        elif any(w in low for w in _has) and not is_negative(message):
            collected["has_logo"] = True
        elif fields.get("design_description"):
            collected["has_logo"] = False

    # Confirmation states: derive the boolean from the raw message.
    if state is S.ASK_MORE_ELEMENTS:
        decline = is_negative(message) or any(w in low for w in _DONE_ELEMENTS)
        collected["wants_more_elements"] = not decline
    elif state is S.ADD_ELEMENTS_MODE:
        decline = is_negative(message) or any(w in low for w in _DONE_ELEMENTS)
        collected["add_another_element"] = not decline
    elif state is S.ASK_PIN_ANNOTATION:
        collected["wants_pins"] = is_affirmative(message) and not is_negative(message)
    elif state is S.PIN_ANNOTATE_MODE:
        collected["add_another_pin"] = "another" in low or (is_affirmative(message) and not is_negative(message))
    elif state is S.UPSELL_PROMPT:
        collected["wants_upsell"] = is_affirmative(message) and not is_negative(message)
    elif state is S.OFFER_REFINE:
        collected["wants_changes"] = (
            ("change" in low or "tweak" in low or "edit" in low or "adjust" in low
             or "modif" in low or "different" in low)
            and not ("looks good" in low or "happy" in low)
        )
    if state is S.DESCRIBE_CHANGES:
        collected["last_change"] = message.strip()[:400]


async def _maybe_gather_element(
    state: ConversationState, fields: dict, collected: dict, message: str
) -> None:
    """Extract a design element from this turn (when there is one) and merge it
    into the canonical structured brief. Runs on the describe turn, the gather
    loop, refinement, and any out-of-order turn where the customer volunteered
    design info. Declines and bare acknowledgements contribute nothing to the
    brief in either gather state — but a bare acknowledgement in
    ADD_ELEMENTS_MODE still leaves `add_another_element` True, so the loop
    keeps gathering on the next turn."""
    volunteered = bool(fields.get("design_description"))
    if state not in _ELEMENT_STATES and not volunteered:
        return
    if state is ConversationState.ASK_MORE_ELEMENTS and (
        not collected.get("wants_more_elements") or message.strip().lower() in _BARE_YES
    ):
        return
    if state is ConversationState.ADD_ELEMENTS_MODE and (
        not collected.get("add_another_element") or message.strip().lower() in _BARE_YES
    ):
        return

    incoming = await ie.extract_design_description(message)
    if incoming:
        collected["design_description"] = brief.merge_brief(
            collected.get("design_description") or {}, incoming
        )


def _can_edit(session_id: str) -> bool:
    """Per-session edit cap check. Guarded so this file imports cleanly before
    the limits module (Task 11) exists."""
    try:
        from app.services import limits  # noqa: PLC0415
    except ImportError:
        return True
    return limits.can_edit(session_id)


def _public_data(state: ConversationState, collected: dict) -> dict:
    """Non-PII data the frontend may need to drive the UI for this state.

    `continuable: True` marks a STATEMENT-only state (no question, no typed
    answer expected) so the UI can show a "Continue" affordance. Free-text
    states (ask_name, ask_purpose, describe_design, ask_email) return neither
    options nor `continuable`, so the UI shows the text input only — never a
    misleading Continue button that would submit a throwaway as the answer.
    """
    S = ConversationState
    if state is S.ASK_QUANTITY:
        return {"options": ["1", "2-11", "12-49", "50-99", "100+", "Not sure"]}
    if state is S.ASK_HAS_LOGO:
        return {"options": ["Upload logo", "Describe what I want"]}
    if state is S.ASK_REMOVE_BG:
        return {"options": ["Yes, remove it", "No, keep as-is"]}
    if state is S.ASK_PLACEMENT_ZONE:
        return {"options": ["Front panel", "Side", "Back", "Under-brim"]}
    if state is S.ASK_PLACEMENT_POSITION:
        return {"options": ["Left", "Centre", "Right"], "options2": ["Upper", "Middle", "Lower"]}
    if state in (S.WARN_PRINT_SETUP, S.RECOMMEND_DECORATION, S.RECOMMEND_EMBROIDERY):
        return {"options": ["Yes, that works", "I prefer print", "I prefer embroidery", "What about a patch?"]}
    if state is S.ASK_MORE_ELEMENTS:
        return {"options": ["Add text", "Add a graphic", "That's everything"]}
    if state is S.ADD_ELEMENTS_MODE:
        return {"options": ["That's everything"]}
    if state is S.ASK_PIN_ANNOTATION:
        return {"options": ["Yes, mark a spot", "No, generate now"]}
    if state is S.UPSELL_PROMPT:
        return {"options": ["Yes, add more", "No, I'm happy"]}
    if state is S.GENERATING:
        return {"trigger_generation": True}
    if state is S.SHOW_DESIGN:
        return {"continuable": True}
    if state is S.OFFER_REFINE:
        return {"options": ["Request changes", "Looks good"]}
    if state is S.REGENERATING:
        return {"trigger_regeneration": True}
    # Statement-only states the user taps through (no typed answer expected).
    if state in (
        S.YOUTH_REFERRAL,
        S.EMAIL_VERIFIED,
        S.SEND_PREVIEW_EMAIL,
        S.QUOTE_REQUESTED,
    ):
        return {"continuable": True}
    return {}
