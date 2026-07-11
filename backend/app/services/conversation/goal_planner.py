"""Goal-oriented conversation planner.

Returns the state of the FIRST unmet questionnaire goal, purely from the
collected data. This replaces the old "advance one state per turn" walk: a slot
that is already filled is never returned, and a genuinely-unmet required slot is
returned no matter which state the customer is nominally on. Downstream/gate
states (pin branching, generation, email verification, refine/quote/upsell) are
NOT owned here — the orchestrator routes those through
``state_machine.advance_state``.
"""
from __future__ import annotations

from app.services.conversation.state_machine import ConversationState as S

# States routed by advance_state (branching gates + async/downstream flow), not
# by the goal planner. The planner owns the forward questionnaire only.
GATE_STATES: frozenset[S] = frozenset(
    {
        S.ASK_PIN_ANNOTATION,
        S.PIN_ANNOTATE_MODE,
        S.ASK_MORE_ELEMENTS,
        S.ADD_ELEMENTS_MODE,
        S.GENERATING,
        S.ASK_EMAIL,
        S.VERIFY_EMAIL,
        S.EMAIL_VERIFIED,
        S.SEND_PREVIEW_EMAIL,
        S.SHOW_DESIGN,
        S.OFFER_REFINE,
        S.DESCRIBE_CHANGES,
        S.REGENERATING,
        S.QUOTE_REQUESTED,
        S.UPSELL_PROMPT,
        S.SESSION_END,
    }
)


def _decoration_state(collected: dict) -> S:
    """Mirror advance_state's DECORATION_ENGINE branch: recommend by quantity."""
    qty = int(collected.get("quantity") or 0)
    if qty <= 1:
        return S.WARN_PRINT_SETUP
    if qty < 12:
        return S.RECOMMEND_DECORATION
    return S.RECOMMEND_EMBROIDERY


def next_goal(collected: dict, *, upsell_count: int = 0) -> S:
    """Return the state for the first unmet forward-questionnaire goal.

    Pure function of ``collected``. When every goal is met, returns GENERATING
    (where the email is captured inline).
    """
    # 1. name (required)
    if not collected.get("name"):
        return S.ASK_NAME

    # 2. purpose (soft: satisfied once given OR once asked)
    if not collected.get("purpose") and not collected.get("purpose_asked"):
        return S.ASK_PURPOSE

    # youth referral (one-shot statement gate, derived from purpose)
    if collected.get("youth_flag") and not collected.get("youth_referred"):
        return S.YOUTH_REFERRAL

    # 3. quantity (required; presence, not truthiness — "not sure" -> 0 counts)
    if "quantity" not in collected:
        return S.ASK_QUANTITY

    # 4. decoration type (required)
    if not collected.get("decoration_type"):
        return _decoration_state(collected)

    # 5. design source (required) + branch
    if "has_logo" not in collected:
        return S.ASK_HAS_LOGO
    if collected.get("has_logo"):
        if not collected.get("uploaded_asset_path"):
            return S.UPLOAD_LOGO
        if "remove_bg" not in collected:
            return S.ASK_REMOVE_BG
    else:
        if not collected.get("design_description"):
            return S.DESCRIBE_DESIGN

    # 5b. additional elements (optional, offered exactly once)
    if not collected.get("elements_offered"):
        return S.ASK_MORE_ELEMENTS

    # 6. placement (required; zone only — position defaults to centre elsewhere)
    if not collected.get("placement_zone"):
        return S.ASK_PLACEMENT_ZONE

    # 7. pin annotation (optional, offered exactly once)
    if not collected.get("pin_offered"):
        return S.ASK_PIN_ANNOTATION

    # 8. email is captured inline at GENERATING
    return S.GENERATING
