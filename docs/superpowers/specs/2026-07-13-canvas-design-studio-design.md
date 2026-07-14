# Canvas Design Studio — Phase 1 Design

> Status: approved design (brainstorming). Next: implementation plan (writing-plans).
> Branch: `feat/canvas-design-studio`
> Date: 2026-07-13

## 1. Problem & Goal

The current design experience is a chat-driven Q&A state machine with a per-element
deep-dive loop. Asking the customer many text questions is high-friction and
irritating. InkyBay's DesignLab lets customers *directly manipulate* a design on the
product (add text, upload art, place graphics, pick colours) — far more frictionless.

**Goal:** replace the Q&A deep-dive with an interactive, InkyBay-style **canvas**
where the customer plays with tools on the real product, then the **flattened canvas
images + an auto-built description** are sent to the existing generation model. Keep
everything downstream (email capture, generation, gated delivery, admin, audit).

This spec covers **Phase 1 — the frictionless core**. Phases 2 (clipart library) and
3 (AI chat helper + smart suggestions) are separate specs.

## 2. Scope Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Relationship to chat flow | **Replace the Q&A deep-dive; reuse all downstream infra** |
| Flows covered | **Both** customise (`?product_id`) and blank (`?mode=blank`) |
| Canvas faces | **Multi-face tabs** — front / back / left / right, independently designed |
| Generation input | **Layout guide + real photo** — real product photo (conditioning) **+** flattened canvas (layout guide) **+** auto-built description |
| Canvas tech | **react-konva** (Konva.js) |
| Phase-1 tools | Add text, upload logo/artwork, product colour + placement zones, move/resize/rotate |
| Deferred | Clipart library (Phase 2), AI chat helper + smart suggestions (Phase 3), AI graphic generation (out) |

## 3. Hard-Constraint Compliance

- **Composite onto real product photos:** the real product reference photo is still
  passed as conditioning on every generation call. The flattened canvas is an
  *additional* layout-guide image, never a from-scratch cap shape.
- **Uploaded files validated** (MIME + magic bytes + size) before processing.
- **Signed URLs** for all stored images (layout PNGs, uploaded logos); bucket stays private.
- **No PII in logs.** Rate limiting + input moderation on the generation call unchanged.
- **InkyBay untouched.** Customise Q&A code is bypassed for canvas sessions, not deleted.

## 4. User Flow & UX

**Entry (routing unchanged):**
- `?product_id=…` → customise → canvas seeded with the Shopify product photo(s).
- `?mode=blank` → `BlankHatPicker` (hat type + colour) → canvas seeded with the blank angles.

**Two-pane layout:**
- **Left — Canvas stage (primary):** active face's product photo as backdrop;
  decorations as draggable/resizable/rotatable Konva objects. **Face tabs** above
  (Front / Back / Left / Right). Selected object shows transform handles +
  contextual toolbar (font, colour, size, delete, layer order).
- **Right — Tool rail:** `Add text`, `Upload logo`, `Clipart` (disabled "coming soon"
  in P1), colourway swatch row, primary **"See it rendered"** button, and a
  collapsed "Ask for help" affordance (stub for Phase 3).

**Core loop:** drag decorations onto each face → switch colour/faces freely →
**See it rendered** → flatten faces + auto-build description → existing generation
pipeline → existing gated delivery (verify email → reveal + inbox). No forced questions.

**Email capture:** kept, moved to the **See it rendered** click (inline, "saves your
progress"), reusing the existing `SAVE_PROGRESS_EMAIL` + verification infra. The only
form moment in the whole flow.

## 5. Frontend Architecture

```
components/DesignStudio/
  index.tsx            page shell: face tabs + stage + tool rail
  CanvasStage.tsx      react-konva <Stage>: bg product image + element layer + Transformer
  elements/
    TextNode.tsx       Konva Text node bound to store
    ImageNode.tsx      Konva Image node bound to store
  ToolRail.tsx         add-text / upload / colour swatches / render button
  SelectedToolbar.tsx  contextual controls for the selected element
store/
  canvasStore.ts       Zustand source of truth (see §6)
```

- `canvasStore` is the **single source of truth**; Konva nodes declaratively reflect
  it. Drag/transform end handlers call `updateElement`.
- Existing `sessionStore` still owns session/generation/delivery state. The two meet
  at "See it rendered": canvas flattens + persists, then hands off to the existing
  generation trigger.
- `ProductViewer` is repurposed as the **result viewer** shown after render
  (design hero + composite angles + gated reveal) — it already supports `compositeViews`.

## 6. Design-State Data Model & Persistence

Element geometry is **normalised 0–1** to the face box (resolution-independent).

```ts
type Element = {
  id: string
  type: 'text' | 'image'
  x: number; y: number; width: number; height: number; rotation: number  // 0–1 / degrees
  zIndex: number
  zone?: string                       // nearest named placement zone
  // text
  content?: string; font?: string; colour?: string; fontSize?: number
  // image
  assetUrl?: string; removeBg?: boolean
}
type CanvasDesign = {
  colourway: string
  faces: Record<'front' | 'back' | 'left' | 'right', Element[]>
}
```

**Persistence:** new additive `canvas_design jsonb` column on `design_sessions`
(migration in `backend/supabase/migrations/`). Saved on debounce as the customer
edits (reuse the session-save path) so refresh/return restores the canvas. For canvas
sessions this replaces `collected.elements` as the design source of truth. Customise
Q&A columns untouched.

## 7. Flatten, Upload, Describe

On **See it rendered**, for each face with ≥1 element:

1. **Flatten:** `stage.toDataURL()` → PNG (product photo + decorations baked in).
2. **Upload:** `POST /sessions/{id}/canvas-layouts` (new route) → validate
   (MIME/magic-bytes/size) → store in private `madhats-assets` bucket → signed URLs.
   These are the **layout-guide images**.
3. **Auto-describe (deterministic, no LLM):** backend builds the description from
   `canvas_design` — per face, per element, with zone/colour/font — e.g.
   *"Front panel: embroidered text 'SURF CO' in white, centred. Back panel: uploaded
   logo, top-left."* This is the description sent to the model.

## 8. Backend Generation Wiring

- **ImageProvider:** add `layout_guide_url: str | None` to `GenerationParams`
  (additive; adapters ignoring it still work). Gemini adapter passes the real product
  photo (conditioning) **+** layout-guide PNG **+** description.
- **prompt_builder:** a canvas branch enumerating `canvas_design` elements (it already
  enumerates elements) + referencing the layout guide: *"Follow the supplied layout
  image for placement; render these decorations onto the real cap: …"*. Fidelity-lock
  instructions retained.
- **Multi-face strategy (cost-conscious):** the **front hero is AI-rendered** (layout
  guide + description), exactly as today — one Gemini call, same cost/latency as the
  current blank flow. **Decorated non-front faces reuse the flattened canvas PNG that
  §7 already produced and uploaded** — it *is* the customer's composite, so it's shown
  directly as that angle's view (no extra Gemini calls, no Pillow re-compositing).
  Undecorated non-front faces fall back to the plain angle photo (blank flow: existing
  Pillow tint for the chosen colourway). All four faces reflect the design; these
  images flow into `compositeViews` in `ProductViewer`. AI-rendering every face is a
  deferred toggle.

## 9. State Machine — Canvas Path

Canvas sessions take a short new path; the deep-dive Q&A states are **bypassed** (code
retained, reversible):

```
CANVAS_DESIGN → SAVE_PROGRESS_EMAIL → GENERATING → (verify email) → deliver → OFFER_REFINE
```

- Retired for canvas sessions: `ASK_MORE_ELEMENTS`, `ELEMENT_DEEPDIVE`, attribute walk.
- Customise Q&A code and states are not deleted — a `flow`/session flag routes canvas
  sessions down the new path.

## 10. Testing

**Frontend (vitest):**
- `canvasStore` reducers: add / update / remove / reorder / select / zone-snap.
- Normalised-geometry round-trip (store ↔ Konva pixel coords).
- Description-builder pure function output.
- "See it rendered" wiring with mocked flatten/upload.

**Backend (pytest):**
- `POST /sessions/{id}/canvas-layouts`: upload validation + signed-URL response.
- `canvas_design` persistence + restore on `GET /sessions/{token}`.
- Description builder from `canvas_design`.
- `prompt_builder` canvas branch output.
- Generation passes `layout_guide_url`; composite path for non-front faces.

## 11. Out of Scope (Phase 1)

- Clipart/graphics library (Phase 2).
- AI chat helper that drives tools + captures extra description (Phase 3).
- Rule-based smart suggestions (Phase 3).
- AI graphic generation (not planned).
- AI-rendering every face (front-AI + composite-others is the P1 strategy).
