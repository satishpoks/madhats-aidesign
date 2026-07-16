import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach } from 'vitest'
import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage can't mount at all. DesignStudioSurface mounts a real
// react-konva <CanvasStage>, so stub getContext the same way
// `lockedNode.test.tsx` does — a permissive no-op 2D context.
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
    set(target, prop: string, value) {
      target[prop] = value
      return true
    },
  }) as unknown as CanvasRenderingContext2D
}

HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

test('directive shows the instruction callout and Done button', () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag to move it', showDone: true },
  } as never)
  render(<DesignStudioSurface />)
  expect(screen.getByText('Drag to move it')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /done/i })).toBeInTheDocument()
})

test('v2: SelectedToolbar mounts so a selected element is editable', () => {
  // Regression: the toolbar was gated on `unlocked` (chatState === 'canvas_design'),
  // which is always false in v2 — so directive copy telling the customer to change
  // font/size/colour "in the toolbar" pointed at a toolbar that never rendered.
  // targetFace null so the face-switch effect (which clears selectedId via
  // setActiveFace) doesn't fire — the active face is already 'front' by default.
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: 'Style your text', showDone: false },
  } as never)
  // Add a text element on the active face and select it — the toolbar no-ops
  // until something is selected, so a selection is what makes it appear.
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().select(id)
  render(<DesignStudioSurface />)
  // SelectedToolbar renders these text controls (stable aria-labels).
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()
  expect(screen.getByLabelText('Font')).toBeInTheDocument()
})
