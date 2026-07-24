# Canvas per-element images + admin 360° view — Design

Date: 2026-07-24
Status: Approved (brainstorm) → ready for plan

---

## 1. Problem

Canvas sessions let a customer place **multiple distinct uploaded images** — one
per face (e.g. a front logo and a back logo), each an independent element in
`canvas_design.faces.<face>[]` with its own `assetUrl`. Two problems follow from
how those uploads are stored and consumed:

### 1a. Generation drops the first image and duplicates the second

- `POST /uploads/logo/{session_id}` overwrites `collected["uploaded_asset_path"]`
  on **every** upload (`backend/app/api/routes/uploads.py:46`). Only the **last**
  upload's storage path survives there.
- At render time, `_run_generation` reads that single
  `collected["uploaded_asset_path"]` (`backend/app/api/routes/generate.py:394`)
  and feeds **that one image** to *every* view that carries a logo
  (`generate.py:436`, gated by `prompt_builder.view_has_logo`).

Net effect for a front-logo + back-logo design:

- The **front (first) upload is dropped** — its global path was overwritten; only
  its flattened outline survives in the layout-guide PNG, so the model has no
  clean source for it.
- The **back (second) upload is fed to both faces** as the conditioning artwork →
  the same logo is duplicated across front and back.

This is the confirmed root cause of "one image is missing (the first one)" and
"duplicates on multiple views / missing elements".

Note: the **per-element** `assetUrl` inside `canvas_design` is NOT overwritten —
each element keeps the URL it was uploaded with. Only the **global**
`uploaded_asset_path` scalar is clobbered. Generation's bug is that it reads the
global scalar instead of the per-element data.

### 1b. The admin 360° view never shows the customer's actual design

`SessionDetailView` (`frontend/src/admin/views/SessionDetailView.tsx`) shows only:

- AI-generated mockups (`generations`)
- The catalogue product photos ("Selected cap — 360°")
- The captured brief + transcript

It never surfaces the **uploaded images**, the **placed text**, or the
**graphics/shapes/drawings** the customer actually composed. The admin session
endpoint (`GET /admin/sessions/{id}`,
`backend/app/api/routes/admin_diagnostics.py:124`) doesn't even return
`canvas_design`, `collected["canvas_previews"]`, or `collected["canvas_layouts"]`.

Additionally, image-element URLs persisted in `canvas_design` are **expiring
signed URLs**; even if surfaced they would be broken when viewed later.

---

## 2. Goals

1. **Persist** every uploaded image as a re-signable storage **path** per canvas
   element — nothing expires, nothing is lost.
2. **Fix generation** (canvas flow only) so each face is conditioned on its **own**
   uploaded image(s) — no missing first image, no duplicate across views.
3. **Admin 360° view** shows the customer's real design: per decorated face, the
   WYSIWYG preview, the layout guide, each individual uploaded image, and a text
   list of every placed element — all with **download**.
4. **Best-effort recovery** so existing sessions (incl. the reporter's) show their
   individual images where the storage object still exists, else fall back to the
   per-face composites.

Non-goals:

- Re-rendering already-completed (broken) generations — they are historical.
- ZIP/bulk "download all" — per-image download only for this pass.
- Any change to v1 customise/blank Q&A flows (single-logo path stays correct).

---

## 3. Data model

### 3a. Canvas image element gains `assetPath`

`CanvasElement` (`frontend/src/store/canvasStore.ts`) adds an optional field:

```ts
assetPath?: string  // private-bucket storage path for uploaded images; re-signable
```

- Set only for **uploaded** images (`/uploads/logo`). Company graphics and clipart
  keep their existing stable `assetUrl` (a `/media` proxy URL) and carry no
  `assetPath`.
- Persisted into `canvas_design` at finalize (it already round-trips the whole
  element object).

### 3b. Described element carries the path

`canvas_describe._element` (`backend/app/services/canvas_describe.py:99`) copies
`assetPath` onto the described `logo` element alongside the existing `assetUrl`:

```python
out["assetUrl"]  = el.get("assetUrl")
out["assetPath"] = el.get("assetPath")   # new — re-signable at render time
```

This is what lets `generate.py` map **per-view** logo images without touching the
global scalar.

No SQL migration: `canvas_design` and `collected` are JSONB; the new keys are
additive.

---

## 4. Part 1 — Persist image paths

### 4a. Upload endpoint returns the path

`POST /uploads/logo/{session_id}` (`backend/app/api/routes/uploads.py`) response
gains `asset_path`:

```python
return {
    "asset_url":  generate_signed_url(path),
    "asset_path": path,             # new
    "asset_hash": asset_hash,
}
```

`collected["uploaded_asset_path"]` continues to be set (v1 flows still read it);
this change is purely additive.

### 4b. Frontend threads the path through

- `uploadLogo` (`frontend/src/lib/api.ts`) return type gains `asset_path: string`.
- `addImage(assetUrl, aspect, assetPath?)` (`canvasStore.ts`) stores `assetPath`
  on the element.
- `handleUpload` (`Surface.tsx`) passes `asset_path` from the upload response.
- `addGraphic` (library graphics) passes **no** `assetPath` (unchanged) — those
  URLs are already stable `/media` proxies.

---

## 5. Part 2 — Generation fix (canvas per-view image conditioning)

### 5a. Provider interface accepts a list

`ImageProvider.generate` (`backend/app/services/image/image_provider.py`) adds:

```python
uploaded_asset_urls: list[str] | None = None,   # multiple artworks (canvas)
```

Semantics: when `uploaded_asset_urls` is provided (non-empty), each URL is
attached as an artwork reference image; the legacy `uploaded_asset_url` (single)
remains for v1 flows. If both are given, `uploaded_asset_urls` wins. A helper
normalises to a single list internally:
`urls = uploaded_asset_urls or ([uploaded_asset_url] if uploaded_asset_url else [])`.

All adapters (`gemini_base` for flash/pro, `fal_flux`, `stub`) accept the new
kwarg. Gemini loops over the list, appending each as a labelled artwork part
(the existing `_SECOND_IMAGE_LABEL` copy is reused; for 2+ images the label text
is generalised to "an artwork to apply" without the ordinal so it reads correctly
for each). `stub`/`fal` update signatures for compatibility.

### 5b. `_render_view` / `_run_generation` map per-view images

`_render_view` (`generate.py:258`) gains `uploaded_urls: list[str] | None` and
passes it through to `provider.generate(uploaded_asset_urls=...)`. The audit log
records the joined list (or first) in `uploaded_asset_url` for continuity.

In `_run_generation`'s `_one(view)` (canvas branch only):

```python
if is_canvas:
    view_logo_urls = _canvas_view_images(collected, view)   # new helper
    uploaded = view_logo_urls or None
else:
    uploaded = uploaded_url_full if prompt_builder.view_has_logo(collected, view) else None
```

`_canvas_view_images(collected, view)` (new, in `generate.py` or
`prompt_builder`):

- Takes `elements_for_view(collected, view)`, keeps `type == "logo"` elements.
- For each, resolves a fetchable URL:
  1. `assetPath` present → `generate_signed_url(assetPath)`
  2. else `assetUrl` is a Supabase signed URL → extract path (see §7) →
     `generate_signed_url(path)`
  3. else `assetUrl` is a `/media` proxy or external http URL → use as-is
     (company graphics/clipart with rasters)
  4. else skip (nothing fetchable)
- Returns the ordered list of URLs for that view.

### 5c. Cache key stays correct

The canvas cache key already folds in the per-face layout path
(`generate.py:457` `[layout:...]`), which is unique per upload set, so distinct
image sets never collide. The `asset_hash` component is left as-is for canvas
(the layout path already disambiguates); no change needed. (Optional hardening:
fold a hash of the sorted per-view image paths into the key — deferred unless a
test shows a collision.)

### 5d. Scope guard

Every change in this part is inside the existing `is_canvas` branch or gated on
`uploaded_asset_urls` being passed. v1 customise/blank single-logo rendering is
byte-identical: it still passes `uploaded_asset_url` (singular) and
`view_has_logo`.

---

## 6. Part 3 — Admin 360° view

### 6a. Endpoint additions

`GET /admin/sessions/{session_id}` (`admin_diagnostics.py`) adds to its response:

```python
"canvas_design": <re-served canvas_design>,   # image elements' URLs re-proxied
"canvas_faces":  [                             # derived, per decorated face
    {
        "face": "front",
        "preview_url": <media_url of canvas_previews[face]>,   # WYSIWYG, or None
        "layout_url":  <media_url of canvas_layouts[face]>,    # guide, or None
        "elements": [
            {"kind": "image", "url": <media_url>, "download_name": "front-logo-1.png"},
            {"kind": "text", "text": "SATISH", "detail": "white · Arial"},
            {"kind": "graphic", "detail": "filled blue rectangle"},
            {"kind": "drawing", "detail": "hand-drawn line in #111827"},
            ...
        ],
    },
    ...
]
```

Derivation:

- Read `session["canvas_design"]` and `collected["canvas_previews"]` /
  `collected["canvas_layouts"]`.
- For each face in canonical order that has any elements OR a preview/layout,
  build a `canvas_faces` entry.
- Image elements → `_resolve_media(el)`: resolve to a storage path (assetPath →
  path; or extract from signed assetUrl; else pass-through http) → `media_url`.
- Text/shape/drawing elements → a human string built from the same fields
  `canvas_describe` uses (reuse `canvas_describe` helpers where practical, or a
  small local formatter — see §8 on the shared helper).
- `preview_url` / `layout_url` from the stored **paths** via `media_url` (always
  re-signable; the reliable fallback for old sessions).

`canvas_design` is only present for `flow_mode == "canvas"` sessions; the field is
`null`/omitted otherwise, so non-canvas sessions render exactly as today.

### 6b. Path extraction from expired signed URLs — see §7.

### 6c. Frontend UI

`SessionDetailView.tsx` adds a **"Customer's design"** card (only when
`canvas_faces` is non-empty), placed above or beside the existing AI-mockups card
in the left column. Layout:

- One sub-panel per decorated face, headed by the face label (Front / Back / Left
  / Right).
- Within a face:
  - A **thumbnail row**: the WYSIWYG preview (labelled "Preview"), the layout
    guide (labelled "Layout guide"), and each uploaded-image element
    (labelled "Upload 1", "Upload 2", …). Each thumbnail has a **Download**
    button.
  - A **text list** of every element on that face: text content + style, graphics,
    drawings. (Images already appear as thumbnails; they may also be listed for
    completeness.)
- Old-session fallback: if a face has no resolvable individual images but has a
  preview/layout, show those with a small "flattened composite" note.

Download uses a blob fetch of the `/media` URL (CORS-enabled) → object URL →
programmatic `<a download>` with the `download_name`. A tiny `downloadImage(url,
name)` util lives in the admin module.

`adminApi.ts` types (`SessionDetail`) add `canvas_design` and `canvas_faces`
(typed interfaces `CanvasFace` / `CanvasFaceElement`).

---

## 7. Path extraction from Supabase signed URLs (recovery)

Supabase signed URLs look like:

```
{SUPABASE_URL}/storage/v1/object/sign/{bucket}/{path}?token=...
```

A pure helper `storage.path_from_signed_url(url) -> str | None`:

- Returns `None` for empty / non-matching input.
- Splits on `/object/sign/{bucket}/` (bucket = `madhats-assets`), takes the
  remainder, strips the `?token=...` query → the storage `path`.
- Also handles the `/object/public/{bucket}/` shape defensively.

Used by both the generation per-view resolver (§5b) and the admin resolver (§6a)
so existing sessions recover their individual uploads. Unit-tested with real-shape
URLs. If extraction fails, callers fall back gracefully (skip in generation; show
composite in admin).

---

## 8. Shared element-description helper

`canvas_describe` already formats text/shape/drawing elements for the prompt. The
admin view needs the same human strings. To avoid divergence:

- Extract the per-element phrase logic into small reusable functions in
  `canvas_describe` (e.g. `element_label(el) -> str` returning "text 'SATISH' in
  white, Arial" / "filled blue rectangle" / "hand-drawn line in #111827" /
  "uploaded image"). `_describe`/`_element` call it; the admin endpoint calls it.
- This keeps one source of truth for how an element reads.

---

## 9. Testing (TDD)

Backend (`pytest`, run with `CANVAS_ORCHESTRATOR_V2=false`):

1. `path_from_signed_url` — real-shape signed URL → path; public URL → path;
   garbage/None → None; already-a-path passthrough behaviour.
2. `/uploads/logo` returns `asset_path` and it equals the stored path.
3. `canvas_describe` — described logo element includes `assetPath` when present.
4. `_canvas_view_images` — **regression for the reported bug**: a canvas_design
   with a front-logo (path A) and a back-logo (path B) yields `[A]` for the front
   view and `[B]` for the back view — never A for both, never B for both, first
   never dropped.
5. Provider list plumbing — `stub`/gemini accept `uploaded_asset_urls`; the gemini
   request payload contains one artwork part per URL (assert on `request_payload`
   `payload_parts` roles, not a live call).
6. Admin endpoint — a canvas session returns `canvas_faces` with per-face
   `preview_url`/`layout_url` and image elements resolved to `/media` URLs; a
   non-canvas session returns `canvas_design: null` / empty `canvas_faces` and is
   otherwise unchanged.

Frontend (`vitest`, Windows-safe targeted files):

7. `canvasStore` — `addImage(url, aspect, path)` stores `assetPath`;
   `toCanvasDesign` round-trips it.
8. `SessionDetailView` — given a mock `canvas_faces`, renders per-face thumbnails
   + element text list + download buttons; a session without `canvas_faces` omits
   the section (existing view unchanged).

---

## 10. Rollout / safety

- All backend changes are additive (no migration; new JSONB keys; new response
  fields). Old clients ignore new fields.
- Generation change is strictly inside the `is_canvas` branch — v1 flows proven
  unchanged by keeping their single-`uploaded_asset_url` path.
- Frontend admin section is conditional on `canvas_faces`.
- The reporter's existing session is expected to now show both front and back
  uploads via §7 recovery (subject to the storage objects still existing).
