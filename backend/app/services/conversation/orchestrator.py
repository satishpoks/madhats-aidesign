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

import re
from datetime import datetime, timezone

import structlog

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services import colours
from app.services import design_summary
from app.services import leads as leads_service
from app.services import settings_service
from app.services.stores import get_store
from app.services.conversation import brief
from app.services.conversation import element_planner as ep
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
# Word-boundary matcher for the above — a plain substring scan lets "ready"
# match inside "already" (Finding 2), wrongly treating "already have the
# logo, also add a star" as a decline and silently dropping the element.
_DONE_ELEMENTS_RE = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _DONE_ELEMENTS) + r")\b"
)

# States where a (non-declining) message contributes a design element.
# ASK_MORE_ELEMENTS / ADD_ELEMENTS_MODE no longer gather a flat brief — the
# per-element deep-dive (`_advance_elements`) owns element capture now. Only
# DESCRIBE_CHANGES (refinement) still merges into the structured brief here;
# any other state can still reach `merge_brief` via the volunteered-fields
# escape hatch below.
_ELEMENT_STATES = frozenset({ConversationState.DESCRIBE_CHANGES})
# Bare acknowledgements that carry no element to extract on their own.
_BARE_YES = frozenset(
    {"yes", "yeah", "yep", "sure", "ok", "okay", "add text", "add a graphic", "add graphic"}
)

# Bare type-choice phrasings (the ASK_MORE_ELEMENTS chips, plus their obvious
# typed equivalents) that carry ONLY the type -- no volunteered content. These
# must keep just seeding {type, deferred: []} and asking content next, with no
# extraction call. Anything else typed at ASK_MORE_ELEMENTS (e.g. "add text
# saying GO TEAM") is assumed to carry more than the bare type and gets one
# extraction pass so volunteered content/colour/etc. isn't silently dropped
# and re-asked (Finding 5, whole-branch review).
_BARE_ELEMENT_CHOICES = frozenset(
    {"add text", "add a graphic", "add graphic", "add a note", "add note"}
)

# Keyword -> element type, checked in order (first match wins). Used to
# classify a type choice typed/tapped at ASK_MORE_ELEMENTS.
_ELEMENT_TYPE_WORDS = (
    ("note", "note"),
    ("graphic", "graphic"), ("logo", "graphic"), ("icon", "graphic"),
    ("image", "graphic"), ("picture", "graphic"), ("pic", "graphic"),
    ("text", "text"), ("word", "text"), ("slogan", "text"), ("name", "text"),
    ("wording", "text"), ("say", "text"),
)


def _element_type_from(message: str) -> str | None:
    low = message.lower()
    for word, etype in _ELEMENT_TYPE_WORDS:
        if word in low:
            return etype
    return None


def _looks_like_text(message: str) -> bool:
    """Heuristic: a short, wording-like message is probably a text element
    (e.g. "TEAM ROCKET" or "our slogan"), otherwise treat it as a graphic
    description."""
    return len(message.split()) <= 5 and any(c.isalpha() for c in message)


# A refine turn that ADDS a new decoration (vs. modifying the existing one).
_ADD_ELEMENT_RE = re.compile(r"\b(add|adding|include|put|also|another|extra|new|second)\b", re.I)


def _refine_new_element_type(message: str) -> str | None:
    """If a refine message asks to ADD a text/graphic/note, return its type."""
    if not _ADD_ELEMENT_RE.search(message or ""):
        return None
    etype = _element_type_from(message or "")
    return etype if etype in ("text", "graphic", "note") else None


def _parse_change_views(message: str) -> list[str]:
    """Which cap views a change text names (front/back/left/right). An unqualified
    'side' means both sides. Used to re-render ONLY the affected views on an edit."""
    low = (message or "").lower()
    views: list[str] = []
    if "back" in low:
        views.append("back")
    if "right" in low:
        views.append("right")
    if "left" in low:
        views.append("left")
    if "side" in low and "right" not in low and "left" not in low:
        views.extend(["left", "right"])
    if any(w in low for w in ("front", "under", "brim", "peak")):
        views.append("front")
    return views


def _add_refine_views(collected: dict, views: list[str]) -> None:
    acc = collected.setdefault("refine_views", [])
    for v in views:
        if v not in acc:
            acc.append(v)


async def _apply_refine(current: ConversationState, collected: dict, message: str) -> None:
    """Own field capture for the refine sub-flow.

    Accumulates every refinement instruction into ``refine_details`` (compiled
    into the regeneration prompt). A request to ADD a new text/graphic/note seeds
    a ``pending_element`` so the SAME per-element deep-dive as the main flow runs
    (asking placement etc. with chips); otherwise a modification builds a short
    follow-up-question queue.
    """
    S = ConversationState
    text = (message or "").strip()
    low = text.lower()
    collected["refine_mode"] = True
    details = collected.setdefault("refine_details", [])
    # Track which views the change touches so regeneration re-renders ONLY those.
    _add_refine_views(collected, _parse_change_views(text))

    async def _seed_element(etype: str) -> None:
        el: dict = {"type": etype, "deferred": []}
        if etype == "note":
            el["content"] = text[:300]
        else:
            attrs = await ie.extract_element_attributes(etype, text)
            attrs.pop("defer", None)
            for k, v in attrs.items():
                if v not in (None, "") and k not in el:
                    el[k] = v
        collected["pending_element"] = el

    if current is S.DESCRIBE_CHANGES:
        details.append(text[:400])
        collected["last_change"] = text[:400]
        etype = _refine_new_element_type(text)
        if etype:
            await _seed_element(etype)
            return
        collected["refine_followups"] = await ie.refine_followups(text, collected)
        collected["refine_followup_idx"] = 0
        return

    if current is S.REFINE_FOLLOWUP:
        details.append(text[:200])
        collected["refine_followup_idx"] = int(collected.get("refine_followup_idx") or 0) + 1
        return

    if current is S.REFINE_CONFIRM:
        # "Anything else?" — a further add deep-dives; anything else is extra
        # detail; a decline ends the loop (advance_state -> REGENERATING).
        if is_negative(text) or bool(_DONE_ELEMENTS_RE.search(low)):
            return
        etype = _refine_new_element_type(text)
        if etype:
            await _seed_element(etype)
        else:
            details.append(text[:200])


_CONFIRM_WORDS = (
    "generate", "looks good", "confirm", "go ahead", "that's right", "thats right",
    "perfect", "correct", "all good", "spot on", "that's everything",
)


async def _apply_brief_confirm(collected: dict, message: str) -> None:
    """Field capture at the pre-generation CONFIRM_BRIEF step.

    Confirming moves to generation; adding a text/graphic/note deep-dives it
    (``brief_confirm_mode`` routes back here after); anything else is recorded as
    a note folded into the image prompt.
    """
    text = (message or "").strip()
    low = text.lower()
    etype = _refine_new_element_type(text)
    if etype:
        collected["brief_confirm_mode"] = True
        el: dict = {"type": etype, "deferred": []}
        if etype == "note":
            el["content"] = text[:300]
        else:
            attrs = await ie.extract_element_attributes(etype, text)
            attrs.pop("defer", None)
            for k, v in attrs.items():
                if v not in (None, "") and k not in el:
                    el[k] = v
        collected["pending_element"] = el
        return
    if (is_affirmative(text) or any(w in low for w in _CONFIRM_WORDS)) and not is_negative(text):
        collected["brief_confirmed"] = True
        return
    # A change or note -> record it for the prompt and re-summarise.
    collected.setdefault("brief_notes", []).append(text[:300])


# Map a decoration name to the prompt style modifier bucket. Anything not
# recognised falls back to print (the safe default the prompt builder uses).
_DECORATION_STYLE_MAP = (
    ("embroider", "embroidery"),
    ("stitch", "embroidery"),
    ("patch", "embroidery"),   # patches render like stitched appliqué
    ("print", "print"),
    ("vinyl", "print"),
    ("transfer", "print"),
    ("screen", "print"),
)


def _decoration_style_bucket(name: str) -> str:
    low = (name or "").lower()
    for kw, bucket in _DECORATION_STYLE_MAP:
        if kw in low:
            return bucket
    return "print"


def _apply_canvas_outro(state: ConversationState, collected: dict, message: str) -> None:
    """Capture the canvas outro answers (decoration multi-select, then notes)."""
    S = ConversationState
    text = (message or "").strip()
    low = text.lower()

    if state is S.ASK_DECORATION:
        options = collected.get("decoration_options") or []
        # The message is the customer's chosen chips, comma-joined (or free text).
        # Match each comma-separated token EXACTLY against an offered option
        # (case-insensitive), preserving the customer's order so their first choice
        # drives the render style. Exact-token match avoids a shorter option name
        # matching inside a longer one (e.g. "Print" inside "Screen Print").
        by_name = {opt.lower(): opt for opt in options}
        chosen: list[str] = []
        for tok in (message or "").split(","):
            opt = by_name.get(tok.strip().lower())
            if opt and opt not in chosen:
                chosen.append(opt)
        collected["decoration_types"] = chosen
        collected["decoration_done"] = True
        if chosen:
            collected.setdefault("brief_notes", []).append(
                f"Decoration method: {', '.join(chosen)}"
            )
            # First choice (in the customer's order) drives the render style modifier.
            collected["decoration_type"] = _decoration_style_bucket(chosen[0])
        return

    if state is S.ASK_NOTES:
        collected["notes_done"] = True
        _skip = is_negative(text) or bool(_DONE_ELEMENTS_RE.search(low))
        if text and not _skip:
            collected["notes"] = text[:600]
            collected.setdefault("brief_notes", []).append(text[:600])
        return


class SessionNotFound(Exception):
    pass


def _apply_generation_gate(
    new_state: ConversationState, collected: dict, *, can_start_design: bool
) -> tuple[ConversationState, str | None]:
    """Guard entry into GENERATING against the per-day design cap.

    When the customer has hit their daily design limit, POST /generate/preview
    returns 429 with NO generation row created. The frontend deliberately
    swallows generation errors (to hide *transient* provider failures), so it
    would advance the flow and falsely announce the design is ready — with
    nothing generated, no retry, and no backfill. So never route to GENERATING
    when a fresh design can't be started: reroute to the quote handoff and speak
    an honest aside instead. Returns ``(state, aside_or_None)``.
    """
    if new_state is ConversationState.GENERATING and not can_start_design:
        collected["generation_blocked"] = "daily_limit"
        return ConversationState.QUOTE_REQUESTED, prompts.GENERATION_BLOCKED_ASIDE
    return new_state, None


def _can_start_design(session_id: str) -> bool:
    """Daily-cap check for the session's lead email (True when no lead yet)."""
    from app.services import limits  # noqa: PLC0415

    res = (
        get_supabase()
        .table("leads")
        .select("email")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    email = res.data[0]["email"] if res.data else None
    return limits.can_start_design(email)


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
        # Refine capture runs BEFORE the brief-merge so an "add element" seeds a
        # pending_element and doesn't ALSO leak into the flat design brief.
        if current in (
            ConversationState.DESCRIBE_CHANGES,
            ConversationState.REFINE_FOLLOWUP,
            ConversationState.REFINE_CONFIRM,
        ):
            await _apply_refine(current, collected, message)
        elif current is ConversationState.CONFIRM_BRIEF:
            await _apply_brief_confirm(collected, message)
        elif current in (ConversationState.ASK_DECORATION, ConversationState.ASK_NOTES):
            _apply_canvas_outro(current, collected, message)
        await _maybe_gather_element(current, interp.get("fields") or {}, collected, message)
        await _advance_elements(current, collected, message)

        # --- 4b. email capture (inline, no separate form) ---
        # SAVE_PROGRESS_EMAIL asks for the email right after the design source
        # is captured; GENERATING and ASK_EMAIL only fallback-capture it later
        # if that early ask was skipped or unusable. We already have the
        # customer's name, so the moment a usable email arrives we create the
        # lead and send a verification email — no second form. The preview
        # itself is released when the customer clicks that link.
        if current in (
            ConversationState.GENERATING,
            ConversationState.ASK_EMAIL,
            ConversationState.SAVE_PROGRESS_EMAIL,
        ) and not collected.get("email_captured"):
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
                # Canvas sessions choose HOW to change first (rework on the
                # canvas vs describe here); the legacy flow describes directly.
                new_state = (
                    ConversationState.ASK_CHANGE_METHOD
                    if collected.get("flow_mode") == "canvas"
                    else ConversationState.DESCRIBE_CHANGES
                )
            else:
                collected["edit_cap_reached"] = True
                new_state = ConversationState.QUOTE_REQUESTED
        else:
            new_state = _route(current, collected, upsell_count)

        # "Rework on the canvas" reopens the canvas for editing: clear the
        # finalized flag (so the overlay unlocks) and mark the rework so
        # canvas-finalize re-renders instead of re-running the outro questions.
        if new_state is ConversationState.CANVAS_DESIGN and current is ConversationState.ASK_CHANGE_METHOD:
            collected["canvas_finalized"] = False
            collected["reworking"] = True

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
        elif new_state is ConversationState.SAVE_PROGRESS_EMAIL:
            collected["email_prompt_shown"] = True
        elif new_state is ConversationState.ASK_MORE_ELEMENTS:
            collected["elements_offered"] = True
        elif new_state is ConversationState.ASK_PIN_ANNOTATION:
            collected["pin_offered"] = True

        # Pre-generation confirmation: before the FIRST render, summarise the
        # extracted brief and let the customer confirm / adjust / add notes.
        # AI designs are limited, so we make sure everything's captured first.
        # Intercept EVERY path into GENERATING at this one point.
        if (
            new_state is ConversationState.GENERATING
            and not collected.get("brief_confirmed")
            and collected.get("flow_mode") != "canvas"
        ):
            new_state = ConversationState.CONFIRM_BRIEF
            collected["brief_prompt_shown"] = True

        # Daily-design cap: if we'd enter GENERATING but the customer has used up
        # their per-day design allowance, generation would 429 and the frontend
        # would falsely claim success. Reroute to an honest quote handoff.
        if new_state is ConversationState.GENERATING and not _can_start_design(session_id):
            new_state, gate_aside = _apply_generation_gate(
                new_state, collected, can_start_design=False
            )
            aside = gate_aside if not aside else f"{gate_aside} {aside}"

        ask_for = None
        ask_text = None
        if new_state is ConversationState.ELEMENT_DEEPDIVE and collected.get("pending_element"):
            ask_for = ep.next_attribute(collected["pending_element"])
            collected["deepdive_ask_for"] = ask_for
        elif new_state is ConversationState.REFINE_FOLLOWUP:
            queue = collected.get("refine_followups") or []
            idx = int(collected.get("refine_followup_idx") or 0)
            if idx < len(queue):
                ask_text = queue[idx]

        if new_state is ConversationState.CONFIRM_BRIEF:
            # Deterministic summary (never paraphrased by the LLM, so no captured
            # detail is dropped before the customer confirms).
            summary = design_summary.customer_brief(collected, session.get("product_ref") or {})
            reply = prompts.CONFIRM_BRIEF_MESSAGE.format(summary=summary)
            if aside:
                reply = f"{aside} {reply}"
        else:
            reply = await ie.generate_reply(
                new_state.value, collected, persona, aside=aside, ask_for=ask_for, ask_text=ask_text,
                element=collected.get("pending_element"),
            )

        # Canvas quote handoff: on entry to the quote ask, pose the yes/no
        # question; on the closing turn surface the quote link (if they said
        # yes) so the frontend can open the /quote page in a new tab.
        if collected.get("flow_mode") == "canvas":
            if new_state is ConversationState.QUOTE_REQUESTED:
                reply = prompts.CANVAS_QUOTE_ASK
            elif new_state is ConversationState.SESSION_END and current is ConversationState.QUOTE_REQUESTED:
                if collected.get("wants_quote"):
                    quote_url = _session_quote_url(session_id)
                    if quote_url:
                        collected["quote_url"] = quote_url
                    reply = prompts.CANVAS_QUOTE_YES
                else:
                    reply = prompts.CANVAS_QUOTE_NO

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

    ack = "Your email's verified — your design is on its way to your inbox."
    reply = await ie.generate_reply(new_state.value, collected, persona, aside=ack)

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
    # Clear the refine sub-flow scratch so the NEXT edit starts fresh.
    for k in ("refine_mode", "refine_details", "refine_followups", "refine_followup_idx",
              "last_change", "refine_views"):
        collected.pop(k, None)

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


async def advance_after_generation(session_id: str) -> dict:
    """One-shot advance used by the chat right after preview generation settles.

    The email is captured earlier now (SAVE_PROGRESS_EMAIL), so GENERATING has
    no user email turn to move it forward. The frontend calls this once, after
    startGeneration(sessionId) settles (success or failure), to advance:
      - email captured + already verified (clicked the link during the
        deep-dive) -> collapse straight through to OFFER_REFINE;
      - email captured, not yet verified -> rest at VERIFY_EMAIL (the verify
        poll finishes it);
      - no email captured -> ASK_EMAIL (terminal fallback ask).
    No-op (reply=None) if the session isn't at GENERATING.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}

    if current is not ConversationState.GENERATING:
        data = _public_data(current, collected)
        data["progress"] = progress(current, collected)
        return {"reply": None, "state": current.value, "data": data}

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name

    new_state = advance_state(current, collected)  # VERIFY_EMAIL or ASK_EMAIL
    aside = None
    if new_state is ConversationState.VERIFY_EMAIL and collected.get("email_verified"):
        # Verified during the deep-dive — collapse through the post-verification
        # statement states to OFFER_REFINE (same landing as check_verification).
        new_state = advance_state(new_state, collected)  # EMAIL_VERIFIED
        while new_state in AUTO_ADVANCE_STATES:
            new_state = advance_state(new_state, collected)
        aside = "Your email's verified — your design is on its way to your inbox."

    reply = await ie.generate_reply(new_state.value, collected, persona, aside=aside)

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


def _route(
    current: ConversationState, collected: dict, upsell_count: int
) -> ConversationState:
    """Forward routing: the goal planner owns the questionnaire; advance_state
    owns the downstream/branching gates."""
    if current in goal_planner.GATE_STATES:
        return advance_state(current, collected, upsell_count=upsell_count)
    return goal_planner.next_goal(collected, upsell_count=upsell_count)


async def _advance_elements(state: ConversationState, collected: dict, message: str) -> None:
    """Own the pending_element lifecycle for the type chooser + deep-dive.

    - ASK_MORE_ELEMENTS: a (non-declining) type choice seeds a fresh
      ``pending_element``; a decline leaves no pending, which routes onward
      (advance_state) toward the pin offer / generation.
    - UPLOAD_LOGO / DESCRIBE_DESIGN: seed the pending element from the design
      source itself, the moment it's available.
    - ELEMENT_DEEPDIVE: extract attributes into the pending element; a defer
      marks the currently-asked attribute deferred; a per-element "done"
      signal defers everything still unset; once the element is complete it
      is appended to ``collected["elements"]`` and the pending slot cleared.
    """
    S = ConversationState
    low = message.strip().lower()

    if state is S.ASK_MORE_ELEMENTS and not collected.get("pending_element"):
        if is_negative(message) or bool(_DONE_ELEMENTS_RE.search(low)):
            return  # declined -> exit handled by advance_state (no pending)
        etype = _element_type_from(message)
        if etype:
            el = {"type": etype, "deferred": []}
            if low not in _BARE_ELEMENT_CHOICES:
                # More than a bare type choice (e.g. "add text saying GO
                # TEAM") -- one extraction pass so volunteered attributes bind
                # to the element now instead of being dropped and re-asked.
                attrs = await ie.extract_element_attributes(etype, message)
                attrs.pop("defer", None)
                for k, v in attrs.items():
                    if v not in (None, ""):
                        el[k] = v
            collected["pending_element"] = el
        return

    if state is S.UPLOAD_LOGO and collected.get("uploaded_asset_path") and not collected.get("pending_element"):
        collected["pending_element"] = {
            "type": "logo",
            "asset_path": collected["uploaded_asset_path"],
            "content": "uploaded logo",
            "deferred": [],
        }
        return

    if state is S.DESCRIBE_DESIGN and not collected.get("pending_element"):
        etype = "text" if _looks_like_text(message) else "graphic"
        el = {"type": etype, "content": message.strip()[:500], "deferred": []}
        collected["pending_element"] = el
        # One extraction pass so a rich description fills volunteered
        # attributes on this same turn (e.g. colour/size) instead of waiting a
        # whole extra turn for the deep-dive to notice them.
        attrs = await ie.extract_element_attributes(etype, message)
        attrs.pop("defer", None)
        for k, v in attrs.items():
            if v not in (None, "") and k not in el:
                el[k] = v
        return

    if state is S.ELEMENT_DEEPDIVE and collected.get("pending_element"):
        el = collected["pending_element"]
        ask_for = collected.get("deepdive_ask_for")
        # per-element done signal -> defer everything remaining
        if bool(_DONE_ELEMENTS_RE.search(low)):
            ep.defer_remaining(el)
        else:
            attrs = await ie.extract_element_attributes(el.get("type"), message, ask_for=ask_for)
            # remove_bg is the only yes/no attribute, so the no-key heuristic
            # can stray-match bare "yes"/"no"/"keep"/"leave" filler in a turn
            # answering a DIFFERENT attribute. Only accept it when it's the
            # attribute currently being asked, so an unrelated later turn
            # can't silently flip an already-answered remove_bg.
            if ask_for != "remove_bg":
                attrs.pop("remove_bg", None)
            deferred_now = attrs.pop("defer", False)
            if deferred_now and ask_for and ask_for != "content":
                if ask_for not in el["deferred"]:
                    el["deferred"].append(ask_for)
            for k, v in attrs.items():
                # Only fill the attribute we asked, or one still unset. A
                # context-free extractor can re-derive an unrelated field from a
                # one-word answer (e.g. "Back" answering placement is also read
                # as content) — that must never clobber an already-captured
                # attribute (regression: text "satish" -> "Back").
                if v in (None, ""):
                    continue
                if k == ask_for or el.get(k) in (None, ""):
                    el[k] = v
            # remove_bg is a strict yes/no the LLM extractor sometimes omits
            # (e.g. it reads "keep as is" as giving no value), which left it
            # unset and looped the question. When it's the attribute being
            # asked, resolve it deterministically from the message.
            if ask_for == "remove_bg" and "remove_bg" not in el and not deferred_now:
                decided = ie.decide_remove_bg(message)
                if decided is not None:
                    el["remove_bg"] = decided
            # a plain answer with no structured field fills the attribute we asked
            # (never on a defer -- that must ONLY append to `deferred`, never
            # write a junk value like "you choose" into the attribute itself)
            if (
                ask_for and ask_for not in el and not attrs and not deferred_now
                and ask_for in ("content", "font", "colour", "style")
            ):
                el[ask_for] = message.strip()[:200]
        if ep.is_complete(el):
            collected.setdefault("elements", []).append(el)
            # An element added during a refine marks its view as affected, so the
            # regeneration re-renders that view (and carries the rest forward).
            if collected.get("refine_mode") or collected.get("brief_confirm_mode"):
                from app.services import prompt_builder  # noqa: PLC0415
                _add_refine_views(collected, [prompt_builder.element_view(el)])
            collected["pending_element"] = None
            collected.pop("deepdive_ask_for", None)


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
    # ASK_MORE_ELEMENTS / ADD_ELEMENTS_MODE are now owned entirely by the
    # pending_element lifecycle in `_advance_elements` — no flat booleans here.
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

    # Change-method choice (canvas refine): rework on the canvas vs describe here.
    if state is S.ASK_CHANGE_METHOD:
        collected["rework_on_canvas"] = (
            ("rework" in low or "canvas" in low or "redesign" in low or "myself" in low)
            and "describe" not in low and "here" not in low
        )

    # Quote ask (canvas): does the customer want to request a quote?
    if state is S.QUOTE_REQUESTED and collected.get("flow_mode") == "canvas":
        collected["wants_quote"] = is_affirmative(message) and not is_negative(message)

    if state is S.COMPOSITE_PREVIEW:
        collected["composite_confirmed"] = is_affirmative(message) and not is_negative(message)
    if state is S.ASK_HAT_COLOUR:
        collected["hat_colour_asked"] = True
        # A tapped colourway chip, a colour name, or a hex typed in chat. Match
        # a tapped/typed name back to its catalogue hex so the composite preview
        # can tint accurately.
        val = message.strip()
        if val and "?" not in val:
            swatches = collected.get("hat_colours") or []
            match = next(
                (c for c in swatches if (c.get("name") or "").strip().lower() == val.lower()), None
            )
            if match:
                collected["hat_colour"] = {"name": match.get("name"), "hex": match.get("hex", "")}
            elif val.startswith("#"):
                collected["hat_colour"] = {"name": val, "hex": val}
            else:
                # A typed colour NAME ("blue", "forest green") — resolve it to a
                # real hex so the tint isn't a grey block.
                collected["hat_colour"] = {"name": val, "hex": colours.name_to_hex(val) or ""}

    if state is S.ASK_COLOUR_DETAIL:
        collected["colour_detail_asked"] = True
        val = message.strip()
        low = val.lower()
        # "Whole hat" / a bare affirmative means one colour everywhere — no note.
        # Anything descriptive (parts + colours, or a colour remark) is captured
        # as a note for the render + the team.
        single = (
            "whole" in low or "one colour" in low or "one color" in low
            or "just this" in low or "keep it simple" in low
            or (is_affirmative(val) and len(low) <= 20)
        )
        if val and "?" not in val and not single:
            collected["colour_note"] = val[:400]


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
    # Finding 4 (whole-branch review): DESCRIBE_DESIGN is no longer an
    # `_ELEMENT_STATES` member -- the per-element deep-dive (`_advance_elements`)
    # owns that state now. But in real no-key operation `interpret_turn` ->
    # `_extract_fields_for_state("describe_design", ...)` still sets
    # `fields["design_description"]`, which makes the `volunteered` escape
    # hatch below fire anyway (an extra flat-brief write, and in keyed mode an
    # extra LLM call) on every describe turn. Guard the state explicitly.
    if state is ConversationState.DESCRIBE_DESIGN:
        return
    # A refine turn that seeded a NEW element (via _apply_refine) is owned by the
    # deep-dive — don't ALSO merge it into the flat brief (double-render).
    if state is ConversationState.DESCRIBE_CHANGES and collected.get("pending_element"):
        return
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

    # Deliberate second extraction call: `fields["design_description"]` (from
    # interpret_turn, if the interpreter set it at all) is a plain string —
    # this call re-extracts the RICH structured dict (text_elements/colours/
    # imagery/style) that the brief needs.
    incoming = await ie.extract_design_description(message)
    if not incoming:
        return
    if state is ConversationState.DESCRIBE_CHANGES and not _is_structured_element(incoming):
        # Finding 1: a refinement turn that produced only a bare `summary`
        # (the no-key path, or the keyed fallback `data or {"summary": message}`)
        # is a freeform instruction like "make the logo bigger" — NOT a new
        # design element. Promoting it here would leak the raw edit text into
        # `text_elements`, and the prompt builder renders those verbatim onto
        # the cap. The edit still reaches generation via `last_change` /
        # `change_request` (set in `_apply_fields`), so nothing is lost.
        return
    collected["design_description"] = brief.merge_brief(
        collected.get("design_description") or {}, incoming
    )


def _is_structured_element(incoming: dict) -> bool:
    """True if the extractor returned real structured content (not just a
    bare summary echo of the raw message). List fields must contain a real
    (non-empty) item — a malformed [""] must not count, mirroring
    `brief.has_incoming_lists`."""
    if incoming.get("style"):
        return True
    return any(
        any(item for item in (incoming.get(k) or []))
        for k in ("text_elements", "colours", "imagery")
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
    """Per-state UI data, plus a cross-state blank-flow tint signal.

    Once a blank-hat colour is chosen, every subsequent turn advertises
    ``tint_ready`` + ``tint_hex`` so the frontend can composite (tint) the blank
    to the chosen colour in the left viewer immediately — no image generation,
    no dedicated chat state.
    """
    data = dict(_state_public_data(state, collected))
    if collected.get("flow_mode") == "blank":
        hc = collected.get("hat_colour")
        if hc:
            data.setdefault("tint_ready", True)
            data.setdefault("tint_hex", (hc.get("hex") if isinstance(hc, dict) else "") or "")
    return data


def _state_public_data(state: ConversationState, collected: dict) -> dict:
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
        return {"options": ["Add text", "Add a graphic", "Add a note", "That's everything"]}
    if state is S.ELEMENT_DEEPDIVE:
        ask = collected.get("deepdive_ask_for")
        chips = {
            "placement_zone": ["Front panel", "Side", "Back", "Under-brim"],
            "placement_position": ["Left", "Centre", "Right"],
            "size": ["Small", "Medium", "Large"],
            "remove_bg": ["Yes, remove it", "No, keep as-is"],
        }.get(ask, [])
        if ask and ask != "content":
            chips = chips + ["You choose"]
        return {"options": chips} if chips else {}
    if state is S.ASK_PIN_ANNOTATION:
        return {"options": ["Yes, mark a spot", "No, generate now"]}
    if state is S.UPSELL_PROMPT:
        return {"options": ["Yes, add more", "No, I'm happy"]}
    if state is S.CONFIRM_BRIEF:
        return {"options": ["Looks good — generate"]}
    if state is S.GENERATING:
        return {"trigger_generation": True}
    if state is S.SHOW_DESIGN:
        return {"continuable": True}
    if state is S.OFFER_REFINE:
        return {"options": ["Request changes", "Looks good"]}
    if state is S.REFINE_CONFIRM:
        return {"options": ["No, that's everything"]}
    if state is S.REGENERATING:
        return {"trigger_regeneration": True}
    # Canvas quote ask is a yes/no question (handled below), NOT a tap-through
    # statement — so it must not fall into the statement-only block.
    if state is S.QUOTE_REQUESTED and collected.get("flow_mode") == "canvas":
        return {"options": ["Yes, request a quote", "No, I'm all set"]}
    # Statement-only states the user taps through (no typed answer expected).
    if state in (
        S.YOUTH_REFERRAL,
        S.EMAIL_VERIFIED,
        S.SEND_PREVIEW_EMAIL,
        S.QUOTE_REQUESTED,
    ):
        return {"continuable": True}
    if state is S.ASK_HAT_COLOUR:
        # Offer the hat type's own colourways as tappable chips (with hex
        # swatches for the UI). Falls back to a free-text colour picker if the
        # catalogue entry has no colourways defined.
        swatches = [c for c in (collected.get("hat_colours") or []) if c.get("name")]
        opts = [c["name"] for c in swatches]
        if opts:
            return {"options": opts, "colour_swatches": swatches, "colour_picker": True}
        return {"colour_picker": True}
    if state is S.ASK_COLOUR_DETAIL:
        # One chip for the simple case; free text captures per-section colours
        # (brim / panels / button / stitching / strap) and any colour remark.
        return {"options": ["Whole hat — one colour"]}
    if state is S.COMPOSITE_PREVIEW:
        return {"options": ["Looks right — generate", "Tweak something"], "composite_preview": True}
    if state is S.ASK_DECORATION:
        return {
            "options": collected.get("decoration_options") or [],
            "multiselect": True,
            "selected": collected.get("decoration_types") or [],
        }
    if state is S.ASK_NOTES:
        return {"options": ["No, generate"]}
    if state is S.ASK_CHANGE_METHOD:
        return {"options": ["Rework on the canvas", "Describe the change here"]}
    if state is S.SESSION_END and collected.get("quote_url"):
        # The customer asked to request a quote — hand them the /quote link so
        # the frontend can show an "Open quote form" button (opens a new tab).
        return {"quote_url": collected["quote_url"]}
    if state is S.CANVAS_DESIGN:
        return {}
    return {}


def _session_quote_url(session_id: str) -> str | None:
    """Build the signed /quote/{token} link for this session's lead (the same
    link referenced in the preview email), for the in-chat quote handoff."""
    res = (
        get_supabase()
        .table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    lead = res.data[0] if res.data else None
    if not lead:
        return None
    token = leads_service.make_quote_token(lead)
    return f"{settings.email_verify_base_url}/quote/{token}"
