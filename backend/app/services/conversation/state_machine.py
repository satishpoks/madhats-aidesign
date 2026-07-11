"""Strict conversation state machine.

Every step and transition is defined here in code. The LLM never decides routing —
it only interprets freeform input into structured data and words the reply. The
machine consumes that structured data to choose the next state.
"""
from __future__ import annotations

from enum import Enum


class ConversationState(str, Enum):
    GREETING = "greeting"
    ASK_NAME = "ask_name"
    ASK_PURPOSE = "ask_purpose"
    CHECK_YOUTH = "check_youth"
    YOUTH_REFERRAL = "youth_referral"
    ASK_QUANTITY = "ask_quantity"
    DECORATION_ENGINE = "decoration_engine"
    WARN_PRINT_SETUP = "warn_print_setup"
    RECOMMEND_DECORATION = "recommend_decoration"
    RECOMMEND_EMBROIDERY = "recommend_embroidery"
    CONFIRM_DECORATION = "confirm_decoration"
    ASK_HAS_LOGO = "ask_has_logo"
    UPLOAD_LOGO = "upload_logo"
    ASK_REMOVE_BG = "ask_remove_bg"
    DESCRIBE_DESIGN = "describe_design"
    ASK_MORE_ELEMENTS = "ask_more_elements"
    ADD_ELEMENTS_MODE = "add_elements_mode"
    ELEMENT_DEEPDIVE = "element_deepdive"
    ASK_PLACEMENT_ZONE = "ask_placement_zone"
    ASK_PLACEMENT_POSITION = "ask_placement_position"
    ASK_PIN_ANNOTATION = "ask_pin_annotation"
    PIN_ANNOTATE_MODE = "pin_annotate_mode"
    GENERATING = "generating"
    ASK_EMAIL = "ask_email"
    VERIFY_EMAIL = "verify_email"
    EMAIL_VERIFIED = "email_verified"
    SEND_PREVIEW_EMAIL = "send_preview_email"
    SHOW_DESIGN = "show_design"
    OFFER_REFINE = "offer_refine"
    DESCRIBE_CHANGES = "describe_changes"
    REGENERATING = "regenerating"
    QUOTE_REQUESTED = "quote_requested"
    UPSELL_PROMPT = "upsell_prompt"
    SESSION_END = "session_end"


S = ConversationState

# Linear "next" candidates per state. Branching states are resolved in
# advance_state() using collected data; the lists document reachability.
TRANSITIONS: dict[ConversationState, list[ConversationState]] = {
    S.GREETING: [S.ASK_NAME],
    S.ASK_NAME: [S.ASK_PURPOSE],
    S.ASK_PURPOSE: [S.CHECK_YOUTH],
    S.CHECK_YOUTH: [S.YOUTH_REFERRAL, S.ASK_QUANTITY],
    S.YOUTH_REFERRAL: [S.ASK_QUANTITY],
    S.ASK_QUANTITY: [S.DECORATION_ENGINE],
    S.DECORATION_ENGINE: [S.WARN_PRINT_SETUP, S.RECOMMEND_DECORATION, S.RECOMMEND_EMBROIDERY],
    S.WARN_PRINT_SETUP: [S.CONFIRM_DECORATION],
    S.RECOMMEND_DECORATION: [S.CONFIRM_DECORATION],
    S.RECOMMEND_EMBROIDERY: [S.CONFIRM_DECORATION],
    S.CONFIRM_DECORATION: [S.ASK_HAS_LOGO],
    S.ASK_HAS_LOGO: [S.UPLOAD_LOGO, S.DESCRIBE_DESIGN],
    S.UPLOAD_LOGO: [S.ELEMENT_DEEPDIVE],
    S.ASK_REMOVE_BG: [S.ELEMENT_DEEPDIVE],
    S.DESCRIBE_DESIGN: [S.ELEMENT_DEEPDIVE],
    S.ASK_MORE_ELEMENTS: [S.ELEMENT_DEEPDIVE, S.ASK_PIN_ANNOTATION, S.GENERATING],
    S.ELEMENT_DEEPDIVE: [S.ELEMENT_DEEPDIVE, S.ASK_MORE_ELEMENTS],
    S.ADD_ELEMENTS_MODE: [S.ADD_ELEMENTS_MODE, S.ASK_PLACEMENT_ZONE],
    S.ASK_PLACEMENT_ZONE: [S.ASK_PLACEMENT_POSITION],
    S.ASK_PLACEMENT_POSITION: [S.ASK_PIN_ANNOTATION],
    S.ASK_PIN_ANNOTATION: [S.PIN_ANNOTATE_MODE, S.GENERATING],
    S.PIN_ANNOTATE_MODE: [S.PIN_ANNOTATE_MODE, S.GENERATING],
    # Email is captured inline from the chat (asked in the GENERATING message) —
    # no separate name/phone form, since we already have the name. We still keep
    # the double opt-in: capturing the email sends a verification link, and
    # clicking it (handled by the leads route) releases the preview. ASK_EMAIL is
    # only reached as a fallback when the message wasn't a usable email address.
    S.GENERATING: [S.VERIFY_EMAIL, S.ASK_EMAIL],
    S.ASK_EMAIL: [S.VERIFY_EMAIL, S.ASK_EMAIL],
    S.VERIFY_EMAIL: [S.EMAIL_VERIFIED, S.VERIFY_EMAIL],
    S.EMAIL_VERIFIED: [S.SEND_PREVIEW_EMAIL],
    S.SEND_PREVIEW_EMAIL: [S.SHOW_DESIGN],
    S.SHOW_DESIGN: [S.OFFER_REFINE],
    S.OFFER_REFINE: [S.DESCRIBE_CHANGES, S.QUOTE_REQUESTED],
    S.DESCRIBE_CHANGES: [S.REGENERATING],
    S.REGENERATING: [S.OFFER_REFINE],
    S.QUOTE_REQUESTED: [S.UPSELL_PROMPT],
    S.UPSELL_PROMPT: [S.ASK_PLACEMENT_ZONE, S.SESSION_END],
    S.SESSION_END: [],
}

# Where a customer is allowed to rewind to from a given state. Never past
# product selection / before name.
ALLOWED_BACKTRACKS: dict[ConversationState, list[ConversationState]] = {
    S.ASK_PURPOSE: [S.ASK_NAME],
    S.CHECK_YOUTH: [S.ASK_NAME, S.ASK_PURPOSE],
    S.ASK_QUANTITY: [S.ASK_NAME, S.ASK_PURPOSE],
    S.DECORATION_ENGINE: [S.ASK_PURPOSE, S.ASK_QUANTITY],
    S.WARN_PRINT_SETUP: [S.ASK_QUANTITY],
    S.RECOMMEND_DECORATION: [S.ASK_QUANTITY],
    S.RECOMMEND_EMBROIDERY: [S.ASK_QUANTITY],
    S.CONFIRM_DECORATION: [S.ASK_QUANTITY],
    S.ASK_HAS_LOGO: [S.ASK_QUANTITY, S.CONFIRM_DECORATION],
    S.UPLOAD_LOGO: [S.ASK_HAS_LOGO],
    S.ASK_REMOVE_BG: [S.ASK_HAS_LOGO, S.UPLOAD_LOGO],
    S.DESCRIBE_DESIGN: [S.ASK_HAS_LOGO],
    S.ASK_MORE_ELEMENTS: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.UPLOAD_LOGO],
    S.ELEMENT_DEEPDIVE: [S.ASK_MORE_ELEMENTS],
    S.ADD_ELEMENTS_MODE: [S.ASK_MORE_ELEMENTS],
    S.ASK_PLACEMENT_ZONE: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.ASK_MORE_ELEMENTS],
    S.ASK_PLACEMENT_POSITION: [S.ASK_PLACEMENT_ZONE],
    S.ASK_PIN_ANNOTATION: [S.ASK_PLACEMENT_ZONE, S.ASK_PLACEMENT_POSITION],
    S.PIN_ANNOTATE_MODE: [S.ASK_PLACEMENT_POSITION],
    S.ASK_EMAIL: [S.ASK_PLACEMENT_ZONE],
}

# Number of distinct placement zones a session may add via upsell.
MAX_UPSELL_ZONES = 2

# Affirmative / negative keyword fallbacks (used alongside LLM interpretation).
_AFFIRMATIVE = {"yes", "yeah", "yep", "sure", "ok", "okay", "sounds good", "that works", "please", "do it"}
_NEGATIVE = {"no", "nope", "skip", "no thanks", "keep as-is", "keep", "don't", "nah", "i'm happy", "im happy"}


def is_affirmative(message: str) -> bool:
    m = message.strip().lower()
    return any(w in m for w in _AFFIRMATIVE) and not any(w in m for w in _NEGATIVE)


def is_negative(message: str) -> bool:
    m = message.strip().lower()
    return any(w in m for w in _NEGATIVE)


def allowed_backtracks(state: ConversationState) -> list[ConversationState]:
    return ALLOWED_BACKTRACKS.get(state, [])


def advance_state(
    current: ConversationState,
    collected: dict,
    *,
    message: str = "",
    upsell_count: int = 0,
) -> ConversationState:
    """Return the next state given the current state and collected data.

    Branch decisions are made ONLY here, from structured `collected` values that
    were populated by the orchestrator (via deterministic logic or LLM extraction).
    """
    # --- Youth branch ---
    if current is S.CHECK_YOUTH:
        return S.YOUTH_REFERRAL if collected.get("youth_flag") else S.ASK_QUANTITY

    # --- Decoration recommendation branch (by quantity) ---
    if current is S.DECORATION_ENGINE:
        qty = int(collected.get("quantity") or 0)
        if qty <= 1:
            return S.WARN_PRINT_SETUP
        if qty < 12:
            return S.RECOMMEND_DECORATION
        return S.RECOMMEND_EMBROIDERY

    # --- Has-logo branch ---
    if current is S.ASK_HAS_LOGO:
        return S.UPLOAD_LOGO if collected.get("has_logo") else S.DESCRIBE_DESIGN

    # --- Pin annotation branch ---
    if current is S.ASK_PIN_ANNOTATION:
        return S.PIN_ANNOTATE_MODE if collected.get("wants_pins") else S.GENERATING

    if current is S.PIN_ANNOTATE_MODE:
        # stay in pin mode while the customer keeps adding pins
        return S.PIN_ANNOTATE_MODE if collected.get("add_another_pin") else S.GENERATING

    # --- Per-element deep-dive ---
    if current is S.ASK_MORE_ELEMENTS:
        if collected.get("pending_element"):
            return S.ELEMENT_DEEPDIVE
        if not collected.get("pin_offered"):
            return S.ASK_PIN_ANNOTATION
        return S.GENERATING

    if current is S.ELEMENT_DEEPDIVE:
        return S.ELEMENT_DEEPDIVE if collected.get("pending_element") else S.ASK_MORE_ELEMENTS

    # --- Email capture branch ---
    # The GENERATING message asks for the email; once we have a usable one we
    # move to the verification step, otherwise fall through to ASK_EMAIL to ask
    # once more. ASK_EMAIL behaves the same on retry.
    if current in (S.GENERATING, S.ASK_EMAIL):
        return S.VERIFY_EMAIL if collected.get("email_captured") else S.ASK_EMAIL

    # --- Email verification branch ---
    # Verification completes out-of-band (the customer clicks the emailed link),
    # so the chat rests at VERIFY_EMAIL until that flips email_verified.
    if current is S.VERIFY_EMAIL:
        return S.EMAIL_VERIFIED if collected.get("email_verified") else S.VERIFY_EMAIL

    # --- Refine loop branch ---
    if current is S.OFFER_REFINE:
        return S.DESCRIBE_CHANGES if collected.get("wants_changes") else S.QUOTE_REQUESTED

    # --- Upsell branch ---
    if current is S.UPSELL_PROMPT:
        if collected.get("wants_upsell") and upsell_count < MAX_UPSELL_ZONES:
            return S.ASK_PLACEMENT_ZONE
        return S.SESSION_END

    # --- Default: first declared successor ---
    nexts = TRANSITIONS.get(current, [])
    return nexts[0] if nexts else S.SESSION_END


# States the orchestrator auto-advances through (they pose no question). Moved
# here from the orchestrator so advance_and_skip can consult it.
AUTO_ADVANCE_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.CHECK_YOUTH,
        ConversationState.DECORATION_ENGINE,
        ConversationState.CONFIRM_DECORATION,
        ConversationState.EMAIL_VERIFIED,
        ConversationState.SEND_PREVIEW_EMAIL,
        ConversationState.SHOW_DESIGN,
    }
)

# Question states → the `collected` key they populate. Used to skip a question
# whose answer the customer already volunteered out of order, and to count
# progress. Only genuine customer-facing question states appear here.
QUESTION_FIELD: dict[ConversationState, str] = {
    ConversationState.ASK_NAME: "name",
    ConversationState.ASK_PURPOSE: "purpose",
    ConversationState.ASK_QUANTITY: "quantity",
    ConversationState.DESCRIBE_DESIGN: "design_description",
    ConversationState.ASK_REMOVE_BG: "remove_bg",
    ConversationState.ASK_PLACEMENT_ZONE: "placement_zone",
    ConversationState.ASK_PLACEMENT_POSITION: "placement_position",
}


def _filled(collected: dict, field: str) -> bool:
    val = collected.get(field)
    return val is not None and val != ""


def advance_and_skip(
    current: ConversationState,
    collected: dict,
    *,
    message: str = "",
    upsell_count: int = 0,
) -> ConversationState:
    """advance_state + skip routing-only states AND question states already answered.

    This is what makes out-of-order capture pay off: if the customer already
    gave (say) the placement zone, the machine walks past ASK_PLACEMENT_ZONE
    instead of re-asking it.
    """
    nxt = advance_state(current, collected, message=message, upsell_count=upsell_count)
    for _ in range(50):  # bounded walk; never loop forever
        if nxt in AUTO_ADVANCE_STATES:
            nxt = advance_state(nxt, collected, upsell_count=upsell_count)
            continue
        field = QUESTION_FIELD.get(nxt)
        if field and _filled(collected, field):
            nxt = advance_state(nxt, collected, upsell_count=upsell_count)
            continue
        break
    return nxt


# Ordered customer-facing question states used for the "Step X of N" counter.
# Branch-dependent segments are chosen from `collected`; a decoration token
# represents the single decoration-choice question (whichever variant is shown).
def _progress_path(collected: dict) -> list[ConversationState]:
    S = ConversationState
    path = [S.ASK_NAME, S.ASK_PURPOSE, S.ASK_QUANTITY, S.RECOMMEND_DECORATION, S.ASK_HAS_LOGO]
    if collected.get("has_logo"):
        path += [S.UPLOAD_LOGO, S.ASK_REMOVE_BG]
    else:
        path += [S.DESCRIBE_DESIGN]
    path += [S.ASK_EMAIL]
    return path


# States that mean "past the design questionnaire" -> progress is complete.
_POST_QUESTION_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.ASK_PIN_ANNOTATION,
        ConversationState.PIN_ANNOTATE_MODE,
        ConversationState.GENERATING,
        ConversationState.VERIFY_EMAIL,
        ConversationState.EMAIL_VERIFIED,
        ConversationState.SEND_PREVIEW_EMAIL,
        ConversationState.SHOW_DESIGN,
        ConversationState.OFFER_REFINE,
        ConversationState.DESCRIBE_CHANGES,
        ConversationState.REGENERATING,
        ConversationState.QUOTE_REQUESTED,
        ConversationState.UPSELL_PROMPT,
        ConversationState.SESSION_END,
    }
)

# Decoration-choice variants all map to the single decoration progress token.
_DECORATION_VARIANTS: frozenset[ConversationState] = frozenset(
    {
        ConversationState.WARN_PRINT_SETUP,
        ConversationState.RECOMMEND_DECORATION,
        ConversationState.RECOMMEND_EMBROIDERY,
        ConversationState.CONFIRM_DECORATION,
        ConversationState.DECORATION_ENGINE,
    }
)


def progress(state: ConversationState, collected: dict) -> dict:
    """Return {"step", "total"} for the 'Step X of N' UI, counting only
    customer-facing question states on the branch the customer is on."""
    path = _progress_path(collected)
    total = len(path)
    if state in _DECORATION_VARIANTS:
        norm = ConversationState.RECOMMEND_DECORATION
    elif state in (
        ConversationState.ASK_PLACEMENT_ZONE,
        ConversationState.ASK_PLACEMENT_POSITION,
        ConversationState.ASK_MORE_ELEMENTS,
        ConversationState.ELEMENT_DEEPDIVE,
        ConversationState.ADD_ELEMENTS_MODE,
    ):
        # Global placement is retired from the forward path (placement is
        # per-element now); ASK_PLACEMENT_ZONE/POSITION remain only as legacy
        # backtrack targets. The per-element deep-dive (and its legacy
        # ADD_ELEMENTS_MODE / placement siblings) sit between the design
        # source and email on both branches, so they all normalize to the
        # branch's design-source step rather than falling back to "step 1"
        # (none of them are in _progress_path or _POST_QUESTION_STATES).
        norm = ConversationState.ASK_REMOVE_BG if collected.get("has_logo") else ConversationState.DESCRIBE_DESIGN
    else:
        norm = state
    if norm in path:
        return {"step": path.index(norm) + 1, "total": total}
    if state in _POST_QUESTION_STATES:
        return {"step": total, "total": total}
    # GREETING / ASK_EMAIL fallback etc.
    return {"step": 1, "total": total}
