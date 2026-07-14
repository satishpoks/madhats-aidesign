# Chat-Gated Canvas Flow — Design

> Date: 2026-07-13
> Status: Approved (brainstorm) → ready for implementation plan
> Scope: the canvas Design Studio experience (`flow_mode='canvas'`) for BOTH
> entry points — customise (`?product_id=`) and blank (`?mode=blank`).

---

## 1. Problem / Intent

Today a canvas session (`flow_mode='canvas'`) bypasses the conversation entirely:
the session is created directly at state `canvas_design`, the split-screen shows
the canvas **and** a dormant chat column at once, and only `canvas-finalize`
wakes the chat up (at `generating`). There is no intro (name/purpose/quantity),
no email capture until finalize, and no post-design decoration/notes step.

We want the chat to **lead** the canvas experience:

1. Greet → ask **name**
2. Capture **email** (right after name) → fire verification email, **non-blocking**
3. Ask **purpose** of the hat
4. Ask **how many pieces**
5. Tell the customer they can *describe their requirement to us or use the tool on
   the left* — and **only now unlock the left-panel canvas tools**
6. Customer designs on the canvas; the render button reads **"Done designing"**
   (not "See it rendered"/"render")
7. After design: ask **what decoration** they want (embroidery, print, … — a list
   **served from the backend so it is changeable**, admin-managed per store),
   **always** asked, **multi-select** with a cost caveat
8. Finally ask for **any additional notes** before generating
9. Generate → existing verify / gated-delivery / refine pipeline (unchanged)

### Decisions locked during brainstorming

| Question | Decision |
|---|---|
| When is email captured? | **During intro, right after name** (verification fires then, non-blocking) |
| Is "describe to us" a separate design path? | **No** — framing only; the canvas is the design tool. "Describe" just means the customer can also type notes/context in chat. |
| How configurable is the decoration list? | **Admin-managed, per store** (new `decoration_types` table + admin CRUD) |
| When is the decoration question asked? | **Always** (not gated on whether images/logos were used) |
| Keep the youth check in this intro? | **Dropped** for the canvas flow |
| Decoration single or multi? | **Multi-select**, with a cost warning surfaced when 2+ are chosen |
| Which entry points? | **Both** customise and blank canvas sessions |
| Blank richer features (per-section colour, etc.)? | **Ship blank with the existing tooling** (colourway tint + 4 face tabs). **Defer** per-panel/per-section colour to a follow-up ticket. |

---

## 2. Conversation shape (canvas sessions only)

```
GREETING
  → ASK_NAME
  → SAVE_PROGRESS_EMAIL     email captured → capture_lead_and_verify() → verification fires (non-blocking)
  → ASK_PURPOSE
  → ASK_QUANTITY
  → CANVAS_DESIGN           tools UNLOCK; chat rests; "Done designing" (finalize) advances the flow
  → ASK_DECORATION          NEW — multi-select from admin list; cost caveat if >1
  → ASK_NOTES               NEW — free-text "anything else before we generate?" (+ "No, generate" chip)
  → GENERATING → VERIFY_EMAIL → … (unchanged downstream: gated delivery, refine, quote)
```

The **non-canvas** Q&A flows (customise Q&A, blank Q&A) are **untouched** — every
new branch is `flow_mode == 'canvas'`-gated.

### 2.1 State machine changes (`state_machine.py`)

- **New states**: `ASK_DECORATION`, `ASK_NOTES`.
- **`CANVAS_DESIGN`** (already an enum value) gains a clear meaning: "tools
  unlocked, customer designing." It is a **rest state** — no chat question; the
  canvas "Done designing" button advances it out of band.
- `TRANSITIONS` / `ALLOWED_BACKTRACKS` extended for the two new states.
- `QUESTION_FIELD`: `ASK_DECORATION → "decoration_done"`, `ASK_NOTES → "notes_done"`
  (gate on the `_done` flags, NOT the `decoration_types` list — an empty list
  would mis-register as "filled" under `_filled`). The canvas planner is the
  primary router here; these entries only keep `advance_and_skip` consistent.
- `_progress_path`: a canvas-specific progress path (name, email, purpose,
  quantity, design, decoration, notes) selected when `flow_mode == 'canvas'`.

### 2.2 Routing (`goal_planner.py`)

Add a dedicated **`_canvas_next_goal(collected)`**, chosen at the top of
`next_goal()` when `collected.get("flow_mode") == "canvas"`:

```
if not name:                          ASK_NAME
elif not email_prompt_shown:          SAVE_PROGRESS_EMAIL
elif not purpose and not purpose_asked: ASK_PURPOSE
elif "quantity" not in collected:     ASK_QUANTITY
elif not canvas_finalized:            CANVAS_DESIGN         # rest until finalize
elif not decoration_done:             ASK_DECORATION
elif not notes_done:                  ASK_NOTES
else:                                 GENERATING
```

`CANVAS_DESIGN`, `ASK_DECORATION`, `ASK_NOTES`, `GENERATING` are added to
`GATE_STATES` (or handled in the canvas branch) so the planner doesn't fight
`advance_state`.

### 2.3 Orchestrator (`orchestrator.py`)

- **Kickoff**: `GREETING` already emits the greeting and advances to `ASK_NAME`
  (works for canvas too, once the session starts at `GREETING`).
- **Decoration capture** at `ASK_DECORATION`: toggling chips accumulates into
  `collected["decoration_types"]` (a list); a "Done"/confirm signal sets
  `decoration_done=True`. Empty selection + "Done" is allowed (no decoration).
- **Notes capture** at `ASK_NOTES`: free text → `collected["notes"]` (folded into
  the brief); a decline / "No, generate" sets `notes_done=True` with no note.
- **Skip `CONFIRM_BRIEF` for canvas**: the existing "intercept every path into
  GENERATING → CONFIRM_BRIEF" guard is gated to `flow_mode != 'canvas'` (the
  notes step is the canvas pre-generation gate).

### 2.4 `canvas-finalize` route (`sessions.py`)

- No longer sets state to `generating`. Instead:
  - records `canvas_design`, `elements`, `design_description` (as today),
  - sets `collected["canvas_finalized"] = True`,
  - computes the next state via the canvas planner → `ASK_DECORATION`,
  - returns `{reply, state: "ask_decoration", data: {options: <active decoration types>, multiselect, ...}}`
    so the chat column resumes in place.
- `body.email` / `body.name` become vestigial for this flow (name + email are
  captured in chat). Keep the params optional for backward-compat; they no longer
  drive lead capture in the canvas flow.
- **`create_canvas_session`** initial state changes from `"canvas_design"` to
  `"greeting"` so the intro runs.

---

## 3. Decoration types — admin-managed, per store

Mirrors the existing store-scoped `hat_types` / `graphics` pattern.

- **Table** `decoration_types` (migration `docs`-dated):
  `id`, `store_id` (FK), `name`, `active` (bool), `sort_order` (int),
  `created_at`. Unique on `(store_id, lower(name))`.
- **Service** `services/decoration_types.py`: `list_active(store_id)`,
  `list_all(store_id)`, `create`, `delete`, `reorder`.
- **Admin routes** (`api/routes/admin_decoration_types.py`, `X-Admin-Secret` +
  `X-Store-Key`): `GET/POST/DELETE /admin/decoration-types`.
- **Customer route**: `GET /decoration-types` (active only, via `X-Store-Key`) →
  chip list for `ASK_DECORATION`.
- **Admin UI**: a small **Decorations** view (`admin/views/DecorationTypesView.tsx`)
  — store selector + add + inline-confirm delete + drag/sort — modelled on
  `GraphicsView`. Add a nav entry.
- **Seed**: default rows (`Embroidery`, `Print`, `Patch`, `Vinyl`) for the local
  store in `seed.sql` so the flow works out of the box.

`collected["decoration_types"]` (list of names) is folded into the generation
brief / `prompt_builder` alongside the existing `decoration_type` handling.

---

## 4. Frontend

### 4.1 `DesignStudioSurface` — lock/unlock

- Add a `locked` overlay (semi-opaque, non-interactive) shown while
  `chatState` is an **intro** state (`greeting`, `ask_name`, `save_progress_email`,
  `ask_purpose`, `ask_quantity`) with a hint: *"Answer a couple of quick questions
  on the right, then design here →"*.
- **Unlocked** at `chatState === 'canvas_design'`.
- **Re-locked** (read-only) during the outro (`ask_decoration`, `ask_notes`,
  `generating`, and all released/downstream states) — designing is finished.
- Render button label: **"See it rendered" → "Done designing"**; enabled only at
  `canvas_design`.

### 4.2 `ChatColumn` — kick off the intro

- Canvas sessions must **kick off** the greeting on load (today `ChatColumn`
  intentionally has no kickoff). Add a canvas-intro kickoff: when the session is a
  canvas session and the thread is empty and the state is an intro state, send the
  opening turn so the greeting + first question render immediately.
- New affordances:
  - **`ask_decoration`**: multi-select chip group (toggle on/off) sourced from
    `GET /decoration-types`, plus a **"Done"** button. When 2+ selected, show the
    cost caveat inline.
  - **`ask_notes`**: the standard text input plus a **"No, generate"** chip.

### 4.3 Blank flow

Same intro/outro as customise. The blank canvas keeps its **existing** tooling
(colourway swatch row → stage tint, 4 face tabs) which becomes available when the
tools unlock. **No new blank-only features in this pass.** Per-panel/per-section
colour is a deferred follow-up ticket.

---

## 5. Data model additions (`collected`)

| Key | Meaning |
|---|---|
| `canvas_finalized` | set True by `canvas-finalize`; gates CANVAS_DESIGN → ASK_DECORATION |
| `decoration_types` | list of chosen decoration names (multi-select) |
| `decoration_done` | True once the decoration step is confirmed |
| `notes` | free-text additional notes for the render / team |
| `notes_done` | True once the notes step is passed |

Existing keys reused unchanged: `name`, `email_prompt_shown`, `email_captured`,
`lead_id`, `purpose`, `purpose_asked`, `quantity`, `elements`,
`design_description`, `flow_mode`, `hat_colour` (blank).

---

## 6. Testing

- **Backend**
  - State-machine: canvas path ordering (name→email→purpose→quantity→canvas_design
    →ask_decoration→ask_notes→generating); non-canvas paths unchanged.
  - `goal_planner._canvas_next_goal` returns each expected state from the matching
    `collected` snapshot.
  - Orchestrator: decoration multi-select accumulation + done; notes capture +
    decline; CONFIRM_BRIEF skipped for canvas.
  - `canvas-finalize` routes to `ask_decoration` and sets `canvas_finalized`.
  - `decoration_types` service + routes (admin CRUD, customer active-only,
    store scoping, X-Admin-Secret gate).
- **Frontend**
  - `DesignStudioSurface` locked during intro, unlocked at `canvas_design`,
    re-locked during outro; button label "Done designing".
  - `ChatColumn` canvas kickoff renders the greeting; decoration multi-select
    toggling + cost caveat; notes step.
  - `DecorationTypesView` admin CRUD.
- Keep the existing backend `pytest` and frontend `vitest` suites green.

---

## 7. Out of scope / deferred

- Per-panel / per-section blank-hat colour selection (follow-up ticket).
- Any change to the non-canvas customise/blank Q&A conversation.
- Decoration → pricing integration (the cost caveat is a **message only**, not a
  live price).
- Voice/STT changes.
