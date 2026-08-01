import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ReviewDialog } from '../components/DesignStudio/ReviewDialog'
import { useCanvasStore } from '../store/canvasStore'

// jsdom has no real <canvas> 2D backend (the `canvas` npm package isn't
// installed here), so `HTMLCanvasElement.getContext('2d')` returns null and a
// real Konva Stage (rendered here via FaceStage) can't mount at all. Same
// permissive no-op 2D context stub used elsewhere in this codebase's
// Konva-adjacent tests (e.g. watermark.test.tsx, faceStage.test.tsx,
// designStudioCenterPivotSmoke.test.tsx).
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

function seedTwoDecoratedFaces() {
  useCanvasStore.setState({
    faces: {
      front: [{ id: 'a', type: 'text', content: 'MADHATS', x: 0.3, y: 0.3,
                width: 0.3, height: 0.1, rotation: 0, zIndex: 0 }],
      back:  [{ id: 'b', type: 'text', content: 'EST 1998', x: 0.3, y: 0.3,
                width: 0.3, height: 0.1, rotation: 0, zIndex: 0 }],
      left: [], right: [],
    } as never,
  })
}

describe('ReviewDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <ReviewDialog open={false} onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows only the decorated faces, each watermarked', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByText('Front')).toBeInTheDocument()
    expect(screen.getByText('Back')).toBeInTheDocument()
    // An undecorated face is just the blank product photo — nothing to review.
    expect(screen.queryByText('Left')).not.toBeInTheDocument()
    expect(screen.getAllByTestId('canvas-watermark')).toHaveLength(2)
  })

  it('is an accessible modal', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    const dlg = screen.getByRole('dialog')
    expect(dlg).toHaveAttribute('aria-modal', 'true')
    expect(dlg).toHaveAccessibleName()
  })

  it('mirrors the two review chips', () => {
    seedTwoDecoratedFaces()
    const onConfirm = vi.fn(); const onRework = vi.fn()
    render(<ReviewDialog open onConfirm={onConfirm} onRework={onRework} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Looks great, send it' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: "I'd like to rework it" }))
    expect(onRework).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape', () => {
    seedTwoDecoratedFaces()
    const onClose = vi.fn()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('closes when the backdrop itself is clicked', () => {
    seedTwoDecoratedFaces()
    const onClose = vi.fn()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={onClose} />)
    // The backdrop is the dialog panel's parent — the fixed inset-0 overlay.
    const backdrop = screen.getByRole('dialog').parentElement!
    fireEvent.click(backdrop)
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not close when a click inside the panel bubbles to the backdrop', () => {
    seedTwoDecoratedFaces()
    const onClose = vi.fn()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={onClose} />)
    // A click that originates INSIDE the panel (not on the backdrop itself)
    // must not be read as a backdrop dismiss, even though it bubbles through
    // the same handler.
    fireEvent.click(screen.getByRole('dialog'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('closes via the visible header close control — the only dismiss path on a phone', () => {
    seedTwoDecoratedFaces()
    const onClose = vi.fn()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={onClose} />)
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('is full-bleed on a phone and a centred panel from md', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    const panel = screen.getByRole('dialog')
    expect(panel.className).toContain('h-full')
    expect(panel.className).toContain('w-full')
    expect(panel.className).toContain('md:h-auto')
    expect(panel.className).toContain('md:max-w-3xl')
  })

  it('escapes a faded ancestor instead of rendering at half opacity', () => {
    // In the app this mounts inside DesignStudioSurface, which sits inside
    // CustomiseStudio's `canvas-column-content` — and that wrapper carries
    // RESTING_CONTENT (`opacity-50`) whenever the canvas is the resting half.
    // At review_design the directive hands over no tool, so useActiveSurface
    // always answers 'chat': the canvas column is ALWAYS resting while this
    // dialog is open.
    //
    // CSS composites an `opacity < 1` subtree as a GROUP, `position: fixed`
    // descendants included, so in place the backdrop rendered at ~30%, the
    // panel was see-through onto the studio behind it, and the per-face
    // watermark — already rgb(255 255 255 / 0.42) under mix-blend-overlay —
    // was halved again on the very surface this gate exists to watermark.
    // jsdom does no compositing, so the only observable, falsifiable form of
    // that is the containment relationship: the dialog must not be a
    // descendant of the faded wrapper.
    seedTwoDecoratedFaces()
    render(
      <div data-testid="resting-wrapper" className="opacity-50">
        <ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />
      </div>,
    )
    const faded = screen.getByTestId('resting-wrapper')
    const panel = screen.getByRole('dialog')
    const backdrop = panel.parentElement!

    expect(faded.contains(panel)).toBe(false)
    // The backdrop too — it is the element carrying bg-black/60, so fading it
    // is what let the studio show through.
    expect(faded.contains(backdrop)).toBe(false)
    // Portalled, not simply unrendered: it is still on screen.
    expect(document.body.contains(panel)).toBe(true)
    expect(screen.getAllByTestId('canvas-watermark').length).toBeGreaterThan(0)
  })
})
