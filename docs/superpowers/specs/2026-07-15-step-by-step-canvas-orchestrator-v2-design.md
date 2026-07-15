# Step-by-Step Canvas Orchestrator (v2) — Design

**Date:** 2026-07-15
**Status:** Approved for planning
**Owner:** Orchestrator / Backend + Frontend

---

## 1. Goal

Introduce a **new AI-chat orchestration flow** for canvas Design Studio sessions that
*leads the customer through the canvas one tool at a time* — the chat unlocks a single
tool, highlights it, gives usage instructions, waits for the customer to place and adjust
the element, then locks that layer + tool before moving on.

The current orchestrator is kept **as a runtime backup**. The new flow is wired as a
parallel copy, selected by a global env flag. When the flag is off, behaviour is
byte-identical to today.

### Requested flow (verbatim intent)

1. Greeting + ask the customer's name.
2. Convey some information + instructions (admin-set).
3. Ask to upload the logo **and** where it goes (front / back / left / right); open the
   upload-image tool on the canvas and explain how to use it.
4. Ask whether the background needs removing and whether the placement is good, or if they
   want to move / resize / rotate it — press **Done** when the placement is good.
5. On **Done**: lock the layer in place and lock the upload tool.
6. Ask whether they want to upload another logo — same process, **max 4 logos**.
7. Ask whether they want to add text or a shape — unlock the required tool, give
   instructions, follow the same Done/lock process.
8. Ask "is that everything or do you want anything else" — lock the tools at this stage.
9. Ask quantity.
10. Ask email.
11. Ask the purpose of the hat.

Then hand off to the **existing** generation → verification → gated delivery → refine tail.

---

## 2. Decisions (locked)

| Decision | Choice |
|---|---|
| Selection mechanism | Global env flag `CANVAS_ORCHESTRATOR_V2` (bool, default off) |
| Flag scope | **Canvas sessions only** (`flow_mode == "canvas"`); legacy Q&A flows always use v1 |
| After collection | **Reuse the existing tail** (AI generation → verify email → gated delivery → refine) |
| Instructional copy | **Only the step-2 intro is admin-set**; per-tool usage tips are built-in canned copy |
| Canvas control mechanic | **Data-directive driven** (state machine emits a `canvas` directive in `data`) |
| Tool highlight | Active tool gets an accent glow + pulse; locked tools dimmed — derived from `allowed_tools` |

---

## 3. Architecture & Isolation

### 3.1 Backend

- **`backend/app/services/conversation/orchestrator_v2.py`** — new module. A trimmed copy of
  `orchestrator.py` implementing the new front-half, then routing into the shared tail
  states. Exposes `handle_message` (v2). The existing poll entry points
  (`check_verification`, `advance_after_generation`, `advance_after_regeneration`) are
  **reused from v1** — they operate on shared tail states and are orchestrator-agnostic, so
  v2 does not re-implement them.
- **`backend/app/services/conversation/state_machine_v2.py`** — new module owning v2 forward
  routing (`advance_state_v2` / a `next_state` equivalent) and any v2-only helpers.
- **Shared enum:** the new states are **added to the existing `ConversationState` enum** in
  `state_machine.py` (purely additive — v1 routing never returns them, so v1 is unaffected).
  This keeps the frontend chat store, tail states, and `progress()` generic.
- **Route dispatch** (`backend/app/api/routes/chat.py`): on `POST /chat/{id}`, load the
  session; if `settings.canvas_orchestrator_v2` **and** `session.flow_mode == "canvas"`,
  dispatch to `orchestrator_v2.handle_message`; otherwise `orchestrator.handle_message`.
  The verification / generation-advance / regeneration poll routes stay on the shared v1
  functions (tail is shared).
- **Config:** `settings.canvas_orchestrator_v2` in `app/config.py` (pydantic-settings, env
  `CANVAS_ORCHESTRATOR_V2`), documented in `.env.example`.

### 3.2 Frontend

`flow_mode` stays `"canvas"`, so `SessionView` still mounts the split-screen
`CustomiseStudio` / `DesignStudioSurface`. The changes are additive and driven by the new
`canvas` directive; when the directive is absent (v1 sessions) behaviour is unchanged.

---

## 4. State Sequence

New states in **bold**; reused states in plain text.

```
GREETING → ASK_NAME
  → SHOW_INTRO*                 (admin-set info + instructions; Continue)
  → LOGO loop (max 4 logos):
       ASK_LOGO_PLACEMENT*      (front / back / left / right)
       LOGO_ADJUST*             (remove-bg? move/resize/rotate; Done → lock layer + tool)
       ASK_ANOTHER_LOGO*        (yes → ASK_LOGO_PLACEMENT / no → ASK_ADD_DECOR)
  → DECOR loop:
       ASK_ADD_DECOR*           (Add text / Add shape / No)
       DECOR_ADJUST*            (place + adjust; Done → lock element + tool)
       ASK_ANYTHING_ELSE*       (yes → ASK_ADD_DECOR / no → lock ALL tools → ASK_QUANTITY)
  → ASK_QUANTITY → ASK_EMAIL → ASK_PURPOSE
  → [flatten + finalize canvas] → GENERATING → (existing shared tail)
```

### 4.1 Branch & counter details

- **Logo cap:** `collected["logo_count"]` increments on each completed logo. `ASK_ANOTHER_LOGO`
  routes back to `ASK_LOGO_PLACEMENT` only while `logo_count < 4`; at 4 it advances to
  `ASK_ADD_DECOR` (and the "another logo?" affordance is suppressed/says the max is reached).
- **Decor loop:** text/shape may repeat until the customer declines at `ASK_ANYTHING_ELSE`
  (no hard cap; a sane guard of e.g. 12 total elements can be added if needed).
- **Reorder:** quantity / email / purpose are captured **after** the design, per the request.
  Email uses the existing `leads.capture_lead_and_verify` (double opt-in unchanged); purpose
  uses the existing `purpose` field capture.
- **Progress counter:** `state_machine_v2` provides a v2 progress path so "Step X of N"
  reflects the new order (name → design steps → quantity → email → purpose).

---

## 5. Canvas Control Mechanic (core)

The state machine is the single source of truth. Each v2 state emits a `canvas` directive
inside its existing `data` payload:

```jsonc
canvas: {
  "allowed_tools": ["upload"],          // tool buttons enabled this step; [] = all locked
  "target_face": "front",               // switch the canvas to this face (front|back|left|right)
  "auto_open": "upload",                // optional: pop this tool's dialog on entry
  "instructions": "Drag to move it…",   // canned per-tool usage tips (frontend constants)
  "show_done": true                     // render the Done affordance for this step
}
```

- **`chatStore.parseData`** extracts `canvas` into store state (whitelisted, like the existing
  `trigger_generation` / `options` fields).
- **`DesignStudioSurface`** reacts: switches `activeFace` to `target_face`, passes
  `allowed_tools` to `ToolRail`, shows the `instructions` callout, auto-opens `auto_open`, and
  renders the Done affordance when `show_done`.
- **Done** (canvas button *or* a chat chip) posts a sentinel `"done"` message. v2 interprets
  it at `LOGO_ADJUST` / `DECOR_ADJUST`: it locks the just-added layer(s), advances, and the
  next state's directive re-locks the tool.

### 5.1 Tool highlight

- The active tool in `allowed_tools` is rendered with an **accent glow ring + subtle pulse**
  (using `--brand-primary`); locked tools are visibly dimmed. This is derived purely from
  `allowed_tools` — no extra backend field.
- When exactly one tool is allowed and `auto_open` is set, the tool is highlighted **and** its
  dialog opens; the highlight persists after the dialog closes so the customer connects the
  chat instruction to the button.

---

## 6. Frontend Changes

- **`store/canvasStore.ts`**: add `locked: boolean` per element; add `lockAll()` /
  `lockUnlocked()` actions. Locked elements: not draggable, not selectable, no transformer.
- **`DesignStudio/nodes.tsx`**: respect `el.locked` on every node type (text, image, shape,
  drawing) — `draggable={!el.locked}`, skip selection + transformer when locked.
- **`DesignStudio/ToolRail.tsx`**: add `allowedTools?: Set<'upload'|'text'|'shape'>` gating and
  a `highlightTool` accent treatment. Legacy `locked` prop stays for v1.
- **`DesignStudio/Surface.tsx` (`DesignStudioSurface`)**: read the `canvas` directive; drive
  face switch, per-tool gating + highlight, instruction callout, auto-open, and the Done
  affordance (posts the `"done"` sentinel via the chat store).
- **New constants file** (e.g. `DesignStudio/toolInstructions.ts`): canned per-tool tip strings
  (upload, text, shape) + placement guidance.
- **Finalize trigger** moves from the "Done designing" render button to **after `ASK_PURPOSE`**:
  when v2 advances into `GENERATING`, the frontend flattens the faces and calls the existing
  `finalizeCanvas` (see §7a), then the existing generation poll runs.

---

## 7. Admin-Set Intro

- One new per-store field for the step-2 intro text, stored in the existing `stores` config
  jsonb (e.g. `stores.brand.canvas_intro` or a sibling config key — chosen at plan time to
  avoid clobbering existing brand keys; PATCH already read-merges brand).
- Surfaced via the existing admin `GET`/`PATCH /admin/stores/{id}` (no new endpoint) and one
  field in the admin Branding/Settings view.
- Crash-safe MadHats default when unset. Exposed to the customer studio via the existing
  `/storefront` public brand subset (or returned in the `SHOW_INTRO` reply text server-side —
  chosen at plan time; server-side reply text is simplest and avoids a public-brand change).

---

## 7a. Known Integration Points (care, not blockers)

1. **Finalize / lead double-capture:** today `finalizeCanvas` both converts the canvas → 
   `collected["elements"]` **and** captures the lead. In v2 the email is already captured at
   `ASK_EMAIL`, and finalize now fires after purpose. Finalize must **not** re-capture / 
   re-verify the lead when one already exists for the session (make the lead capture in the
   finalize path idempotent / skip when `collected["email_captured"]`).
2. **`flow_mode` unchanged:** stays `"canvas"` so the frontend studio mounts as today; v2 is
   selected by the env flag at the chat route, not by a new flow_mode.
3. **Layer locking granularity:** on Done, lock **all currently-unlocked** elements (each step
   adds then locks, so this equals "lock the new one"). Simpler and race-free.
4. **Directive absence:** v1 sessions emit no `canvas` directive; the frontend must treat
   absence as "legacy behaviour" (whole-rail `locked` gating) so v1 is visually unchanged.

---

## 8. Testing

**Backend**
- v2 state-machine unit tests: every branch, the ≤4 logo cap, Done-locks-layer transitions,
  the quantity/email/purpose reorder, and the hand-off into the shared tail.
- Flag-off regression: with `CANVAS_ORCHESTRATOR_V2` off, a canvas session produces the exact
  same states/replies as today (v1 untouched).
- Route dispatch test: flag on + `flow_mode="canvas"` → v2; flag on + non-canvas → v1;
  flag off → v1 always.

**Frontend**
- `ToolRail`: per-tool `allowedTools` gating + highlight treatment (enabled/dimmed/pulse).
- `nodes`: locked elements are non-draggable / non-selectable / no transformer.
- `DesignStudioSurface`: `canvas` directive drives face switch, tool gating, instruction
  callout, auto-open, and Done posts the `"done"` sentinel.
- Directive-absent regression: v1 canvas session renders the whole-rail lock as before.

---

## 9. Out of Scope

- Per-tool admin-editable instructions (canned in code for now).
- Any change to the legacy chat-Q&A flows or the non-canvas orchestrator.
- New generation / delivery / refine behaviour (tail reused verbatim).
- Per-store selection of v1 vs v2 (global flag only for this iteration).
