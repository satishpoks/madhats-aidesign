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

test('IMPORTANT 4: Draw + cap-colour are disabled in v2 even though neither is a `Tool`', () => {
  // v2 never lists "draw" or a colourway swatch in allowedTools (they aren't
  // part of the Tool union at all), so they must be gated on
  // `allowedTools !== undefined` too — not just `locked` — otherwise they
  // stay enabled through every v2 step, including ones where the backend's
  // directive is `allowed_tools: []` ("everything locked").
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked={false}
      allowedTools={new Set([])} highlightTool={null} />,
  )
  expect(screen.getByRole('button', { name: /draw/i })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Red' })).toBeDisabled()
})

test('v1 (no allowedTools, not locked): Draw + cap-colour stay enabled', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked={false} />,
  )
  expect(screen.getByRole('button', { name: /draw/i })).not.toBeDisabled()
  expect(screen.getByRole('button', { name: 'Red' })).not.toBeDisabled()
})
