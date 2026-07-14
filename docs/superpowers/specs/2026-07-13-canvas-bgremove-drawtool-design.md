# Canvas: Real Background Removal + Freehand Draw Tool — Design

**Date:** 2026-07-13
**Status:** Approved (brainstorming)
**Area:** frontend — Canvas Design Studio (`frontend/src/components/DesignStudio`, `store/canvasStore.ts`) + a small backend `canvas_describe` addition.

## Problem

Two customer-facing gaps in the Canvas Design Studio:

1. **"Remove background" is a dead toggle.** `SelectedToolbar` toggles
   `el.removeBg`, but nothing acts on it — `ImageNode` never reads it (the canvas
   always draws the image with its background), and the backend captures
   `GenerationParams.remove_bg` (`image_provider.py:19`, set in
   `prompt_builder.build_params:124`) but **no code ever consumes it** (no
   `rembg`/matting lib, no prompt instruction). So an uploaded logo keeps its
   background on the canvas, in the flattened layout guide, AND in the final
   Gemini render. Confirmed root cause: the feature was wired but never
   implemented.

2. **No draw tool.** Customers can add text, images and shapes but cannot draw
   freehand on the cap.

## Decisions (from brainstorming)

1. **Background removal runs client-side** (browser WASM matting via
   `@imgly/background-removal`), producing a transparent PNG used **both** on the
   canvas (so the flattened layout guide is clean) **and** as the crisp asset sent
   to Gemini (so the final render is clean). Lazy-loaded via dynamic `import()` so
   it never enters the main bundle; first use fetches the model from its CDN
   (~tens of MB, then cached) — the accepted UX cost.
2. **Draw tool = freehand pen** with a customer-chosen colour + thickness. A
   completed stroke (pen-down → pen-up) is one element supporting **move +
   delete** (no resize/rotate).

## Part A — Client-side background removal

### Data model
`CanvasElement` gains `originalAssetUrl?: string` so the toggle is reversible.

### Flow (in `SelectedToolbar`'s "Remove background" checkbox)
The checkbox's `onChange` becomes an async handler with a per-element busy state
("Removing…", toggle disabled while working):

- **Toggle ON:**
  1. `const blob = await removeBackground(el.assetUrl)` (dynamic-imported).
  2. `const { asset_url } = await uploadLogo(sessionId, fileFromBlob(blob))`.
  3. `updateElement(id, { assetUrl: asset_url, removeBg: true, originalAssetUrl: el.originalAssetUrl ?? el.assetUrl })`.
- **Toggle OFF:**
  1. `const orig = el.originalAssetUrl ?? el.assetUrl`.
  2. `const blob = await (await fetch(orig)).blob()`; `uploadLogo(sessionId, fileFromBlob(blob))`.
  3. `updateElement(id, { assetUrl: orig, removeBg: false })`.

### Why re-upload on both toggles
The crisp asset Gemini receives is the session's `uploaded_asset_path`, set
server-side by `uploadLogo` (last write wins). Re-uploading the now-active image
keeps the on-canvas image (→ clean flattened guide via the existing flatten) AND
the crisp 2nd image (via `view_has_logo` → `uploaded_asset_path`) in sync with the
toggle. `ImageNode` already renders `el.assetUrl`, so a transparent PNG shows
through with no `ImageNode` change.

### Error / edge handling
- Matting failure or upload failure: surface the existing `error` banner, leave
  `removeBg` unchanged (do not half-apply). The busy state clears in `finally`.
- Multi-logo caveat is pre-existing (only the last-uploaded logo's crisp asset is
  sent) and out of scope here — single-logo behaviour is correct.

### No backend change for Part A
The transparent PNG rides the existing `uploadLogo` → `uploaded_asset_path` →
`view_has_logo` → 2nd-image seam.

## Part B — Freehand draw tool

### Store (`canvasStore.ts`)
- `CanvasElement.type` union gains `'drawing'`.
- New field `points?: number[]` — a flat array of normalised `x,y` pairs
  (`[x0,y0,x1,y1,…]`, each in `0..1`).
- Reuse `stroke` (colour) and `strokeWidth` (stored **normalised** — a fraction of
  stage width — so it renders identically on the 480px stage and the small
  thumbnails via `strokeWidth * stageW`).
- New draw-mode state + setters: `drawMode: boolean`, `drawColour: string`
  (default e.g. `#111827`), `drawWidth: number` (normalised, default e.g.
  `0.01`); `setDrawMode`, `setDrawColour`, `setDrawWidth`.
- New action `addDrawing(points: number[])`: commits one stroke as an element on
  the active face — `{ type:'drawing', points, stroke: drawColour,
  strokeWidth: drawWidth, x:0, y:0, width:0, height:0, rotation:0, zIndex }`.
  `x/y` are a drag offset (start 0), applied at render so the stroke can be moved
  without rewriting its points.
- `reset()` also clears `drawMode` (back to false) and leaves colour/width at
  their defaults.

### Stage (`CanvasStage.tsx`)
- When `drawMode` is on: element nodes render with `listening={false}` so pointer
  events reach the stage; the stage's mouse/touch **down** starts a stroke
  (collect the pointer position as a normalised point in local state), **move**
  appends points and renders a live in-progress Konva `Line`, **up** calls
  `addDrawing(points)` when the stroke has ≥2 points, then clears local state.
- When `drawMode` is off, behaviour is unchanged (select/deselect + element drag).
- Reading the pointer: use `stage.getPointerPosition()` → divide by `STAGE_W`/`STAGE_H`.

### Node (`nodes.tsx`)
- New `DrawingNode`: a Konva `Group` positioned at `(el.x*stageW, el.y*stageH)`
  containing a `Line` with `points` mapped to px (`p*stageW`/`p*stageH`),
  `stroke: el.stroke`, `strokeWidth: (el.strokeWidth ?? 0.01) * stageW`,
  `lineCap:'round'`, `lineJoin:'round'`, `tension:0.5`. Selectable (`onClick`/
  `onTap` → `onSelect`), draggable when selected; `onDragEnd` updates
  `x`/`y` offset (normalised). No `Transformer` (move + delete only).
- `CanvasStage` renders `DrawingNode` for `el.type === 'drawing'`.

### Thumbnails (`FaceThumbnails.tsx`)
Render the same `Line` (scaled to the mini-stage) for `drawing` elements so
strokes appear in the left rail.

### Tool UI
- `ToolRail.tsx`: add a "✎ Draw" toggle button bound to `drawMode`
  (active-state styling when on). When `drawMode` is on, show a small draw bar: a
  colour `<input type="color">` bound to `drawColour` and a thickness
  `<input type="range">` bound to `drawWidth` (mapped to a sensible normalised
  range, e.g. `0.004`–`0.03`).
- `SelectedToolbar.tsx`: add a `drawing` branch — a stroke-colour control
  (`update(id, { stroke })`) alongside the shared delete/duplicate/reorder that
  already apply to any element. (Thickness is chosen at draw time; post-hoc
  thickness editing is out of scope — YAGNI.)

## Part C — Backend description (`canvas_describe.py`)

Add a `'drawing'` branch to `_element` and `_describe`:
- `_element`: map `type:'drawing'` → element `{"type":"graphic", "content": <phrase>, "colour": el.get("stroke")}` + the face's zone (same as shapes).
- Phrase: `"a hand-drawn line in {colour}"` when a stroke colour is present, else
  `"a hand-drawn line"`.
- `_describe`: `f"a hand-drawn line ... on the {face label}"`.

No pixel coordinates enter the text — the flattened layout PNG owns exact
geometry, consistent with the multi-angle rendering constraint. Because a drawing
maps to a `graphic` with a `placement_zone`, it flows through the existing
`element_view` / `render_views` path, so a drawn non-front face AI-renders like
any other decorated face.

## Files touched

**Frontend:**
- `frontend/package.json` — add `@imgly/background-removal`.
- `frontend/src/store/canvasStore.ts` — `originalAssetUrl`, `'drawing'` type +
  `points`, draw-mode state + setters, `addDrawing`, `reset` clears draw-mode.
- `frontend/src/components/DesignStudio/SelectedToolbar.tsx` — async bg-remove
  handler + busy state; `drawing` stroke-colour branch.
- `frontend/src/components/DesignStudio/CanvasStage.tsx` — draw-mode pointer
  handling + live stroke + `DrawingNode` wiring + `listening` gate.
- `frontend/src/components/DesignStudio/nodes.tsx` — `DrawingNode`.
- `frontend/src/components/DesignStudio/ToolRail.tsx` — Draw toggle + colour/
  thickness bar.
- `frontend/src/components/DesignStudio/FaceThumbnails.tsx` — render drawings.
- `frontend/src/lib/bgRemove.ts` (new) — thin wrapper: dynamic-import
  `@imgly/background-removal`, expose `removeBackgroundToFile(src): Promise<File>`
  (one mockable seam for tests).

**Backend:**
- `backend/app/services/canvas_describe.py` — `'drawing'` branch.
- `backend/tests/test_canvas_describe.py` — drawing → graphic test.

## Testing
- `canvasStore` unit tests: `addDrawing` appends a `drawing` element to the active
  face with the current `drawColour`/`drawWidth`; `setDrawMode`/`setDrawColour`/
  `setDrawWidth` update state; `reset` clears `drawMode`.
- bg-remove handler test with `../../lib/bgRemove` mocked: toggling ON swaps
  `assetUrl` to the uploaded transparent URL, sets `removeBg:true`, records
  `originalAssetUrl`; toggling OFF restores the original + `removeBg:false`.
- `tsc` gate for `DrawingNode`/`CanvasStage`/`ToolRail` wiring (matches how
  existing canvas components are covered — jsdom lacks canvas).
- Backend `canvas_describe`: a `drawing` element maps to a `graphic` carrying the
  stroke colour phrase and the correct zone; no pixel coords in the description.

## What does NOT change
- Customise/blank chat flows, the generation pipeline, the multi-angle rendering
  work, and the fidelity-locked prompt templates.
- `ImageNode` (renders `el.assetUrl` — a transparent PNG needs no change).
- The `uploaded_asset_path` / `view_has_logo` crisp-asset seam (reused as-is).

## Trade-offs / caveats
- First background removal fetches a multi-MB model from the `@imgly` CDN, so the
  first removal is slow; subsequent ones are cached. Fully client-side, no backend
  dependency added.
- Docker dev gotcha (from CLAUDE.md §13): the new frontend dependency must be
  installed **inside** the container (`docker compose exec frontend npm install`
  → `docker compose restart frontend`), not only on the host, or Vite will fail to
  resolve the import.
