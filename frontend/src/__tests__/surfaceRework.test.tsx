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

test('mounting with nothing locked does NOT clear the current selection', () => {
  // The re-arm branch also runs on every ordinary mount (triggerFinalize starts
  // false). unlockAll() clears selectedId, so an unguarded call there would
  // deselect the element being edited and unmount SelectedToolbar with it —
  // taking the background-removal toggle (which only renders for a selected
  // element) out of reach at ask_logo_bg. It must be a true no-op until a
  // finalize has actually locked the canvas.
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().select(id)

  useChatStore.setState({
    chatState: 'canvas_design',
    canvasDirective: null,
    triggerFinalize: false,
  } as never)
  render(<DesignStudioSurface />)

  expect(useCanvasStore.getState().selectedId).toBe(id)
})
