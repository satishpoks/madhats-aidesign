import { describe, it, test, expect, vi } from 'vitest'
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
  it('is enabled with label "Done designing" by default', () => {
    renderRail({ rendering: false, rendered: false })
    const btn = screen.getByRole('button', { name: 'Done designing' })
    expect(btn).not.toBeDisabled()
  })

  it('is disabled with label "Saving…" while rendering', () => {
    renderRail({ rendering: true, rendered: false })
    const btn = screen.getByRole('button', { name: 'Saving…' })
    expect(btn).toBeDisabled()
  })

  it('is disabled with label "Design saved ✓" after a successful render', () => {
    renderRail({ rendering: false, rendered: true })
    const btn = screen.getByRole('button', { name: 'Design saved ✓' })
    expect(btn).toBeDisabled()
  })
})

test('render button reads "Done designing" and disables when disabled', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false} disabled
    />,
  )
  const btn = screen.getByRole('button', { name: /done designing/i })
  expect(btn).toBeDisabled()
})
