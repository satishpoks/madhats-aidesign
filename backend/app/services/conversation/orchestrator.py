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
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import (
    AUTO_ADVANCE_STATES,
    ConversationState,
    QUESTION_FIELD,
    advance_and_skip,
    advance_state,
    allowed_backtracks,
    is_affirmative,
    is_negative,
    progress,
)

log = structlog.get_logger()


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
        if intent in ("ask_question", "chitchat"):
            # Answer/redirect, then RE-ASK the current question. Do not advance.
            new_state = current
            reply = await ie.generate_reply(
                current.value, collected, persona, aside=interp.get("question_answer") or None
            )
        else:
            if intent in ("revise", "backtrack"):
                target = interp.get("revise_target") or interp.get("backtrack_target")
                new_state = ConversationState(target) if target else current
                if target:
                    log.info("backtrack", session_id=session_id, frm=state_before, to=new_state.value)
            elif current is ConversationState.OFFER_REFINE and collected.get("wants_changes"):
                # Enforce the per-session edit cap here (guarded import so this
                # file works before Task 11 lands).
                if _can_edit(session_id):
                    new_state = ConversationState.DESCRIBE_CHANGES
                else:
                    collected["edit_cap_reached"] = True
                    new_state = ConversationState.QUOTE_REQUESTED
            else:
                new_state = advance_and_skip(
                    current, collected, message=message, upsell_count=upsell_count
                )
            if new_state is ConversationState.UPSELL_PROMPT and collected.get("wants_upsell"):
                upsell_count += 1
            # auto-advance through routing-only states
            while new_state in AUTO_ADVANCE_STATES:
                new_state = advance_state(new_state, collected, upsell_count=upsell_count)
            reply = await ie.generate_reply(new_state.value, collected, persona)

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


def _apply_fields(state: ConversationState, fields: dict, collected: dict, message: str) -> None:
    """Merge validated interpreter fields into collected and derive the branch
    booleans the state machine reads. The interpreter does not emit the yes/no
    booleans for confirmation states, so we derive those from the raw message
    (works with and without an LLM key)."""
    S = ConversationState
    low = message.lower()

    for key in (
        "name", "purpose", "quantity", "decoration_type", "design_description",
        "placement_zone", "placement_position", "remove_bg", "has_logo", "youth_flag",
    ):
        if key in fields and fields[key] is not None:
            collected[key] = fields[key]

    # Decoration default: if the customer just accepted the recommendation,
    # neither the interpreter nor the heuristic set decoration_type — fall back
    # to the recommended type for the current state (mirrors the old _ingest).
    if state in (S.WARN_PRINT_SETUP, S.RECOMMEND_DECORATION, S.RECOMMEND_EMBROIDERY):
        if not collected.get("decoration_type"):
            collected["decoration_type"] = "embroidery" if state is S.RECOMMEND_EMBROIDERY else "print"

    # has_logo fallback: not explicitly set but a description was given -> describe path.
    if state is S.ASK_HAS_LOGO and "has_logo" not in fields and fields.get("design_description"):
        collected["has_logo"] = False

    # Confirmation states: derive the boolean from the raw message.
    if state is S.ASK_PIN_ANNOTATION:
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
