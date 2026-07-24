import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach } from 'vitest'
import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'

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
})

test('an unlocked, selected, rotated text element mounts through Surface without throwing (FIX 1 centre-pivot wired end to end)', () => {
  useChatStore.setState({ chatState: 'canvas_design' } as never)
  const s = useCanvasStore.getState()
  s.addText('hello')
  const id = useCanvasStore.getState().faces.front[0].id
  // A non-zero rotation exercises the centre-pivot render path (offsetX/Y,
  // centerPosition) end to end, not just the identity (rotation===0) case.
  s.updateElement(id, { rotation: 30 })
  s.select(id)

  expect(() => render(<DesignStudioSurface />)).not.toThrow()

  // The pre-existing transform groups still render (Fix 1 must not disturb them).
  expect(screen.getByRole('group', { name: 'Rotate' })).toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Move' })).toBeInTheDocument()
  expect(screen.getByRole('group', { name: 'Size' })).toBeInTheDocument()
})

test('a rotated shape and a rotated drawing also mount cleanly (all four node types exercised)', () => {
  useChatStore.setState({ chatState: 'canvas_design' } as never)
  const s = useCanvasStore.getState()
  s.addShape('star')
  const shapeId = useCanvasStore.getState().faces.front[0].id
  s.updateElement(shapeId, { rotation: 60 })
  s.addDrawing([0.1, 0.1, 0.3, 0.15, 0.2, 0.3])
  const drawId = useCanvasStore.getState().faces.front[1].id
  s.updateElement(drawId, { rotation: 15 })

  expect(() => render(<DesignStudioSurface />)).not.toThrow()
})

test('a rotated image element also mounts cleanly', () => {
  useChatStore.setState({ chatState: 'canvas_design' } as never)
  const s = useCanvasStore.getState()
  s.addImage('http://x/a.png', 1.5)
  const id = useCanvasStore.getState().faces.front[0].id
  s.updateElement(id, { rotation: 200 })
  s.select(id)

  expect(() => render(<DesignStudioSurface />)).not.toThrow()
})
