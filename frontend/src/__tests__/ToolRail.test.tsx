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

test('render button reads "Done designing" and disables when locked', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false} locked
    />,
  )
  const btn = screen.getByRole('button', { name: /done designing/i })
  expect(btn).toBeDisabled()
})

test('locked disables every tool so no modification can be made', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked
    />,
  )
  expect(screen.getByRole('button', { name: /add text/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /upload image/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /graphics/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: /draw/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Red' })).toBeDisabled()
})

test('unlocked leaves the tools enabled', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
    />,
  )
  expect(screen.getByRole('button', { name: /add text/i })).not.toBeDisabled()
})

test('only allowed tool is enabled and highlighted', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      allowedTools={new Set(['upload'])} highlightTool="upload" />,
  )
  const upload = screen.getByText('↑ Upload image')
  const text = screen.getByText('+ Add text')
  expect(upload).not.toBeDisabled()
  expect(text).toBeDisabled()
  expect(upload.className).toMatch(/animate-pulse|ring-2/)
})
