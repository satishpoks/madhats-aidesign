import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

function renderRail(props: Partial<{ rendering: boolean; rendered: boolean }> = {}) {
  return render(
    <ToolRail
      onAddText={vi.fn()}
      onUploadClick={vi.fn()}
      onGraphicsClick={vi.fn()}
      colourways={[]}
      onRender={vi.fn()}
      rendering={props.rendering ?? false}
      rendered={props.rendered ?? false}
    />
  )
}

describe('ToolRail render button', () => {
  it('is enabled with label "See it rendered" by default', () => {
    renderRail({ rendering: false, rendered: false })
    const btn = screen.getByRole('button', { name: 'See it rendered' })
    expect(btn).not.toBeDisabled()
  })

  it('is disabled with label "Rendering…" while rendering', () => {
    renderRail({ rendering: true, rendered: false })
    const btn = screen.getByRole('button', { name: 'Rendering…' })
    expect(btn).toBeDisabled()
  })

  it('is disabled with label "Rendered ✓" after a successful render', () => {
    renderRail({ rendering: false, rendered: true })
    const btn = screen.getByRole('button', { name: 'Rendered ✓' })
    expect(btn).toBeDisabled()
  })
})
