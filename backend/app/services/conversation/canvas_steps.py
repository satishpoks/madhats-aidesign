"""The v2 canvas step registry — the single source of truth for the flow.

Each Step declares everything about one step in one literal: its question copy,
its chips (the label AND the fields that label means, together), the slots the
interpreter fills, when the step is satisfied, any effect it needs, and the
canvas tool it hands over.

Declaring a chip's label next to its fields is the point: the old code declared
the label in `v2_public_data` and re-derived its meaning by grepping the string
in `_apply_v2_fields`, and the two silently disagreed ("Yes, another logo" read
as a decline, because "another" contains "no"). Here a chip cannot disagree with
itself.

Adding a step = adding one record here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app import prompts
from app.services.conversation.state_machine import ConversationState as S

MAX_LOGOS = 4

FACES: frozenset[str] = frozenset({"front", "back", "left", "right"})


@dataclass(frozen=True)
class Chip:
    """An offered button: the exact label we ship, and what tapping it means."""
    label: str
    fields: dict


@dataclass(frozen=True)
class Step:
    id: S
    ask: str                                   # format string; ctx = name/persona/intro
    done_when: Callable[[dict], bool]
    ask_retry: str | None = None               # shorter copy when re-asked
    chips: tuple[Chip, ...] = ()
    slots: tuple[str, ...] = ()                # what THIS step asks for; () = ack-only
    apply: Callable[[dict, dict, dict], None] | None = None   # (collected, fields, session)
    tool: str | None = None
    tip: str | None = None
    continuable: bool = False
    auto_open: str | None = None
    show_done: bool = False
    face_target: bool = False                  # directive should carry the logo face


# --- loop helpers -----------------------------------------------------------
# The logo loop is a collection plus a pending item (the shape goal_planner
# already uses for the element deep-dive). Looping is slot-clearing: clearing
# `another_logo` and re-seeding `pending_logo` makes the three logo steps unmet
# again, so the router walks back to them by itself. No back-edges.

def _pending(c: dict) -> dict:
    return c.get("pending_logo") or {}


def _logos_open(c: dict) -> bool:
    return not c.get("logos_done")


REGISTRY: tuple[Step, ...] = (
    Step(
        id=S.ASK_NAME,
        ask=prompts.V2_ASK_NAME,
        ask_retry=prompts.V2_ASK_NAME_RETRY,
        slots=("name",),
        # Task 4 wires apply=_apply_name here (rejects filler — "ok" is not a name).
        done_when=lambda c: bool(c.get("name")),
    ),
    Step(
        id=S.SHOW_INTRO,
        ask="{intro}\n\nReady? Tap continue when you are.",
        continuable=True,
        slots=(),                              # ack-only: any reply satisfies it
        done_when=lambda c: bool(c.get("intro_ack")),
    ),
    Step(
        id=S.ASK_LOGO_PLACEMENT,
        ask=("Great, {name}! Let's add your logo. Which part of the cap should "
             "it go on — front, back, left or right?"),
        chips=(Chip("Front", {"logo_face": "front"}),
               Chip("Back", {"logo_face": "back"}),
               Chip("Left", {"logo_face": "left"}),
               Chip("Right", {"logo_face": "right"})),
        slots=("logo_face",),
        done_when=lambda c: not _logos_open(c) or "face" in _pending(c),
        tool="upload",
        tip=prompts.V2_TOOL_TIPS["upload"],
        # auto_open stays None: the file dialog must not open before the face is
        # answered, or the logo lands on whatever face is already active.
        auto_open=None,
        face_target=True,
    ),
    Step(
        id=S.LOGO_ADJUST,
        ask=("Pop your logo on there — I've opened the picker for you. Once "
             "it's on, drag to move it, pull a corner to resize, or rotate it. "
             "There's a background-removal toggle in the toolbar if you need "
             "it. Press Done when the placement looks right."),
        chips=(Chip("Done", {"logo_placed": True}),),
        slots=("logo_placed",),
        done_when=lambda c: not _logos_open(c) or bool(_pending(c).get("placed")),
        tool="upload",
        tip=prompts.V2_TOOL_TIPS["upload"],
        auto_open="upload",
        show_done=True,
        face_target=True,
    ),
    Step(
        id=S.ASK_ANOTHER_LOGO,
        ask="Locked that in. Would you like to add another logo?",
        chips=(Chip("Yes, another logo", {"another_logo": True}),
               Chip("No, that's it", {"another_logo": False})),
        slots=("another_logo",),
        done_when=lambda c: not _logos_open(c) or c.get("another_logo") is not None,
    ),
    Step(
        id=S.ASK_ADD_DECOR,
        ask="Would you like to add any text or a shape to your design?",
        chips=(Chip("Add text", {"decor_choice": "text"}),
               Chip("Add a shape", {"decor_choice": "shape"}),
               Chip("No, nothing else", {"decor_done": True})),
        slots=("decor_choice",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("decor_choice")),
    ),
    Step(
        id=S.DECOR_ADJUST,
        # reply_for prepends the tip for the tool actually chosen (text vs
        # shape), which is why this copy is only the tail of the sentence.
        ask="Press Done when you're happy with it.",
        chips=(Chip("Done", {"decor_placed": True}),),
        slots=("decor_placed",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("decor_placed")),
        tool="text",                           # overridden per decor_choice in Task 6
        tip=prompts.V2_TOOL_TIPS["text"],
        auto_open="text",
        show_done=True,
        face_target=True,
    ),
    Step(
        id=S.ASK_ANYTHING_ELSE,
        ask="Is that everything, or would you like to add anything else?",
        chips=(Chip("Add something else", {"more_decor": True}),
               Chip("No, that's everything", {"decor_done": True})),
        slots=("more_decor",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("more_decor")),
    ),
    Step(
        id=S.ASK_QUANTITY,
        ask="How many caps are you after?",
        chips=(Chip("1", {"quantity": 1}),
               Chip("2-11", {"quantity": 2}),
               Chip("12-49", {"quantity": 12}),
               Chip("50-99", {"quantity": 50}),
               Chip("100+", {"quantity": 100}),
               Chip("Not sure", {"quantity": 0, "quantity_unsure": True})),
        slots=("quantity",),
        # Presence, not truthiness: "Not sure" -> 0 is a real answer. The old
        # code gated on `quantity not in (None, "")` while the parser fell back
        # to 0, so ANY input advanced and the re-ask branch was dead code.
        done_when=lambda c: "quantity" in c,
    ),
    Step(
        id=S.ASK_EMAIL,
        ask="What's the best email to send your design preview to?",
        slots=("email",),
        # `email_captured` is set ONLY by _apply_email after a real
        # capture_lead_and_verify, and is not a writable slot — so the
        # interpreter cannot fake it and FINALIZE_CANVAS cannot be reached
        # without a captured lead.
        done_when=lambda c: bool(c.get("email_captured")),
    ),
    Step(
        id=S.ASK_PURPOSE,
        ask="Last thing — if you don't mind me asking, what's the hat for?",
        slots=("purpose",),
        done_when=lambda c: bool(c.get("purpose")),
    ),
    Step(
        id=S.FINALIZE_CANVAS,
        ask="Perfect — putting your design together now…",
        # Terminal: never satisfied, so the router returns it once every earlier
        # step is done. The finalize route (-> GENERATING) resolves it.
        done_when=lambda c: False,
    ),
)

_BY_ID: dict[S, Step] = {s.id: s for s in REGISTRY}


def by_id(state: S) -> Step | None:
    """The Step for a state, or None for a shared-tail state v2 doesn't own."""
    return _BY_ID.get(state)


# Every slot any step asks for. This is the interpreter's writable set: it may
# fill the current step's slot AND any other slot the customer volunteers
# ("logo on the back and 50 caps"), which is where reordering comes from.
# Internal bookkeeping (logos/pending_logo/logos_done/email_captured/_asked) is
# deliberately absent — the interpreter must never write it.
WRITABLE_SLOTS: frozenset[str] = frozenset(
    s for step in REGISTRY for s in step.slots
)

SLOT_ENUMS: dict[str, frozenset[str]] = {
    "logo_face": FACES,
    "decor_choice": frozenset({"text", "shape"}),
}
