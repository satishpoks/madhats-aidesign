import { render, screen, fireEvent, act } from '@testing-library/react'
import { expect, test, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_another_logo', data: {} }),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

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

test('clicking Done locks the just-placed element (IMPORTANT 3)', async () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag to move it', showDone: true },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  expect(useCanvasStore.getState().faces.front[0].locked).toBeFalsy()

  render(<DesignStudioSurface />)
  fireEvent.click(screen.getByRole('button', { name: /^done$/i }))

  // lockPlaced() runs synchronously inside postDone, before the (mocked)
  // sendMessage network round-trip resolves.
  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)
  // Let the mocked sendChat promise's async continuation settle inside an
  // act() so its state update doesn't land after the test body.
  await act(async () => { await new Promise(r => setTimeout(r, 0)) })
})

test('answering Done via the chat chip also locks the placed element', () => {
  // THE LOCK BUG: `LOGO_ADJUST` offers Done twice — the canvas button (which
  // runs postDone -> lockPlaced) AND a chat chip (options: ["Done"], which
  // calls sendMessage directly). Customers tap the chip, so lockPlaced never
  // ran: the chat said "Locked that in" while the logo stayed draggable.
  // Locking must follow the DIRECTIVE leaving a showDone step, not the button.
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag it', showDone: true },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id

  const { rerender } = render(<DesignStudioSurface />)
  expect(useCanvasStore.getState().faces.front[0].locked).toBeFalsy()

  // The chip reply lands: the backend moves to ask_another_logo ("Locked that
  // in") — a step with no tools and no Done.
  act(() => {
    useChatStore.setState({
      chatState: 'ask_another_logo',
      canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    } as never)
  })
  rerender(<DesignStudioSurface />)

  expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.locked).toBe(true)
})

test('v2: the stage is read-only on a step that hands over no tools', () => {
  // Surface passed `locked={isV2 ? false : !unlocked}` — hardcoded false for
  // EVERY v2 turn — so the stage stayed interactive through the quantity/
  // email/purpose questions where the directive locks all tools.
  useChatStore.setState({
    chatState: 'ask_quantity',
    canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  useCanvasStore.getState().addText('hi')
  const id = useCanvasStore.getState().faces.front[0].id
  useCanvasStore.getState().select(id)
  render(<DesignStudioSurface />)

  // No tools in play -> the element-editing toolbar must not be reachable.
  expect(screen.queryByLabelText('Text content')).not.toBeInTheDocument()
})
