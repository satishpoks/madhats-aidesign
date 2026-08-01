"""v2 canvas routing — a generic engine over the canvas_steps registry.

Routing is first-unmet resolution: return the first step whose done_when(collected)
is False. That is a pure function of `collected`, so it is exhaustively testable
with plain dicts and needs no LLM, no mocking and no Supabase.

Flexibility comes from slot-filling, not from anyone choosing a route: if the
interpreter banks a volunteered answer ("logo on the back and 50 caps"), the
step that asks for it is already done, so the router simply doesn't return it.

Order is enforced inherently — the router never returns any step positioned
after an unmet one — which is why there is no separate "gate" concept. The
load-bearing invariant (no FINALIZE_CANVAS without email_captured) holds because
ask_email precedes finalize_canvas and its done_when reads `email_captured`,
which only _apply_email sets and the interpreter cannot write.
"""
from __future__ import annotations

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation.canvas_steps import MAX_LOGOS, Step  # noqa: F401 re-export
from app.services.conversation.intent_extractor import repair_mojibake
from app.services.conversation.state_machine import ConversationState as S

# Every state a v2 turn may rest on. GREETING is the kickoff (no registry step:
# it greets and advances without ingesting the turn). Anything NOT here is a
# shared tail state v1 owns — orchestrator_v2 delegates those turns to v1.
V2_OWNED: frozenset[S] = frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}

# Flags that RECORD something rather than describe a preference: a lead
# captured, a quote submitted, a design confirmed or sent back for rework, the
# final-notes step answered. Each is made true by its owning step's `apply` (or
# its chip), and each satisfies a done_when. `merge_fields` is the only reader.
#
# The interpreter sees every WRITABLE_SLOT on every turn, so free text at ANY
# step can set one of these — and because a truthy write is normally always
# banked, that makes first-unmet SKIP the owning step, and its apply never runs.
# Two live regressions: session 766b8361 ("that's it let's go" at
# ASK_FINAL_NOTES -> quote_requested, so no MH-XXXXXX reference, no customer
# email, no sales notification) and session bb62d05a ("i need to go back to How
# many caps" at NEEDED_BY -> design_rework, so the design review was skipped
# entirely and the customer was dropped into the rework loop unasked).
#
# Deliberately NOT `checkpoints.CARRY_FORWARD_KEYS`, which is a wider set
# (lead_id, email_verified, reference_code) serving a different concern: what a
# Back restore must not roll back. Conflating them would let the interpreter
# write, say, reference_code off-step. Two concepts, two constants.
#
# Deliberately NOT extended to the loop-control slots (decor_done, has_logo,
# another_logo, more_decor, logo_placed, decor_placed): those are MEANT to be
# volunteerable from an earlier turn — "no, text only" satisfying ASK_HAS_LOGO
# is the slot-filling flexibility the registry design rests on.
_STEP_OWNED_FLAGS: frozenset[str] = frozenset({
    "email_captured", "quote_requested",
    "design_rework", "design_confirmed", "final_notes_done",
})


def merge_fields(step: Step, collected: dict, fields: dict) -> dict:
    """The fields of one interpreted turn that are safe to bank.

    First-unmet routing only moves forward while answered stays answered: every
    done_when is a truthiness read, so the ONE write that can un-answer a settled
    step is truthy -> falsy. The interpreter sees every WRITABLE_SLOT on every
    turn (deliberately — that is what banks a volunteered "and I need 50 caps"),
    which means a stray "no" anywhere in a free-text answer can fill an unrelated
    bool false and walk the router backward into a question the customer already
    answered. Live case: "no - i just want embroydary" at ASK_DECORATION_MIX
    filled decor_done:false, re-asking two settled steps.

    So: a falsy value may only overwrite a truthy one on the step that ASKED for
    that slot, where clearing it is the answer (backing out of a mix). Writes to
    unset slots pass untouched, keeping slot-filling flexible, and a truthy
    correction (50 -> 100 caps) never un-answers anything, so it passes too.

    A `_STEP_OWNED_FLAG` is the one exception in the OTHER direction: a truthy
    write is normally always banked, but volunteering one from free text at an
    earlier step makes first-unmet SKIP the owning step, so its apply never
    runs. Such a flag may only be set on the step that OWNS it (its chip, or
    the interpreter while that step is current), which is exactly where the
    apply runs too. See the constant for the two live regressions.

    "Its chip" is why `own` is not just `step.slots`: ASK_FINAL_NOTES's
    "Nothing to add" chip sets `final_notes_done` directly, and that flag is
    deliberately NOT one of the step's slots (so the interpreter can never
    fabricate it — see `_apply_final_notes`). Reading `own` from `step.slots`
    alone would make this guard drop the step's own chip write along with
    everyone else's, which is not "off-step" — it IS the step answering
    itself. `cs.chips_of` is the existing single read path for a step's chips
    (dynamic or static), so this reuses it rather than adding a second one.
    """
    own = set(step.slots) | {k for chip in cs.chips_of(step, collected)
                              for k in chip.fields}
    return {k: v for k, v in fields.items()
            if (k in own or v or not collected.get(k))
            and (k not in _STEP_OWNED_FLAGS or k in own)}


def effective_registry(config: dict | None) -> tuple[Step, ...]:
    """The registry as reordered/filtered by a store's canvas_flow config.

    PURE: a function of (config, cs.REGISTRY) only — no collected, no DB, no
    LLM — so the whole compose is exhaustively unit-testable with plain dicts.

    Locked steps keep their EXACT registry index; the configurable steps are
    redistributed among the indices configurable steps already occupy, in the
    admin's order, with disabled ones dropped (the trailing configurable slots
    collapse). Nothing ever crosses a locked step's position — that is what
    keeps this trivial, and it is the invariant that let Workstream D pass its
    Complexity gate. Needing to move a locked step, splice a configurable step
    into a locked index, or add a cross-step done_when dependency would mean the
    compose had entangled, and D should be dropped rather than forced.

    Ids outside CONFIGURABLE_STEP_IDS are ignored rather than honoured — the
    admin API rejects them (branding._validate_canvas_flow), and this second
    read keeps a hand-edited stores.brand row from moving a locked step either.

    A falsy/absent config returns cs.REGISTRY unchanged, so every existing
    caller and the whole non-configured baseline are byte-identical.
    """
    registry = cs.REGISTRY
    if not config:
        return registry
    steps_cfg = config.get("steps") or []
    cfg_ids = cs.CONFIGURABLE_STEP_IDS

    disabled: set[str] = set()
    ordered: list[str] = []
    seen: set[str] = set()
    for item in steps_cfg:
        sid = (item or {}).get("id")
        if sid not in cfg_ids or sid in seen:
            continue
        seen.add(sid)
        if item.get("enabled") is False:
            disabled.add(sid)
        else:
            ordered.append(sid)
    # Configurable steps the admin never mentioned keep default (registry)
    # order, enabled, appended after the ones they did.
    for step in registry:
        sid = step.id.value
        if sid in cfg_ids and sid not in seen:
            ordered.append(sid)

    by_id = {s.id.value: s for s in registry if s.id.value in cfg_ids}
    present = [by_id[sid] for sid in ordered if sid in by_id]

    slots = [i for i, s in enumerate(registry) if s.id.value in cfg_ids]
    result: list[Step | None] = list(registry)
    for i in slots:
        result[i] = None
    for pos, step in zip(slots, present):
        result[pos] = step
    return tuple(s for s in result if s is not None)


def back_targets(collected: dict, rows: list[dict]) -> list[dict]:
    """The Back destinations offerable right now, newest first.

    PURE: a function of (collected, rows) — the caller does the DB read, so the
    whole menu is testable with plain dicts.

    A row is offerable unless its checkpoint's own `frozen_when` says otherwise.
    Freezing is per-checkpoint rather than a positional floor, which is what
    lets `name` freeze at email verification (mid-design) while the logo placed
    just before the email step stays rewindable.

    An empty list is how "no going back" is expressed — there is no separate
    disable flag to keep in sync with this one.
    """
    if collected.get("quote_requested"):
        # Submitted: the reference is minted and sales has been emailed. Nothing
        # before it is undoable.
        return []
    out: list[dict] = []
    for row in rows:
        step = cs.by_id_value(row.get("step_id"))
        cp = step.checkpoint if step else None
        if cp is None or cp.frozen_when(collected):
            continue
        out.append({"seq": row["seq"], "label": row["label"], "kind": row["kind"]})
    out.sort(key=lambda t: t["seq"], reverse=True)
    return out


def next_step(collected: dict, config: dict | None = None) -> Step:
    """The first step whose done_when is False, over the config-composed
    registry. FINALIZE_CANVAS is terminal (done_when is always False) and is
    always locked-last, so this always returns a Step.

    `config` defaults to None so every existing caller and test is unchanged.
    """
    for step in effective_registry(config):
        if not step.done_when(collected):
            return step
    return cs.REGISTRY[-1]


# The customer-facing question steps, in order — the loop/adjust steps collapse
# onto their loop's anchor so "Step X of N" stays steady during a deep-dive.
_PROGRESS_ANCHORS: dict[S, S] = {
    S.ASK_HAS_LOGO: S.ASK_LOGO_PLACEMENT,
    S.LOGO_ADJUST: S.ASK_LOGO_PLACEMENT,
    S.ASK_LOGO_BG: S.ASK_LOGO_PLACEMENT,
    S.ASK_ANOTHER_LOGO: S.ASK_LOGO_PLACEMENT,
    S.ASK_DECOR_PLACEMENT: S.ASK_ADD_DECOR,
    S.DECOR_ADJUST: S.ASK_ADD_DECOR,
    S.ASK_ANYTHING_ELSE: S.ASK_ADD_DECOR,
    # Describing a mix is a follow-up to the decoration question, not a step of
    # its own — asking for a mix must not make the counter grow a step.
    S.ASK_DECORATION_MIX: S.ASK_DECORATION,
    # The explicit submit is the last beat of ASK_PURPOSE, not a numbered step.
    S.REQUEST_QUOTE: S.ASK_PURPOSE,
    # The pre-submit review (and any rework loop it opens) also folds onto the
    # final beat, so the counter stays put rather than growing past "done".
    S.REVIEW_DESIGN: S.ASK_PURPOSE,
    S.REWORK_CANVAS: S.ASK_PURPOSE,
    S.ASK_FINAL_NOTES: S.ASK_PURPOSE,
    # Email rides the design phase (asked right after the first element is
    # placed) — it is not a numbered step of its own, so it must not move the
    # counter backward relative to whatever design step is in progress.
    S.ASK_EMAIL: S.ASK_LOGO_PLACEMENT,
    # The verification wait is the second beat of the email ask, not a step of
    # its own — the counter must sit still while the customer checks their inbox.
    S.AWAIT_EMAIL_VERIFY: S.ASK_LOGO_PLACEMENT,
}
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE,
]

_SECTIONS: list[str] = [
    "Intro", "Logo & Image", "Text & Graphics", "Review", "Quote request",
]
# Every registry step -> its milestone section (0-based). FINALIZE_CANVAS is
# deliberately absent: it (and any shared-tail state with no registry step)
# resolves to len(_SECTIONS) == "all milestones complete".
_STEP_SECTION: dict[S, int] = {
    S.ASK_NAME: 0, S.SHOW_INTRO: 0,
    S.ASK_HAS_LOGO: 1, S.ASK_LOGO_PLACEMENT: 1, S.LOGO_ADJUST: 1,
    S.ASK_LOGO_BG: 1, S.ASK_EMAIL: 1, S.AWAIT_EMAIL_VERIFY: 1,
    S.ASK_ANOTHER_LOGO: 1,
    S.ASK_ADD_DECOR: 2, S.ASK_DECOR_PLACEMENT: 2, S.DECOR_ADJUST: 2,
    S.ASK_ANYTHING_ELSE: 2,
    S.ASK_QUANTITY: 3, S.ASK_DECORATION: 3, S.ASK_DECORATION_MIX: 3,
    S.NEEDED_BY: 3, S.ASK_PURPOSE: 3, S.REVIEW_DESIGN: 3, S.REWORK_CANVAS: 3,
    S.ASK_FINAL_NOTES: 3,
    S.REQUEST_QUOTE: 4,
}


def section_for(step: Step) -> int:
    """The 0-based milestone section for a step. finalize + any unmapped step
    resolve to len(_SECTIONS) == all milestones complete."""
    return _STEP_SECTION.get(step.id, len(_SECTIONS))


def progress_for(step: Step) -> dict:
    total = len(_PROGRESS_PATH)
    section = {"sections": _SECTIONS, "section": section_for(step)}
    anchor = _PROGRESS_ANCHORS.get(step.id, step.id)
    if anchor in _PROGRESS_PATH:
        return {"step": _PROGRESS_PATH.index(anchor) + 1, "total": total, **section}
    return {"step": total, "total": total, **section}   # finalize + tail -> complete


def progress_v2(state: S, collected: dict | None = None) -> dict:
    """State-keyed wrapper, kept at its original signature for
    `sessions.py`'s canvas-finalize route — which calls it with GENERATING, a
    shared-tail state that has no registry step (-> "complete")."""
    step = cs.by_id(state)
    if step is None:
        total = len(_PROGRESS_PATH)
        return {"step": total, "total": total,
                "sections": _SECTIONS, "section": len(_SECTIONS)}
    return progress_for(step)


def _norm(s: str) -> str:
    """Casefolded comparison key for a chip label.

    `repair_mojibake` is applied because a chip label round-trips through the
    browser and can come back CP1252-mangled — live session bb62d05a posted
    "2â€“4 weeks" for the en-dash chip "2–4 weeks". Without the repair the
    exact-label match misses, so a chip tap (designed as a 0-LLM identity
    lookup on a set we own) burns an interpreter call AND the mangled text is
    what gets stored, reaching brief_notes and the sales email. Repairing the
    KEY rather than the value means a matched chip still banks its own clean
    payload. `repair_mojibake` is a no-op on clean text, so nothing else moves.
    """
    return repair_mojibake(s or "").strip().casefold()


# The decor branch's steps. They read `decor_face`; the logo branch reads the
# pending logo's face. DECOR_ADJUST always set face_target=True but _face read
# pending_logo — which is None once the logo loop closes — so text silently
# always targeted "front".
_DECOR_STEPS: frozenset[S] = frozenset({S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST})


def _face(step: Step, collected: dict) -> str:
    if step.id in _DECOR_STEPS:
        face = collected.get("decor_face")
    else:
        face = (collected.get("pending_logo") or {}).get("face")
    return face if face in cs.FACES else "front"


def _decor_tool(collected: dict) -> str:
    return "shape" if collected.get("decor_choice") == "shape" else "text"


def directive_for(step: Step, collected: dict) -> dict:
    """The canvas-control blob for a step. EVERY owned step returns one: the
    tool steps hand over their single tool, every other step locks all tools
    explicitly. A null directive means "not a v2 turn" and makes the frontend
    fall back to v1's whole-rail gating + status strip — which showed "Design
    locked in — finishing up" mid-design."""
    if step.id is S.REWORK_CANVAS:
        return {"allowed_tools": ["upload", "text", "shape"], "target_face": None,
                "auto_open": None, "instructions": prompts.V2_REWORK_INSTRUCTIONS,
                "show_done": True, "unlock_all": True}
    if step.tool is None:
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False, "unlock_all": False}
    tool = _decor_tool(collected) if step.id in _DECOR_STEPS else step.tool
    return {
        "allowed_tools": [tool],
        "target_face": _face(step, collected) if step.face_target else None,
        "auto_open": tool if step.auto_open else None,
        "instructions": step.instructions or prompts.V2_TOOL_TIPS[tool],
        "show_done": step.show_done,
        "unlock_all": False,
    }


def canvas_directive(state: S, collected: dict) -> dict | None:
    """State-keyed wrapper: None for a shared-tail state v2 doesn't own."""
    step = cs.by_id(state)
    return directive_for(step, collected) if step else None


def public_data_for(step: Step, collected: dict) -> dict:
    data: dict = {}
    chips = cs.chips_of(step, collected)
    if chips:
        data["options"] = [c.label for c in chips]
    if step.multiselect:
        # The shape ChatColumn's multi-select already consumes from v1.
        data["multiselect"] = True
        data["selected"] = []
    if step.continuable:
        data["continuable"] = True
    if step.id is S.FINALIZE_CANVAS:
        data["trigger_finalize"] = True
    data["canvas"] = directive_for(step, collected)
    data["progress"] = progress_for(step)
    return data


def reply_for(step: Step, collected: dict, *, persona: str, intro: str,
              ack: str = "", colour_note: str = "") -> str:
    """ack (LLM, best-effort) + the step's copy + its tool tip (verbatim).

    The tip is concatenated from the registry and never passes through a model,
    so a warm paraphrase cannot drop "select the highlighted button" and leave
    the customer stuck. Without an ack the reply is simply the scripted copy.

    Parts are joined with a BLANK LINE, not a space. The chat bubble is
    `whitespace-pre-wrap`, so this is what makes an instruction render as its
    own paragraph under the question instead of running into it.
    """
    if step.id is S.DECOR_ADJUST:
        # The tip is resolved at runtime (text vs shape), so it is PREPENDED to
        # this step's copy rather than appended like every other step. `step.ask`
        # is used rather than a re-typed literal so the two cannot drift.
        body = f"{prompts.V2_TOOL_TIPS[_decor_tool(collected)]}\n\n{step.ask}"
    else:
        asked = step.ask_retry and step.id.value in (collected.get("_asked") or [])
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
            colour_note=colour_note,
        )
        if step.tip and step.id is not S.LOGO_ADJUST:
            body = f"{body}\n\n{step.tip}"
    return f"{ack}\n\n{body}".strip() if ack else body


def resolve_chip(step: Step, message: str, collected: dict) -> dict | None:
    """The fields for an offered chip, or None if `message` isn't one of them.

    A chip tap is not natural language: we generated the label in this registry
    and shipped it to the browser, which sent it straight back. Matching it is an
    identity lookup on a closed set we own — no model, no latency, no failure
    mode. Only the CURRENT step's chips match; a stale chip tapped on an older
    message falls through to the interpreter, which reads it in context.
    """
    chips = cs.chips_of(step, collected)
    if step.multiselect:
        return _resolve_multi(step, chips, message)
    target = _norm(message)
    for chip in chips:
        if _norm(chip.label) == target:
            return dict(chip.fields)
    return None


def _resolve_multi(step: Step, chips: tuple[cs.Chip, ...], message: str) -> dict | None:
    """A multi-select submission: the labels we shipped, comma-joined.

    Both strings the UI can send here are ours: `decoSel.join(', ')` and the
    literal 'none' when Continue is tapped with nothing selected
    (ChatColumn.submitDeco:274). Anything else is free text and belongs to the
    interpreter, so this returns None for it.
    """
    if _norm(message) == "none":
        return {slot: [] for slot in step.slots}
    by_label = {_norm(c.label): c for c in chips}
    out: dict = {}
    matched = False
    for tok in message.split(","):
        chip = by_label.get(_norm(tok))
        if chip is None:
            continue
        matched = True
        for key, val in chip.fields.items():
            if isinstance(val, list):
                cur = out.setdefault(key, [])
                cur.extend(v for v in val if v not in cur)
            else:
                out[key] = val
    return out if matched else None
