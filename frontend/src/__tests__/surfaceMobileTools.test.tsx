import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

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

// jsdom has no real <canvas> 2D backend, so a react-konva Stage cannot mount
// unless getContext is stubbed. Same permissive no-op proxy the other Surface
// tests use (surfaceDirective.test.tsx, selectedToolbarPlacement.test.tsx).
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

// Same helper shape as selectedToolbarPlacement.test.tsx — jsdom ships no
// matchMedia, so useIsDesktop() falls back to `true`. Stub per-file (never in
// the shared setup.ts) to drive the phone branch.
function setMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true, configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  })
}

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

afterEach(() => {
  // @ts-expect-error — restore jsdom's default (absent), never leak into
  // another file's tests.
  delete window.matchMedia
})

function selectText() {
  const s = useCanvasStore.getState()
  s.addText('hi')
  s.select(useCanvasStore.getState().faces.front[0].id)
}

test('desktop: no floating tools button at all', () => {
  setMatchMedia(true)
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: null, showDone: true },
  } as never)
  render(<DesignStudioSurface />)
  expect(screen.queryByTestId('mobile-tools-toggle')).not.toBeInTheDocument()
})

test('mobile: the tool rail is collapsed by default and the floating button reveals/hides it', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: null, showDone: true },
  } as never)
  render(<DesignStudioSurface />)

  // Collapsed by default: the rail's own control is not reachable.
  expect(screen.queryByRole('button', { name: /upload image/i })).not.toBeInTheDocument()

  const toggle = screen.getByTestId('mobile-tools-toggle')
  fireEvent.click(toggle)
  expect(screen.getByRole('button', { name: /upload image/i })).toBeInTheDocument()

  // Toggling again hides it — the button stays around to close it back up.
  fireEvent.click(toggle)
  expect(screen.queryByRole('button', { name: /upload image/i })).not.toBeInTheDocument()
  expect(screen.getByTestId('mobile-tools-toggle')).toBeInTheDocument()
})

test('mobile: adding/selecting an element does NOT auto-open the Adjust sheet; the tools button opens it (owner fix, 2026-08-03)', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  selectText()
  const id = useCanvasStore.getState().selectedId
  expect(id).toBeTruthy()

  render(<DesignStudioSurface />)
  // Sheet stays closed even though something is selected — this is the bug
  // fix: previously the sheet auto-opened whenever `selectedId` changed,
  // which meant every element a step's tool placed (auto-selected on add)
  // sprang the sheet open unasked.
  expect(screen.queryByTestId('adjust-panel')).not.toBeInTheDocument()

  // The floating button is the only way to reveal it, and it pulses to say
  // so — this is `ask_logo_bg`'s whole discoverability story on a phone: the
  // step's copy points at the Adjust panel's "Remove background" toggle, and
  // the customer needs a reason to go looking for it.
  const toggle = screen.getByTestId('mobile-tools-toggle')
  expect(toggle.className).toMatch(/(^|\s)animate-pulse(\s|$)/)
  fireEvent.click(toggle)
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()
  expect(toggle.className).not.toMatch(/(^|\s)animate-pulse(\s|$)/)
})

test('mobile: the Adjust sheet close button hides the sheet WITHOUT deselecting, and the tools button brings it back', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  selectText()
  const id = useCanvasStore.getState().selectedId
  expect(id).toBeTruthy()

  render(<DesignStudioSurface />)
  // Sheet starts closed (see the test above) — open it explicitly first.
  fireEvent.click(screen.getByTestId('mobile-tools-toggle'))
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()

  fireEvent.click(screen.getByTestId('adjust-sheet-close'))

  // Hidden...
  expect(screen.queryByTestId('adjust-panel')).not.toBeInTheDocument()
  // ...but selection survives (this is the whole point — ask_logo_bg's toggle
  // must stay reachable, which requires the element to still be selected).
  expect(useCanvasStore.getState().selectedId).toBe(id)

  // The floating tools button is the way back.
  fireEvent.click(screen.getByTestId('mobile-tools-toggle'))
  expect(screen.getByLabelText('Text content')).toBeInTheDocument()
})

test('mobile: pulses when tools are available and hidden (REWORK_CANVAS), and stops once opened', () => {
  setMatchMedia(false)
  useCanvasStore.getState().addText('hi')
  useCanvasStore.getState().lockAll()

  useChatStore.setState({
    chatState: 'rework_canvas',
    canvasDirective: {
      allowedTools: ['upload', 'text', 'shape'], targetFace: null, autoOpen: null,
      instructions: 'Edit your design', showDone: true, unlockAll: true,
    },
  } as never)

  render(<DesignStudioSurface />)
  const toggle = screen.getByTestId('mobile-tools-toggle')
  expect(toggle.className).toMatch(/(^|\s)animate-pulse(\s|$)/)

  fireEvent.click(toggle)
  expect(toggle.className).not.toMatch(/(^|\s)animate-pulse(\s|$)/)
})

test('mobile: no pulse when there is nothing to open', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'ask_quantity',
    canvasDirective: { allowedTools: [], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  render(<DesignStudioSurface />)
  const toggle = screen.getByTestId('mobile-tools-toggle')
  expect(toggle.className).not.toMatch(/(^|\s)animate-pulse(\s|$)/)
})

test('mobile: closing the sheet, then selecting a different element, leaves it closed (owner: only the tools button opens it — not selection)', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  useCanvasStore.getState().addText('one')
  useCanvasStore.getState().addText('two')
  const [first, second] = useCanvasStore.getState().faces.front.map(e => e.id)
  useCanvasStore.getState().select(first)

  render(<DesignStudioSurface />)
  // Opened, then closed, for the first element.
  fireEvent.click(screen.getByTestId('mobile-tools-toggle'))
  expect(screen.getByTestId('adjust-panel')).toBeInTheDocument()
  fireEvent.click(screen.getByTestId('adjust-sheet-close'))
  expect(screen.queryByTestId('adjust-panel')).not.toBeInTheDocument()

  // Selecting a DIFFERENT element must not resurrect it — this is the
  // opposite of the pre-fix behaviour (which reset `mobileSheetHidden` to
  // false on every `selectedId` change).
  act(() => { useCanvasStore.getState().select(second) })
  expect(screen.queryByTestId('adjust-panel')).not.toBeInTheDocument()
})

test('mobile: once explicitly opened, the sheet stays open across a selection change (the less-surprising choice — see task report)', () => {
  setMatchMedia(false)
  useChatStore.setState({
    chatState: 'text_adjust',
    canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
  } as never)
  useCanvasStore.getState().addText('one')
  useCanvasStore.getState().addText('two')
  const [first, second] = useCanvasStore.getState().faces.front.map(e => e.id)
  useCanvasStore.getState().select(first)

  render(<DesignStudioSurface />)
  fireEvent.click(screen.getByTestId('mobile-tools-toggle'))
  expect(screen.getByTestId('adjust-panel')).toBeInTheDocument()

  // Switching to a different element while the sheet is open must not hide
  // it — the customer explicitly asked to see the panel and is plausibly
  // about to adjust the next element too.
  act(() => { useCanvasStore.getState().select(second) })
  expect(screen.getByTestId('adjust-panel')).toBeInTheDocument()
})
