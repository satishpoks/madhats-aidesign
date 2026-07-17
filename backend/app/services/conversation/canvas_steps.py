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

from dataclasses import dataclass
from typing import Callable

from app import prompts
from app.services import leads as leads_service
from app.services.conversation import intent_extractor as ie
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
    # Used ONLY when the interpreter is unavailable. For these steps the answer
    # IS the message — no interpretation, no keywords, no guessing. Without it a
    # Haiku outage dead-ends every session at step 1 (ask_name has no chips, so
    # the chip-nudge escape hatch cannot fire).
    direct_answer: Callable[[str], dict] | None = None
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


# --- apply hooks --------------------------------------------------------------
# Most steps need no effect — merging the resolved fields into `collected` IS
# the update. These few need bookkeeping beyond that merge: the logo loop, the
# email double-opt-in capture, and one-shot flags. Declaring the hook on the
# step's own record is the point — the alternative is a hidden switch statement.

# Replies that are plainly not a name. Ported verbatim from orchestrator_v2
# (commit 44e8eda): the old ASK_NAME step took the customer's first message
# verbatim, so "ok" became their name and the bot said "Great, ok! Let's add
# your logo." The interpreter is better at this than the old keyword ingest was,
# but it is still a model — this deterministic guard is what GUARANTEES the bug
# cannot come back. The model proposes; the guard disposes; done_when re-asks.
_NAME_FILLER = frozenset({
    "ok", "okay", "k", "yes", "yeah", "yep", "yup", "no", "nope", "nah",
    "sure", "hi", "hello", "hey", "hiya", "thanks", "ta", "cool", "great",
    "continue", "next", "done", "start", "go", "ready", "please",
})


def _plausible_name(candidate: str) -> bool:
    if not candidate or "?" in candidate:
        return False
    if ie._is_greeting_only(candidate):
        return False
    if not any(ch.isalpha() for ch in candidate):
        return False
    return candidate.lower().strip(" .!,'\"") not in _NAME_FILLER


def _apply_name(c: dict, f: dict, s: dict) -> None:
    name = (f.get("name") or "").strip().split("\n")[0][:60]
    if _plausible_name(name):
        c["name"] = name
    else:
        c.pop("name", None)      # never let filler satisfy done_when


def _apply_intro(c: dict, f: dict, s: dict) -> None:
    # Any reply to the intro is an acknowledgement — there is nothing to parse,
    # which is why show_intro declares no slots and never calls the model.
    c["intro_ack"] = True


def _apply_logo_face(c: dict, f: dict, s: dict) -> None:
    face = f.get("logo_face")
    if not face:
        return
    if c.get("pending_logo") is None:
        c["pending_logo"] = {}
    c["pending_logo"]["face"] = face


def _apply_logo_placed(c: dict, f: dict, s: dict) -> None:
    if f.get("logo_placed") and c.get("pending_logo") is not None:
        c["pending_logo"]["placed"] = True


def _apply_another_logo(c: dict, f: dict, s: dict) -> None:
    """The entire loop mechanism, declared next to the step it belongs to.

    Bank the finished logo, then either re-seed a pending one (which makes the
    three logo steps unmet again, so the router walks back to them by itself)
    or close the loop. Looping is slot-clearing.
    """
    logos = c.setdefault("logos", [])
    pending = c.get("pending_logo")
    if pending:
        logos.append(pending)
    if f.get("another_logo") and len(logos) < MAX_LOGOS:
        c["pending_logo"] = {}
        c.pop("another_logo", None)
    else:
        c["pending_logo"] = None
        c["logos_done"] = True


def _apply_anything_else(c: dict, f: dict, s: dict) -> None:
    if f.get("more_decor"):
        for k in ("decor_choice", "decor_placed", "more_decor"):
            c.pop(k, None)


def _apply_email(c: dict, f: dict, s: dict) -> None:
    """Double opt-in capture. `email_captured` is set ONLY here, and only after a
    real capture — which is what makes FINALIZE_CANVAS unreachable without a
    lead. On failure nothing is set, so ask_email re-asks itself."""
    email = f.get("email")
    if not email:
        return
    lead_id, ok = leads_service.capture_lead_and_verify(s, c, email)
    if lead_id:
        c["lead_id"] = lead_id
    if ok:
        c["email_captured"] = True
    c.pop("email", None)   # the lead owns the address; don't persist it here too


# --- direct answers ------------------------------------------------------------
# Used ONLY when the interpreter is unavailable (see Step.direct_answer). For
# these three steps the answer IS the message — no interpretation needed, and
# none of these is a keyword fallback: there is nothing to match against a
# keyword list, just the raw message assigned to the one slot the step asks
# for. Each result still passes through validate_fields and the step's own
# apply/done_when, so no guardrail is bypassed.

def _direct_name(message: str) -> dict:
    return {"name": message}          # _apply_name still guards plausibility


def _direct_purpose(message: str) -> dict:
    return {"purpose": message.strip()}


def _direct_email(message: str) -> dict:
    email = leads_service.extract_email(message)
    return {"email": email} if email else {}


REGISTRY: tuple[Step, ...] = (
    Step(
        id=S.ASK_NAME,
        ask=prompts.V2_ASK_NAME,
        ask_retry=prompts.V2_ASK_NAME_RETRY,
        slots=("name",),
        apply=_apply_name,                     # rejects filler — "ok" is not a name.
        direct_answer=_direct_name,
        done_when=lambda c: bool(c.get("name")),
    ),
    Step(
        id=S.SHOW_INTRO,
        ask="{intro}\n\nReady? Tap continue when you are.",
        continuable=True,
        slots=(),                              # ack-only: any reply satisfies it
        apply=_apply_intro,
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
        apply=_apply_logo_face,
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
        apply=_apply_logo_placed,
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
        apply=_apply_another_logo,
        done_when=lambda c: not _logos_open(c) or c.get("another_logo") is not None,
    ),
    Step(
        id=S.ASK_ADD_DECOR,
        ask="Would you like to add any text or a shape to your design?",
        chips=(Chip("Add text", {"decor_choice": "text"}),
               Chip("Add a shape", {"decor_choice": "shape"}),
               Chip("No, nothing else", {"decor_done": True})),
        slots=("decor_choice", "decor_done"),
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
        slots=("more_decor", "decor_done"),
        apply=_apply_anything_else,
        # Presence, not truthiness: "no, that's everything" -> more_decor=False
        # is a real, satisfying answer (mirrors ASK_ANOTHER_LOGO's `is not
        # None` check). Truthiness-only gating meant a typed decline could
        # never satisfy this step — bool(False) is False — so it re-asked
        # forever; only the chip (which sets decor_done=True) escaped.
        done_when=lambda c: bool(c.get("decor_done")) or c.get("more_decor") is not None,
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
        apply=_apply_email,
        direct_answer=_direct_email,
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
        direct_answer=_direct_purpose,
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
