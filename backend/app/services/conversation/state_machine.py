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
    ASK_PLACEMENT_ZONE = "ask_placement_zone"
    ASK_PLACEMENT_POSITION = "ask_placement_position"
    ASK_PIN_ANNOTATION = "ask_pin_annotation"
    PIN_ANNOTATE_MODE = "pin_annotate_mode"
    GENERATING = "generating"
    ASK_EMAIL = "ask_email"
    VERIFY_EMAIL = "verify_email"
    EMAIL_VERIFIED = "email_verified"
    SEND_PREVIEW_EMAIL = "send_preview_email"
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
    S.UPLOAD_LOGO: [S.ASK_REMOVE_BG],
    S.ASK_REMOVE_BG: [S.ASK_PLACEMENT_ZONE],
    S.DESCRIBE_DESIGN: [S.ASK_PLACEMENT_ZONE],
    S.ASK_PLACEMENT_ZONE: [S.ASK_PLACEMENT_POSITION],
    S.ASK_PLACEMENT_POSITION: [S.ASK_PIN_ANNOTATION],
    S.ASK_PIN_ANNOTATION: [S.PIN_ANNOTATE_MODE, S.GENERATING],
    S.PIN_ANNOTATE_MODE: [S.PIN_ANNOTATE_MODE, S.GENERATING],
    S.GENERATING: [S.ASK_EMAIL],
    S.ASK_EMAIL: [S.VERIFY_EMAIL],
    S.VERIFY_EMAIL: [S.EMAIL_VERIFIED, S.VERIFY_EMAIL],
    S.EMAIL_VERIFIED: [S.SEND_PREVIEW_EMAIL],
    S.SEND_PREVIEW_EMAIL: [S.QUOTE_REQUESTED],
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
    S.ASK_PLACEMENT_ZONE: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN],
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

    # --- Email verification branch ---
    if current is S.VERIFY_EMAIL:
        return S.EMAIL_VERIFIED if collected.get("email_verified") else S.VERIFY_EMAIL

    # --- Upsell branch ---
    if current is S.UPSELL_PROMPT:
        if collected.get("wants_upsell") and upsell_count < MAX_UPSELL_ZONES:
            return S.ASK_PLACEMENT_ZONE
        return S.SESSION_END

    # --- Default: first declared successor ---
    nexts = TRANSITIONS.get(current, [])
    return nexts[0] if nexts else S.SESSION_END
