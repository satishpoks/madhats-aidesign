# Canvas-led refine + background removal that ticks itself

**Date:** 2026-07-17
**Status:** Approved — ready for implementation plan
**Touches:** `backend/app/services/conversation/{canvas_steps,state_machine_v2,orchestrator,canvas_edit}.py`, `backend/app/{prompts,models/message}.py`, `backend/app/api/routes/sessions.py`, `frontend/src/store/{chatStore,canvasStore}.ts`, `frontend/src/components/DesignStudio/Surface.tsx`

## 1. Why

Two requests from the live session review (`917c9aff`, 2026-07-17), plus one
live bug found while tracing them.

**A described change goes straight to the image model.** At `OFFER_REFINE` →
"Request changes", a canvas session gets `ASK_CHANGE_METHOD` with two chips:
"Rework on the canvas" (the customer edits it themselves) and "Describe the
change here". The describe branch collects text into `refine_details`, folds it
into the prompt as `change_request` (`generate.py:183-191` →
`prompt_builder.py:263-269`), and re-renders. So "move the logo up a bit" — a
change the canvas can make exactly, instantly, for free — becomes a paid,
non-deterministic round trip to Gemini that may also disturb everything else on
the cap. The canvas is right there on screen, already holding the design.

**Background removal asks the customer to do the app's job** — and silently
fails if they don't. `ASK_LOGO_BG` says *"click it on the cap and tick 'Remove
background' in the toolbar underneath"*, with chips "Yes, I've ticked it" /
"No, it's fine as is".

**The live bug:** `_apply_logo_bg` writes `c["pending_logo"]["bg"]`
(`canvas_steps.py:162`). That slot **routes** — `ask_logo_bg`'s `done_when` is
`not _logos_open(c) or "bg" in _pending(c)`, so it is the step's answered-marker
and is load-bearing. But **nothing on the render path ever reads it**: the
knockout is driven solely by the canvas element flag, `canvas_describe.py:103`
reading `el.removeBg` off the `canvas_design` blob → `prompt_builder.py:152`
emitting the knockout instruction. So the chip answer moves the conversation on
while changing nothing about the render, and a customer who taps **"Yes, I've
ticked it" without ticking it gets no background removal, silently**. (The
`remove_bg` machinery in `orchestrator.py`/`element_planner.py` is v1's
deep-dive path — a separate flow that does feed the prompt. This defect is
confined to v2 canvas.)

Having the bot tick it closes the hole by construction: the answer and the flag
become the same act.

## 2. Decisions taken during design

| Question | Decision |
|---|---|
| Changes the canvas can't express ("make the embroidery thicker", "make it pop") | **Refuse, don't render.** A described change never becomes a prompt edit. Captured to `brief_notes` for the team at quote time. |
| What the customer sees before a render is spent | **Canvas updates, chat asks to confirm.** Iteration before "Looks right" is free and burns no edit cap. |
| Op vocabulary | **Adjust existing elements only.** No adding, no logo swap. Every op targets an element that already exists. |
| Geometry | **The LLM picks intent, code does the maths.** Closed vocabulary (`direction`, `amount`); the model never emits a number. |
| `ASK_CHANGE_METHOD` | **Both chips stay.** Manual rework beats describing it for fiddly work. |

## 3. The channel: `data.canvas_ops`

Neither feature is possible today: the only backend→canvas channel is the v2
`data.canvas` directive, which is five keys of tool gating
(`state_machine_v2.directive_for:123-139`) and is **v2-only** —
`canvas_directive` returns `None` for shared-tail states, and refine lives in
the v1-owned tail (`OFFER_REFINE` ∉ `V2_OWNED`).

Add one field to the chat response, usable from both v1 and v2:

```jsonc
data.canvas_ops: [ { "target": {...}, "patch": {...} } ]
```

The backend resolves **everything** — arithmetic, clamping, colour names → hex —
so each op is a flat patch the frontend applies verbatim. Dumb frontend,
testable backend. `ChatResponse.data` is an untyped `dict`
(`models/message.py:13`), so the wire costs nothing.

The directive stays purely about tool gating. Bolting `set_remove_bg` onto it
would make it v2-only and mix "gate the tools" with "mutate the design".

### Two target kinds

```jsonc
{ "kind": "element", "id": "el_3", "face": "front" }   // refine
{ "kind": "pending_logo", "face": "front" }            // background removal
```

They differ because the backend's knowledge differs. At refine time the
persisted `canvas_design` blob holds every element **with its id** (`canvasStore
.toCanvasDesign` is a bare `{colourway, faces}` — lossless). At `ASK_LOGO_BG`
the just-placed logo exists **only in the browser's `canvasStore`** —
`canvas_design` is written at finalize and never before — so the backend has no
id to target. The frontend resolves `pending_logo` to *the last unlocked image
on that face*, the same trick `lockPlaced()` already leans on ("lock all
unlocked" == "lock what was just placed", `canvasStore.ts:73-75`).

### Applied in the store's response handler, NOT a React effect

Ops are applied imperatively in `chatStore` where the response lands, not via
`useEffect` in `Surface`. An effect fires on *change*, which reopens
idempotency: re-applying on resume/hydrate, or re-flagging a different logo on a
later loop pass. Applying at the response site runs exactly once, and
`hydrate()` (resume) simply never calls it.

This also lands the patch before `Surface.tsx:111-113`'s `lockPlaced()` effect.
Ordering is safe either way — `updateElement` (`canvasStore.ts:138-143`) doesn't
check `locked` — but the sequence is patch-then-lock, which is what we want.

**Constraint:** `updateElement` patches only within `s.activeFace`. Every op
carries `face`, so the store action must take a face argument rather than rely
on the active one.

## 4. Background removal

- Chips → `Chip("Yes, remove background", {"logo_bg": "removed"})`,
  `Chip("No, it's fine as is", {"logo_bg": "none"})`.
- `logo_bg == "removed"` → emit
  `{target: {kind: "pending_logo", face: <logo face>}, patch: {removeBg: true}}`.
- The ✂ badge appears on the logo as visible confirmation (`nodes.tsx:234-238`,
  `name="export-hide"` — never bakes into the layout guide).
- Copy stays honest per the standing rule: never promise processing, never ask
  the customer to wait, because the mark is instant. *"I've marked it — we'll
  knock the background out when we render your design."*
- `pending_logo["bg"]` **stays as-is**: it is `ask_logo_bg`'s answered-marker
  (`done_when` reads `"bg" in _pending(c)`), so it routes. It simply stops being
  the *only* consequence of the answer — the op is what makes it true on the
  render. Do not "clean it up": deleting it strands the step.

**`tool="upload"` stays.** It is documented as load-bearing and pinned by
`test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable` plus the
e2e walk, purely so the logo stays selectable and the toolbar checkbox is
reachable. Once Ricardo ticks it, that reason evaporates — but keeping it
preserves manual tick/untick as a fallback and leaves a documented invariant
undisturbed. Removing it buys little and breaks the tests that exist to catch
exactly that removal. `instructions` must stay non-`None` (a `None` falls back
to `V2_TOOL_TIPS["upload"]`, the wrong tip — which is why the field exists).

## 5. Canvas-led refine

```
OFFER_REFINE → "Request changes" → ASK_CHANGE_METHOD   (unchanged, both chips)
  └─ "Describe the change here" → DESCRIBE_CHANGES
       ├─ ops found  → apply to canvas → CONFIRM_CANVAS_EDIT
       │                 ├─ "Looks right" → reworking=True → doRender/finalize → REGENERATING
       │                 └─ "Not quite"   → back to DESCRIBE_CHANGES
       └─ no ops     → append to brief_notes, stay at OFFER_REFINE
```

Canvas-only; every branch gated on `flow_mode == "canvas"`. Non-canvas sessions
(`session`/`blank`) keep `DESCRIBE_CHANGES` → `change_request` → regenerate
exactly as today.

### `services/conversation/canvas_edit.py`

A new module, deliberately small and independently testable.

- **Inventory** built from `canvas_design`: `[{id, face, type, description}]`.
  Ids are a closed set we own, so validation is an identity lookup — a
  hallucinated id is dropped, never applied.
- **Haiku returns a closed vocabulary**, never a number:
  `{op, element_id, direction, amount}`.
- **Resolution is pure**: `amount` → delta, apply, clamp to stage bounds. A pure
  function over plain dicts, exactly like `next_step` — no LLM, no Supabase, no
  mocking in its tests.

Ops: `move`, `resize`, `rotate`, `recolour`, `font`, `curve`, `set_text`,
`delete`.

The split mirrors v2's existing stance — *the LLM reads the customer, it never
routes* — extended to *it never computes geometry*.

### Consequences

- **`change_request` retires for canvas sessions.** The re-render is a fresh
  render of the updated canvas, not a prompt edit. This sidesteps an existing
  defect on the rework branch: `sessions.py:251-263` hands the model
  `prior_design_url` (the old render) alongside a new layout guide with **no**
  `change_request`, so the "start from CURRENT DESIGN, change only what's
  requested" instruction never fires and the model must guess the relationship.
- **`LLMUnavailable` stalls**, no keyword fallback — geometry is precisely where
  a wrong guess wrecks an approved design. Reply suggests "Rework on the canvas"
  as the escape hatch.
- **Iteration is free.** No model call, no edit cap, until "Looks right".
- **Confirm reuses the rework path.** "Looks right" sets `reworking=True` and
  emits `trigger_finalize`; `Surface`'s existing effect runs `doRender()` →
  re-flatten → re-upload layouts/previews → `finalize` → `sessions.py:251-263`
  → `REGENERATING`. No parallel machinery.

## 6. Testing

- `canvas_edit` op resolution: pure-dict tests — each op, each amount, clamping
  at every edge, hallucinated id dropped, unknown op dropped.
- Refuse path: a render-level description yields zero ops → `brief_notes` gets
  the note, state stays `OFFER_REFINE`.
- `LLMUnavailable` → stall, state unchanged.
- Registry: `ask_logo_bg` chips resolve to the right `logo_bg`; the step still
  allows a tool (existing test must stay green).
- `canvas_ops` emitted only when `logo_bg == "removed"`.
- Frontend: `chatStore` applies ops once on response and **not** on `hydrate`;
  `canvasStore` patches the named face, not the active one.
- Non-canvas regression: `session`/`blank` refine still produces
  `change_request`.

## 7. Explicitly out of scope

Both pre-existing and orthogonal; noted during the trace, deliberately not
fixed here:

- **429 `edit_limit` is swallowed.** `ChatColumn.tsx:306-313` treats a rejected
  regeneration identically to success, so a capped edit lands back at
  `OFFER_REFINE` as if a render happened — the exact failure
  `_apply_generation_gate` was written to prevent on the generation side.
- **`wants_changes` is substring keyword matching** (`orchestrator.py:952`), so
  "can you make it pop more?" registers as neither a change request nor a
  refusal and falls through to `QUOTE_REQUESTED`. It only works because the
  chips are worded to match.
- **`canvas_design` is only persisted at finalize** — no mid-design autosave; a
  customer who closes the tab before "Done designing" loses everything.
