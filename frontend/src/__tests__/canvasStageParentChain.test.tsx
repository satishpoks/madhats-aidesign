import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'review_design', data: {} }),
  uploadLogo: vi.fn(),
  uploadCanvasLayouts: vi.fn(),
  finalizeCanvas: vi.fn(),
}))

import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'
import { useBrandStore } from '../store/brandStore'

// jsdom has no real <canvas> 2D backend, so a real Konva Stage can't mount at
// all without this. Same permissive no-op 2D context stub used elsewhere in
// this codebase's Konva-adjacent tests (e.g. surfaceDirective.test.tsx).
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
  useBrandStore.setState({ watermarkText: 'MADHATS PREVIEW' } as never)
})

// CanvasStage measures itself by walking UP two levels — its own root, the
// `canvas-stage-wrap` slot, then the centre column whose OTHER children (Adjust
// panel, instruction callout, Done button) are the height budget it subtracts.
// jsdom performs no layout and ships neither ResizeObserver nor
// MutationObserver, so the sizing effect is inert here and NO test can observe
// the resulting pixels. What is observable — and what actually broke — is the
// DOM chain the walk depends on, so that is what these pin.
test('the stage root is a DIRECT child of canvas-stage-wrap (its sizing walks up through it)', () => {
  useChatStore.setState({ chatState: 'canvas_design' } as never)
  render(<DesignStudioSurface />)

  const slot = screen.getByTestId('canvas-stage-slot')
  // An extra element here (e.g. wrapping CanvasStage in a `relative` div for a
  // watermark) makes `availableHeight` read the wrapper instead of the column:
  // `used` collapses to 0 (the slot is then the wrapper's only child) and
  // `col.clientHeight` becomes content-derived — the stage's own output — so
  // every measure pass shrinks it by FIT_MARGIN until it hits MIN_DISPLAY.
  expect(slot.parentElement).toBe(screen.getByTestId('canvas-stage-wrap'))
})

test('the chain survives the watermark, which stays inside the stage box and outside the Konva tree', () => {
  useChatStore.setState({ chatState: 'review_design', watermark: true } as never)
  render(<DesignStudioSurface />)

  expect(screen.getByTestId('canvas-stage-slot').parentElement)
    .toBe(screen.getByTestId('canvas-stage-wrap'))

  const mark = screen.getByTestId('canvas-watermark')
  // Still scoped to the stage box (it is `absolute inset-0`, so its positioned
  // ancestor decides what it covers) — not tiling over the whole column.
  expect(screen.getByTestId('canvas-stage-slot').contains(mark)).toBe(true)
  expect(mark.parentElement!.className).toContain('relative')
  // ...and still a plain-DOM sibling of the Konva stage rather than anything
  // inside it. `.konvajs-content` is the container div Konva itself creates and
  // the only DOM Konva rasterises from, so a watermark under it would be the
  // one thing this branch must never do: visible in stage.toDataURL(), i.e. in
  // the decorations-only layout guide the image model conditions on.
  expect(mark.closest('.konvajs-content')).toBeNull()
})
