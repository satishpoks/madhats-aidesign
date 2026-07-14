# Canvas: Real Background Removal + Freehand Draw Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the canvas "Remove background" toggle actually strip an uploaded image's background (client-side, transparent PNG used on-canvas AND in the final render), and add a freehand draw tool (pen with customer-chosen colour + thickness).

**Architecture:** Both are additive to the Canvas Design Studio. Background removal runs in-browser via a lazy-loaded WASM matting library; the transparent result is re-uploaded through the existing `uploadLogo` seam so both the flattened layout guide and the crisp Gemini asset are clean. The draw tool adds a `drawing` element type (a Konva `Line`) created by pointer-drag on the stage; it maps to the existing `graphic` element downstream, so multi-angle generation covers drawn faces with no pipeline change.

**Tech Stack:** React 18 / Zustand / react-konva / Vite / Vitest (frontend); Python 3.12 / FastAPI / pytest (backend); `@imgly/background-removal` (new frontend dep).

## Global Constraints

- **Background removal is client-side only** and must produce a transparent PNG used in BOTH places: on the canvas (so the flattened layout guide is clean) AND as the crisp asset sent to Gemini — achieved by re-uploading the active image through `uploadLogo` (session `uploaded_asset_path`, last write wins).
- **No pixel coordinates in the backend text description** — the flattened layout PNG owns exact geometry (consistent with the multi-angle rendering work).
- **Drawings map to the existing `graphic` element type** (with a `placement_zone`) so they flow through `element_view` / `render_views` / `build_view_prompt` unchanged.
- **Frontend canvas components are tsc-gated** (jsdom has no canvas); store and `lib/` logic get real Vitest unit tests. Verify components with `cd frontend && npm run build` (tsc) and focused Vitest with `cd frontend && npx vitest run <file>` (`npm test` is watch mode — never use it).
- **New frontend dependency must also be installed inside the docker container** for dev (`docker compose exec frontend npm install` → `docker compose restart frontend`, per CLAUDE.md §13) — the host `npm install` in Task 2 covers build/tests only.
- End every commit message body with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Use targeted `git add` of only the files each task names — the working tree may hold unrelated files; never stage them.

---

### Task 1: Store foundations — `drawing` type, draw-mode state, `addDrawing`, `originalAssetUrl`

**Files:**
- Modify: `frontend/src/store/canvasStore.ts`
- Test: `frontend/src/store/canvasStore.test.ts`

**Interfaces:**
- Produces: `CanvasElement` gains `originalAssetUrl?: string`, the `type` union gains `'drawing'`, and `points?: number[]`. Store gains `drawMode: boolean`, `drawColour: string`, `drawWidth: number`, `setDrawMode(v: boolean)`, `setDrawColour(c: string)`, `setDrawWidth(w: number)`, and `addDrawing(points: number[]): void` (commits one `drawing` element to the active face using the current `drawColour`/`drawWidth`, selects it). `reset()` also sets `drawMode:false` and restores `drawColour`/`drawWidth` defaults.

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/store/canvasStore.test.ts` (inside the `describe('canvasStore', …)` block):

```ts
  it('addDrawing appends a drawing element with the current colour + width, selected', () => {
    const s = useCanvasStore.getState()
    s.setDrawColour('#ff0000'); s.setDrawWidth(0.02)
    s.addDrawing([0.1, 0.1, 0.2, 0.2])
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.type).toBe('drawing')
    expect(el.points).toEqual([0.1, 0.1, 0.2, 0.2])
    expect(el.stroke).toBe('#ff0000')
    expect(el.strokeWidth).toBe(0.02)
    expect(useCanvasStore.getState().selectedId).toBe(el.id)
  })

  it('setDrawMode toggles draw mode and reset clears it', () => {
    const s = useCanvasStore.getState()
    s.setDrawMode(true)
    expect(useCanvasStore.getState().drawMode).toBe(true)
    useCanvasStore.getState().reset()
    expect(useCanvasStore.getState().drawMode).toBe(false)
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/store/canvasStore.test.ts`
Expected: FAIL — `setDrawColour`/`setDrawWidth`/`addDrawing`/`setDrawMode`/`drawMode` don't exist on the store.

- [ ] **Step 3: Extend `CanvasElement`**

In `frontend/src/store/canvasStore.ts`, change the `type` union and add the two fields:

```ts
export interface CanvasElement {
  id: string
  type: 'text' | 'image' | 'shape' | 'drawing'
  x: number; y: number; width: number; height: number; rotation: number
  zIndex: number
  content?: string; font?: string; colour?: string; fontSize?: number
  /** Text arch: 0 = straight, negative = arch down, positive = arch up. */
  curve?: number
  assetUrl?: string; removeBg?: boolean
  /** Original (pre-background-removal) asset URL, so the toggle is reversible. */
  originalAssetUrl?: string
  /** Freehand drawing: flat list of normalised x,y pairs [x0,y0,x1,y1,…]. */
  points?: number[]
  // shape
  shapeKind?: ShapeKind
  fill?: string
  stroke?: string
  strokeWidth?: number
  filled?: boolean
}
```

- [ ] **Step 4: Add draw-mode state + setters + `addDrawing` to the `CanvasState` interface and store**

In the `CanvasState` interface (after `setColourway`), add:

```ts
  drawMode: boolean
  drawColour: string
  drawWidth: number
  setDrawMode: (v: boolean) => void
  setDrawColour: (c: string) => void
  setDrawWidth: (w: number) => void
  addDrawing: (points: number[]) => void
```

In the store's initial state (after `faceImages: {...}`), add:

```ts
  drawMode: false,
  drawColour: '#111827',
  drawWidth: 0.01,
```

Add the setters + action (place near `addShape`):

```ts
  setDrawMode: v => set({ drawMode: v, selectedId: null }),
  setDrawColour: c => set({ drawColour: c }),
  setDrawWidth: w => set({ drawWidth: w }),

  addDrawing: points => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'drawing', x: 0, y: 0, width: 0, height: 0, rotation: 0,
      zIndex: s.faces[s.activeFace].length,
      points, stroke: s.drawColour, strokeWidth: s.drawWidth,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),
```

Update `reset` to clear draw-mode state:

```ts
  reset: () => set({ faces: emptyFaces(), activeFace: 'front', selectedId: null, colourway: null,
    faceImages: { front: '', back: '', left: '', right: '' },
    drawMode: false, drawColour: '#111827', drawWidth: 0.01 }),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/store/canvasStore.test.ts`
Expected: PASS — all pre-existing canvasStore tests plus the two new ones.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/store/canvasStore.test.ts
git commit -m "feat(canvas): store — drawing element type, draw-mode state, originalAssetUrl"
```

---

### Task 2: Background removal — `lib/bgRemove.ts` + wire the "Remove background" toggle

**Files:**
- Modify: `frontend/package.json` (add `@imgly/background-removal`)
- Create: `frontend/src/lib/bgRemove.ts`
- Create: `frontend/src/lib/bgRemove.test.ts`
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx`

**Interfaces:**
- Consumes: `uploadLogo(sessionId, file) → Promise<{ asset_url, asset_hash }>` (`lib/api.ts`); `CanvasElement`, `useCanvasStore` (Task 1); `useSessionStore` (`s.sessionId`).
- Produces: `removeBackgroundToFile(src: string): Promise<File>` and `toggleBackground(sessionId: string, el: CanvasElement, on: boolean): Promise<Partial<CanvasElement>>` in `lib/bgRemove.ts`.

- [ ] **Step 1: Add the dependency (host install for build/tests)**

Run: `cd frontend && npm install @imgly/background-removal`
Expected: `package.json` gains the dependency and it installs. (Dev note: it must ALSO be installed inside the docker container — see Global Constraints — but that's a runtime step, not part of this commit's verification.)

- [ ] **Step 2: Write the failing test for the orchestrator**

Create `frontend/src/lib/bgRemove.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('@imgly/background-removal', () => ({
  removeBackground: vi.fn(async () => new Blob(['x'], { type: 'image/png' })),
}))
vi.mock('./api', () => ({
  uploadLogo: vi.fn(async () => ({ asset_url: 'stored/nobg.png', asset_hash: 'h' })),
}))

import { toggleBackground } from './bgRemove'
import { uploadLogo } from './api'

beforeEach(() => vi.clearAllMocks())

describe('toggleBackground', () => {
  it('ON: mattes, uploads the transparent PNG, records the original url', async () => {
    const el = { id: '1', type: 'image', assetUrl: 'orig.png' } as never
    const patch = await toggleBackground('s1', el, true)
    expect(uploadLogo).toHaveBeenCalledTimes(1)
    expect(patch).toEqual({ assetUrl: 'stored/nobg.png', removeBg: true, originalAssetUrl: 'orig.png' })
  })

  it('OFF: re-uploads the original image and clears removeBg', async () => {
    globalThis.fetch = vi.fn(async () => ({ blob: async () => new Blob(['y'], { type: 'image/png' }) })) as never
    const el = { id: '1', type: 'image', assetUrl: 'nobg.png', originalAssetUrl: 'orig.png' } as never
    const patch = await toggleBackground('s1', el, false)
    expect(globalThis.fetch).toHaveBeenCalledWith('orig.png')
    expect(uploadLogo).toHaveBeenCalledTimes(1)
    expect(patch).toEqual({ assetUrl: 'stored/nobg.png', removeBg: false })
  })
})
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/bgRemove.test.ts`
Expected: FAIL — `./bgRemove` / `toggleBackground` does not exist.

- [ ] **Step 4: Implement `lib/bgRemove.ts`**

Create `frontend/src/lib/bgRemove.ts`:

```ts
import type { CanvasElement } from '../store/canvasStore'
import { uploadLogo } from './api'

/**
 * Run in-browser background matting on an image URL → a transparent PNG File.
 * The library is dynamic-imported so its multi-MB WASM model only downloads when
 * a customer actually removes a background — it never enters the main bundle.
 */
export async function removeBackgroundToFile(src: string): Promise<File> {
  const { removeBackground } = await import('@imgly/background-removal')
  const blob = await removeBackground(src)
  return new File([blob], 'logo-nobg.png', { type: 'image/png' })
}

/**
 * Compute the element patch for toggling background removal on/off. Re-uploads
 * the now-active image via uploadLogo so the crisp asset Gemini receives
 * (session uploaded_asset_path, last write wins) stays in sync with the canvas.
 */
export async function toggleBackground(
  sessionId: string,
  el: CanvasElement,
  on: boolean,
): Promise<Partial<CanvasElement>> {
  if (on) {
    const file = await removeBackgroundToFile(el.assetUrl ?? '')
    const { asset_url } = await uploadLogo(sessionId, file)
    return { assetUrl: asset_url, removeBg: true, originalAssetUrl: el.originalAssetUrl ?? el.assetUrl }
  }
  const orig = el.originalAssetUrl ?? el.assetUrl ?? ''
  const blob = await (await fetch(orig)).blob()
  const file = new File([blob], 'logo.png', { type: blob.type || 'image/png' })
  const { asset_url } = await uploadLogo(sessionId, file)
  return { assetUrl: asset_url, removeBg: false }
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/lib/bgRemove.test.ts`
Expected: PASS — both cases.

- [ ] **Step 6: Wire the toggle in `SelectedToolbar.tsx`**

In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`, update the imports at the top:

```ts
import { useState } from 'react'
import { useCanvasStore, LINE_SHAPES, type CanvasElement } from '../../store/canvasStore'
import { useSessionStore } from '../../store/sessionStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'
import { toggleBackground } from '../../lib/bgRemove'
```

Replace the current image branch (lines 50-55):

```tsx
      {el.type === 'image' && (
        <label className="flex items-center gap-1.5 text-sm text-textPrimary">
          <input type="checkbox" checked={!!el.removeBg} onChange={e => update(el.id, { removeBg: e.target.checked })} />
          Remove background
        </label>
      )}
```

with a call to a dedicated sub-component (hooks can't live in a conditional branch):

```tsx
      {el.type === 'image' && <BgRemoveToggle el={el} />}
      {el.type === 'drawing' && (
        <label className="flex items-center gap-1 text-xs text-textMuted" title="Stroke colour">
          <span>Colour</span>
          <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
            className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Stroke colour" />
        </label>
      )}
```

Add the sub-component at the end of the file (after the `SelectedToolbar` function's closing brace):

```tsx
/** Background-removal toggle: runs client-side matting, swaps the element's image
 *  to the transparent (or restored original) upload. Async, with a busy state. */
function BgRemoveToggle({ el }: { el: CanvasElement }) {
  const sessionId = useSessionStore(s => s.sessionId)
  const update = useCanvasStore(s => s.updateElement)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)

  async function onToggle(on: boolean) {
    if (!sessionId) return
    setBusy(true); setFailed(false)
    try {
      const patch = await toggleBackground(sessionId, el, on)
      update(el.id, patch)
    } catch {
      setFailed(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <label className="flex items-center gap-1.5 text-sm text-textPrimary">
      <input type="checkbox" checked={!!el.removeBg} disabled={busy}
        onChange={e => void onToggle(e.target.checked)} />
      {busy ? 'Removing…' : failed ? 'Failed — try again' : 'Remove background'}
    </label>
  )
}
```

- [ ] **Step 7: Verify the build (tsc gate) + re-run the lib test**

Run: `cd frontend && npm run build && npx vitest run src/lib/bgRemove.test.ts src/store/canvasStore.test.ts`
Expected: build succeeds (tsc clean); both test files PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/bgRemove.ts frontend/src/lib/bgRemove.test.ts frontend/src/components/DesignStudio/SelectedToolbar.tsx
git commit -m "feat(canvas): real client-side background removal (imgly WASM) wired to the toggle"
```

---

### Task 3: Draw tool — `DrawingNode`, stage pointer handling, tool-rail draw bar, thumbnails

**Files:**
- Modify: `frontend/src/components/DesignStudio/nodes.tsx` (add `DrawingNode`)
- Modify: `frontend/src/components/DesignStudio/CanvasStage.tsx` (draw-mode pointer handling + render)
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx` (Draw toggle + colour/thickness bar)
- Modify: `frontend/src/components/DesignStudio/FaceThumbnails.tsx` (render drawings)

**Interfaces:**
- Consumes: `useCanvasStore` draw-mode state + `addDrawing` (Task 1); `NodeProps` (existing, `nodes.tsx`); `STAGE_W`/`STAGE_H` (`CanvasStage.tsx`).
- Produces: `DrawingNode(props: NodeProps)` exported from `nodes.tsx`. Verified by tsc + focused store tests (jsdom has no canvas, so no render test — consistent with the other canvas nodes).

- [ ] **Step 1: Add `DrawingNode` to `nodes.tsx`**

The `Line` and `Group` imports already exist at the top of `nodes.tsx`. Append this export (e.g. after `ImageNode`):

```tsx
export function DrawingNode({ el, stageW, stageH, onSelect, onChange }: NodeProps) {
  const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * stageW : p * stageH))
  const sw = (el.strokeWidth ?? 0.01) * stageW
  return (
    <Group
      x={el.x * stageW}
      y={el.y * stageH}
      draggable
      onClick={onSelect}
      onTap={onSelect}
      onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
    >
      <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={sw}
        lineCap="round" lineJoin="round" tension={0.5} hitStrokeWidth={Math.max(sw, 12)} />
    </Group>
  )
}
```

(Move + delete only — no `Transformer`, per the design.)

- [ ] **Step 2: Wire draw-mode pointer handling + rendering in `CanvasStage.tsx`**

Replace the entire body of `frontend/src/components/DesignStudio/CanvasStage.tsx` with:

```tsx
import { useRef, useEffect, useState, type RefObject } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect, Line } from 'react-konva'
import type Konva from 'konva'
import { useCanvasStore } from '../../store/canvasStore'
import { TextNode, ImageNode, ShapeNode, DrawingNode } from './nodes'
import { getCachedImage, loadImage } from '../../lib/imageCache'

export const STAGE_W = 480
export const STAGE_H = 480

export function CanvasStage({ stageRef }: { stageRef: RefObject<Konva.Stage> }) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const faceImages = useCanvasStore(s => s.faceImages)
  const selectedId = useCanvasStore(s => s.selectedId)
  const select = useCanvasStore(s => s.select)
  const updateElement = useCanvasStore(s => s.updateElement)
  const colourway = useCanvasStore(s => s.colourway)
  const drawMode = useCanvasStore(s => s.drawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const addDrawing = useCanvasStore(s => s.addDrawing)

  const [stroke, setStroke] = useState<number[] | null>(null)

  const bgUrl = faceImages[activeFace]
  const [bg, setBg] = useState<HTMLImageElement | null>(() => {
    const cached = getCachedImage(bgUrl)
    return cached && cached.complete ? cached : null
  })
  useEffect(() => {
    if (!bgUrl) { setBg(null); return }
    const cached = getCachedImage(bgUrl)
    if (cached && cached.complete) { setBg(cached); return }
    let cancelled = false
    loadImage(bgUrl).then(img => { if (!cancelled) setBg(img) })
    return () => { cancelled = true }
  }, [bgUrl])

  const els = [...faces[activeFace]].sort((a, b) => a.zIndex - b.zIndex)

  function pointerNorm(stage: Konva.Stage | null): number[] | null {
    const p = stage?.getPointerPosition()
    return p ? [p.x / STAGE_W, p.y / STAGE_H] : null
  }
  function onDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!drawMode) { if (e.target === e.target.getStage()) select(null); return }
    const n = pointerNorm(e.target.getStage())
    if (n) setStroke(n)
  }
  function onMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!drawMode || !stroke) return
    const n = pointerNorm(e.target.getStage())
    if (n) setStroke(prev => (prev ? [...prev, ...n] : n))
  }
  function onUp() {
    if (!drawMode || !stroke) return
    if (stroke.length >= 4) addDrawing(stroke) // ≥ 2 points
    setStroke(null)
  }

  const livePts = stroke ? stroke.map((p, i) => (i % 2 === 0 ? p * STAGE_W : p * STAGE_H)) : []

  return (
    <Stage
      ref={stageRef as never}
      width={STAGE_W}
      height={STAGE_H}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onTouchStart={onDown}
      onTouchMove={onMove}
      onTouchEnd={onUp}
      style={{ cursor: drawMode ? 'crosshair' : 'default' }}
      className="rounded-2xl bg-surface"
    >
      {/* Elements stop listening while drawing so every pointer event reaches the
          stage handlers above (start/extend/commit a stroke anywhere on the cap). */}
      <Layer listening={!drawMode}>
        {bg && <KonvaImage image={bg} width={STAGE_W} height={STAGE_H} listening={false} />}
        {colourway && (
          <Rect width={STAGE_W} height={STAGE_H} fill={colourway.hex}
                globalCompositeOperation="multiply" listening={false} />
        )}
        {els.map(el => {
          const props = {
            el, stageW: STAGE_W, stageH: STAGE_H,
            isSelected: el.id === selectedId,
            onSelect: () => select(el.id),
            onChange: (p: Partial<typeof el>) => updateElement(el.id, p),
          }
          if (el.type === 'text') return <TextNode key={el.id} {...props} />
          if (el.type === 'shape') return <ShapeNode key={el.id} {...props} />
          if (el.type === 'drawing') return <DrawingNode key={el.id} {...props} />
          return <ImageNode key={el.id} {...props} />
        })}
        {stroke && stroke.length >= 4 && (
          <Line points={livePts} stroke={drawColour} strokeWidth={drawWidth * STAGE_W}
            lineCap="round" lineJoin="round" tension={0.5} listening={false} />
        )}
      </Layer>
    </Stage>
  )
}
```

- [ ] **Step 3: Add the Draw toggle + colour/thickness bar to `ToolRail.tsx`**

In `frontend/src/components/DesignStudio/ToolRail.tsx`, add the draw-mode store reads inside the component (after the existing `colourway`/`setColourway` lines):

```tsx
  const drawMode = useCanvasStore(s => s.drawMode)
  const setDrawMode = useCanvasStore(s => s.setDrawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const setDrawColour = useCanvasStore(s => s.setDrawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const setDrawWidth = useCanvasStore(s => s.setDrawWidth)
```

Add the button + bar immediately after the "Graphics" button (line 21):

```tsx
      <button onClick={() => setDrawMode(!drawMode)}
        className={`px-4 py-2 border rounded-lg text-sm transition-colors ${
          drawMode ? 'border-accent bg-accent/10 text-accent' : 'bg-surface border-border text-textPrimary hover:border-accent'
        }`}>
        ✎ Draw{drawMode ? ' (on)' : ''}
      </button>
      {drawMode && (
        <div className="flex items-center gap-3 px-1">
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Draw colour">
            <span>Colour</span>
            <input type="color" value={drawColour} onChange={e => setDrawColour(e.target.value)}
              className="w-7 h-7 p-0 border-0 bg-transparent" aria-label="Draw colour" />
          </label>
          <label className="flex items-center gap-1 text-xs text-textMuted" title="Thickness">
            <span>Thickness</span>
            <input type="range" min={0.004} max={0.03} step={0.002} value={drawWidth}
              onChange={e => setDrawWidth(Number(e.target.value))} aria-label="Draw thickness" />
          </label>
        </div>
      )}
```

- [ ] **Step 4: Render drawings in `FaceThumbnails.tsx`**

In `frontend/src/components/DesignStudio/FaceThumbnails.tsx`, add `Line` to the react-konva import (line 2):

```tsx
import { Stage, Layer, Image as KonvaImage, Rect, Text, TextPath, Group, Line } from 'react-konva'
```

In `ElementThumb`, add a `drawing` branch (before the `if (el.type === 'text')` block):

```tsx
  if (el.type === 'drawing') {
    const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * TW : p * TH))
    return (
      <Group x={el.x * TW} y={el.y * TH}>
        <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={(el.strokeWidth ?? 0.01) * TW}
          lineCap="round" lineJoin="round" tension={0.5} listening={false} />
      </Group>
    )
  }
```

- [ ] **Step 5: Verify the build (tsc gate) + run the canvas store tests**

Run: `cd frontend && npm run build && npx vitest run src/store/canvasStore.test.ts`
Expected: build succeeds (tsc clean across the four changed components); store tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/nodes.tsx frontend/src/components/DesignStudio/CanvasStage.tsx frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/components/DesignStudio/FaceThumbnails.tsx
git commit -m "feat(canvas): freehand draw tool — pen strokes with colour + thickness"
```

---

### Task 4: Backend — describe a drawing as a graphic (`canvas_describe`)

**Files:**
- Modify: `backend/app/services/canvas_describe.py` (`_element` + `_describe`)
- Test: `backend/tests/test_canvas_describe.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `canvas_to_elements` now maps a `type:"drawing"` canvas element to `{"type":"graphic", "content":"a hand-drawn line[ in <colour>]", "colour": <stroke>}` + the face's placement zone; the description string carries the same coarse phrase and no pixel coordinates.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_canvas_describe.py`:

```python
def test_drawing_maps_to_graphic_with_stroke_colour():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "d1", "type": "drawing", "x": 0, "y": 0, "width": 0, "height": 0,
                "rotation": 0, "zIndex": 0, "points": [0.1, 0.1, 0.5, 0.5],
                "stroke": "#ff0000", "strokeWidth": 0.01,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    el = elements[0]
    assert el["type"] == "graphic"
    assert "hand-drawn line" in el["content"]
    assert el["colour"] == "#ff0000"
    assert el["placement_zone"] == "front_panel"
    assert "hand-drawn line" in description
    assert "0.1" not in description  # no pixel/normalised coords leak into the text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && python -m pytest tests/test_canvas_describe.py::test_drawing_maps_to_graphic_with_stroke_colour -v`
Expected: FAIL — a `drawing` currently falls into the `else` branch and is mapped to a `logo` (`el["type"] == "graphic"` assertion fails).

- [ ] **Step 3: Add the `drawing` branch to `_element`**

In `backend/app/services/canvas_describe.py`, in `_element`, insert a `drawing` branch between the `shape` branch and the final `else` (i.e. after the block ending at the `out["colour"] = el["fill"]` line for shapes, before `else:  # image / uploaded logo …`):

```python
    elif etype == "drawing":
        # A freehand pen stroke. Describe it as a graphic; the flattened layout PNG
        # carries the exact geometry, this is just the text hint.
        out["type"] = "graphic"
        colour = el.get("stroke")
        out["content"] = f"a hand-drawn line in {colour}" if colour else "a hand-drawn line"
        if colour:
            out["colour"] = colour
```

- [ ] **Step 4: Add the `drawing` branch to `_describe`**

In `_describe`, add a branch before the shape check (after the `text` block):

```python
    if etype == "drawing":
        colour = el.get("stroke")
        phrase = f"a hand-drawn line in {colour}" if colour else "a hand-drawn line"
        return f"{phrase} {where}"
```

- [ ] **Step 5: Run the test + the full describe suite to verify pass**

Run: `cd backend && python -m pytest tests/test_canvas_describe.py -v`
Expected: PASS — the new test plus all pre-existing describe tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/canvas_describe.py backend/tests/test_canvas_describe.py
git commit -m "feat(canvas): describe a freehand drawing as a graphic for generation"
```

---

### Task 5: Full-suite verification + docs

**Files:**
- Modify: `CLAUDE.md` (canvas bullet + test counts)
- Verify: whole frontend + backend suites.

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS — full suite green (prior baseline 415; this plan adds 1 backend test → ~416).

- [ ] **Step 2: Run the frontend build + focused test suites**

Run: `cd frontend && npm run build && npx vitest run src/store/canvasStore.test.ts src/lib/bgRemove.test.ts`
Expected: build clean; both suites PASS. (A full `npx vitest run` may show the 2 pre-existing `adminQuotes` Router-context failures + the known Windows tinypool flake — these are unrelated; rerun focused to confirm the new/changed suites are green.)

- [ ] **Step 3: Update `CLAUDE.md`**

In the Canvas Studio UI polish bullet(s) of `CLAUDE.md`, add a sentence documenting: (a) **real background removal** — the "Remove background" toggle now runs client-side matting (`@imgly/background-removal`, lazy-loaded via `lib/bgRemove.ts`) and re-uploads the transparent PNG through `uploadLogo` so both the flattened layout guide and the crisp Gemini asset are clean (the flag was previously inert — captured but never applied); and (b) **freehand draw tool** — a `drawing` element type (Konva `Line`, `canvasStore` `points`/`stroke`/`strokeWidth` + `drawMode`/`drawColour`/`drawWidth`), created by pointer-drag on the stage, colour + thickness chosen in the tool rail, move + delete per stroke, rendered in the face thumbnails, and mapped to a described `graphic` (`canvas_describe`) so it flows through the multi-angle pipeline. Also note the docker-container install requirement for the new dep.

Update the test-count line (currently `backend pytest 415, frontend vitest run 181`) to the new backend count from Step 1 (and frontend count if it changed — the two new frontend test cases live in existing/new files counted by a full run).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(canvas): real background removal + freehand draw tool"
```

---

## Self-Review notes

- **Spec coverage:** Part A (client-side bg removal, transparent PNG on canvas + as crisp asset via re-upload, reversible via `originalAssetUrl`) → Tasks 1 (`originalAssetUrl`) + 2. Part B (freehand pen, colour+thickness, move+delete, thumbnails, tool UI) → Tasks 1 (`drawing` type + draw-mode state + `addDrawing`) + 3. Part C (`canvas_describe` → graphic, no pixel coords) → Task 4. Testing (store units, bg-remove orchestrator unit, tsc gate, backend describe) → Tasks 1-4; full-suite + docs → Task 5.
- **Constraints:** client-side-only + dual-use of the transparent PNG enforced in Task 2's `toggleBackground` (re-upload both directions); no-pixel-coords enforced + asserted in Task 4; drawings-as-graphic (so they ride `render_views`/`build_view_prompt`) enforced in Task 4; tsc-gated component verification in Tasks 2/3; docker-container dep note in Global Constraints + Task 5.
- **Placeholder scan:** none — every code step contains the full code; the only prose step is the CLAUDE.md doc edit (Task 5 Step 3), which is documentation, not code.
- **Type consistency:** `toggleBackground(sessionId, el, on)` / `removeBackgroundToFile(src)` (Task 2) match their uses; `DrawingNode(NodeProps)` (Task 3) matches the existing `NodeProps`; `addDrawing(points)` / `drawMode`/`drawColour`/`drawWidth` / `originalAssetUrl` / `points` (Task 1) match every later reference; `uploadLogo` return shape `{ asset_url, asset_hash }` matches `lib/api.ts`.
