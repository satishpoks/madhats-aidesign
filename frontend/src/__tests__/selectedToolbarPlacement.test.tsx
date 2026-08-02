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

  test('its root is FIXED to the viewport (the sheet), not sticky in-flow', () => {
    // 2026-08-02: the default variant changed from the old in-flow "stacked"
    // panel (sticky, sharing the centre column with the cap) to a fixed
    // bottom sheet — see SelectedToolbar's variant doc comment.
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toMatch(/(^|\s)fixed(\s|$)/)
  })

  test('carries shrink-0 regardless of variant (retained defensively; not load-bearing for the fixed sheet)', () => {
    // History: this class mattered when the mobile panel was in-flow inside
    // the centre column's flex column (the pre-2026-08-02 "stacked" variant) —
    // without it, the flex algorithm squashed the panel down to near-zero
    // height beside the fixed-size Konva stage (it rendered as a ~2px accent
    // line in the browser). The sheet variant is now `position: fixed` and
    // portalled to `document.body`, so it is no longer a flex participant at
    // all and cannot be squashed regardless of this class — it is kept for
    // parity with the rail variant's classes, which must stay byte-identical
    // to before this change.
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('shrink-0')
  })

  test('bounds the controls region with a viewport-relative (vh) class — correct now that the sheet is position:fixed', () => {
    // 2026-08-02: this used to be the opposite assertion, for the old in-flow
    // "stacked" variant — `vh` was WRONG there because that panel shared a
    // column shorter than the viewport (the chat + two header bars), so a flat
    // 45vh cap exceeded the region it was meant to bound, and the sticky root
    // kept it pinned so the cap never came back. The sheet variant is
    // `position: fixed` and portalled to `document.body` — it is no longer
    // constrained by any ancestor column at all, it IS sized against the
    // viewport, so `vh` is now the correct unit rather than the wrong one.
    // There is nothing left to MEASURE (no ResizeObserver over a parent
    // column), which is why this is a plain Tailwind class rather than an
    // inline style computed in an effect.
    selectText()
    render(<SelectedToolbar variant="sheet" />)
    const controls = screen.getByTestId('adjust-controls')
    expect(controls.className).toMatch(/max-h-\[\d+vh\]/)
  })

  test('the rail variant applies no vh-based cap either — its column scrolls itself, same as before', () => {
    selectText()
    render(<SelectedToolbar variant="rail" />)
    const controls = screen.getByTestId('adjust-controls')
    expect(controls.className).not.toMatch(/max-h-\[\d+vh\]/)
    expect(controls.style.maxHeight).toBe('')
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

    test('MOBILE: renders as a FIXED bottom sheet, not in-flow above the cap (2026-08-02 redesign)', () => {
      // Superseded assertion, kept as history: this used to check DOM ORDER
      // (panel precedes the cap) because the old "stacked" panel was in-flow,
      // sticky at the top of the centre column, so document order was visual
      // order. The sheet variant is `position: fixed` and rendered through a
      // portal straight into `document.body` — document order no longer
      // reflects on-screen position at all (a `fixed` element's box is
      // computed from the viewport, not from where it sits in the tree). What
      // is verifiable in jsdom (which performs no layout) is the mechanism
      // that makes the overlay work: the fixed positioning classes, and that
      // it is NOT nested inside the cap's own wrapper (portalled out).
      setMatchMedia(false)   // md query does not match -> useIsDesktop() === false
      useChatStore.setState({
        chatState: 'logo_adjust',
        canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
      } as never)
      selectText()
      render(<DesignStudioSurface />)
      const panel = screen.getByTestId('adjust-panel')
      const stage = screen.getByTestId('canvas-stage-wrap')
      expect(panel.className).toMatch(/(^|\s)fixed(\s|$)/)
      expect(panel.className).toMatch(/(^|\s)bottom-0(\s|$)/)
      expect(stage.contains(panel)).toBe(false)
      // Portalled straight to document.body, not left as a child of the
      // centre column — the correctness reason (not just styling) is in
      // SelectedToolbar's portal comment: CanvasStage.availableHeight sums
      // each sibling's real getBoundingClientRect().height, which a `fixed`
      // element still reports non-zero even though it occupies no flow space,
      // so leaving it as a `col` child would still shrink the cap's budget.
      expect(panel.parentElement).toBe(document.body)
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
