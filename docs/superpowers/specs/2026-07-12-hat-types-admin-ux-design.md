# Hat Types Admin — CMS-style Management UX

**Date:** 2026-07-12
**Status:** Approved (brainstorm) → ready for implementation plan
**Area:** `frontend/src/admin` (Hat Types view) + small `backend` change

---

## 1. Problem

The current `/admin/hat-types` page (`frontend/src/admin/views/HatTypesView.tsx`) crams
everything onto one screen: a store dropdown, a bare `name` + `slug` create form, and a
flat list of cards. It falls short of a "proper admin-oriented page" for a non-technical
user in three ways:

- **Create** exposes only `name` + `slug` (and "slug" is developer jargon).
- **Preview** shows no images — only the text "uploaded" / "—" per angle, because the
  admin API returns raw storage **paths**, not browser-loadable URLs.
- **Applicable parameters** the blank-hat flow actually consumes — **colourways**
  (name + hex; drives the widget colour picker + composite tint), **placement zones**,
  and **decoration types** — are not editable in the UI at all, even though the data
  model (`backend/app/models/hat_type.py`) already supports them plus `style` and
  `description`.

Goal: a create → list → preview → configure flow that is both **functional** (every
applicable parameter settable) and **intuitive for a non-technical user**.

## 2. What the blank flow actually consumes (why these parameters matter)

Verified downstream usage:

- **colours** — the customer picks a colour from the hat type's `colours` list in
  `BlankHatPicker`; the chosen hex drives the composite tint (`api/routes/composite.py`,
  `sessions.py`). **Critical.**
- **placement_zones**, **decoration_types** — copied into the session `collected` at
  blank-session creation (`sessions.py`) and used during the design deep-dive.
- **style** — descriptive; feeds prompt/session context.
- **description** — internal admin note (not consumed downstream).
- **blank_view_images** (front/back/left/right) — essential; drive the composite and the
  reference image.
- **pricing_slabs** — present in the model but **not consumed anywhere downstream**.
  **Out of scope** — building an editor for a dead field would confuse a non-technical
  user. Revisit when quoting uses it.

## 3. Design decisions (from brainstorm)

- **Create** = guided **5-step wizard** (most hand-holding for first-timers).
- **Edit** = **single scrollable page** with independently-saveable sections.
- **Preview** = **blank angle thumbnails** (not the heavier live-composite or
  customer-eye previews).
- **Parameters exposed**: colourways, placement zones, decoration types, style,
  description. `slug` is auto-derived from the name and never shown.

## 4. Information architecture

Three states under the `/admin/hat-types` route; the store selector persists across all:

| Route | State |
|---|---|
| `/admin/hat-types` | **List** — browse/search hat types for the selected store |
| `/admin/hat-types/new` | **Create** — guided 5-step wizard |
| `/admin/hat-types/:id` | **Edit** — scrollable page, per-section save |

The store selector value is lifted so it survives navigation between these (e.g. via the
existing admin store / URL query, matching how other admin views scope by store).

## 5. List view

- Store dropdown (kept — multi-tenant) + **"+ Add hat type"** button + search-by-name box.
- Row: **front-angle thumbnail**, name, style, **status pill**, colourway count, row
  actions (**Edit**, **Delete** with inline confirm — no `window.confirm`).
- **Status logic:**
  - `Needs images` — fewer than 4 angle images.
  - `Draft` — all 4 angles present but `active = false`.
  - `Active` — `active = true`.
- Empty state: "No hat types yet — add your first" + the CTA.

## 6. Create wizard (5 steps, linear Back/Next)

1. **Basics** — Name, Style, Description. On **Next**, POSTs a draft record (inactive)
   so subsequent steps have an `id`. Slug auto-derived from name (slugify), hidden.
2. **Angle images** — 4 drop/click upload tiles (front/back/left/right) with live
   thumbnails + a ✓ once uploaded. **Next** enabled only once all 4 are present.
3. **Colourways** — repeatable rows: colour-name + native swatch (hex) + remove;
   "Add colour".
4. **Zones & decoration** — two chip inputs (type + Enter to add, × to remove) with
   suggestions (Front panel / Left side / Back / Under-brim; Embroidery / Print / Patch).
5. **Review & activate** — summary + **Activate** (gated on all 4 angles; mirrors the
   backend 400 `All four angle images required before activating`).

A half-finished wizard leaves a **resumable Draft** — no data loss. Each step after
Basics persists via PATCH / upload against the draft `id`, so navigating away keeps
progress.

## 7. Edit page

Same field components as the wizard, stacked as independently-saveable sections
(Basics / Angles / Colourways / Zones & decoration) plus an **Active** toggle
(disabled with a hint until all 4 angles present). Each section has its own **Save** so
a colour tweak doesn't touch anything else.

## 8. Shared components (isolation)

Each is a self-contained controlled component consuming/emitting one slice of the hat
type; written once, used by both the wizard (one-per-step) and the edit page (stacked):

- `BasicsFields` — name / style / description.
- `AngleUploader` — the 4 upload tiles + thumbnails + presence ✓; calls `uploadHatAngle`.
- `ColourwayEditor` — rows of `{ name, hex }` with add/remove.
- `ChipListEditor` — generic tag input (used for zones and decoration), with an optional
  `suggestions` prop.

Wizard and edit page are thin containers that arrange these + own their own
navigation/save affordances.

## 9. Backend change (small, required for preview)

`HatTypeAdmin` returns raw storage **paths** in `blank_view_images`, which are not
browser-loadable. Add a computed **`view_images`** field of proxy URLs (via the existing
`media_url`, exactly as the public `/hat-types` route does) to:

- `GET /admin/hat-types` (list)
- `POST /admin/hat-types/{id}/angle/{view}` (return the new angle's URL too)

No new `GET /admin/hat-types/{id}` endpoint: the edit page reuses the store's list fetch
and finds the record by `id` (consistent with the current code, which has no admin
get-by-id route). The list already carries `view_images`, so the edit page's angle
thumbnails come for free.

No DB/schema change. `CreateHatTypeRequest` / `UpdateHatTypeRequest` already accept every
parameter we expose. The activation gate (`all_angles_present`) is unchanged.

Frontend `adminApi.ts`:
- Extend the `HatType` interface with `view_images: Record<string, string>`.
- Widen `createHatType` to accept `style` / `description` (already partially there).
- `updateHatType` already takes `Partial<HatType>`.

## 10. Testing

**Frontend (`HatTypesView.test.tsx` + new tests):**
- Wizard step progression; Basics-Next creates a draft.
- Activation gated on all 4 angles (button disabled / error surfaced).
- Colourway add/remove; chip add/remove for zones & decoration.
- List search filters; status pills reflect angle/active state.
- Delete inline-confirm flow.

**Backend:**
- Admin list and detail responses include `view_images` proxy URLs.
- Upload endpoint returns the angle URL.

## 11. Out of scope (deliberate)

- `pricing_slabs` editor (unused downstream).
- Live-composite / customer's-eye previews.
- Any change to the customer-facing `BlankHatPicker` or `/hat-types` public route.
- The customise flow is untouched.
