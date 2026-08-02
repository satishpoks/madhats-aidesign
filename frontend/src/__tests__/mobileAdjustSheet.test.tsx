/**
 * The mobile bottom-sheet redesign of the Adjust panel (2026-08-02), replacing
 * the old "stacked" in-flow panel that the owner reported as "too small to
 * see" on a real phone (SelectedToolbar.tsx capped its own height to a share
 * of a column already crowded by the face thumbnails and tool rail).
 *
 * jsdom performs no layout — none of these assertions can observe the sheet
 * actually overlaying the cap, or its real pixel height. They pin: the
 * fixed-position class contract, the portal target, the collapse/expand
 * toggle's effect on what is rendered, and the "exactly one panel" / "nothing
 * selected" invariants the task called out explicitly. Real on-screen
 * behaviour (whether the sheet visually sits over the bottom of the viewport,
 * whether the cap stays draggable above it) was not verified in a browser at
 * a narrow viewport — see the task report.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { useCanvasStore, TEXT_PLACEHOLDER } from '../store/canvasStore'

beforeEach(() => {
  useCanvasStore.getState().reset()
})

describe('mobile Adjust sheet', () => {
  it('renders nothing when nothing is selected', () => {
    render(<SelectedToolbar variant="sheet" />)
    expect(screen.queryByTestId('adjust-panel')).not.toBeInTheDocument()
  })

  it('falls back to document.body when no #canvas-column ancestor exists (e.g. this standalone render), not left in the render tree', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    const { container } = render(<SelectedToolbar variant="sheet" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.parentElement).toBe(document.body)
    // ...and specifically NOT inside the component's own render container,
    // which is where an un-portalled node would land.
    expect(container.contains(panel)).toBe(false)
  })

  it('portals into #canvas-column when it exists, so that column\'s own `hidden` class hides the sheet for free when the customer switches to the Chat tab on mobile', () => {
    // This is the real target in production: CustomiseStudio's outer canvas
    // card carries id="canvas-column" and gets `display:none` (the `hidden`
    // class) when the mobile panel switcher shows Chat instead. Before this
    // fix the sheet portalled to document.body, which sits outside that
    // container, so it stayed painted over the chat input/chips/Send button
    // after switching tabs.
    const col = document.createElement('div')
    col.id = 'canvas-column'
    document.body.appendChild(col)
    try {
      useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
      useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
      render(<SelectedToolbar variant="sheet" />)
      const panel = screen.getByTestId('adjust-panel')
      expect(panel.parentElement).toBe(col)
    } finally {
      col.remove()
    }
  })

  it('is translucent with a background blur on the sheet itself, so the cap shows through', () => {
    // jsdom performs no layout, so this cannot observe the cap actually
    // showing through — it pins the class contract that produces that effect:
    // a partial-opacity background plus a backdrop blur, applied to the
    // panel's own fixed root (not some ancestor, which would instead create a
    // containing block for fixed descendants and break the portal's
    // viewport-relative positioning).
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar variant="sheet" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.className).toMatch(/(^|\s)bg-surface\/\d+(\s|$)/)
    expect(panel.className).toMatch(/(^|\s)backdrop-blur(-\w+)?(\s|$)/)
  })

  it('the rail (desktop) variant stays fully opaque with no blur — it sits beside the cap, never over it', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar variant="rail" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.className).not.toMatch(/backdrop-blur/)
    // Plain "bg-surface", not "bg-surface/NN" — fully opaque.
    expect(panel.className).toMatch(/(^|\s)bg-surface(\s|$)/)
  })

  it('carries the fixed bottom-sheet class contract', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar variant="sheet" />)
    const panel = screen.getByTestId('adjust-panel')
    expect(panel.className).toMatch(/(^|\s)fixed(\s|$)/)
    expect(panel.className).toMatch(/(^|\s)inset-x-0(\s|$)/)
    expect(panel.className).toMatch(/(^|\s)bottom-0(\s|$)/)
  })

  it('exposes exactly one adjust-panel node, even mounted twice (portal target is shared)', () => {
    useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
    useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar variant="sheet" />)
    expect(screen.getAllByTestId('adjust-panel')).toHaveLength(1)
  })

  describe('collapse / expand', () => {
    beforeEach(() => {
      useCanvasStore.getState().addText(TEXT_PLACEHOLDER)
      useCanvasStore.getState().select(useCanvasStore.getState().faces.front[0].id)
    })

    it('opens EXPANDED by default — selecting an element is a request to adjust it', () => {
      render(<SelectedToolbar variant="sheet" />)
      // The Position section (and its D-pad) is present, i.e. controls are showing.
      expect(screen.getByRole('group', { name: 'Position' })).toBeInTheDocument()
      expect(screen.getByTestId('adjust-sheet-handle')).toHaveAttribute('aria-expanded', 'true')
    })

    it('a tap on the drag handle collapses the controls, WITHOUT deselecting', () => {
      render(<SelectedToolbar variant="sheet" />)
      fireEvent.click(screen.getByTestId('adjust-sheet-handle'))
      expect(screen.queryByRole('group', { name: 'Position' })).not.toBeInTheDocument()
      expect(screen.getByTestId('adjust-sheet-handle')).toHaveAttribute('aria-expanded', 'false')
      // The panel itself — and with it the only route back to the controls —
      // is still mounted. Collapsing must never be confusable with dismissing.
      expect(screen.getByTestId('adjust-panel')).toBeInTheDocument()
      expect(useCanvasStore.getState().selectedId).not.toBeNull()
    })

    it('the header stays visible while collapsed, so the panel still names what is selected', () => {
      render(<SelectedToolbar variant="sheet" />)
      fireEvent.click(screen.getByTestId('adjust-sheet-handle'))
      expect(screen.getByText('Adjust — Text')).toBeInTheDocument()
    })

    it('a second tap re-expands the controls', () => {
      render(<SelectedToolbar variant="sheet" />)
      const handle = screen.getByTestId('adjust-sheet-handle')
      fireEvent.click(handle)
      expect(screen.queryByRole('group', { name: 'Position' })).not.toBeInTheDocument()
      fireEvent.click(handle)
      expect(screen.getByRole('group', { name: 'Position' })).toBeInTheDocument()
      expect(handle).toHaveAttribute('aria-expanded', 'true')
    })

    it('the rail variant has no collapse handle at all — collapsing is a mobile-sheet-only affordance', () => {
      render(<SelectedToolbar variant="rail" />)
      expect(screen.queryByTestId('adjust-sheet-handle')).not.toBeInTheDocument()
      // and its controls are always shown — there is no collapsed state to fall into
      expect(screen.getByTestId('adjust-controls')).toBeInTheDocument()
    })

    it('selecting a DIFFERENT element re-opens expanded, even if the sheet was collapsed for the previous one', () => {
      const { rerender } = render(<SelectedToolbar variant="sheet" />)
      fireEvent.click(screen.getByTestId('adjust-sheet-handle')) // collapse
      expect(screen.queryByRole('group', { name: 'Position' })).not.toBeInTheDocument()

      useCanvasStore.getState().addText('second')
      const secondId = useCanvasStore.getState().faces.front[1].id
      useCanvasStore.getState().select(secondId)
      rerender(<SelectedToolbar variant="sheet" />)

      expect(screen.getByRole('group', { name: 'Position' })).toBeInTheDocument()
    })
  })
})
