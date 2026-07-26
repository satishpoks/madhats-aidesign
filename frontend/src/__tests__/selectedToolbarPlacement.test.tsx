import { beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_another_logo', data: {} }),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useCanvasStore } from '../store/canvasStore'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'

// jsdom has no real <canvas> 2D backend, so a react-konva Stage cannot mount
// unless getContext is stubbed. Same permissive no-op proxy surfaceDirective.test.tsx uses.
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
  useCanvasStore.getState().reset()
  useChatStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

function selectText() {
  const s = useCanvasStore.getState()
  s.addText('hi')
  s.select(useCanvasStore.getState().faces.front[0].id)
}

describe('Adjust panel', () => {
  test('is titled for the selected element type', () => {
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByText('Adjust — Text')).toBeInTheDocument()
  })

  test('titles an image element as Image', () => {
    const s = useCanvasStore.getState()
    s.addImage('http://x/a.png', 1)
    s.select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar />)
    expect(screen.getByText('Adjust — Image')).toBeInTheDocument()
  })

  test('its root is sticky so it stays visible while the canvas column scrolls', () => {
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })

  test('its root does not shrink in the flex column (jsdom performs no layout, so this pins the class that prevents the collapse rather than the collapse itself)', () => {
    // The centre column in Surface.tsx is a flex column whose other child, the
    // canvas-stage wrapper, contains a fixed-size Konva stage that resists
    // shrinking. Flex items default to shrink:1, so without `shrink-0` the
    // flex algorithm squashes this panel — the shrinkable sibling — down to
    // near-zero height (it rendered as a ~2px accent line in the browser).
    // jsdom never runs layout, so no test here can observe the squashed
    // height directly; this pins the class responsible instead.
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('shrink-0')
  })

  test('bounds the controls region tightly on mobile, roomier on desktop (jsdom performs no layout, so this pins the classes rather than the rendered height)', () => {
    selectText()
    render(<SelectedToolbar />)
    const controls = screen.getByTestId('adjust-panel').querySelector('.overflow-y-auto')
    expect(controls?.className).toContain('max-h-[9rem]')
    expect(controls?.className).toContain('md:max-h-[45vh]')
  })

  test('renders ABOVE the cap, not below it (small screens hid it under the fold)', () => {
    useChatStore.setState({
      chatState: 'logo_adjust',
      canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    } as never)
    selectText()
    render(<DesignStudioSurface />)
    const panel = screen.getByTestId('adjust-panel')
    const stage = screen.getByTestId('canvas-stage-wrap')
    // DOCUMENT_POSITION_FOLLOWING means `stage` comes after `panel` in the document.
    expect(panel.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
