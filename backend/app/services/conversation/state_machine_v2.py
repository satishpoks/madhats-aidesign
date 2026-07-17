"""v2 step-by-step canvas orchestrator routing.

Linear front half with two loops (logos ≤4, then text/shape), then the
quantity/email/purpose reorder, then a finalize handoff into the shared tail.
The orchestrator sets the branch flags on `collected`; this module only maps
(state, collected) -> next state. Downstream of FINALIZE_CANVAS the shared v1
tail (advance_state) takes over.
"""
from __future__ import annotations

from app import prompts
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
        # An ambiguous/unrecognised reply (decor_answered False) must NOT
        # silently fall through to the quantity step — re-ask instead. Only a
        # recognised decline ("nothing else") or a recognised type (text/
        # shape) counts as answered.
        if not collected.get("decor_answered"):
            return S.ASK_ADD_DECOR
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


_VALID_FACES = {"front", "back", "left", "right"}


def _logo_face(collected: dict) -> str:
    face = (collected.get("logo_face") or "front")
    return face if face in _VALID_FACES else "front"


def canvas_directive(state: S, collected: dict) -> dict | None:
    """The canvas-control blob for a v2 state, or None when the state drives no
    canvas change (tail/question-only states)."""
    if state is S.ASK_LOGO_PLACEMENT:
        # The customer is about to pick a face; the upload tool is enabled
        # (highlighted) but must NOT auto-open yet — the file dialog would
        # open before the face is answered, so `addImage` would land on
        # whatever face is currently active (defaulting to "front") instead
        # of the face the customer is about to name.
        return {
            "allowed_tools": ["upload"],
            "target_face": _logo_face(collected),
            "auto_open": None,
            "instructions": prompts.V2_TOOL_TIPS["upload"],
            "show_done": False,
        }
    if state is S.LOGO_ADJUST:
        # By now `logo_face` is set from the answer, so `_logo_face` resolves
        # to the correct face — safe to switch the canvas there and THEN open
        # the upload picker.
        return {
            "allowed_tools": ["upload"],
            "target_face": _logo_face(collected),
            "auto_open": "upload",
            "instructions": prompts.V2_TOOL_TIPS["upload"],
            "show_done": True,
        }
    if state is S.DECOR_ADJUST:
        tool = "text" if collected.get("decor_choice") == "text" else "shape"
        return {
            "allowed_tools": [tool],
            "target_face": _logo_face(collected),
            "auto_open": tool,
            "instructions": prompts.V2_TOOL_TIPS[tool],
            "show_done": True,
        }
    if state in (S.ASK_ANYTHING_ELSE, S.ASK_QUANTITY):
        # Lock every tool once the design phase is over.
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False}
    return None


def v2_public_data(state: S, collected: dict) -> dict:
    """Non-PII UI data for a v2 state: chips + directive + trigger flags."""
    data: dict = {}
    if state is S.SHOW_INTRO:
        data["continuable"] = True
    elif state is S.ASK_LOGO_PLACEMENT:
        data["options"] = ["Front", "Back", "Left", "Right"]
    elif state is S.LOGO_ADJUST:
        data["options"] = ["Done"]
    elif state is S.ASK_ANOTHER_LOGO:
        data["options"] = ["Yes, another logo", "No, that's it"]
    elif state is S.ASK_ADD_DECOR:
        data["options"] = ["Add text", "Add a shape", "No, nothing else"]
    elif state is S.DECOR_ADJUST:
        data["options"] = ["Done"]
    elif state is S.ASK_ANYTHING_ELSE:
        data["options"] = ["Add something else", "No, that's everything"]
    elif state is S.ASK_QUANTITY:
        data["options"] = ["1", "2-11", "12-49", "50-99", "100+", "Not sure"]
    elif state is S.FINALIZE_CANVAS:
        data["trigger_finalize"] = True
    directive = canvas_directive(state, collected)
    if directive is not None:
        data["canvas"] = directive
    data["progress"] = progress_v2(state, collected)
    return data


def v2_reply(state: S, collected: dict, persona: str, intro_text: str) -> str:
    """Deterministic reply copy per v2 state (never LLM-paraphrased, so no
    instruction detail is dropped)."""
    name = collected.get("name") or "there"
    tips = prompts.V2_TOOL_TIPS
    if state is S.SHOW_INTRO:
        return f"{intro_text}\n\nReady? Tap continue when you are."
    if state is S.ASK_LOGO_PLACEMENT:
        return (
            f"Great, {name}! Let's add your logo. Which part of the cap should it "
            f"go on — front, back, left or right? {tips['upload']}"
        )
    if state is S.LOGO_ADJUST:
        return (
            "Pop your logo on there — I've opened the picker for you. Once "
            "it's on, drag to move it, pull a corner to resize, or rotate "
            "it. There's a background-removal toggle in the toolbar if you "
            "need it. Press Done when the placement looks right."
        )
    if state is S.ASK_ANOTHER_LOGO:
        return "Locked that in. Would you like to add another logo?"
    if state is S.ASK_ADD_DECOR:
        return "Would you like to add any text or a shape to your design?"
    if state is S.DECOR_ADJUST:
        tool = "text" if collected.get("decor_choice") == "text" else "shape"
        return f"{tips[tool]} Press Done when you're happy with it."
    if state is S.ASK_ANYTHING_ELSE:
        return "Is that everything, or would you like to add anything else?"
    if state is S.ASK_QUANTITY:
        return "How many caps are you after?"
    if state is S.ASK_EMAIL:
        return "What's the best email to send your design preview to?"
    if state is S.ASK_PURPOSE:
        return "Last thing — if you don't mind me asking, what's the hat for?"
    if state is S.FINALIZE_CANVAS:
        return "Perfect — putting your design together now…"
    return "Let's keep going."
