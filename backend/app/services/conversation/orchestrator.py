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

import structlog

from app.config import settings
from app.db import get_supabase
from app.services.stores import get_store
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import (
    ConversationState,
    advance_state,
    allowed_backtracks,
    is_affirmative,
    is_negative,
)

log = structlog.get_logger()

# States that are purely routing or statement nodes — they pose no question and
# all required data was captured during the preceding state's ingest. The
# orchestrator auto-advances through them so every reply the user sees ends with
# an actionable question (otherwise the user's next answer is ingested one state
# late, silently shifting all subsequent captures — an off-by-one).
_AUTO_ADVANCE_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.CHECK_YOUTH,
        ConversationState.DECORATION_ENGINE,
        ConversationState.CONFIRM_DECORATION,
    }
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
        # --- 3. back-track detection ---
        targets = [s.value for s in allowed_backtracks(current)]
        backtrack_target = await ie.detect_backtrack(message, current.value, targets)

        if backtrack_target:
            new_state = ConversationState(backtrack_target)
            log.info("backtrack", session_id=session_id, frm=state_before, to=new_state.value)
        else:
            # --- 4. interpret message for the current state ---
            await _ingest(current, message, collected)
            # --- 5a. advance ---
            new_state = advance_state(
                current, collected, message=message, upsell_count=upsell_count
            )
            if new_state is ConversationState.UPSELL_PROMPT and collected.get("wants_upsell"):
                upsell_count += 1

        # --- 5b. auto-advance through routing-only states ---
        while new_state in _AUTO_ADVANCE_STATES:
            new_state = advance_state(
                new_state, collected, message="", upsell_count=upsell_count
            )

        # --- 6. word the reply ---
        reply = await ie.generate_reply(new_state.value, collected, persona)

    # --- 7. persist state + messages ---
    sb.table("design_sessions").update(
        {
            "state": new_state.value,
            "collected": collected,
            "upsell_count": upsell_count,
            "updated_at": "now()",
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

    return {
        "reply": reply,
        "state": new_state.value,
        "data": _public_data(new_state, collected),
    }


async def _ingest(state: ConversationState, message: str, collected: dict) -> None:
    """Mutate `collected` based on the answer to the current state's question.

    GREETING is intentionally excluded — name capture only happens at ASK_NAME.
    """
    S = ConversationState

    if state is S.ASK_NAME:
        # Capture the name verbatim (first line, trimmed, max 60 chars).
        name = message.strip().split("\n")[0][:60]
        if name:
            collected["name"] = name

    elif state is S.ASK_PURPOSE:
        collected["purpose"] = message.strip()
        collected["youth_flag"] = await ie.detect_youth(message)

    elif state is S.ASK_QUANTITY:
        collected["quantity"] = await ie.parse_quantity(message)

    elif state in (S.WARN_PRINT_SETUP, S.RECOMMEND_DECORATION, S.RECOMMEND_EMBROIDERY):
        # Capture an explicit decoration preference if stated, else use the recommendation.
        low = message.lower()
        if "embroid" in low:
            collected["decoration_type"] = "embroidery"
        elif "patch" in low:
            collected["decoration_type"] = "patch"
        elif "print" in low:
            collected["decoration_type"] = "print"
        else:
            collected.setdefault(
                "decoration_type",
                "embroidery" if state is S.RECOMMEND_EMBROIDERY else "print",
            )

    elif state is S.ASK_HAS_LOGO:
        low = message.lower()
        has_logo = ("upload" in low or "logo" in low or "yes" in low or "artwork" in low) and not (
            "describe" in low or "instead" in low or "don't" in low
        )
        collected["has_logo"] = has_logo

    elif state is S.ASK_REMOVE_BG:
        collected["remove_bg"] = is_affirmative(message) or "remove" in message.lower()

    elif state is S.DESCRIBE_DESIGN:
        collected["design_description"] = await ie.extract_design_description(message)

    elif state is S.ASK_PLACEMENT_ZONE:
        collected["placement_zone"] = _match_zone(message)

    elif state is S.ASK_PLACEMENT_POSITION:
        collected["placement_position"] = message.strip()[:60]

    elif state is S.ASK_PIN_ANNOTATION:
        collected["wants_pins"] = is_affirmative(message) and not is_negative(message)

    elif state is S.PIN_ANNOTATE_MODE:
        collected["add_another_pin"] = "another" in message.lower() or (
            is_affirmative(message) and not is_negative(message)
        )

    elif state is S.UPSELL_PROMPT:
        collected["wants_upsell"] = is_affirmative(message) and not is_negative(message)


def _match_zone(message: str) -> str:
    low = message.lower()
    if "under" in low or "brim" in low:
        return "under_brim"
    if "side" in low:
        return "side"
    if "back" in low:
        return "back"
    return "front_panel"


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
    # Statement-only states the user taps through (no typed answer expected).
    if state in (
        S.YOUTH_REFERRAL,
        S.EMAIL_VERIFIED,
        S.SEND_PREVIEW_EMAIL,
        S.QUOTE_REQUESTED,
    ):
        return {"continuable": True}
    return {}
