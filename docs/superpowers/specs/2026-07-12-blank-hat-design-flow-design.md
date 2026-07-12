# Blank-Hat Design Flow — Design Spec

**Date:** 2026-07-12
**Status:** Approved for planning
**Owner:** Orchestrator

---

## 1. Summary

Add a second design flow to the MadHats AI Design Studio: **design a full custom hat
from a blank hat canvas**. Today's flow ("customise") adds prints/graphics/logos onto a
fixed-colour Shopify product. The new flow ("blank") starts from an admin-uploaded blank
(white) hat whose **colour is selectable**, lets the customer place decorations across all
four faces, shows a **simple on-screen 4-angle render before generation**, and then
produces the AI hero render.

The two flows have **distinct entry points** and share almost all conversation
machinery. This is implemented as **Approach A**: extend the existing state machine with a
`flow_mode` branch rather than forking the conversation engine.

### Goals

- A `flow_mode` of `customise` (unchanged) vs `blank` on each session.
- Admin CRUD for **hat types**, including upload of the 4 blank angle images
  (front/back/left/right), a colour list, allowed placement zones/decoration types,
  pricing, description, and an active toggle.
- A blank entry point + `BlankHatPicker` where the customer picks a hat type and colour.
- Reuse of the full conversation spine (name → purpose → quantity → decoration → design
  source → per-element deep-dive → email → generation → delivery/refine/quote).
- A backend-composited **4-angle preview** (tinted blank + overlaid elements) shown for
  confirmation before the expensive AI render.
- AI generation of the **front hero** only; the other 3 angles are served from the
  composite.

### Non-goals

- A pixel-precise drag/resize canvas editor (placement stays chat-driven: zone +
  position, "anywhere" = any of the four faces). 
- Per-colour photographed blanks (colour is AI-recoloured from a single white blank).
- Touching the customise flow's behaviour, prompts, or routing.
- Replacing or altering InkyBay.

---

## 2. Hard-constraint alignment

- **Composite onto the real reference photo, never synthesize a cap.** Preserved: the
  admin-uploaded blank hat photo *is* the real reference. Recolouring/tinting it is a
  modification of that photo, not synthesis of hat geometry. The front blank is passed as
  `reference_image_url` to every generation call.
- **Human-in-the-loop.** AI recolour is best-effort; the design team approves before
  production, and the customer can adjust colour in the refine loop.
- **No secrets in code / signed URLs / private bucket.** All blank angle images live in
  the private `madhats-assets` bucket and are surfaced only via signed URLs
  (TTL `SIGNED_URL_TTL`).
- **Admin gated by `X-Admin-Secret`.** All hat-type management routes use `require_admin`.
- **Multi-tenancy.** Hat types are tenant-scoped (`store_id`), mirroring
  `product_references`.

---

## 3. Data model

### New table `hat_types`

Migration: `backend/supabase/migrations/20260712000001_hat_types.sql`.

| column | type | notes |
|---|---|---|
| `id` | uuid pk | `gen_random_uuid()` |
| `store_id` | uuid → stores | tenant-scoped, `on delete cascade` |
| `slug` | text | unique per store |
| `name` | text | display name |
| `style` | text | e.g. "5-panel", "trucker" |
| `description` | text | optional |
| `blank_view_images` | jsonb | `{front,back,left,right}` → **storage paths** (not URLs) |
| `colours` | jsonb | `[{name, hex}]` suggested swatches; customer may also free-pick |
| `placement_zones` | text[] | feeds the element deep-dive (can include all 4 faces) |
| `decoration_types` | text[] | `embroidery` / `print` |
| `pricing_slabs` | jsonb | optional, same shape as products |
| `active` | bool | controls customer visibility; requires all 4 angles present |
| `created_at` / `updated_at` | timestamptz | `default now()` |

RLS: enabled, matching the existing pattern — `service_role` full access; anon `select`
restricted to `active = true` rows. Grants mirror `product_references`.

### `design_sessions` change

Add column **`flow_mode text not null default 'customise'`** (`customise` | `blank`).
Existing sessions default to `customise`, so no data migration is required.

### `product_ref` reuse (no new column)

For a blank session, the existing `product_ref` jsonb carries the generation reference:
`reference_image_url` = the blank **front** angle path, `view_images` = the 4 blank angle
paths, `colour` = the chosen colour (name/hex), plus `product_id` = the hat type id and
`style`/`name` from the hat type. This lets the whole generation/prompt path flow
unchanged except for the recolour instruction.

### `collected` keys (blank mode)

- `flow_mode = "blank"`
- `hat_type_id`
- `hat_colour` — `{name, hex}` (or bare hex)
- `composite_views` — `{front,back,left,right}` storage paths (set by the composite route)
- `composite_confirmed` — bool (set true when the customer confirms `COMPOSITE_PREVIEW`)

---

## 4. Admin: hat-type management

### Backend — new `backend/app/api/routes/admin_hat_types.py`

All routes gated by `X-Admin-Secret` (`require_admin`), consistent with
`admin_stores.py`.

- `POST   /admin/hat-types` — create (auto slug from name if omitted).
- `GET    /admin/hat-types` — list for the admin's store scope.
- `PATCH  /admin/hat-types/{id}` — update fields (name, style, colours, zones, decoration
  types, pricing, description, active).
- `DELETE /admin/hat-types/{id}` — delete.
- `POST   /admin/hat-types/{id}/angle/{view}` — upload one blank angle image
  (`view ∈ {front,back,left,right}`). Reuses `upload_asset` + the magic-byte / 10 MB size
  validation from `uploads.py`; writes the returned path into `blank_view_images[view]`.

Validation: a hat type may only be set `active` when all four `blank_view_images` are
present.

### Customer-facing — new `GET /hat-types`

Tenant-scoped via `X-Store-Key` (like `/products`). Returns **active** hat types with
**signed URLs** for the 4 angles (TTL `SIGNED_URL_TTL`), plus colours and zones. Bucket
stays private.

### Frontend — admin SPA

New `AdminHatTypesView` (list) + a detail editor:
- 4 labelled angle drop-zones (front/back/left/right) with upload + preview.
- Colour-list editor: rows of `{name, hex}` with a swatch preview and a colour-picker
  input (admin swatches are suggestions; the customer may also free-pick).
- Zone + decoration-type checkboxes.
- Pricing rows, description, active toggle (active disabled until all 4 angles uploaded).
- Added to `AdminLayout` nav alongside Stores / Leads / Ops / Settings.

---

## 5. Entry points & conversation flow

### Entry

- **Customise (unchanged):** Shopify "customise this hat" → `?product_id=…` →
  `bootstrapFromUrl` → today's flow.
- **Blank (new):** `?mode=blank` (widget "design from scratch" button). `App.tsx` /
  `bootstrapFromUrl` detects it and shows **`BlankHatPicker`** (from `GET /hat-types`):
  the customer picks a hat type and a colour (swatch grid + free colour-picker). On
  selection → create a blank session.

### Blank session creation

Add a dedicated **`POST /sessions/blank`** accepting `{ hat_type_id, colour }` (keeping the
product-required `/sessions` route unchanged). It:
- loads the hat type, builds `product_ref` from it (front blank as `reference_image_url`,
  4 blanks as `view_images`, chosen `colour`),
- sets `flow_mode = 'blank'` (column) and seeds `collected.flow_mode`,
  `collected.hat_type_id`, `collected.hat_colour`,
- seeds `placement_zones` / `decoration_types` from the hat type.

### Conversation spine (reused)

name → purpose → quantity → decoration recommendation → design source (upload logo /
describe) → **per-element deep-dive** → more elements → email (captured early, as today) →
`COMPOSITE_PREVIEW` (blank only) → generation → delivery / refine / quote.

- **"Place anywhere" needs no new mechanism.** The deep-dive already captures
  `placement_zone` + `placement_position` per element. For blank hats the zone options are
  widened to all four faces via `hat_type.placement_zones`. Multiple decorations across
  multiple faces already work.
- **Colour** comes from the landing picker; changeable later via the refine loop.

### New states (both `flow_mode == 'blank'` gated)

- **`ASK_HAT_COLOUR`** — fallback only, if colour is somehow unset. Fires via
  `goal_planner`.
- **`COMPOSITE_PREVIEW`** — statement/confirm state inserted by `goal_planner` after "that's
  everything", before `GENERATING`. `_public_data` returns the 4 composite angle URLs +
  options `["Looks right — generate", "Tweak something"]`. "Tweak" routes back to
  `ASK_MORE_ELEMENTS` / refine; confirm sets `composite_confirmed` and routes to
  `GENERATING`. Customise mode skips this state entirely.

### Routing integration

- `state_machine.py`: add the two states to `ConversationState`, `TRANSITIONS`,
  `ALLOWED_BACKTRACKS`, and the progress helpers; gate their reachability on `flow_mode`.
- `goal_planner.next_goal`: in blank mode, return `ASK_HAT_COLOUR` when colour missing,
  and return `COMPOSITE_PREVIEW` when all elements are gathered and
  `composite_confirmed` is false; otherwise fall through to `GENERATING` as today.
- `orchestrator.handle_message`: derive `composite_confirmed` / "tweak" intent at
  `COMPOSITE_PREVIEW` from the interpreter + affirmative/negative heuristics.

---

## 6. Composite preview & generation

### Composite service — new `backend/app/services/composite.py`

Inputs: the hat's 4 blank angle paths, the chosen colour hex, and `collected["elements"]`
(each with `placement_zone` / `placement_position`, plus logo asset paths / text content).
Produces **4 flat preview PNGs** with Pillow:

1. **Recolour** — tint each white blank by multiplying the chosen colour over the blank's
   luminance (preserves shadows/highlights so it reads as a real coloured hat).
2. **Overlay elements** — text drawn with a bundled font; logos pasted (optionally
   bg-removed) scaled into a zone box. A lookup table maps `(view, placement_zone,
   position)` → an approximate bounding box on that angle.
3. Store the 4 PNGs to the private bucket, save paths to `collected["composite_views"]`,
   return **signed URLs**.

Deterministic, no model call — safe to re-run on every "tweak."

### Route — `POST /composite/{session_id}`

Called by the frontend on entering `COMPOSITE_PREVIEW`; returns the 4 signed URLs for
in-chat display. On composite failure, returns a clear error and the chat falls back to
showing the plain tinted blanks (no overlay), still allowing the customer to proceed.

### Real generation — one bounded change to `prompt_builder.build_prompt`

When `collected["flow_mode"] == "blank"` and a colour is set, prepend a base-cap
**recolour instruction** ("the blank cap is white; render the cap body in {colour}") ahead
of the decoration block. Reference image = the front blank (via existing
`reference_image_for`). Retry, caching, watermark, logging, and gated delivery are
**unchanged**. Only the **front hero** is AI-rendered (one call); the other 3 angles come
from `composite_views`.

### Display & delivery

The emailed preview stays the AI front hero (today's verified-email gated delivery,
unchanged). The on-screen `ProductViewer` shows the AI front hero as the main image plus
the 3 `composite_views` as the back/left/right angles.

---

## 7. Edge cases & error handling

- **No blank hats configured** → `BlankHatPicker` empty-state; blank entry effectively
  unavailable until admin adds one. Customise flow unaffected.
- **Composite failure** → route returns a clear error; chat falls back to plain tinted
  blanks and still proceeds to generation. Never a dead end.
- **Colour fidelity** → best-effort AI recolour; human-in-the-loop backstop + refine-loop
  adjustment.
- **Missing angle upload** → a hat type cannot be `active` until all 4 angles are present;
  inactive types never reach customers.
- **`flow_mode` isolation** → every new state/branch is gated on `flow_mode == 'blank'`,
  so customise behaviour is provably untouched.

---

## 8. Testing (TDD)

Matching the repo's pytest / vitest split.

### Backend (pytest)

- `hat_types` CRUD + angle upload (magic-byte validation reused).
- `GET /hat-types` — signed URLs + active-only filter + tenant scope.
- Blank session creation — `product_ref` built from hat type, `flow_mode` set.
- `goal_planner` blank branch — colour fallback + `COMPOSITE_PREVIEW` insertion + skip in
  customise mode.
- `composite.py` — tint + overlay + storage (mocked Pillow output / storage).
- `build_prompt` — recolour line present only when `flow_mode='blank'`; **regression test**
  asserting customise-mode prompts/routing are unchanged.

### Frontend (vitest)

- `BlankHatPicker` — list, colour pick, blank session start.
- `COMPOSITE_PREVIEW` chat state renders the 4 angles + confirm/tweak options.
- `AdminHatTypesView` — form, 4 angle uploads, colour-list editor, active-toggle gating.
- Admin nav includes Hat Types.

---

## 9. Rollout

Additive: new migration, new routes, new states behind `flow_mode`. No change to existing
customise sessions in flight. Sequence:

1. `hat_types` table + admin CRUD + angle uploads + `AdminHatTypesView` (staff can author
   blanks first).
2. `GET /hat-types` + `BlankHatPicker` + blank session creation + `flow_mode` column.
3. Conversation states (`ASK_HAT_COLOUR`, `COMPOSITE_PREVIEW`) + `goal_planner` /
   `orchestrator` wiring.
4. `composite.py` + `POST /composite` + `build_prompt` recolour + `ProductViewer` angle
   display.

---

## 10. New/changed surface (reference)

**Backend**
- `supabase/migrations/20260712000001_hat_types.sql` (new: `hat_types`, `design_sessions.flow_mode`)
- `app/api/routes/admin_hat_types.py` (new)
- `app/api/routes/hat_types.py` (new: customer `GET /hat-types`)
- `app/api/routes/composite.py` (new: `POST /composite/{session_id}`)
- `app/services/composite.py` (new)
- `app/api/routes/sessions.py` (blank session creation)
- `app/services/conversation/state_machine.py` (new states, transitions, progress)
- `app/services/conversation/goal_planner.py` (blank branch)
- `app/services/conversation/orchestrator.py` (COMPOSITE_PREVIEW handling, `_public_data`)
- `app/services/prompt_builder.py` (recolour instruction for blank mode)
- models for hat types / blank session request

**Frontend**
- `src/components/BlankHatPicker/` (new)
- `src/admin/views/AdminHatTypesView.tsx` (+ detail editor) (new)
- `src/admin/AdminLayout.tsx` (nav)
- `src/store/sessionStore.ts` (`mode=blank` bootstrap, blank session start)
- `src/components/ProductViewer/` (composite angle display)
- `src/components/ChatPanel/` (COMPOSITE_PREVIEW rendering)
- `src/lib/api.ts` / `src/admin/adminApi.ts` (new endpoints)
