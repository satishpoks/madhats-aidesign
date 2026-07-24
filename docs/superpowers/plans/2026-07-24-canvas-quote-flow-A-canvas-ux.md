# Workstream A — Canvas Editor UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every selected canvas element explicit rotate/move/size controls, fix the rework-unlock bug so refined designs are fully editable again, de-emphasise the upload button's highlight without breaking its load-bearing unlock, and align upload copy to "image or logo".

**Architecture:** All work is frontend-only inside `frontend/src/components/DesignStudio/` and `frontend/src/store/canvasStore.ts`. The Zustand `canvasStore` is the single source of truth for element geometry (`x`,`y`,`width`,`height` normalised 0–1; `rotation` in degrees; `fontSize` for text; `points` for drawings; `locked`). New universal transform controls patch those fields through the existing active-face-scoped `updateElement(id, patch)`; a new `unlockAll()` mirrors `lockAll()` and is invoked from `Surface.tsx` when the finalize guard re-arms (canvas re-opens for rework); `fromCanvasDesign` stops persisting a permanent lock. A4 is a documentation-only note: the copy strings live in the backend and the on-screen button label stays "Upload image".

**Tech Stack:** React 18, react-konva, Zustand, Vitest, TypeScript

## Global Constraints
- Frontend tests: run the Windows-stall-safe TARGETED subset, e.g. `npx vitest run src/store/canvasStore... ` (full `vitest run` stalls on this Windows host). Never `npm test` (watch mode hangs).
- Do not modify the load-bearing v2 `ask_logo_bg` backend behaviour or its pinning test (A3 is highlight-only).
- All element coords are normalised 0-1; clamp move to [0,1]. rotation in degrees.
- All `npx vitest run …` commands are run from the `frontend/` directory (paths below are relative to `frontend/`).

---

## File Structure

| File | Create / Modify | Responsibility |
|---|---|---|
| `frontend/src/store/canvasStore.ts` | Modify | Add `unlockAll()`; strip `locked` in `fromCanvasDesign()`. |
| `frontend/src/components/DesignStudio/Surface.tsx` | Modify | Call `unlockAll()` in the finalize re-arm branch (canvas re-opens for rework). |
| `frontend/src/components/DesignStudio/SelectedToolbar.tsx` | Modify | Add the universal transform block (rotate / move / size) before the reorder/duplicate/delete buttons. |
| `frontend/src/components/DesignStudio/ToolRail.tsx` | Modify | Suppress the accent ring + pulse for the `upload` tool only (keep it enabled). |
| `frontend/src/__tests__/canvasStoreUnlock.test.ts` | Create | Store-level tests for `unlockAll` + `fromCanvasDesign` lock-strip. |
| `frontend/src/__tests__/surfaceRework.test.tsx` | Create | Surface test: finalize → rework re-open unlocks all elements. |
| `frontend/src/__tests__/selectedToolbarTransform.test.tsx` | Create | Transform-controls behaviour (rotate/move/size, drawing has no size). |
| `frontend/src/__tests__/toolRailUploadHighlight.test.tsx` | Create | Upload tool is enabled but NOT highlighted. |
| `frontend/src/__tests__/ToolRail.test.tsx` | Modify | Update the one existing "highlighted" assertion that used `upload` to use a non-upload tool. |
| `backend/app/prompts.py`, `backend/app/services/conversation/canvas_steps.py`, `backend/app/services/conversation/intent_extractor.py` | (A4 — backend-owned) | Copy strings only; NOT changed in this frontend plan (see Task 5 note). |

---

### Task 1: `unlockAll()` in the store + `fromCanvasDesign` lock-strip

**Files:**
- Modify: `frontend/src/store/canvasStore.ts` (interface `CanvasState` ~line 72–76; implementation `lockPlaced` ~line 226–232; `fromCanvasDesign` ~line 243–253)
- Test: `frontend/src/__tests__/canvasStoreUnlock.test.ts` (create)

**Interfaces:**
- Produces: `unlockAll(): void` — sets `locked:false` on every element across all four faces; clears `selectedId` (mirror of `lockAll`).
- Modifies: `fromCanvasDesign(design)` — hydrated elements come back with `locked` removed (editable), so a serialised `locked:true` never permanently freezes a resumed design.

- [ ] **Step 1 — Write the failing store test.** Create `frontend/src/__tests__/canvasStoreUnlock.test.ts`:
```ts
import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'
import type { CanvasDesign } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

test('unlockAll clears locked on every element across all faces', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  s.setActiveFace('back'); s.addText('b')
  s.lockAll()
  expect(useCanvasStore.getState().faces.front[0].locked).toBe(true)
  expect(useCanvasStore.getState().faces.back[0].locked).toBe(true)

  useCanvasStore.getState().unlockAll()
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].locked).toBe(false)
  expect(faces.back[0].locked).toBe(false)
})

test('unlockAll clears the current selection', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  const id = useCanvasStore.getState().faces.front[0].id
  s.select(id)
  expect(useCanvasStore.getState().selectedId).toBe(id)
  s.unlockAll()
  expect(useCanvasStore.getState().selectedId).toBeNull()
})

test('fromCanvasDesign strips a persisted locked flag so resumed elements are editable', () => {
  const design: CanvasDesign = {
    colourway: null,
    faces: {
      front: [{
        id: 'x1', type: 'text', x: 0.5, y: 0.4, width: 0.3, height: 0.12,
        rotation: 0, zIndex: 0, content: 'hi', locked: true,
      }],
      back: [], left: [], right: [],
    },
  }
  useCanvasStore.getState().fromCanvasDesign(design)
  const el = useCanvasStore.getState().faces.front[0]
  expect(el.content).toBe('hi')
  expect(el.locked).toBeFalsy()
})
```

- [ ] **Step 2 — Run the test (expected FAIL).**
```
npx vitest run src/__tests__/canvasStoreUnlock.test.ts
```
Expected: FAIL — `unlockAll is not a function` and the resumed element still carries `locked:true`.

- [ ] **Step 3 — Add `unlockAll` to the `CanvasState` interface.** In `frontend/src/store/canvasStore.ts`, insert after the `lockPlaced` declaration in the interface (currently ~line 76, right after its doc comment block):
```ts
  lockPlaced: () => void
  /** Rework/refine re-open: clear locked on every element across all faces so
   *  a refined design is fully editable again (mirror of lockAll). */
  unlockAll: () => void
```

- [ ] **Step 4 — Implement `unlockAll` in the store body.** Insert immediately after the `lockPlaced` implementation (the block ending `}),` at ~line 232):
```ts
  unlockAll: () => set(s => {
    const faces = { ...s.faces }
    for (const f of FACES) faces[f] = faces[f].map(e => ({ ...e, locked: false }))
    return { faces, selectedId: null }
  }),
```

- [ ] **Step 5 — Strip `locked` in `fromCanvasDesign`.** Replace the current `fromCanvasDesign` implementation (~line 243–253):
```ts
  fromCanvasDesign: design => set(() => {
    // Merge onto a full empty-faces base so a partial/legacy blob (missing a
    // face key) still yields a valid Record<Face, …> and never throws downstream.
    const faces = { ...emptyFaces(), ...(design?.faces ?? {}) }
    return {
      faces,
      colourway: design?.colourway ?? null,
      activeFace: 'front' as Face,
      selectedId: null,
    }
  }),
```
with:
```ts
  fromCanvasDesign: design => set(() => {
    // Merge onto a full empty-faces base so a partial/legacy blob (missing a
    // face key) still yields a valid Record<Face, …> and never throws downstream.
    // Strip any persisted `locked:true` so a resumed/refined design comes back
    // editable — a permanent lock must never survive into the design blob's
    // editability (the rework-unlock bug fix).
    const base = { ...emptyFaces(), ...(design?.faces ?? {}) }
    const faces = { ...emptyFaces() } as Record<Face, CanvasElement[]>
    for (const f of FACES) faces[f] = (base[f] ?? []).map(e => ({ ...e, locked: false }))
    return {
      faces,
      colourway: design?.colourway ?? null,
      activeFace: 'front' as Face,
      selectedId: null,
    }
  }),
```

- [ ] **Step 6 — Run the test (expected PASS).**
```
npx vitest run src/__tests__/canvasStoreUnlock.test.ts
```
Expected: PASS (3 tests).

- [ ] **Step 7 — Guard against regressions in the existing lock test.**
```
npx vitest run src/__tests__/canvasStoreLock.test.ts
```
Expected: PASS (3 tests) — `unlockAll`/`fromCanvasDesign` changes don't touch `lockAll`/`lockPlaced`.

- [ ] **Step 8 — Commit.**
```
git add frontend/src/store/canvasStore.ts frontend/src/__tests__/canvasStoreUnlock.test.ts
git commit -m "feat(canvas): add unlockAll + strip persisted lock in fromCanvasDesign (A2)"
```

---

### Task 2: Surface calls `unlockAll()` when the canvas re-opens for rework

**Files:**
- Modify: `frontend/src/components/DesignStudio/Surface.tsx` (finalize effect re-arm branch ~line 118–133; store selector list ~line 50–52)
- Test: `frontend/src/__tests__/surfaceRework.test.tsx` (create)

**Interfaces:**
- Consumes: `useCanvasStore(s => s.unlockAll)` (Task 1).
- Produces: on the `!triggerFinalize` re-arm branch (fires when the refine/rework flow drops `triggerFinalize` back to false after a finalize, i.e. the canvas re-opens for editing), `unlockAll()` runs so every pre-existing `locked:true` element becomes draggable/selectable again.

- [ ] **Step 1 — Write the failing Surface test.** Create `frontend/src/__tests__/surfaceRework.test.tsx`:
```tsx
import { render, act } from '@testing-library/react'
import { expect, test, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'

// jsdom has no real <canvas> 2D backend, so stub getContext with a permissive
// no-op 2D context (same shape as surfaceDirective.test.tsx) — a real Konva
// Stage otherwise can't mount.
function stubCanvasContext(): CanvasRenderingContext2D {
  const noop = () => {}
  const store: Record<string, unknown> = {}
  return new Proxy(store, {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      switch (prop) {
        case 'measureText': return () => ({ width: 0 })
        case 'createLinearGradient':
        case 'createRadialGradient': return () => ({ addColorStop: noop })
        case 'createPattern': return () => ({})
        case 'getImageData': return () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 })
        case 'canvas': return undefined
        default: return noop
      }
    },
    set(target, prop: string, value) { target[prop] = value; return true },
  }) as unknown as CanvasRenderingContext2D
}
HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

test('finalize then rework re-open unlocks every element', async () => {
  // A placed element, then finalize (locks all), then the refine flow drops
  // triggerFinalize back to false (canvas re-opens) → unlockAll must run.
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id

  useChatStore.setState({
    chatState: 'generating',
    canvasDirective: null,
    triggerFinalize: true,
  } as never)
  const { rerender } = render(<DesignStudioSurface />)
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })
  // The finalize branch locked everything.
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)

  // Rework re-open: triggerFinalize falls back to false.
  act(() => { useChatStore.setState({ triggerFinalize: false } as never) })
  rerender(<DesignStudioSurface />)

  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(false)
})
```

- [ ] **Step 2 — Run the test (expected FAIL).**
```
npx vitest run src/__tests__/surfaceRework.test.tsx
```
Expected: FAIL — after the `triggerFinalize:false` re-arm the element is still `locked:true` (nothing unlocks it yet).

- [ ] **Step 3 — Add the `unlockAll` selector.** In `frontend/src/components/DesignStudio/Surface.tsx`, alongside the existing lock selectors (~line 51–52):
```tsx
  const lockAll = useCanvasStore(s => s.lockAll)
  const lockPlaced = useCanvasStore(s => s.lockPlaced)
  const unlockAll = useCanvasStore(s => s.unlockAll)
```

- [ ] **Step 4 — Call `unlockAll()` in the re-arm branch.** In the finalize effect (~line 119–133), replace:
```tsx
    if (!triggerFinalize) {
      // Re-arm: the refine confirm step fires trigger_finalize a SECOND time.
      // Without this the ref stays true from the first finalize and the
      // re-render is silently swallowed.
      finalizeStarted.current = false
      return
    }
```
with:
```tsx
    if (!triggerFinalize) {
      // Re-arm: the refine confirm step fires trigger_finalize a SECOND time.
      // Without this the ref stays true from the first finalize and the
      // re-render is silently swallowed.
      finalizeStarted.current = false
      // Rework re-open: the canvas is editable again, but every pre-existing
      // element is still locked:true from the finalize lockAll(). Nothing else
      // ever clears it, so refined designs render non-draggable/non-selectable
      // ("not all layers are unlocked"). Unlock them here. No-op on first mount
      // (nothing placed/locked yet).
      unlockAll()
      return
    }
```

- [ ] **Step 5 — Add `unlockAll` to the effect's dependency array.** The effect currently has `// eslint-disable-next-line react-hooks/exhaustive-deps` and `}, [triggerFinalize])`. Keep the disable comment (the effect intentionally excludes `doRender`/`lockAll`) — `unlockAll` is a stable zustand action reference, so no dependency change is required and the existing `[triggerFinalize]` array stays as-is. (Do not widen the deps; the guard is deliberately keyed on `triggerFinalize` only.)

- [ ] **Step 6 — Run the test (expected PASS).**
```
npx vitest run src/__tests__/surfaceRework.test.tsx
```
Expected: PASS (1 test).

- [ ] **Step 7 — Guard the existing Surface directive suite.**
```
npx vitest run src/__tests__/surfaceDirective.test.tsx
```
Expected: PASS (6 tests) — the re-arm branch's `unlockAll()` is additive; `a second trigger_finalize re-arms and fires again` still passes (unlockAll runs alongside the ref reset, doRender still fires twice).

- [ ] **Step 8 — Commit.**
```
git add frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/surfaceRework.test.tsx
git commit -m "fix(canvas): unlock all elements when canvas re-opens for rework (A2)"
```

---

### Task 3: Universal transform controls block in `SelectedToolbar`

**Files:**
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx` (insert a transform block immediately before the reorder/duplicate/delete buttons at ~line 106)
- Test: `frontend/src/__tests__/selectedToolbarTransform.test.tsx` (create)

**Interfaces:**
- Consumes: the already-resolved `el` (`faces[activeFace].find(...)`) and `update = useCanvasStore(s => s.updateElement)`.
- Produces: rotate (`−45°` / `+45°` normalised into `[0,360)`, custom-degree input bound to `el.rotation`, Reset → `{rotation:0}`), move nudges (fixed `0.02` delta on `x`/`y`, clamped `[0,1]`), and size (text → `fontSize ×1.1 / ÷1.1` min 8; image/shape → `width`/`height ×1.1 / ÷1.1` clamped ≤1; drawings → no size buttons).

Per-type capability (from the spec):

| Type | Rotate | Move | Size |
|---|---|---|---|
| text | yes | yes | yes (`fontSize`) |
| image | yes | yes | yes (`width`/`height`) |
| shape | yes | yes | yes (`width`/`height`) |
| drawing | yes | yes | no |

- [ ] **Step 1 — Write the failing transform test.** Create `frontend/src/__tests__/selectedToolbarTransform.test.tsx`:
```tsx
import { beforeEach, describe, expect, test } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

function selectedText() {
  const s = useCanvasStore.getState()
  s.addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  s.select(id)
  return id
}

describe('SelectedToolbar transform controls', () => {
  test('+45° / −45° rotate and normalise into [0,360)', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Rotate right 45 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(45)
    // 45 - 45 - 45 wraps: click −45 twice → 45 → 0 → 315
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 45 degrees' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 45 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(315)
  })

  test('custom degree input sets rotation and Reset zeroes it', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    fireEvent.change(screen.getByLabelText('Rotation degrees'), { target: { value: '123' } })
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(123)
    fireEvent.click(screen.getByRole('button', { name: 'Reset rotation' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(0)
  })

  test('move nudges shift x/y by a fixed delta, clamped to [0,1]', () => {
    const id = selectedText() // default x=0.5, y=0.4
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Nudge right' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.x).toBeCloseTo(0.52, 5)
    fireEvent.click(screen.getByRole('button', { name: 'Nudge up' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.y).toBeCloseTo(0.38, 5)
  })

  test('size on TEXT scales fontSize (not width/height), min 8', () => {
    const id = selectedText() // default fontSize 36
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Increase size' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.fontSize).toBe(40) // round(36*1.1)
    fireEvent.click(screen.getByRole('button', { name: 'Decrease size' }))
    fireEvent.click(screen.getByRole('button', { name: 'Decrease size' }))
    // 40 -> round(40/1.1)=36 -> round(36/1.1)=33
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.fontSize).toBe(33)
  })

  test('size on an IMAGE scales width and height together', () => {
    const s = useCanvasStore.getState()
    s.addImage('http://x/a.png', 1) // square → width=height=0.4
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id)
    render(<SelectedToolbar />)
    const before = useCanvasStore.getState().faces.front[0]
    fireEvent.click(screen.getByRole('button', { name: 'Increase size' }))
    const after = useCanvasStore.getState().faces.front.find(e => e.id === id)!
    expect(after.width).toBeCloseTo(before.width * 1.1, 5)
    expect(after.height).toBeCloseTo(before.height * 1.1, 5)
  })

  test('drawings offer rotate + move but NO size buttons', () => {
    const s = useCanvasStore.getState()
    s.addDrawing([0.1, 0.1, 0.2, 0.2])
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id)
    render(<SelectedToolbar />)
    expect(screen.getByRole('button', { name: 'Rotate right 45 degrees' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Nudge right' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Increase size' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Decrease size' })).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2 — Run the test (expected FAIL).**
```
npx vitest run src/__tests__/selectedToolbarTransform.test.tsx
```
Expected: FAIL — none of the transform buttons/inputs exist yet.

- [ ] **Step 3 — Add transform helpers + the JSX block.** In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`, after the `const el = ...; if (!el) return null` guard (line 13–14) and before the `return (`, add the helper constants/functions:
```tsx
  const el = faces[activeFace].find(e => e.id === selectedId)
  if (!el) return null

  // --- Universal transform helpers (rotate / move / size) ---
  const NUDGE = 0.02
  const SIZE_FACTOR = 1.1
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
  const norm360 = (deg: number) => ((deg % 360) + 360) % 360
  const rotateBy = (delta: number) => update(el.id, { rotation: norm360((el.rotation ?? 0) + delta) })
  const nudge = (dx: number, dy: number) =>
    update(el.id, { x: clamp01((el.x ?? 0) + dx), y: clamp01((el.y ?? 0) + dy) })
  const resize = (factor: number) => {
    if (el.type === 'text') {
      update(el.id, { fontSize: Math.max(8, Math.round((el.fontSize ?? 36) * factor)) })
    } else {
      update(el.id, {
        width: clamp01((el.width ?? 0.2) * factor),
        height: clamp01((el.height ?? 0.2) * factor),
      })
    }
  }
  // Drawings have no width/height (geometry lives in `points`), matching their
  // rotate-only on-canvas Transformer — so size is not offered for them.
  const canResize = el.type !== 'drawing'
```

- [ ] **Step 4 — Insert the transform JSX before the reorder/duplicate/delete buttons.** In the same file, immediately before the line `<button onClick={() => reorder(el.id, 'up')} ...>` (~line 106), insert:
```tsx
      {/* Universal transform block — rotate / move / (size) for every element. */}
      <div className="flex items-center gap-1" role="group" aria-label="Rotate">
        <button onClick={() => rotateBy(-45)} className="px-2 py-1 text-sm border border-border rounded" title="Rotate 45° left" aria-label="Rotate left 45 degrees">⟲</button>
        <input type="number" value={Math.round(el.rotation ?? 0)} onChange={e => update(el.id, { rotation: norm360(Number(e.target.value) || 0) })}
          className="w-14 bg-base border border-border rounded px-1 py-1 text-sm text-textPrimary" aria-label="Rotation degrees" title="Rotation (degrees)" />
        <button onClick={() => rotateBy(45)} className="px-2 py-1 text-sm border border-border rounded" title="Rotate 45° right" aria-label="Rotate right 45 degrees">⟳</button>
        <button onClick={() => update(el.id, { rotation: 0 })} className="px-2 py-1 text-xs border border-border rounded" title="Reset rotation" aria-label="Reset rotation">Reset</button>
      </div>
      <div className="flex items-center gap-1" role="group" aria-label="Move">
        <button onClick={() => nudge(0, -NUDGE)} className="px-2 py-1 text-sm border border-border rounded" title="Move up" aria-label="Nudge up">↑</button>
        <button onClick={() => nudge(0, NUDGE)} className="px-2 py-1 text-sm border border-border rounded" title="Move down" aria-label="Nudge down">↓</button>
        <button onClick={() => nudge(-NUDGE, 0)} className="px-2 py-1 text-sm border border-border rounded" title="Move left" aria-label="Nudge left">←</button>
        <button onClick={() => nudge(NUDGE, 0)} className="px-2 py-1 text-sm border border-border rounded" title="Move right" aria-label="Nudge right">→</button>
      </div>
      {canResize && (
        <div className="flex items-center gap-1" role="group" aria-label="Size">
          <button onClick={() => resize(1 / SIZE_FACTOR)} className="px-2 py-1 text-sm border border-border rounded" title="Smaller" aria-label="Decrease size">−</button>
          <button onClick={() => resize(SIZE_FACTOR)} className="px-2 py-1 text-sm border border-border rounded" title="Larger" aria-label="Increase size">+</button>
        </div>
      )}
```

- [ ] **Step 5 — Run the transform test (expected PASS).**
```
npx vitest run src/__tests__/selectedToolbarTransform.test.tsx
```
Expected: PASS (6 tests).

- [ ] **Step 6 — Guard the Surface directive suite (SelectedToolbar mounts inside it).**
```
npx vitest run src/__tests__/surfaceDirective.test.tsx
```
Expected: PASS (6 tests) — the toolbar's `Text content` / `Font` aria-labels are unchanged; the transform block is additive.

- [ ] **Step 7 — Commit.**
```
git add frontend/src/components/DesignStudio/SelectedToolbar.tsx frontend/src/__tests__/selectedToolbarTransform.test.tsx
git commit -m "feat(canvas): universal rotate/move/size transform controls (A1)"
```

---

### Task 4: De-emphasise the upload button (remove highlight only)

**Files:**
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx` (the `hi` helper ~line 38–39)
- Modify: `frontend/src/__tests__/ToolRail.test.tsx` (the one existing `only allowed tool is enabled and highlighted` test uses `upload` — retarget it)
- Test: `frontend/src/__tests__/toolRailUploadHighlight.test.tsx` (create)

**Interfaces:**
- Consumes: existing `allowedTools?: Set<Tool>` and `highlightTool?: Tool | null` props (unchanged).
- Produces: `upload` never receives the accent ring + pulse classes, even when `highlightTool === 'upload'`. The button stays enabled (`toolDisabled` untouched) so the load-bearing `ask_logo_bg` unlock is preserved. Non-upload highlights (`text`, `shape`) are unaffected.

- [ ] **Step 1 — Write the failing de-highlight test.** Create `frontend/src/__tests__/toolRailUploadHighlight.test.tsx`:
```tsx
import { expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

function rail(extra: Record<string, unknown> = {}) {
  return render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      {...extra} />,
  )
}

test('upload is enabled but NOT highlighted even when highlightTool="upload"', () => {
  rail({ allowedTools: new Set(['upload']), highlightTool: 'upload' })
  const upload = screen.getByText('↑ Upload image')
  expect(upload).not.toBeDisabled()               // load-bearing unlock preserved
  expect(upload.className).not.toMatch(/animate-pulse|ring-2/) // no emphasis
})

test('a non-upload tool still highlights (text)', () => {
  rail({ allowedTools: new Set(['text']), highlightTool: 'text' })
  const text = screen.getByText('+ Add text')
  expect(text).not.toBeDisabled()
  expect(text.className).toMatch(/animate-pulse|ring-2/)
})
```

- [ ] **Step 2 — Run the test (expected FAIL).**
```
npx vitest run src/__tests__/toolRailUploadHighlight.test.tsx
```
Expected: FAIL — the first test fails because `upload` currently gets the `ring-2 … animate-pulse` classes.

- [ ] **Step 3 — Suppress the highlight for `upload` only.** In `frontend/src/components/DesignStudio/ToolRail.tsx`, replace the `hi` helper (~line 38–39):
```tsx
  const hi = (t: Tool) =>
    highlightTool === t ? ' ring-2 ring-accent ring-offset-2 ring-offset-surface animate-pulse' : ''
```
with:
```tsx
  // A3: the upload tool is intentionally NOT emphasised in the main flow — the
  // chips do the real work, and ask_logo_bg only holds the tool open (to keep
  // the just-placed logo selectable) without wanting to draw the eye to it.
  // Its `allowedTools`/`toolDisabled` behaviour is untouched (still enabled +
  // unlocked); only the ring + pulse are dropped. Other tools still highlight.
  const hi = (t: Tool) =>
    t !== 'upload' && highlightTool === t
      ? ' ring-2 ring-accent ring-offset-2 ring-offset-surface animate-pulse'
      : ''
```

- [ ] **Step 4 — Retarget the existing conflicting test.** In `frontend/src/__tests__/ToolRail.test.tsx`, the test `only allowed tool is enabled and highlighted` (~line 75–87) asserts the `upload` button carries the highlight — now false by design. Replace that test body's tool from `upload` to `text` so the "only allowed tool is enabled + highlighted" intent still holds for a highlightable tool:
```tsx
test('only allowed tool is enabled and highlighted', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      allowedTools={new Set(['text'])} highlightTool="text" />,
  )
  const text = screen.getByText('+ Add text')
  const upload = screen.getByText('↑ Upload image')
  expect(text).not.toBeDisabled()
  expect(upload).toBeDisabled()
  expect(text.className).toMatch(/animate-pulse|ring-2/)
})
```

- [ ] **Step 5 — Run both ToolRail suites (expected PASS).**
```
npx vitest run src/__tests__/toolRailUploadHighlight.test.tsx src/__tests__/ToolRail.test.tsx
```
Expected: PASS — new de-highlight suite (2 tests) + the existing ToolRail suite (retargeted test now green, all others unchanged).

- [ ] **Step 6 — Commit.**
```
git add frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/__tests__/toolRailUploadHighlight.test.tsx frontend/src/__tests__/ToolRail.test.tsx
git commit -m "feat(canvas): de-emphasise upload button highlight, keep unlock (A3)"
```

---

### Task 5: A4 wording — note only (backend-owned copy)

**Files:**
- No frontend source change. Documentation/hand-off note for the Backend agent.

**Interfaces:**
- N/A (copy strings).

- [ ] **Step 1 — Record the boundary (no code).** A4 ("uploads read as 'image or logo'") is **backend-owned** and out of scope for this frontend workstream. The Backend agent updates:
  - `backend/app/prompts.py` — `V2_TOOL_TIPS["upload"]`: "to add your logo" → "to add your image or logo".
  - `backend/app/services/conversation/canvas_steps.py` — step `ask` copy referencing "logo" where a general image is also valid (`LOGO_ADJUST`, `ASK_LOGO_BG`, `ASK_ANOTHER_LOGO` as appropriate).
  - `backend/app/services/conversation/intent_extractor.py` — `_SLOT_DOCS` logo-slot descriptions.

- [ ] **Step 2 — Confirm the frontend button label is already correct.** The on-screen tool button label in `frontend/src/components/DesignStudio/ToolRail.tsx` (line 54) is already the generic **"↑ Upload image"**, and `frontend/src/__tests__/ToolRail.test.tsx` asserts the literal `/upload image/i`. **Do not change the button label** — it stays "Upload image". No frontend code or test change is required for A4.

- [ ] **Step 3 — No commit (nothing changed in frontend).** If tracking is desired, note the hand-off in the workstream ledger / PR description; do not create an empty frontend commit.

---

## Final verification (run before handing off)

- [ ] Run the full Workstream A targeted subset (Windows-stall-safe):
```
npx vitest run src/__tests__/canvasStoreUnlock.test.ts src/__tests__/canvasStoreLock.test.ts src/__tests__/surfaceRework.test.tsx src/__tests__/surfaceDirective.test.tsx src/__tests__/selectedToolbarTransform.test.tsx src/__tests__/toolRailUploadHighlight.test.tsx src/__tests__/ToolRail.test.tsx
```
Expected: all PASS.

- [ ] Type-check / build (no new TypeScript errors):
```
npm run build
```
Expected: build succeeds.

- [ ] Report back to the orchestrator: transform controls (A1), rework-unlock fix (A2), upload de-highlight (A3) shipped with tests; A4 copy handed to the Backend agent; button label unchanged.
