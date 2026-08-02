import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { render, renderHook, screen } from '@testing-library/react'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore, TEXT_PLACEHOLDER } from '../store/canvasStore'
import { useIsDesktop } from '../lib/useIsDesktop'

function setMatchMedia(matches: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true, configurable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches, media: query, onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
    })),
  })
}

describe('useIsDesktop', () => {
  afterEach(() => {
    // @ts-expect-error — restore jsdom's default (absent)
    delete window.matchMedia
  })

  it('falls back to desktop when matchMedia is absent (jsdom)', () => {
    // @ts-expect-error — jsdom ships no matchMedia
    delete window.matchMedia
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(true)
  })

  it('reports mobile when the md query does not match', () => {
    setMatchMedia(false)
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(false)
  })

  it('reports desktop when the md query matches', () => {
    setMatchMedia(true)
    const { result } = renderHook(() => useIsDesktop())
    expect(result.current).toBe(true)
  })
})

describe('SelectedToolbar variants', () => {
  beforeEach(() => {
    useCanvasStore.setState({
      faces: { front: [], back: [], left: [], right: [] },
      activeFace: 'front', selectedId: null,
    })
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
  })

  // 2026-08-02: the mobile "stacked" variant (sticky, in-flow, sharing the
  // centre column with the cap) was replaced with a fixed bottom sheet,
  // rendered through a portal to document.body — see SelectedToolbar.tsx's
  // portal comment for why a portal specifically. `sticky` is gone; the panel
  // is now `fixed` to the viewport regardless of where it sits in the flow.
  it('is FIXED to the viewport in the sheet (mobile) variant, not sticky in-flow', () => {
    render(<SelectedToolbar variant="sheet" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.className).toMatch(/(^|\s)fixed(\s|$)/)
    expect(panel.className).not.toMatch(/(^|\s)sticky(\s|$)/)
  })

  it('is NOT fixed in the rail variant — it is ordinary in-flow content in the tool rail column', () => {
    render(<SelectedToolbar variant="rail" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.className).not.toMatch(/(^|\s)fixed(\s|$)/)
    expect(panel.className).not.toMatch(/(^|\s)sticky(\s|$)/)
  })

  it('applies no height cap in the rail variant, where it competes with nothing', () => {
    render(<SelectedToolbar variant="rail" />)
    const controls = screen.getByTestId('adjust-controls')
    expect(controls.style.maxHeight).toBe('')
  })

  it('defaults to the sheet variant when no variant is given', () => {
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toMatch(/(^|\s)fixed(\s|$)/)
  })

  // I6: the rail panel mounts BELOW ToolRail inside an overflow-y-auto column
  // and takes no height cap, so on a short column it can appear at or past the
  // fold with no scroll cue — the same "selecting an element did nothing" bug
  // the placement work exists to fix.
  describe('rail variant scrolls itself into view', () => {
    const original = Element.prototype.scrollIntoView

    afterEach(() => {
      if (original) Element.prototype.scrollIntoView = original
      // @ts-expect-error — restore jsdom's default (absent on some elements)
      else delete Element.prototype.scrollIntoView
    })

    it('calls scrollIntoView({ block: "nearest" }) on mount', () => {
      const spy = vi.fn()
      Element.prototype.scrollIntoView = spy
      render(<SelectedToolbar variant="rail" />)
      expect(spy).toHaveBeenCalledWith({ block: 'nearest' })
    })

    it('does not scroll the sheet variant — it is fixed to the viewport, there is no "into view" for it to reach', () => {
      const spy = vi.fn()
      Element.prototype.scrollIntoView = spy
      render(<SelectedToolbar variant="sheet" />)
      expect(spy).not.toHaveBeenCalled()
    })

    it('mounts without throwing when scrollIntoView is absent (jsdom)', () => {
      // @ts-expect-error — jsdom leaves this undefined on some element types
      delete Element.prototype.scrollIntoView
      expect(() => render(<SelectedToolbar variant="rail" />)).not.toThrow()
    })
  })
})
