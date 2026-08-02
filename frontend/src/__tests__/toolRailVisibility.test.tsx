import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

function renderRail(toolsVisible?: boolean) {
  return render(
    <ToolRail
      onAddText={vi.fn()} onUploadClick={vi.fn()} onGraphicsClick={vi.fn()}
      colourways={[{ name: 'Red', hex: '#c00' }]}
      onRender={vi.fn()} rendering={false} rendered={false}
      toolsVisible={toolsVisible}
    />,
  )
}

const CONTROLS = [/add text/i, /upload image/i, /graphics/i, /draw/i, /done designing/i]

describe('ToolRail visibility', () => {
  it('renders every control when the canvas is editable', () => {
    renderRail(true)
    for (const name of CONTROLS) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Red' })).toBeInTheDocument()
  })

  it('renders NO control when the canvas is not editable', () => {
    // Disabled buttons at 50% opacity read as a broken app, not as "not yet" —
    // so they are removed from the DOM, not merely dimmed.
    renderRail(false)
    for (const name of CONTROLS) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: 'Red' })).not.toBeInTheDocument()
  })

  it('defaults to visible when the prop is omitted (v1 call shape)', () => {
    renderRail(undefined)
    expect(screen.getByRole('button', { name: /add text/i })).toBeInTheDocument()
  })

  it('keeps its width classes while empty so the cap does not resize', () => {
    // CanvasStage sizes itself from a live measurement of the centre column
    // (ResizeObserver + MutationObserver). A rail that collapsed to zero width
    // would resize the cap on every turn transition. jsdom does no layout, so
    // this pins the class tokens, not pixels.
    const { container } = renderRail(false)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain('md:w-44')
    expect(root.className).toContain('lg:w-52')
    expect(root.className).toContain('xl:w-64')
  })
})
