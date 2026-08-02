import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

// Same shape as adjustPanelPlacement.test.tsx's helper — kept local to this
// file rather than shared, since each caller must remember to clean it up in
// its own afterEach (matchMedia must never leak into another file's tests).
function setMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true, configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  })
}

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

  test('bounds the controls region by MEASURING its column, not by a breakpoint class', () => {
    // The clamp used to be `max-h-[9rem] md:max-h-[45vh]`, and neither half
    // could be right: `vh` is a fraction of the VIEWPORT, but this panel lives
    // in a column shorter than the viewport by the chat and two header bars, so
    // `45vh` exceeded the region it was bounding — and the root is `sticky`, so
    // an over-cap panel stays pinned and the cap never comes back. The cap is
    // now a measured share of the parent column, which needs no breakpoint.
    selectText()
    render(<SelectedToolbar />)
    const controls = screen.getByTestId('adjust-panel').querySelector('.overflow-y-auto')
    expect(controls).toBeTruthy()
    expect(controls?.className).not.toContain('max-h-[9rem]')
    expect(controls?.className).not.toContain('45vh')
  })

  test('falls back to the MIN floor when the column reports no height (jsdom reports 0 for every element, which is exactly the degenerate case)', () => {
    // jsdom performs no layout, so `clientHeight` is 0 — the measured share is
    // 0 and the floor is what survives. That makes this the one piece of the
    // clamp arithmetic jsdom CAN verify: that a zero/unknown column can never
    // produce a zero-height, unusable controls region.
    selectText()
    render(<SelectedToolbar />)
    const controls = screen.getByTestId('adjust-panel')
      .querySelector('.overflow-y-auto') as HTMLElement
    expect(controls.style.maxHeight).toBe('72px')
  })

  test('keeps its group captions at every column width (the compact mode is gone)', () => {
    // The captions used to be hidden below a measured column width, to save
    // ~24px per group in the cramped centre column. The panel now lives in the
    // tool rail on desktop and the captions are the point of the restructure,
    // so they are unconditional.
    selectText()
    render(<SelectedToolbar />)
    const position = screen.getByRole('group', { name: 'Position' })
    const caption = Array.from(position.querySelectorAll('span'))
      .find(s => s.textContent === 'Position')
    expect(caption).toBeTruthy()
    expect(caption?.className).not.toContain('hidden')
  })

  describe('placement is viewport-dependent (2026-07-28: the panel moved into the rail on desktop)', () => {
    afterEach(() => {
      // Never let a mocked matchMedia leak into another file's tests.
      // @ts-expect-error — restore jsdom's default (absent)
      delete window.matchMedia
    })

    test('MOBILE: renders ABOVE the cap, not below it (small screens hid it under the fold)', () => {
      setMatchMedia(false)   // md query does not match -> useIsDesktop() === false
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

    test('DESKTOP: renders in the tool rail, AFTER the cap', () => {
      setMatchMedia(true)   // md query matches -> useIsDesktop() === true
      useChatStore.setState({
        chatState: 'logo_adjust',
        canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
      } as never)
      selectText()
      render(<DesignStudioSurface />)
      const panel = screen.getByTestId('adjust-panel')
      const stage = screen.getByTestId('canvas-stage-wrap')
      // DOCUMENT_POSITION_PRECEDING means `stage` comes before `panel` in the
      // document — the rail mount sits after ToolRail, in the third column.
      expect(panel.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy()
      // And it really is inside the rail column, not just later in the DOM by
      // accident. Can't anchor on a rail tool button here (Task 10: those are
      // hidden while an element is selected — this very test selects one), so
      // find the rail column directly by its own structural class instead.
      const railColumn = document.querySelector('.md\\:border-l')
      expect(railColumn?.contains(panel)).toBe(true)
    })

    test('exactly one adjust-panel node exists at a time, in both viewports', () => {
      useChatStore.setState({
        chatState: 'logo_adjust',
        canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
      } as never)
      selectText()

      setMatchMedia(false)
      const mobile = render(<DesignStudioSurface />)
      expect(screen.getAllByTestId('adjust-panel')).toHaveLength(1)
      mobile.unmount()

      setMatchMedia(true)
      const desktop = render(<DesignStudioSurface />)
      expect(screen.getAllByTestId('adjust-panel')).toHaveLength(1)
      desktop.unmount()
    })
  })
})
