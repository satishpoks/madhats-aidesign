# v2 Canvas Orchestrator — Flow Gaps (background removal, decor placement, decoration type)

**Date:** 2026-07-17
**Status:** Approved — ready for implementation plan
**Touches:** `backend/app/services/conversation/{canvas_steps,state_machine_v2,orchestrator_v2}.py`, `backend/app/prompts.py`

## 1. Why

A full v2 canvas session (`583c9e34-38fc-4776-9630-7bd49fa0e1fe`, ran end-to-end
to a quote request) exposed four gaps. Reviewed against the transcript:

1. **Background removal is never asked.** `LOGO_ADJUST` mentions the toggle in a
   trailing clause; there is no question and no chip, so it scrolls past. Nothing
   ever confirms whether the logo has a background.
2. **Text/shape placement is never asked.** Logos get a face question
   (`ASK_LOGO_PLACEMENT`); text and shapes go straight from `ASK_ADD_DECOR` to
   `DECOR_ADJUST`, so the decoration lands on whatever face is active.
3. **The logo loop repeats itself verbatim.** After "Yes, another logo" the copy
   is word-for-word the first ask, including "Let's add your logo" — it reads as
   a reset, not a second item.
4. **The flow assumes a logo exists.** A text-only customer is marched through
   the logo steps with no exit.

Plus one addition requested during design: **ask the decoration type** (screen
print, embroidery, …) after quantity. v1 asks this; v2 skips straight from
`FINALIZE_CANVAS` to `GENERATING`, so `decoration_type` — which drives the
render-style bucket in the image prompt — is never collected on a v2 session.

The size/colour tip is a false alarm worth recording: `V2_TOOL_TIPS["text"]`
already says *"You can change the font, size and colour from the toolbar under
the cap."* and that line shipped in the reviewed session. The information exists
but reads as a footnote. Treated as a copy problem, not a missing feature.

**Explicitly out of scope** (considered, declined): reading the typed text back
in chat to catch typos. It needs the canvas to report the string to the chat —
new plumbing, deferred.

## 2. Load-bearing constraint: the lock

`Surface.tsx:111-113` locks every unlocked element as soon as the flow leaves an
**editing** step, where `v2Editing = canvasDirective.allowedTools.length > 0`
(`Surface.tsx:41`). `canvasStore.ts:36`: *"a locked layer can't be
moved/resized/selected"*, and `lockPlaced` clears the selection. `SelectedToolbar`
— which hosts the "Remove background" toggle — renders only when an element is
selected and `v2Editing` is true (`Surface.tsx:274`).

Therefore a background-removal step that declared no tool would lock the logo,
deselect it, and instruct the customer to tick a toggle they cannot reach.

**`ASK_LOGO_BG` declares `tool="upload"`.** `v2Editing` stays true, nothing
locks, the logo stays selected, the toolbar stays up. The lock then fires
naturally on arrival at `ASK_ANOTHER_LOGO` (no tool). **No frontend change is
required by this spec.**

`auto_open` must stay `None` on this step, or the file picker reopens on top of
the placed logo.

## 3. Registry changes

Order after this change (`REGISTRY` is the flow; first-unmet resolution is the
router):

```
ASK_NAME → SHOW_INTRO → ASK_HAS_LOGO
  → [ASK_LOGO_PLACEMENT → LOGO_ADJUST → ASK_LOGO_BG → ASK_ANOTHER_LOGO]  (loop, skippable)
  → ASK_ADD_DECOR → ASK_DECOR_PLACEMENT → DECOR_ADJUST → ASK_ANYTHING_ELSE
  → ASK_QUANTITY → ASK_DECORATION → ASK_EMAIL → ASK_PURPOSE → FINALIZE_CANVAS
```

### A. `ASK_LOGO_BG` (new)

- Between `LOGO_ADJUST` and `ASK_ANOTHER_LOGO`.
- Ask: does the logo have a background to remove; if so tick "Remove background"
  in the toolbar under the cap. The customer ticks the **existing** toggle — no
  auto-matting, no new directive machinery.
- Chips: `Yes, I've removed it` → `{"logo_bg": "removed"}`; `No, it's fine as is`
  → `{"logo_bg": "none"}`.
- `slots=("logo_bg",)`, `tool="upload"`, `auto_open=None`, `show_done=False`,
  `face_target=True`.
- `apply=_apply_logo_bg`: writes `pending_logo["bg"]`.
- `done_when`: `not _logos_open(c) or "bg" in _pending(c)` — the same shape as
  every other logo step, so the no-logo skip and the loop both work unchanged.

`Step.instructions: str | None` is added: `directive_for` currently derives the
canvas instruction from `V2_TOOL_TIPS[tool]`, which for this step would show the
upload tip ("Tap the highlighted Upload image button…") — wrong. When
`instructions` is set the directive uses it; otherwise `V2_TOOL_TIPS[tool]` as
today. `tip=None` on this step so `reply_for` does not append the upload tip to
the chat copy either.

### B. `ASK_DECOR_PLACEMENT` (new)

- Between `ASK_ADD_DECOR` and `DECOR_ADJUST`. Mirrors `ASK_LOGO_PLACEMENT`.
- Chips: Front/Back/Left/Right → `{"decor_face": <face>}`.
- `slots=("decor_face",)`, `done_when`: `bool(c.get("decor_done")) or
  c.get("decor_face") in FACES`.
- `SLOT_ENUMS["decor_face"] = FACES`.

`_face(collected)` becomes step-aware. Today it reads `pending_logo.face` for
every step, but `DECOR_ADJUST` already sets `face_target=True` and runs after the
logo loop has set `pending_logo = None` — so it falls back to `"front"` and text
has always silently targeted the front face. **This is a live bug the placement
step fixes.** New signature: `_face(step, collected)` — decor steps read
`decor_face`, logo steps read `pending_logo.face`, both falling back to `"front"`.

`_apply_anything_else` must also clear `decor_face` alongside `decor_choice` /
`decor_placed` / `more_decor` / `decor_done`, or a second decoration reuses the
first one's face without asking.

### C. `ASK_HAS_LOGO` (new)

- Before `ASK_LOGO_PLACEMENT`.
- Chips: `Yes, I have a logo` → `{"has_logo": True}`; `No — text only` →
  `{"has_logo": False}`.
- `slots=("has_logo",)`, `done_when`: `"has_logo" in c` (presence, not
  truthiness — `False` is a real answer; same rule as `ASK_ANOTHER_LOGO` and
  `ASK_QUANTITY`).
- `apply=_apply_has_logo`: on `False`, set `logos_done=True` and
  `pending_logo=None`. Every logo step's `done_when` already short-circuits on
  `not _logos_open(c)`, so first-unmet skips the whole branch. **No new routing,
  no branches, no back-edges.**

### D. Logo loop copy

Set `ask_retry` on `ASK_LOGO_PLACEMENT`: *"Where should this one go — front,
back, left or right?"* `reply_for` already selects `ask_retry` when the step id is
in `collected["_asked"]`, which is true from the second logo onward. The copy must
read correctly for **both** senses (a re-ask after an unparsed answer, and the
next logo) — it does. No new mechanism.

### E. Text tip copy

Split `V2_TOOL_TIPS["text"]` so the styling sentence stands on its own line
rather than trailing the positioning sentence. Copy-only; no behaviour change.

### F. `ASK_DECORATION` (new)

Between `ASK_QUANTITY` and `ASK_EMAIL`. Reuses the existing
`ConversationState.ASK_DECORATION` and v1's
`orchestrator._decoration_style_bucket`.

- Ask copy states the cost caveat **upfront**, matching how v1 words it
  (`prompts.py:80-83`: pick more than one, each extra decoration adds to the
  cost). No new "2+ selected" mechanism — the caveat is unconditional in the ask.
- `slots=("decoration_types",)`, `multiselect=True`.
- `apply=_apply_decoration`: filter the chosen names against
  `collected["decoration_options"]` by exact case-insensitive match, preserving
  the customer's order; set `decoration_types`, `decoration_done`, append
  `"Decoration method: …"` to `brief_notes`, and set `decoration_type =
  _decoration_style_bucket(chosen[0])`. Porting v1's exact-token matching matters:
  it stops a shorter option name matching inside a longer one ("Print" inside
  "Screen Print").
- `done_when`: `bool(c.get("decoration_done"))`.

Options are store-scoped DB rows, so three registry capabilities are added:

| Field | Contract |
|---|---|
| `prepare: Callable[[dict, dict], None] \| None` | `(collected, store)`, run before the step is rendered. Loads `decoration_options` via `decoration_types.list_types(store_id, active_only=True)` if absent. |
| `chips_from: Callable[[dict], tuple[Chip, ...]] \| None` | Chips derived from `collected` when they can't be literals. `chips_of(step, collected)` returns `chips_from(collected)` if set, else `step.chips`; `public_data_for` and `resolve_chip` call `chips_of`. |
| `multiselect: bool` | `resolve_chip` splits the message on commas, matches every token against the step's chips, and merges list-valued fields by concatenation (order preserved, duplicates dropped). |

`public_data_for` emits `multiselect: True` and `selected: []` for this step, the
shape the frontend multi-select already consumes from v1
(`orchestrator.py:1184-1188`, `sessions.py:292-300`).

`prepare` is called in `orchestrator_v2.handle_message` on the resolved `next_`
step, before `reply_for`/`public_data_for` — the orchestrator already holds
`store`. It is a generic hook on the step record, deliberately not an
`if next_.id is S.ASK_DECORATION` branch in the orchestrator: the registry design
exists to keep per-state switches out of the engine.

**Interpreter guard.** `decoration_types` is store-dynamic, so it cannot go in
`SLOT_ENUMS`. `_apply_decoration`'s filter against `decoration_options` **is** the
guard: a model returning an invented method name yields an empty `chosen`,
`decoration_done` stays unset, and the step re-asks itself. Nothing invented ever
reaches the brief.

### Progress path

`_PROGRESS_PATH` goes 7 → 8:

```
ASK_NAME, SHOW_INTRO, ASK_LOGO_PLACEMENT, ASK_ADD_DECOR,
ASK_QUANTITY, ASK_DECORATION, ASK_EMAIL, ASK_PURPOSE
```

`_PROGRESS_ANCHORS` gains `ASK_HAS_LOGO → ASK_LOGO_PLACEMENT`, `ASK_LOGO_BG →
ASK_LOGO_PLACEMENT`, `ASK_DECOR_PLACEMENT → ASK_ADD_DECOR` (joining the existing
`LOGO_ADJUST` / `ASK_ANOTHER_LOGO` / `DECOR_ADJUST` / `ASK_ANYTHING_ELSE`
anchors), so "Step X of N" stays steady through both loops.

## 4. What does not change

- **`V2_OWNED` is derived** (`{s.id for s in REGISTRY} | {GREETING}`), so the new
  states become v2-owned automatically. No second list to update.
- **The finalize route** (`sessions.py:268-280`) still sends a v2 session straight
  to `GENERATING`; decoration is now collected in chat, before finalize.
- **v1 is untouched.** Every change is inside the v2 registry/engine. Dispatch is
  still `settings.canvas_orchestrator_v2 and flow_mode == "canvas"`.
- **No frontend change** (see §2).
- **No migration.** `decoration_types` already exists (`20260713000004`).

## 5. Known caveat (accepted)

Adding `ASK_DECORATION` to the v2 registry makes that state v2-owned, so a **v1**
canvas session resting at `ask_decoration` when the flag is flipped on would now
be handled by v2 (whose ask copy and chip contract differ). This is the same
flag-flip caveat already recorded in CLAUDE.md for `canvas_design`, not a new
class of problem. Accepted, not mitigated.

## 6. Testing

The registry is a pure function of `collected`, so all routing is testable with
plain dicts — no LLM, no mocking, no Supabase.

- `ASK_HAS_LOGO` = False → `next_step` skips all four logo steps and returns
  `ASK_ADD_DECOR`.
- `ASK_HAS_LOGO` = True → routes into `ASK_LOGO_PLACEMENT`.
- `ASK_LOGO_BG` is reached after `LOGO_ADJUST` and before `ASK_ANOTHER_LOGO`; its
  directive carries `allowed_tools == ["upload"]` (the anti-lock invariant from
  §2 — assert it explicitly, since a later "tidy-up" removing the tool would
  silently re-break the toggle) and `auto_open is None`.
- `ASK_DECOR_PLACEMENT` sets `decor_face`; `DECOR_ADJUST`'s directive
  `target_face` follows it (regression test for the always-"front" bug).
- `_apply_anything_else` clears `decor_face`, so a second decoration re-asks the
  face.
- Multi-select: `resolve_chip` on a comma-joined message returns every matched
  option in order; an unoffered token is dropped.
- `_apply_decoration` filters to offered options, sets the style bucket from the
  first choice, and leaves `decoration_done` unset when nothing matches (so the
  step re-asks).
- `prepare` loads `decoration_options` once and is not re-fetched when present.
- Loop copy: the second `ASK_LOGO_PLACEMENT` renders `ask_retry`, not the first
  ask.
- The `test_v2_e2e.py` walk drives the **exact chip labels the UI ships** and
  raises `LLMUnavailable` throughout — update it for the new steps, preserving
  that property (the front half must need no model at all).
- The `test_v2_no_longer_uses_the_shared_keyword_matchers` guard test must keep
  passing (`state_machine.is_negative` still matches "a**no**ther" by substring).

Run with `CANVAS_ORCHESTRATOR_V2=false pytest -q` (the repo-root `.env` default of
`true` flips 3 unrelated tests red).
