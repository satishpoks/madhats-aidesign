# Studio review gate + orchestrator correctness — design

**Date:** 2026-08-01
**Branch:** `feat/studio-review-gate-and-orchestrator-fixes`
**Status:** approved, ready for planning

Four workstreams shipped as one branch. Three came out of a live session review
(`bb62d05a`, 2026-08-01 08:22–08:27 UTC); the fourth is a customer-comprehension
gap the same session exposed.

---

## 1. Why

A real v2 canvas session was walked end to end and left two pieces of feedback in
the transcript itself. Investigation reproduced both deterministically against the
live Haiku model and turned up a third defect the customer never mentioned.

### 1a. A routing flag written off-step silently skipped the review

At `NEEDED_BY` the customer typed:

> "i need to go back to How many caps do you need? - it should be possible. from here."

`orchestrator_v2` has no conversational-back concept, so the turn went to
`intent_extractor.interpret_turn_v2`, which is shown **every** `WRITABLE_SLOT` on
every turn. It read "go back and change something" and filled a slot owned by a
step four positions later. Reproduced 3/3:

```
STEP needed_by  MSG: 'i need to go back to How many caps do you need? ...'
  [0] raw_fields={"design_rework": true}   -> next_step=needed_by
  [1] raw_fields={"design_rework": true}   -> next_step=needed_by
  [2] raw_fields={"design_rework": true}   -> next_step=needed_by
```

`merge_fields` banked it — an unset→truthy write is explicitly allowed — and
routing did not move, because `needed_by` was still unmet. **Nothing looked wrong
at the time.** `collected` was silently poisoned.

Two turns later, once `purpose` was banked, `REVIEW_DESIGN.done_when`
(`design_confirmed or design_rework`) was already satisfied:

```
clean               -> review_design
design_rework=True  -> rework_canvas
```

That is the exact live transition `ask_purpose -> rework_canvas`. The customer was
never asked "are you happy with it?" — the review step was skipped outright and
they were dropped into the rework loop.

This is the same bug class as `240b7f9` (a volunteered `quote_requested` skipping
`REQUEST_QUOTE`, which cost a reference code, a customer email and a sales
notification), one slot over.

### 1b. The ack model answered the system prompt instead of the customer

At `ASK_PURPOSE` the customer typed "dont say". Interpretation was correct
(`purpose: "dont say"`, banked via `accept_verbatim`). The damage came from
`intent_extractor.write_ack`:

```
fields={"purpose": "dont say"}
  [0] ack="I'm Ricardo, your design assistant at MadHats. What brings you in today?"
  [1] ack="I appreciate you sharing that context, but I'm ready to help customers
           design caps whenever they arrive."
  [2] ack="I appreciate you sharing that context, but I'm ready to start fresh
           when a customer arrives..."
```

`V2_ACK_PROMPT` renders `We understood: {"purpose": "dont say"}`. Haiku reads
`"dont say"` as an operator instruction rather than customer data and answers
`RICARDO_SYSTEM_PROMPT` — the system prompt `_complete` passes by default —
paraphrasing its hard rules back at the customer. Run `[0]` is worse: a fresh
greeting mid-flow, which that same system prompt forbids, and an ack that asks a
question, which `V2_ACK_PROMPT` forbids.

Nothing validates the ack. `_strip_meta_preamble` only removes a
`"Here's Ricardo's message:"` prefix; a wholly out-of-character reply is
concatenated verbatim into the customer's bubble. The customer replied
"whay message is this???".

### 1c. The en-dash chips are broken (not reported, found in the data)

`collected["needed_by"]` stored as `2â€“4 weeks`
(`U+00E2 U+20AC U+201C`), and the **user chat row carries the same mojibake** — the
browser posted the mangled label. The registry source is clean UTF-8
(`E2 80 93`). Consequences:

- `resolve_chip`'s exact-label match fails, so a chip tap — designed as a 0-LLM
  identity lookup — burns an interpreter call.
- Corrupted text lands in `needed_by`, which flows into `brief_notes` and the
  sales email.

Affects `"2–4 weeks"` and `"1–2 months"` today, and threatens any non-ASCII chip
label. The v2 copy is full of em-dashes.

### 1d. The customer cannot tell who is talking

The chat renders attribution as *bubble side + colour only*
(`ChatColumn.tsx:451-465`). There is no name, no avatar, no per-message marker.

---

## 2. Workstream A — orchestrator correctness

### A1. Gate flags become step-owned

`state_machine_v2._TERMINAL_FLAGS` already carries the exact guard needed:

```python
and (k not in _TERMINAL_FLAGS or k in own)
```

— a flag may only be written by a step that declares it as a slot. It is missing
the flags that bit us. Rename to `_STEP_OWNED_FLAGS` and extend to:

```python
frozenset({
    "email_captured", "quote_requested",      # existing (240b7f9)
    "design_rework", "design_confirmed",      # 1a
    "final_notes_done",                       # same class
})
```

The mechanical rule is identical for all five, so one constant is honest. The
"two concepts, two constants" note in that file draws its line against
`checkpoints.CARRY_FORWARD_KEYS` — a different concern (what a Back restore must
not roll back) — and is **unchanged**.

Why each is safe:

| Flag | Owning step(s) | Off-step write would |
|---|---|---|
| `design_rework` | `REVIEW_DESIGN`, `REWORK_CANVAS` | skip the review (proven, 1a) |
| `design_confirmed` | `REVIEW_DESIGN` | skip the review, straight to final notes |
| `final_notes_done` | `ASK_FINAL_NOTES` | skip the colour-disclaimer copy entirely |

`design_rework` is a slot of both `REVIEW_DESIGN` and `REWORK_CANVAS`, so setting
it at review and clearing it at rework both keep working. Only off-step writes are
blocked.

**Explicitly not added:** `decor_done`, `has_logo`, `another_logo`, `more_decor`,
`logo_placed`, `decor_placed`. These are loop-control slots the interpreter is
*meant* to be able to volunteer ("no, text only" must satisfy `ASK_HAS_LOGO` from
an earlier turn). Restricting them without evidence would break intended
slot-filling flexibility.

### A2. The ack cannot leak, and cannot break character

Two independent changes.

**Stop handing the ack call a persona brief.** `write_ack` calls `_complete`
without overriding `system`, so it inherits `RICARDO_SYSTEM_PROMPT` — a
behavioural brief for a *conversational* Ricardo. The ack call is a one-line
transform over a JSON field dump. Giving a model a behavioural brief and then
ambiguous data is what let it answer the brief. It gets a minimal system prompt
with no instructions to leak.

**Validate before use.** A pure `_ack_is_sane(text) -> bool` rejecting:

- contains `?` (the prompt forbids questions)
- opens with a greeting token (reuse the existing `_GREETING_TOKENS`)
- more than 20 words, or more than one paragraph
- self-reference: `customer`, `Ricardo`, the store persona name, `I'm ready`

Failing → return `""`, which every caller already handles (an outage makes the bot
terse, never uninstructive). Unit-tested against the three captured live strings.

Both are needed: the minimal system prompt removes the *source* of the leak, the
guard catches any future breach of the ack's own rules regardless of cause.

### A3. Mojibake chips

The mangling layer is **not yet identified** — the registry source is clean and
the browser posts corrupted text, but which hop corrupts it is unknown. Assistant
message content containing em-dashes round-trips correctly, so it is not a blanket
response-decoding fault. This workstream therefore **starts with a timeboxed
investigation**, not a guess.

Independent of what it finds, two defence-in-depth changes go in:

1. `resolve_chip` normalises both sides through the existing `repair_mojibake`
   before comparing, so a mangled label still resolves as a chip (0 LLM calls).
2. Slot values are repaired on store, so corrupted text cannot reach `brief_notes`
   or the sales email.

These kill the class, not just the two labels. Rewriting the en-dashes to ASCII
hyphens is **rejected**: it hides a real bug that will resurface on any other
non-ASCII copy.

### A4. Not in scope

Free-text Back ("take me back to quantity") is **not** implemented here. The
structured Back menu already offers `Quantity — 45` as a live, unfrozen
checkpoint; the customer did not find it. That is a discoverability question worth
its own decision, and conflating it with the correctness fix would widen the
branch. A1 makes the free-text request *harmless* (it no longer corrupts routing);
making it *work* is a separate ticket.

---

## 3. Workstream B — review gate: dialog + watermark

### B1. Watermark is a DOM overlay, never a Konva layer

A sibling `<div>` positioned over the stage is **structurally incapable** of
appearing in `stage.toDataURL()`. That means:

- no `EXPORT_HIDE_NAME` tagging to maintain,
- the decorations-only layout guide (`flattenStage`) can never be contaminated —
  a watermark reaching the image model would be rendered onto the cap,
- the WYSIWYG preview (`flattenFull`) is never double-stamped, since
  `delivery.py::_canvas_design_images` already burns the watermark server-side at
  send time.

One `<Watermark>` component: absolutely positioned, `pointer-events-none`,
`aria-hidden="true"`, repeating diagonal text rendered as inline SVG. Used over
the canvas stage and over each review-dialog image.

### B2. Visibility is backend-driven

`state_machine_v2` ships a `watermark: bool` alongside the existing `canvas`
directive in the turn's public data:

- `True` — `REVIEW_DESIGN`, `ASK_FINAL_NOTES`, `REQUEST_QUOTE`,
  `FINALIZE_CANVAS`, and every v1-delegated tail state (generating, verify,
  refine, quote).
- `False` — `REWORK_CANVAS` and every step before review.

One authoritative source, resume-safe, no frontend state list to drift out of
sync. Same pattern `useActiveSurface` already follows. The rule matches the
approved boundary: **watermarked when the design is locked, clean while they are
actually editing.**

### B3. The dialog needs no flatten, no upload, no endpoint

`FaceThumbnails` already renders a static mini Konva stage per face (angle photo +
colour tint + placed elements, at scale). `ReviewDialog` reuses that technique at
full size for each **decorated** face, with `<Watermark>` overlaid.

Consequences: always in sync with the canvas, no round trip before the dialog
opens, no new backend route, nothing uploaded early.

Behaviour: opens when `chatState === 'review_design'`; `role="dialog"`
`aria-modal="true"`; focus trap; Esc closes; mirrors the two review chips
("Looks great, send it" / "I'd like to rework it") so the customer can act from
inside it. Closing is allowed — the canvas behind it is watermarked anyway.

### B4. Watermark text

Sourced from the existing `watermark_text` admin app setting, exposed to the
customer via `GET /storefront` → `branding.public_brand`. A deliberate allow-list
addition of a display string. `watermark_asset_url` stays internal, as documented.

### B5. What this does and does not buy

**Does:** every pixel on screen from `review_design` onward carries a watermark,
so a screenshot is a watermarked screenshot. The images that actually leave the
system — the emailed previews — remain burned server-side by `delivery.py` and are
unaffected by anything in the browser.

**Does not:** the displayed watermark is a DOM node and can be deleted from
devtools. Screenshots cannot be prevented in a browser by any means; the
achievable goal is that no clean pixels are ever rendered. Making the *displayed*
watermark unstrippable requires server-rendered dialog images — offered and
declined in favour of the no-round-trip client overlay.

---

## 4. Workstream C — focus cue

Replaces the current `ring-2 ring-canvasAccent` + `shadow-[0_0_18px_-4px_…]` +
blanket `opacity-60` treatment in `CustomiseStudio/index.tsx`.

**Approved design: a filled per-column header on lifted cards.**

- Both columns become cards on a warm-grey desk, each with a **permanent header
  strip** naming it: `Your design` (canvas) / `Ricardo` (chat).
- The active column's header **fills with the brand accent**, white text, and
  states the instruction: `Your turn — design here` / `Your turn — answer here`.
- The active card carries a **layered shadow**
  (`0 10px 24px -10px …, 0 2px 6px -2px …`). No outline, no glow.
- The resting column softens its **content only** — the cap, the tools, the
  thread. Its header and card structure stay at full contrast, so it reads as
  "not your turn" rather than "disabled" or "error".

Fixed names beat status words (`Waiting` / `Up next`): they teach a first-time
customer what the two halves *are*, and the accent fill already carries the
whose-turn signal.

Kept exactly as-is:

- `useActiveSurface()` — still the single source of truth.
- No `pointer-events-none`. Dimming is a cue, never a lock; real locking stays
  per-affordance (`CanvasStage` `locked`, `ToolRail` `allowedTools`, `ChatColumn`
  `inputLocked`). Blocking events would stop the customer scrolling back through
  the thread or re-reading the cap.
- `CHAT_UNANSWERABLE_STATES` — those states get the resting header, not the
  accent one.

`FocusPill` (the `▶` chip) is **removed**; `role="status"` moves onto the active
header, so the cue is still announced to assistive tech and is never colour-only.

---

## 5. Workstream D — message attribution

**Approved: coloured lane on every message, name line on speaker change.**

- Every message carries a 2px coloured spine — accent for Ricardo (left), slate
  for the customer (right). This is the per-message identifier and it is
  **always** present.
- The name line (`Ricardo · Design assistant` / `You`) renders only when the
  speaker changes from the previous message.

Why grouping the *words* but not the *marker*: v2 routinely emits multiple
assistant bubbles per turn (`data.extra_replies`, plus the reply/instruction
split). Repeating an identical header on consecutive Ricardo bubbles reads as
padding, especially on a phone. The lane keeps every single message unambiguous.

No avatar column: it costs ~30px of width, which is material at 320px, and the
lane already answers the question.

Persona name comes from the store (`persona_name`), not a hardcoded "Ricardo".
The customer's label is the literal word `You` — never their captured name, which
avoids putting PII in a repeated UI element.

---

## 6. Mobile

Explicitly requested. Included in the same branch.

- The chat's hard `h-[45vh]` becomes a flexible split, so the thread can breathe
  when the canvas is not in play.
- The new column headers are counted into the sub-`md` Adjust-panel budget
  (`max-h-[9rem]`) rather than stealing height from the cap.
- Bubbles widen past `max-w-[80%]` on narrow screens — with no avatar column, the
  lane provides the offset.
- `ReviewDialog` goes full-screen under `md`, views stacked and scrollable, not a
  shrunken desktop modal.

**Verification limitation, stated up front:** sub-768px has never been observed in
a real browser on this project — `resize_window` is a no-op in this environment
and the devtools MCP cannot attach (already recorded in CLAUDE.md). Mobile will
rest on clamp arithmetic plus class-pinning tests. It will **not** be reported as
verified. Closing that gap needs the studio opened on a real phone against the dev
server.

---

## 7. Testing

**Workstream A** — pure-function tests, no LLM:

- `merge_fields` drops `design_rework` / `design_confirmed` / `final_notes_done`
  written off-step; accepts each on its owning step. Each case must be verified to
  **fail with the guard removed** (the standard `240b7f9` set).
- `next_step` regression driving the live sequence: quantity → the back-request
  turn → purpose, asserting it lands on `review_design`, not `rework_canvas`.
- `_ack_is_sane` rejects the three captured live strings; accepts a normal ack.
- `resolve_chip` resolves a mojibake-mangled `"2–4 weeks"` with zero interpreter
  calls.

**Workstreams B–D** — vitest:

- `watermark` directive true/false per state; the overlay mounts and unmounts with it.
- The overlay is **absent from both** `flattenStage` and `flattenFull` output
  (guards the layout-guide contamination risk directly, not just by construction).
- `ReviewDialog` opens at `review_design`, lists only decorated faces, traps
  focus, closes on Esc.
- Focus cue: active/resting header classes, `role="status"` placement, and the
  absence of `pointer-events-none`.
- Attribution: a lane on every message; a name line only on speaker change,
  including across an `extra_replies` multi-bubble turn.

**Suite baselines to hold** (from CLAUDE.md, re-measured before starting):
backend flag-off 1259+, the five v2 suites flag-on 330+, frontend 330+,
`tsc --noEmit` clean.

---

## 8. Risks

| Risk | Handling |
|---|---|
| A3's root cause is not found in the timebox | The two defence-in-depth changes stand alone and fix the customer-visible symptom; the investigation becomes a follow-up ticket. |
| `_ack_is_sane` is too strict and silences normal acks | Guard returns `""`, a path the code already handles gracefully. Tuned against real ack samples, not invented ones. |
| Mobile regressions | Cannot be fully mitigated here — see §6. Stated as unverified rather than claimed. |
| The review dialog's static-stage render diverges from the live canvas | It reads the same `canvasStore` state as `FaceThumbnails`, which is already proven to stay in sync during editing. |

---

## 9. Out of scope

- Free-text Back (§A4).
- Server-rendered watermarked dialog images (§B5) — offered, declined.
- Any change to `delivery.py`'s server-side watermarking of emailed previews.
- Any change to v1 (`orchestrator.py`) or the non-canvas flows.
