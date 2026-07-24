# Canvas Quote-Flow Batch — Design Spec

> Date: 2026-07-24
> Status: Approved for planning
> Scope: Canvas editor UX, v2 conversation flow, quote-gated delivery + generation
> fix, and a conditional admin-configurable flow (V3).

This spec captures a batch of canvas-flow feature requests and bug fixes. It is
organised into **four independently-shippable workstreams** (A/B/C/D). Each will
get its own implementation plan. A and B are low-risk and independent; C is the
heavy backend workstream; D is conditional and low-complexity-only.

The two reframes that drive the whole batch:

1. **The AI render leaves the customer flow.** The customer treats the **canvas**
   as their design reference. There is no immediate `GENERATING` wait, no
   on-screen AI render, and no design image in the post-verification email. The
   (now-fixed) photorealistic render is produced **on-demand, triggered by sales**
   from the admin quote-requests view. Its only consumer is sales.

2. **Delivery is quote-gated.** After the customer explicitly requests a quote and
   verifies their email, they receive a **tracking reference** (a new short code,
   e.g. `MH-7F3K2A`) — not the design. Sales is notified with a summary + all
   uploaded components. **The system never emails the design to the customer in
   this batch**; sales handles the quote + design delivery entirely externally
   ("send quote" is explicitly out of scope, with provision to add it later).

---

## Workstream A — Canvas editor UX (frontend only)

Files: `frontend/src/components/DesignStudio/SelectedToolbar.tsx`,
`frontend/src/components/DesignStudio/ToolRail.tsx`,
`frontend/src/store/canvasStore.ts`,
`frontend/src/components/DesignStudio/Surface.tsx`,
plus copy in `backend/app/prompts.py` / `canvas_steps.py` for A4.

### A1 — Element transform controls (all element types)

Add a **universal transform block** to `SelectedToolbar.tsx`, inserted before the
existing reorder/duplicate/delete buttons (~line 106), rendered for every selected
element. All fields already exist on `CanvasElement` (`rotation` in degrees; `x`,
`y`, `width`, `height` normalised 0–1) and are patched through the existing
`updateElement(id, patch)` (active-face scoped).

- **Rotate:** a `−45°` button and a `+45°` button (default 45° interval), a
  **custom-degree number input** bound to `el.rotation` (accepts any integer
  degree), and a **Reset** button → `{ rotation: 0 }`.
  - `+45°` → `update(el.id, { rotation: ((el.rotation ?? 0) + 45) % 360 })`
  - `−45°` → normalise into `[0,360)`.
- **Move (shift):** up / down / left / right nudge buttons applying a small fixed
  delta to `x`/`y`, **clamped to `[0,1]`**. (Coords are normalised.)
- **Size (large/small):** `−` / `+` buttons that scale `width` and `height`
  together by a fixed factor (e.g. ×1.1 / ÷1.1). For **text**, size adjusts
  `fontSize` instead of width/height. For **drawings**, size is **not** offered
  (geometry lives in `points`, not width/height) — drawings get rotate + move
  only, matching their Transformer (rotate-only) behaviour today.

Per-type capability summary:

| Type | Rotate | Move | Size |
|---|---|---|---|
| text | ✅ | ✅ | ✅ (`fontSize`) |
| image | ✅ | ✅ | ✅ (`width`/`height`) |
| shape | ✅ | ✅ | ✅ (`width`/`height`) |
| drawing | ✅ | ✅ | ❌ |

These controls are additive to the existing on-canvas Konva Transformer
(drag/resize/rotate) — they don't replace it. The flatten/export path already
bakes `rotation`/size from the live stage, so no export change is needed. Values
must also reflect live in `FaceThumbnails` (they already read `rotation`).

### A2 — Rework-unlock bug fix

**Root cause:** there is no unlock path anywhere. `locked:true` is set by
`lockAll()`/`lockPlaced()` but nothing ever sets it back to `false`, and
`fromCanvasDesign()` re-hydrates persisted `locked:true` flags verbatim. On
rework/refine the stage chrome re-enables (`v2Editing` → Layer listening + tool
rail) but every pre-existing element still carries `locked:true`, so it renders
non-draggable, non-selectable, with no Transformer. Only freshly-placed elements
are editable → "not all layers are unlocked."

**Fix (`canvasStore.ts` + `Surface.tsx`):**

1. Add `unlockAll()` to `canvasStore` — sets `locked:false` on every element
   across all faces (mirror of `lockAll`).
2. Invoke `unlockAll()` when a rework/refine directive re-opens the canvas — in
   the Surface finalize re-arm branch (where `!triggerFinalize` resets the
   `finalizeStarted` guard), i.e. when the canvas transitions back into an
   editable state after a finalize.
3. Strip the `locked` flag in `fromCanvasDesign()` so resumed/hydrated sessions
   come back editable (don't persist a permanent lock into the design blob's
   editability).

Guard against regressions with a store-level test: place elements → `lockAll` →
`unlockAll` → assert none `locked`; and `fromCanvasDesign` on a design whose
elements were serialised `locked:true` yields editable elements.

### A3 — Upload button: remove highlight only (keep the unlock)

Per decision, take the **safe** option. The `ask_logo_bg` step's `tool="upload"`
is load-bearing (keeps the just-placed logo selectable so the "Remove background"
toggle stays reachable) and is pinned by tests — **keep it**. Only remove the
visual **highlight/pulse** so the upload button is no longer emphasised in the
main flow (the chips do the real work). In `ToolRail.tsx`, suppress the accent
ring + pulse for the upload tool (or generally de-emphasise the highlight) while
keeping the button enabled and the element unlocked. No test changes to the
load-bearing `ask_logo_bg` assertions (they check tool presence + instructions,
not the highlight).

### A4 — Wording: "image or logo"

Update customer-facing copy so uploads read as "image or logo" (not just "logo"),
since customers upload general images too:

- `prompts.py:V2_TOOL_TIPS["upload"]` — "to add your logo" → "to add your image or
  logo".
- `canvas_steps.py` step `ask` copy referencing "logo" where a general image is
  also valid (`LOGO_ADJUST`, `ASK_LOGO_BG`, `ASK_ANOTHER_LOGO` as appropriate).
- `intent_extractor.py:_SLOT_DOCS` logo-slot descriptions.
- Keep the on-screen button label **"Upload image"** unchanged (tests assert the
  literal string; and it's already generic).

---

## Workstream B — v2 conversation flow (orchestrator)

Files: `backend/app/services/conversation/canvas_steps.py`,
`backend/app/services/conversation/state_machine_v2.py` (progress only),
`backend/app/services/conversation/intent_extractor.py`,
`backend/app/services/conversation/state_machine.py` (enum),
`backend/app/prompts.py`.

### B1 — "When do you want it by?" step (before purpose)

Add one registry `Step` inserted immediately **before `ASK_PURPOSE`** in
`canvas_steps.REGISTRY`. Because routing is pure first-unmet over tuple order, no
engine change is required beyond the record itself plus the standard wiring:

- **Chips** (each label carries its meaning fields): `ASAP`, `2–4 weeks`,
  `1–2 months`, `Just exploring`. Plus support for a **custom date** given as free
  text (interpreter fills the slot).
- **Slot:** `needed_by` (string — a chip bucket or a free-text/parsed date),
  added to the step's `slots` (auto-derived into `WRITABLE_SLOTS`).
- **Deferrable:** "Just exploring" (or no firm date) is a valid answer; the step
  is satisfied by any non-empty answer including the defer chip.
- **`done_when`:** `"needed_by" in collected`.
- Add `NEEDED_BY` (or similar) `ConversationState` enum member in
  `state_machine.py` (imported as `S`).
- Add a `_SLOT_DOCS["needed_by"]` entry in `intent_extractor.py` so the
  interpreter can fill it from free text.
- Add to `_PROGRESS_PATH` in `state_machine_v2.py` so the "Step X of N" counter
  includes it (counter grows by one).
- The value flows into the brief for sales (folded into `brief_notes` /
  `collected`, surfaced in the quote summary — Workstream C).

### B2 — Email timing (#3 folded in)

Item #3 ("email ask on second upload — fix placement") is **subsumed by the
quote-gated email rework** in Workstream C. The v2 email step
(`ASK_EMAIL`) stays where it is (near the end, before purpose/finalize); no
separate placement bug is fixed here. Its behaviour changes only downstream (what
happens *after* verification — see C).

### B3 — Voice verification (#10)

No new mechanism; a verification obligation. Voice-dictated answers become text
that flows through the interpreter into slots, and chip labels are matched from
transcribed text. Add an e2e test that drives the new `needed_by` step and the
explicit request-a-quote step via free-text (interpreter) answers, and do a manual
voice pass through the full v2 canvas flow. Document the result.

---

## Workstream C — Quote-gated delivery + generation fix (backend, largest)

Files: `backend/app/services/delivery.py`, `backend/app/services/leads.py`,
`backend/app/api/routes/quote.py`, `backend/app/api/routes/admin_leads.py`,
`backend/app/services/email.py`, `backend/app/prompts.py`,
`backend/app/api/routes/generate.py`, `backend/app/services/prompt_builder.py`,
`backend/app/services/catalogue_sync.py`, `backend/app/services/canvas_describe.py`,
`backend/app/services/conversation/canvas_steps.py` (request-a-quote step),
a new migration for the tracking reference, plus admin frontend views.

### C1 — Explicit "Request a quote" step

After the canvas is finalised (design recorded + lead captured), add an explicit
customer action to submit the quote request. Realised as a v2 registry step near
the end of the flow (after purpose / at finalize) with a clear "Request a quote"
chip. Tapping it **records the quote request** for the session. This is the
deliberate submit gesture — the design existing on the canvas is not itself a
request until this step.

- The request records: reference to the session/design, quantity, `needed_by`,
  purpose, decoration selection, any notes, and the lead email.
- Recording sets a `quote_requested` marker (+ timestamp) on the lead/session.

### C2 — Tracking reference (#7)

Introduce a **customer-facing short reference code** (`MH-` + 6 uppercase base32
chars, ambiguous chars `0/O/1/I` excluded). New column on **`leads`** (the request
identity), generated at quote-request time, collision-checked against the column,
unique-indexed.

- **Stop emailing the design** at `delivery.py:231-245` for this flow, and disable
  the `send_final_design` re-send.
- After **email verification** completes for a quote-requested session, send the
  customer a **reference email**: "We've received your request — your reference is
  `MH-XXXXXX`. Our team will be in touch with a quote." No design image.
- The reference is shown on-screen too (the confirmation the customer lands on
  after requesting), so they have it immediately.
- Reuse the existing decoupled/idempotent pattern (verification track +
  request track converge; send once).

### C3 — Sales notification (#8)

When a quote request is **recorded and the lead is verified** (deduped, fired
once), email the store's `sales_notification_email` (already per-store,
admin-configurable — reused, no new field) a **summary**:

- Reference code, store, customer email, quantity, `needed_by`, purpose,
  decoration method(s), notes.
- **All uploaded components attached** (see C5).

Prefer firing after verification so sales only gets real leads; if already
verified at request time, fire immediately. Model on the existing
`send_quote_to_sales` / `quote_request_sent` dedup path in `delivery.py`, but
decoupled from generation (generation no longer runs in the customer flow).

### C4 — Render on-demand (sales-triggered)

Generation no longer runs at canvas finalize for this flow. Instead:

- Add an **admin endpoint** (e.g. `POST /admin/quote-requests/{id}/render`,
  `X-Admin-Secret` [+ `X-Store-Key` as the other admin routes]) that triggers the
  render for a quote request, reusing the existing `_run_generation` canvas
  pipeline **with the C6 fix applied**.
- The admin quote-requests view gets a **"Generate render"** button; the resulting
  render is viewable/downloadable there for sales to use externally.
- Gate the existing auto-generation-at-finalize so it does **not** fire for the
  quote-gated canvas flow (the customer path ends at the reference email). Keep
  other flows' generation behaviour intact.

### C5 — Downloadable components (#9)

The complete uploaded-component set per session is enumerable from `collected`:
`uploaded_asset_path`, every `canvas_previews[face]`, every `canvas_layouts[face]`,
each element's `asset_path`, and (once rendered) the generation image(s). Each
downloads via `storage.download_asset(path)`.

- **Admin quote-requests view:** list every component with individual download
  links + a "download all" affordance.
- **Sales email attachment:** attach all uploaded components (base64, reuse the
  `email.send_preview_email` attachment machinery) to the C3 notification.

### C6 — Generation fix (#11)

Two-part fix; the render pipeline's per-face orchestration is already correct — the
bug is the per-face **conditioning image source** and missing overlap ordering.

**Primary — stop silent front-aliasing.** `catalogue_sync._map_views`
(`catalogue_sync.py:75-79`) fills `back`/`left`/`right` with the front photo when a
product lacks four genuine, well-named angle photos; and
`prompt_builder.reference_image_url_for_view` (`:114`) adds a second front
fallback. So a *back* decoration renders onto a *front-facing* cap.

- Change behaviour so a decorated face **without a genuine per-angle photo is
  skipped**, not rendered onto the wrong angle (better a missing face than a
  wrong-angle face). Concretely:
  - `_map_views` **stops fabricating positional aliases** (`catalogue_sync.py:75-79`):
    it no longer fills `back`/`left`/`right` with `image_srcs[0]`/front. Only
    genuine keyword-matched angles (and `front`) are recorded; a face with no real
    photo is left **absent** from `view_images`.
  - The **canvas render loop** (`generate.py` `_one`) decides per face whether a
    **genuine** angle exists (view key present in `view_images`, or a blank
    session's real per-angle blank). A decorated non-front face with no genuine
    angle is **skipped** and a per-request note recorded so sales sees "back face
    not rendered — no back angle photo for this product." The **front hero always
    renders** (`reference_image_url` is always present).
  - `prompt_builder.reference_image_url_for_view`'s existing front-fallback
    (`:114`) is **left intact** so non-canvas / single-view callers are unaffected;
    the skip decision lives in the canvas render loop, not in the resolver.
- **Operational follow-up (documented, not code):** canvas-enabled synced products
  must carry real per-angle photos; blank sessions already carry all four. Note
  this in the spec's follow-ups and (later) CLAUDE.md.

**Secondary — overlap/z-order in prompt text.** Today stacking order survives only
in the flattened grey layout guide (`canvas_describe.py:130` zIndex sort), never in
the prompt text (`prompt_builder._element_line`). On multi-element faces the model
misreads stacking. Inject explicit **front-to-back ordering** of a face's elements
into the per-face prompt (`build_view_prompt` / `_design_block`) so overlap no
longer relies solely on the grey card.

### C7 — Admin quote-requests view (frontend)

Extend the existing admin quote-requests listing (`GET /admin/quote-requests`) /
its view with: the reference code, the collected summary (quantity/needed-by/
purpose/decoration/notes), the component download list + "download all", and the
"Generate render" button (C4) with the rendered result shown/downloadable.

---

## Workstream D — V3: admin-configurable flow sequence (conditional, low-complexity)

Files: `backend/app/services/conversation/canvas_steps.py` /
`state_machine_v2.py` (config-aware registry read), store config (`stores.brand`
or a new small config blob), admin Branding/flow view.

Scope is **toggle + reorder of a curated safe subset only**:

- A fixed set of **independent, reorderable/optional steps** — e.g. `purpose`,
  `needed_by`, `quantity`, `decoration`, `anything_else`. Admin can enable/disable
  each and reorder within this subset, per store.
- **Dependency-locked steps stay fixed and non-reorderable:** `name`, the intro,
  the logo loop, `email`, `prepare`-bearing steps (`decoration`'s store load), and
  `finalize` (email must precede finalize; the logo loop is self-contained;
  `prepare` steps load store data). These are never moved or disabled by admin.
- Persist a per-store ordering + on/off map. The first-unmet engine reads the
  registry **through** this config (compose the effective step list: locked steps
  in their fixed positions, configurable steps ordered/filtered per config). Pure
  function of config + `collected`; testable with plain dicts.
- **Out of scope:** arbitrary drag-anywhere reordering, moving locked steps,
  cross-store templates. If the safe-subset approach turns out to carry hidden
  complexity during planning, D is dropped from this batch (it was explicitly
  conditional).

---

## Cross-cutting: testing & verification

- **Backend:** `CANVAS_ORCHESTRATOR_V2=false pytest -q` baseline stays green; new
  tests for the `needed_by` step, request-a-quote step, tracking-reference
  generation/uniqueness, sales-notification dedup, component enumeration, the
  `_map_views`/skip-face behaviour, and z-order prompt injection.
- **Frontend:** targeted (Windows-stall-safe) vitest for `canvasStore` unlock,
  the transform-controls block, and the de-emphasised upload button.
- **Voice (B3):** e2e free-text walk + manual voice pass.
- **v2 e2e:** the existing chip-label walk extended through the new steps.

## Follow-ups / known gaps (documented, not built here)

- In-app "send quote to customer" action (design + quote email) — provisioned for
  later, out of scope now.
- Canvas-enabled synced products must carry real per-angle photos (operational).
- V3 is capped at the safe subset; arbitrary reordering deferred.

## Sequencing recommendation

A and B ship first (independent, low-risk). C is the heavy workstream and should
be planned/reviewed on its own. D is planned last and only if it stays
low-complexity.
