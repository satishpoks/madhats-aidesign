# Canvas lock, segregated email, diagonal watermark, refine→quote — Design

**Date:** 2026-07-14
**Status:** Approved

Five independent parts, built + committed separately.

## A. Canvas lock UX (frontend)

Today `DesignStudioSurface` covers the whole left panel with a blurred overlay
whenever the chat isn't at `canvas_design`. Replace that: keep the canvas fully
visible, but make it **read-only + tools disabled** when locked.

- `locked = chatState !== 'canvas_design'`.
- `ToolRail` gets a `locked` prop → every control disabled (Add text, Upload,
  Graphics, Draw, colour swatches, Done designing).
- `CanvasStage` gets a `locked` prop → elements `listening={false}`, no
  add-on-empty-click, no transformer/selection while locked.
- Remove the `backdrop-blur` overlay. Replace with a slim, non-blocking inline
  hint (intro: "Answer the questions on the right to unlock editing →";
  post-design: "Design locked in ✓").

## B. Copy (backend)

Remove the "on-screen" claim from the delivery/verification acknowledgement.
- Old: "Your email's verified — your design's in your inbox and on-screen now."
- New: "Your email's verified — your design is on its way to your inbox."
Scrub any other "on-screen" delivery phrasing (orchestrator acks + prompts).

## C. Watermark → single diagonal configurable text (backend + admin)

`watermark.py`: replace the tiled repeat + corner badge with **one line of text
running bottom-left → top-right**, sized to span the image diagonal,
semi-transparent (readable, not obscuring).

- Signature: `apply_watermark(image_bytes: bytes, text: str) -> bytes`.
- New global setting `watermark_text` (default `"MADHATS PREVIEW"`):
  - `app_settings` column (migration) + `StudioSettings` + `settings_service`
    get/update + admin **Settings** view text field + `adminApi`.
  - Callers (`generate._make_watermarked`, delivery canvas-preview watermarking)
    read `settings_service.get_settings().watermark_text`.

## D. Email — two segregated sections (frontend + backend)

Two labelled image groups in the preview email:
1. **"Your design"** — full WYSIWYG canvas per face (cap photo + colour +
   decorations, as seen on screen).
2. **"On the real hat"** — the photorealistic AI renders (existing
   `view_images`).

Both watermarked.

- Frontend `doRender`: in addition to the existing decorations-only layout-guide
  flatten, flatten each decorated face **without** hiding the product
  (`flattenStage(stage, {full: true})` or a sibling that skips the
  `flatten-hide` step) → upload via a new `canvas_previews` slot on
  `POST /sessions/{id}/canvas-layouts` (extended) → stored in
  `collected["canvas_previews"]` (`{face: storage_path}`).
- `delivery.py`: build `design_images` (canvas previews, watermarked at send
  time via `apply_watermark`) + `product_images` (AI renders, already
  watermarked). Pass both to `email_service.send_preview_email`.
- `email.py`: render two headed sections ("Your design", "On the real hat").
  Legacy sessions with no canvas previews fall back to the single group.

## E. Refine flow + quote handoff (backend + frontend)

New state `ASK_CHANGE_METHOD` between `OFFER_REFINE` and the change capture.

- `OFFER_REFINE` (canvas): "Request changes" → `ASK_CHANGE_METHOD`
  (options: **"Rework on the canvas"**, **"Describe the change here"**).
  "Looks good" → `QUOTE_REQUESTED` (repurposed as a yes/no quote ask).
- `ASK_CHANGE_METHOD`:
  - "Rework on the canvas" → clear `canvas_finalized` (+ set `reworking`),
    state → `CANVAS_DESIGN` (frontend unlocks). "Done designing" re-finalizes;
    a rework skips ASK_DECORATION/ASK_NOTES (already answered) and regenerates
    (tier `edit`), then → `OFFER_REFINE`.
  - "Describe the change here" → `DESCRIBE_CHANGES` (existing) → regen →
    `OFFER_REFINE`.
- `QUOTE_REQUESTED` (canvas): a yes/no question, "Want to request a quote for
  this design?"
  - **Yes** → data carries `quote_url` (`/quote/{token}`, same as the email
    link); frontend shows an **"Open quote form"** button (opens new tab);
    message closes the chat. State → `SESSION_END`.
  - **No** → friendly close. State → `SESSION_END`.
- The auto sales notification (`send_final_design`) still fires on entry to
  `QUOTE_REQUESTED` as today.

Whenever the customer is happy (first round or after a change), the loop ends at
the quote ask — the existing per-session edit cap bounds how many change rounds
are possible.

## Testing

Per part: watermark draws the passed text on a diagonal; settings round-trip
`watermark_text`; state-machine routes (`ASK_CHANGE_METHOD`, rework vs describe,
quote yes/no → `SESSION_END` + `quote_url`); delivery assembles two image
groups; frontend: locked disables tools + read-only canvas, quote button opens
the link.

## Out of scope / notes

- No per-store watermark text (settings are global `app_settings`, per §3b).
- Rework re-render reuses the existing edit/regeneration pipeline; no new
  generation mechanism.
