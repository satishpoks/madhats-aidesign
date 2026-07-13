# Canvas Photorealistic Multi-Angle Rendering — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorming)
**Area:** backend — canvas generation pipeline

## Problem

The Canvas Design Studio lets a customer place text, logos and shapes on four
face tabs (front/back/left/right), then hit "See it rendered". Today the
generated result is only partly photorealistic:

- **Only the FRONT hero is AI-rendered.** The back/left/right faces reuse the
  customer's *flat* canvas PNG directly (`generate.py` canvas splice) — a 2D
  mock-up (colour-tinted flat cap photo + placed elements), not a photoreal
  render. Any angle other than the front looks like a flat sticker sheet.
- **Non-front components never reach the image model.** Because those faces
  aren't AI-rendered, the components placed on them are never described to
  Gemini — so there is no "extract the components at their locations → detailed
  description" happening for anything but the front.

The goal: every decorated angle comes back photorealistic and consistent, driven
by (1) the real uncustomised product photo for that angle as the main reference,
(2) the customer's flattened canvas for that face as a placement guide, and
(3) an extracted per-face description of the components on that face.

## Decisions (from brainstorming)

1. **Render every decorated angle.** Each face that carries decoration gets its
   own Gemini render. Front hero is always rendered (as the anchor) even if
   undecorated. Undecorated non-front faces are not rendered at all. Cost scales
   with decorated-face count (accepted); latency stays ~one render because faces
   render concurrently.
2. **Layout image owns exact placement; text description stays coarse.** The
   per-face flattened canvas PNG (already uploaded) is sent as the LAYOUT GUIDE
   and owns pixel-exact placement. The extracted text description gives each
   component's identity + styling attributes + coarse zone words (e.g. "on the
   front panel") — never pixel coordinates. This avoids text-vs-image conflicts
   and keeps the layout-sensitive cache key intact.

## Current behaviour (what exists)

The per-view rendering machinery is already built and used by the non-canvas
(customise/blank) flow — it is merely bypassed for canvas sessions:

- `prompt_builder.render_views(collected)` → front + every face carrying a
  decoration element, in canonical order.
- `prompt_builder.build_view_prompt(collected, product_ref, params, view)` →
  a prompt enumerating only that view's elements.
- `prompt_builder.reference_image_url_for_view(product_ref, view)` → the real
  product photo for that angle (falls back to front).
- In `generate.py::_run_generation`, the inner `_one(view)` coroutine already:
  - picks the per-view reference angle,
  - for canvas sessions looks up `canvas_layouts.get(view)` as the layout guide,
  - folds the layout path into the cache key (layout-sensitive),
  - builds the per-view scoped prompt,
  - and calls `_render_view(...)`.
- Faces render concurrently via `asyncio.gather`.

The **only** reason non-front canvas faces aren't photoreal is two lines:

```python
elif is_canvas:
    views = [prompt_builder.PRIMARY_VIEW]   # only the front hero is AI-rendered
```

plus the splice that fills the other faces with their flat PNGs:

```python
if is_canvas:
    for face, path in canvas_layouts.items():
        if face == prompt_builder.PRIMARY_VIEW:
            continue
        new_views[face] = {"image_url": path, "watermarked_url": _make_watermarked(path)}
```

The frontend only flattens/uploads **decorated** faces
(`Surface.tsx::doRender` skips `design.faces[face].length === 0`), so
`canvas_layouts` contains exactly the decorated faces — which is exactly what
`render_views()` returns (front + decorated faces). They align with no extra
bookkeeping.

## Design

### 1. Render every decorated face (backend/app/api/routes/generate.py)

In `_run_generation`, the canvas branch changes from rendering only the front to
rendering the full decorated view set:

```python
elif is_canvas:
    views = prompt_builder.render_views(collected)  # front hero + every decorated face
    prev_views = {}
```

**Delete** the flat-PNG reuse splice (the `if is_canvas:` block after
`new_views` is built). No face reuses the flat mock anymore; every entry in
`view_images` now comes from a real Gemini render.

No change is needed inside `_one(view)` — it already attaches the per-view
reference angle, the per-view layout guide (`canvas_layouts.get(view)`), the
layout-sensitive cache key, and the per-view scoped prompt. Once `views` includes
the decorated non-front faces, each one flows through that same path.

Update the `_run_generation` docstring and the inline canvas comments to describe
the new behaviour (every decorated face AI-rendered with its own reference angle +
layout guide; no flat-PNG reuse).

### 2. Complete the extracted per-face description (backend/app/services/canvas_describe.py)

`canvas_to_elements` maps the canvas JSON into the existing `collected["elements"]`
shape that `build_view_prompt` enumerates. Tighten it so every captured attribute
survives into the description, keeping it coarse (identity + styling + zone; no
pixel coordinates):

- **Text:** content, colour, font, coarse size, and map the canvas `curve` prop
  to a `style` hint (e.g. `curved`) so curved text is described. Keep the coarse
  zone word from `FACE_ZONE`.
- **Shape:** keep the described phrase (e.g. "filled blue rectangle") and fill
  colour — already handled.
- **Logo/image:** keep the uploaded-artwork mapping + `remove_bg` — already
  handled.

Size handling: keep a coarse size word if present, but do not emit raw pixel
dimensions into the text (the layout guide owns exact size on the face). No pixel
x/y is ever written into the description — this preserves the property the
cache-key test relies on (identical elements + different layouts still produce the
same `view_prompt`, differentiated only by the layout path folded into the key).

### Data flow (per decorated face, after the change)

```
real product angle photo  ──► FIRST image (conditioning / source of truth)
flattened canvas PNG(face) ──► LAYOUT GUIDE image (exact placement)
extracted face description ──► prompt DECORATION(S) block (identity + styling + zone)
        │
        └─► Gemini render ─► watermark ─► view_images[face]
```

## Blast radius

- `backend/app/api/routes/generate.py` — canvas branch (`views = render_views`),
  remove the flat-PNG splice, refresh docstring/comments.
- `backend/app/services/canvas_describe.py` — attribute-completeness enrichment
  (curve→style; ensure colour/font/coarse-size captured).

### Tests

- **Rewrite** `test_canvas_run_renders_front_and_reuses_flattened_for_back`
  (it pins the retired reuse behaviour). New assertions for a front+back design:
  - both `front` and `back` go to the provider (`calls["views"] == ["front", "back"]`),
  - `view_images` has both faces and neither `image_url` is the raw flat
    `uploads/*.png` path — both are real render outputs,
  - each face's render received a non-null `layout_guide_url` and the correct
    per-view reference angle.
- **Keep** `test_canvas_cache_key_differs_by_layout_guide_path` and
  `test_non_canvas_cache_key_unaffected_by_fix` — both remain valid.
- **Add** a `canvas_describe` case asserting curved text surfaces a `style`
  hint and that no element carries pixel x/y in its description string.

## What does NOT change

- Customise/blank **chat** flows and the non-canvas `render_views` path.
- Delivery/verification gating, ops-alert-on-failure, all-or-nothing across views.
- The fidelity-locked prompt templates (`IMAGE_GEN_PROMPT` / `_BLANK`).
- Frontend (flatten → upload → finalize → handoff) — unchanged.
- Cache-key layout-sensitivity for canvas sessions.

## Trade-off / caveat

Non-front faces are now subject to the same model variability as the front
(vs. the pixel-exact flat mock they got before). The real product photo
(conditioning) + the flattened layout guide are what keep each render faithful
and consistent. This is the direct, accepted cost of photorealism on every angle.
