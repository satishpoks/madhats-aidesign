"""v2 step-by-step canvas orchestrator routing.

Linear front half with two loops (logos ≤4, then text/shape), then the
quantity/email/purpose reorder, then a finalize handoff into the shared tail.
The orchestrator sets the branch flags on `collected`; this module only maps
(state, collected) -> next state. Downstream of FINALIZE_CANVAS the shared v1
tail (advance_state) takes over.
"""
from __future__ import annotations

from app.services.conversation.state_machine import ConversationState as S

MAX_LOGOS = 4

# The front-half states v2 owns (everything before the shared tail).
V2_STATES: frozenset[S] = frozenset({
    S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO,
    S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE, S.FINALIZE_CANVAS,
})


def advance_state_v2(current: S, collected: dict) -> S:
    if current is S.ASK_NAME:
        return S.SHOW_INTRO
    if current is S.SHOW_INTRO:
        return S.ASK_LOGO_PLACEMENT
    if current is S.ASK_LOGO_PLACEMENT:
        return S.LOGO_ADJUST
    if current is S.LOGO_ADJUST:
        return S.ASK_ANOTHER_LOGO if collected.get("logo_done") else S.LOGO_ADJUST
    if current is S.ASK_ANOTHER_LOGO:
        if collected.get("wants_another_logo") and int(collected.get("logo_count") or 0) < MAX_LOGOS:
            return S.ASK_LOGO_PLACEMENT
        return S.ASK_ADD_DECOR
    if current is S.ASK_ADD_DECOR:
        return S.DECOR_ADJUST if collected.get("decor_choice") else S.ASK_QUANTITY
    if current is S.DECOR_ADJUST:
        return S.ASK_ANYTHING_ELSE if collected.get("decor_done") else S.DECOR_ADJUST
    if current is S.ASK_ANYTHING_ELSE:
        return S.ASK_ADD_DECOR if collected.get("wants_more_decor") else S.ASK_QUANTITY
    if current is S.ASK_QUANTITY:
        return S.ASK_EMAIL if collected.get("quantity") not in (None, "") else S.ASK_QUANTITY
    if current is S.ASK_EMAIL:
        return S.ASK_PURPOSE if collected.get("email_captured") else S.ASK_EMAIL
    if current is S.ASK_PURPOSE:
        return S.FINALIZE_CANVAS if collected.get("purpose") not in (None, "") else S.ASK_PURPOSE
    # FINALIZE_CANVAS is resolved by the finalize route (-> GENERATING), not here.
    return current


# "Step X of N" — the ordered customer-facing question states for v2.
_V2_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT,
    S.ASK_ADD_DECOR, S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE,
]


def progress_v2(state: S, collected: dict) -> dict:
    total = len(_V2_PROGRESS_PATH)
    # Loop/adjust states collapse onto their loop's anchor question.
    norm = state
    if state in (S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        norm = S.ASK_LOGO_PLACEMENT
    elif state in (S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        norm = S.ASK_ADD_DECOR
    if norm in _V2_PROGRESS_PATH:
        return {"step": _V2_PROGRESS_PATH.index(norm) + 1, "total": total}
    # Past the questionnaire (finalize + tail) -> complete.
    return {"step": total, "total": total}
