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

  it('is sticky in the stacked (mobile) variant, where it shares a column with the cap', () => {
    render(<SelectedToolbar variant="stacked" />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })

  it('is NOT sticky in the rail variant — the rail column scrolls itself', () => {
    render(<SelectedToolbar variant="rail" />)
    expect(screen.getByTestId('adjust-panel').className).not.toContain('sticky')
  })

  it('applies no height cap in the rail variant, where it competes with nothing', () => {
    render(<SelectedToolbar variant="rail" />)
    const controls = screen.getByTestId('adjust-controls')
    expect(controls.style.maxHeight).toBe('')
  })

  it('defaults to stacked when no variant is given', () => {
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })
})
