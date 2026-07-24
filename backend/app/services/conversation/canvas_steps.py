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
    instructions: str | None = None            # overrides V2_TOOL_TIPS[tool] in the directive
    continuable: bool = False
    auto_open: str | None = None
    show_done: bool = False
    face_target: bool = False                  # directive should carry the logo face
    # Chips that can't be literals because they come from store-scoped data.
    # `chips_of` is the single read path, so a dynamic step is invisible to
    # every consumer (public_data_for, resolve_chip) — they just ask for chips.
    chips_from: Callable[[dict], tuple[Chip, ...]] | None = None
    # The customer may pick several. The UI comma-joins the labels it was given
    # (ChatColumn.submitDeco:274), so resolution stays an identity lookup on the
    # closed set we shipped — just one per token instead of one per message.
    multiselect: bool = False
    # Impure setup run before the step is rendered: loads store-scoped data the
    # step's chips need. Declared on the record — the alternative is an
    # `if next_.id is ASK_DECORATION` branch in the orchestrator, which is the
    # per-state switch this registry exists to avoid. May satisfy its own step
    # (see _prepare_decoration), so the orchestrator re-resolves after it runs.
    prepare: Callable[[dict, dict | None], None] | None = None
    # Canvas mutations this step's ANSWER implies, as fully-resolved canvas_ops
    # (see docs/superpowers/specs/2026-07-17-canvas-led-refine-design.md).
    # (collected, fields) -> list of {"target": …, "patch": …}. Declared on the
    # record for the same reason as `prepare`: the alternative is an
    # `if step.id is ASK_LOGO_BG` branch in the orchestrator.
    ops: Callable[[dict, dict], list[dict]] | None = None


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


def _apply_has_logo(c: dict, f: dict, s: dict) -> None:
    """A text-only customer closes the logo loop before it opens.

    Every logo step's done_when short-circuits on `not _logos_open(c)`, so
    setting logos_done here makes first-unmet skip all four by itself — no
    branch, no back-edge. `has_logo is False` (not falsy) because the slot is
    absent until answered.
    """
    if f.get("has_logo") is False:
        c["logos_done"] = True
        c["pending_logo"] = None


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


def _apply_logo_bg(c: dict, f: dict, s: dict) -> None:
    bg = f.get("logo_bg")
    if bg and c.get("pending_logo") is not None:
        c["pending_logo"]["bg"] = bg


def _ops_logo_bg(c: dict, f: dict) -> list[dict]:
    """Tick the box for the customer.

    The backend has no element id here — `canvas_design` isn't persisted until
    finalize — so the target is the semantic "pending logo": the last unlocked
    image on the face, the same anchor `lockPlaced` leans on.
    """
    if f.get("logo_bg") != "removed":
        return []
    return [{"target": {"kind": "pending_logo",
                        "face": _pending(c).get("face") or "front"},
             "patch": {"removeBg": True}}]


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
    # `decor_done` is popped too: it became interpreter-writable, so a model
    # returning the contradictory {"more_decor": True, "decor_done": True} would
    # otherwise leave decor_done set — and every decor step short-circuits on it,
    # silently routing a customer who asked to ADD something to the quantity
    # question with their decor state wiped. "Add more" always wins.
    if f.get("more_decor"):
        for k in ("decor_choice", "decor_face", "decor_placed", "more_decor",
                  "decor_done"):
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


MIX_CHIP_LABEL = "I want a mix"


def _decoration_chips(c: dict) -> tuple[Chip, ...]:
    """One chip per method the store offers (loaded by _prepare_decoration), plus
    the mix escape hatch.

    Single-select is the default because one method is the normal answer and
    mixing costs the customer more per hat — so a mix is a deliberate choice that
    routes to ASK_DECORATION_MIX to be described, not something you fall into by
    tapping a second chip.
    """
    return tuple(Chip(name, {"decoration_types": [name]})
                 for name in (c.get("decoration_options") or [])) + (
        Chip(MIX_CHIP_LABEL, {"decoration_mix": True}),
    )


def _prepare_decoration(c: dict, store: dict | None) -> None:
    """Load the store's active decoration methods before the step renders.

    A store with none configured would leave the step with no chips and no way
    to answer, dead-ending the funnel one step before the email — so mark it
    done and let first-unmet skip it. Same for a store we can't read: the
    decoration method is a nice-to-have on the brief, never worth losing a lead.
    """
    if "decoration_options" not in c:
        from app.services import decoration_types as deco_svc  # noqa: PLC0415 cycle

        opts: list[str] = []
        if store and store.get("id"):
            try:
                opts = [t["name"] for t in
                        deco_svc.list_types(store["id"], active_only=True)]
            except Exception:  # noqa: BLE001 — never lose the lead over this
                opts = []
        c["decoration_options"] = opts
    if not c["decoration_options"]:
        c["decoration_done"] = True


def _apply_decoration(c: dict, f: dict, s: dict) -> None:
    """Filter the answer to what the store actually offers, then set the brief.

    This filter IS the interpreter guard: `decoration_types` is store-dynamic,
    so it cannot live in SLOT_ENUMS. An invented method yields nothing and never
    reaches the brief. Exact token match (not substring) so a shorter name can't
    match inside a longer one — "Print" inside "Screen Print".
    """
    if "decoration_types" not in f:
        return
    raw = f["decoration_types"]
    if isinstance(raw, str):
        raw = raw.split(",")            # the interpreter may return a bare string
    if not isinstance(raw, list):
        raw = []
    offered = {str(o).casefold(): o for o in (c.get("decoration_options") or [])}
    chosen: list[str] = []
    for tok in raw:
        opt = offered.get(str(tok).strip().casefold())
        if opt and opt not in chosen:
            chosen.append(opt)

    c["decoration_types"] = chosen
    c["decoration_done"] = True
    if chosen:
        c.setdefault("brief_notes", []).append(
            f"Decoration method: {', '.join(chosen)}"
        )
        # v1's mapping, imported rather than re-typed: one keyword table, one
        # behaviour. Local import — orchestrator imports this module's siblings.
        from app.services.conversation.orchestrator import (  # noqa: PLC0415 cycle
            _decoration_style_bucket,
        )
        c["decoration_type"] = _decoration_style_bucket(chosen[0])


def _apply_decoration_mix(c: dict, f: dict, s: dict) -> None:
    """Record the customer's own description of the mix they want.

    Deliberately NOT filtered against `decoration_options` the way a chip answer
    is: the whole point of this step is that no single offered method covers what
    they want, so the note goes to the team verbatim. The render-style bucket
    still comes from their words, via the same keyword table a single pick uses —
    it falls back to the prompt builder's own default ("print") when nothing
    matches, which is exactly what an unset bucket would have done anyway.
    """
    note = (f.get("decoration_mix_note") or "").strip()[:600]
    if not note:
        return                                  # done_when re-asks
    c["decoration_mix_note"] = note
    c.setdefault("brief_notes", []).append(f"Decoration method: a mix — {note}")
    from app.services.conversation.orchestrator import (  # noqa: PLC0415 cycle
        _decoration_style_bucket,
    )
    c["decoration_type"] = _decoration_style_bucket(note)


def _apply_request_quote(c: dict, f: dict, s: dict) -> None:
    """Record the explicit quote request and stash the reference for on-screen.

    The lead already exists (email was captured at ASK_EMAIL). Recording mints
    the tracking reference, marks the lead, and best-effort converges with the
    verification track. `quote_requested` on `collected` is what satisfies
    done_when; `reference_code` is surfaced to the customer immediately.
    """
    if not f.get("quote_requested"):
        return
    code = leads_service.record_quote_request(s, c)
    if code:
        c["reference_code"] = code
    c["quote_requested"] = True


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
        id=S.ASK_HAS_LOGO,
        ask="Great, {name}! Do you have a logo or image you'd like on the cap?",
        chips=(Chip("Yes, I have a logo", {"has_logo": True}),
               Chip("No — text only", {"has_logo": False})),
        slots=("has_logo",),
        apply=_apply_has_logo,
        # NOT `"has_logo" in c`: the interpreter can volunteer this slot on an
        # earlier turn, and a step that is already done never becomes current,
        # so `_apply_has_logo` would never run and `logos_done` would never be
        # set — marching a text-only customer into the logo loop, the exact bug
        # this step exists to prevent. `True` needs no side effect, so it may
        # skip on the raw slot; `False` stays unmet until the apply has actually
        # run (which is what `not _logos_open(c)` observes).
        done_when=lambda c: c.get("has_logo") is True or not _logos_open(c),
    ),
    Step(
        id=S.ASK_LOGO_PLACEMENT,
        ask="Which part of the cap should it go on — front, back, left or right?",
        ask_retry="Where should this one go — front, back, left or right?",
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
        id=S.ASK_LOGO_BG,
        # "Remove background" is a MARK, not an edit: the op only flags the
        # element (a ✂ badge, `name="export-hide"` so it never bakes into the
        # layout guide). Nothing is matted client-side — `prompt_builder`
        # instructs the image model to knock the background out at render time.
        # So this copy must not promise processing or ask the customer to wait.
        ask="Does your logo have a background that needs removing?",
        # The chip IS the tick (see _ops_logo_bg). Previously this asked the
        # customer to tick it themselves and only recorded their claim —
        # pending_logo["bg"] routes but nothing on the RENDER path reads it, so
        # "Yes, I've ticked it" without ticking silently rendered no knockout.
        chips=(Chip("Yes, remove background", {"logo_bg": "removed"}),
               Chip("No, it's fine as is", {"logo_bg": "none"})),
        slots=("logo_bg",),
        apply=_apply_logo_bg,
        ops=_ops_logo_bg,
        done_when=lambda c: not _logos_open(c) or "bg" in _pending(c),
        # tool="upload" is LOAD-BEARING, not decoration: it keeps v2Editing true
        # on the frontend, so the just-placed logo is NOT locked and stays
        # selectable. The customer no longer NEEDS the toggle (the op ticks it),
        # but it stays reachable as a manual override / untick. The lock fires on
        # ASK_ANOTHER_LOGO instead. See Surface.tsx:111-113 + canvasStore.ts:36.
        tool="upload",
        tip=None,                              # the upload tip is wrong here
        instructions=prompts.V2_BG_INSTRUCTIONS,
        auto_open=None,                        # or the file picker reopens
        show_done=False,
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
        id=S.ASK_DECOR_PLACEMENT,
        ask="Which part of the cap should it go on — front, back, left or right?",
        chips=(Chip("Front", {"decor_face": "front"}),
               Chip("Back", {"decor_face": "back"}),
               Chip("Left", {"decor_face": "left"}),
               Chip("Right", {"decor_face": "right"})),
        slots=("decor_face",),
        done_when=lambda c: bool(c.get("decor_done")) or c.get("decor_face") in FACES,
        # Mirrors ASK_LOGO_PLACEMENT: hand the tool over (highlighted) but do
        # NOT auto-open it until the face is answered, or the decoration lands
        # on whatever face is already active.
        tool="text",                           # resolved per decor_choice at runtime
        tip=None,
        auto_open=None,
        face_target=True,
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
        id=S.ASK_DECORATION,
        # The cost caveat lives in the copy because this step is single-select:
        # ChatColumn only renders its own "each extra decoration adds to the
        # cost" line when 2+ chips are ticked (a v1 multi-select path), which
        # can never happen here.
        ask=("How would you like this decorated? Pick the one that suits — our "
             f"team will confirm what works best for your artwork. Tap "
             f"'{MIX_CHIP_LABEL}' if you need more than one method, just note "
             "that mixing costs more per hat."),
        chips_from=_decoration_chips,
        slots=("decoration_types", "decoration_mix"),
        prepare=_prepare_decoration,
        apply=_apply_decoration,
        # A mix IS an answer to this step; ASK_DECORATION_MIX asks what it is.
        done_when=lambda c: bool(c.get("decoration_done") or c.get("decoration_mix")),
    ),
    Step(
        id=S.ASK_DECORATION_MIX,
        ask=("No problem — tell me which methods you'd like and where each one "
             "goes, and I'll pass it straight to the team. (Mixing methods does "
             "add to the cost per hat.)"),
        # decoration_mix is a slot of this step, not just of ASK_DECORATION: it
        # is what lets the customer back out ("actually, just embroidery") after
        # tapping the mix chip. Only the asking step may clear a settled flag —
        # see state_machine_v2.merge_fields. Cancelling re-opens ASK_DECORATION,
        # which is the right question to land on.
        slots=("decoration_mix_note", "decoration_mix"),
        apply=_apply_decoration_mix,
        # No chips, so the stall-and-nudge escape hatch cannot fire — without a
        # direct answer an interpreter outage strands the session one step
        # before the email. See Step.direct_answer.
        direct_answer=lambda m: {"decoration_mix_note": m.strip()},
        # Conditional: only asked when the customer actually asked for a mix.
        done_when=lambda c: (not c.get("decoration_mix")
                             or bool(c.get("decoration_mix_note"))),
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
        id=S.NEEDED_BY,
        ask="When do you need these by?",
        # Each label carries its own meaning field — a chip cannot disagree with
        # itself (see the module docstring). The value stored is the bucket
        # itself; a typed custom date arrives instead via the interpreter filling
        # the `needed_by` slot (no chip tapped).
        chips=(Chip("ASAP", {"needed_by": "ASAP"}),
               Chip("2–4 weeks", {"needed_by": "2–4 weeks"}),
               Chip("1–2 months", {"needed_by": "1–2 months"}),
               Chip("Just exploring", {"needed_by": "Just exploring"})),
        slots=("needed_by",),
        # Any non-empty answer satisfies it — including the "Just exploring" defer
        # chip. No apply/direct_answer: chips carry the buckets, the interpreter
        # parses typed dates, and the value lives in collected["needed_by"] for
        # Workstream C to surface in the sales quote summary. Free text, so no
        # SLOT_ENUMS entry (a custom date must pass validate_fields untouched).
        done_when=lambda c: "needed_by" in c,
    ),
    Step(
        id=S.ASK_PURPOSE,
        ask="Last thing — if you don't mind me asking, what's the hat for?",
        slots=("purpose",),
        direct_answer=_direct_purpose,
        done_when=lambda c: bool(c.get("purpose")),
    ),
    Step(
        id=S.REQUEST_QUOTE,
        ask=("Your design's ready to go, {name}! Tap below to send it to our "
             "team — they'll put together a quote and get back to you."),
        chips=(Chip("Request a quote", {"quote_requested": True}),),
        slots=("quote_requested",),
        apply=_apply_request_quote,
        done_when=lambda c: bool(c.get("quote_requested")),
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


def chips_of(step: Step, collected: dict) -> tuple[Chip, ...]:
    """The step's chips — derived from `collected` when they can't be literals."""
    return step.chips_from(collected) if step.chips_from else step.chips


# Every slot any step asks for. This is the interpreter's writable set: it may
# fill the current step's slot AND any other slot the customer volunteers
# ("logo on the back and 50 caps"), which is where reordering comes from.
# Internal bookkeeping (logos/pending_logo/logos_done/email_captured/_asked) is
# deliberately absent — the interpreter must never write it.
WRITABLE_SLOTS: frozenset[str] = frozenset(
    s for step in REGISTRY for s in step.slots
)

# --- V3 admin-configurable flow (Workstream D) --------------------------------
# The curated SAFE SUBSET: the only steps an admin may reorder/disable per store.
# Each is genuinely independent — its done_when reads only its OWN slot, it has
# no apply cross-effect, no prepare, no ops, and it belongs to no loop — so no
# other step's done_when can break when it moves or is dropped. Everything else
# is dependency-LOCKED and never moves: ASK_NAME, SHOW_INTRO, the logo loop, the
# decor loop (incl. ASK_ANYTHING_ELSE, which re-opens the loop), ASK_DECORATION
# (prepare-bearing — its store load may satisfy its own step) with its
# conditional partner ASK_DECORATION_MIX, ASK_EMAIL (must precede finalize, and
# is what makes FINALIZE_CANVAS unreachable without a captured lead), and
# FINALIZE_CANVAS itself.
#
# `needed_by` is added by Workstream B. Sourcing the set from REGISTRY by id
# string means a not-yet-merged needed_by simply drops out here rather than
# raising at import — and becomes configurable for free once B ships it.
_CONFIGURABLE_STEP_NAMES: frozenset[str] = frozenset(
    {"ask_quantity", "needed_by", "ask_purpose"}
)
CONFIGURABLE_STEP_IDS: frozenset[str] = frozenset(
    s.id.value for s in REGISTRY if s.id.value in _CONFIGURABLE_STEP_NAMES
)

SLOT_ENUMS: dict[str, frozenset[str]] = {
    "logo_face": FACES,
    "logo_bg": frozenset({"removed", "none"}),
    "decor_choice": frozenset({"text", "shape"}),
    "decor_face": FACES,
}
