"""v2 step-by-step canvas orchestrator (parallel to orchestrator.py).

Owns the front half: greeting -> name -> admin intro -> logo loop (<=4) ->
text/shape loop -> quantity -> email -> purpose -> FINALIZE_CANVAS. From
FINALIZE_CANVAS the frontend flattens the canvas and calls /canvas-finalize,
which routes into the SHARED tail (GENERATING -> verify -> deliver -> refine).
Selected only when settings.canvas_orchestrator_v2 and flow_mode == "canvas".
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services import leads as leads_service
from app.services.branding import canvas_intro_text
from app.services.stores import get_store
from app.services.conversation import intent_extractor as ie
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation import orchestrator as _v1
from app.services.conversation.orchestrator import (
    SessionNotFound,
    _can_start_design,        # reused
)
from app.services.conversation.state_machine import (
    ConversationState,
    is_affirmative,
    is_negative,
)

S = ConversationState

# States v2 owns (its front half). Every other state is a shared tail state
# that v1's orchestrator already handles fully (refine loop, quote, upsell) —
# delegate those turns to v1 so a canvas session isn't stranded post-design.
#
# LOAD-BEARING INVARIANT: ASK_EMAIL is claimed by v2 here (not delegated to
# the shared tail) — that's only safe because v2 guarantees `email_captured`
# is set via the double opt-in capture inline in `handle_message` below
# BEFORE `advance_state_v2` is ever allowed to leave ASK_EMAIL, and again
# before FINALIZE_CANVAS is reached. If ASK_EMAIL is ever removed from this
# set (delegated to v1 instead), that guarantee no longer holds and a canvas
# session could reach FINALIZE_CANVAS with no verified lead.
_V2_OWNED = v2.V2_STATES | {S.GREETING, S.ASK_NAME, S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE}

# Word-boundary matched (like v1's `_DONE_ELEMENTS_RE` in orchestrator.py) so
# "good" doesn't match inside another word, and multi-word phrases match as a
# whole. `is_negative`/the "n't" check run first in `_is_done` so a negated
# reply ("not ready", "isn't good") never reads as done.
_DONE_WORDS = ("done", "looks good", "that's it", "thats it", "finished", "ready", "good")
_DONE_WORDS_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _DONE_WORDS) + r")\b")


def _is_done(message: str) -> bool:
    low = (message or "").strip().lower()
    # `is_negative` already catches "no"/"not" (substring — "not" contains
    # "no"); "n't" contractions (e.g. "isn't good") don't contain any
    # _NEGATIVE keyword as a substring, so check them explicitly.
    if is_negative(message) or "n't" in low:
        return False
    if _DONE_WORDS_RE.search(low):
        return True
    return is_affirmative(message)


def _face_from(message: str) -> str | None:
    low = (message or "").lower()
    for f in ("front", "back", "left", "right"):
        if f in low:
            return f
    return None


def _apply_v2_fields(state: ConversationState, collected: dict, message: str) -> None:
    """Capture the field(s) a v2 state expects, mutating ``collected`` in place.

    At ASK_EMAIL this only stashes the parsed address as ``_pending_email``;
    the actual double-opt-in capture (which needs the full session row) stays
    inline in ``handle_message``.
    """
    low = (message or "").strip().lower()

    if state is S.ASK_NAME and not collected.get("name"):
        candidate = message.strip().split("\n")[0][:60]
        if candidate and "?" not in candidate and not ie._is_greeting_only(candidate):
            collected["name"] = candidate

    elif state is S.ASK_LOGO_PLACEMENT:
        face = _face_from(message)
        if face:
            collected["logo_face"] = face

    elif state is S.LOGO_ADJUST:
        if _is_done(message):
            collected["logo_done"] = True
            collected["logo_count"] = int(collected.get("logo_count") or 0) + 1

    elif state is S.ASK_ANOTHER_LOGO:
        collected["wants_another_logo"] = is_affirmative(message) and not is_negative(message)
        collected["logo_done"] = False  # reset for the next loop iteration
        if collected["wants_another_logo"]:
            # Clear the previous logo's face so loop 2 re-asks ASK_LOGO_PLACEMENT
            # cleanly instead of `_logo_face` defaulting to the prior answer.
            collected.pop("logo_face", None)

    elif state is S.ASK_ADD_DECOR:
        # Reset per loop entry — a stale decor_choice/decor_answered from a
        # previous pass through this loop must never leak into this turn's
        # decision.
        collected.pop("decor_choice", None)
        if is_negative(message) or "nothing" in low:
            collected["decor_choice"] = None
            collected["decor_answered"] = True
        elif "text" in low:
            collected["decor_choice"] = "text"
            collected["decor_answered"] = True
        elif "shape" in low or "graphic" in low:
            collected["decor_choice"] = "shape"
            collected["decor_answered"] = True
        else:
            # Ambiguous/unrecognised free text — do NOT silently decline;
            # advance_state_v2 re-asks while decor_answered is False.
            collected["decor_answered"] = False
        collected["decor_done"] = False

    elif state is S.DECOR_ADJUST:
        if _is_done(message):
            collected["decor_done"] = True

    elif state is S.ASK_ANYTHING_ELSE:
        collected["wants_more_decor"] = (
            is_affirmative(message) or "add" in low
        ) and not is_negative(message)

    elif state is S.ASK_QUANTITY:
        collected["quantity"] = ie._parse_quantity_heuristic(message)

    elif state is S.ASK_PURPOSE:
        collected["purpose"] = message.strip()

    # Email capture (double opt-in) at ASK_EMAIL.
    if state is S.ASK_EMAIL and not collected.get("email_captured"):
        email = leads_service.extract_email(message)
        if email:
            # Need the full session row for capture; caller passes collected only,
            # so this branch is handled in handle_message (has the session).
            collected["_pending_email"] = email


async def handle_message(session_id: str, message: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])

    # Only the front half is v2's. Every shared tail state (refine loop, quote,
    # upsell, change-method …) is fully handled by v1's orchestrator — delegate
    # so a canvas session isn't stranded once it reaches the tail.
    if current not in _V2_OWNED:
        return await _v1.handle_message(session_id, message)

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro_text = canvas_intro_text(store)
    state_before = current.value

    # KICKOFF: greet + advance to ASK_NAME without ingesting the opening turn.
    if current is S.GREETING:
        new_state = S.ASK_NAME
        reply = v2.v2_reply(new_state, collected, persona, intro_text)
    else:
        _apply_v2_fields(current, collected, message)

        # Email capture needs the full session row (leads.capture_lead_and_verify).
        # No separate "retry" tracking needed: when capture fails (ok=False),
        # `email_captured` is simply never set, so `advance_state_v2` below
        # already re-asks ASK_EMAIL on its own (its ASK_EMAIL branch checks
        # `collected.get("email_captured")`).
        if current is S.ASK_EMAIL and collected.pop("_pending_email", None):
            email = leads_service.extract_email(message)
            if email:
                lead_id, ok = leads_service.capture_lead_and_verify(session, collected, email)
                if lead_id:
                    collected["lead_id"] = lead_id
                if ok:
                    collected["email_captured"] = True

        new_state = v2.advance_state_v2(current, collected)

        # Daily-cap honesty gate on entry to FINALIZE_CANVAS (which leads to
        # generation): reroute to the quote handoff if the customer is capped.
        # QUOTE_REQUESTED is a shared tail state, so the NEXT turn delegates to
        # v1 (Fix 1) — but THIS turn must still speak honestly and pose the
        # quote ask, since v2_reply/v2_public_data have no copy for it.
        capped = False
        if new_state is S.FINALIZE_CANVAS and not _can_start_design(session_id):
            collected["generation_blocked"] = "daily_limit"
            new_state = S.QUOTE_REQUESTED
            capped = True

        # One-shot flag: mark the intro shown.
        if new_state is S.SHOW_INTRO:
            collected["intro_shown"] = True

        if capped:
            reply = f"{prompts.GENERATION_BLOCKED_ASIDE} {prompts.CANVAS_QUOTE_ASK}"
        else:
            reply = v2.v2_reply(new_state, collected, persona, intro_text)

    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert([
        {"session_id": session_id, "role": "user", "content": message,
         "state_before": state_before, "state_after": state_before},
        {"session_id": session_id, "role": "assistant", "content": reply,
         "state_before": state_before, "state_after": new_state.value},
    ]).execute()

    if new_state is S.QUOTE_REQUESTED:
        # Match v1's canvas quote ask chips (v2_public_data has no copy for the
        # shared tail state).
        data = {"options": ["Yes, request a quote", "No, I'm all set"],
                "progress": v2.progress_v2(new_state, collected)}
    else:
        data = v2.v2_public_data(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}
