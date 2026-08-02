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

test('only the allowed tool renders (the rest are absent, not merely disabled) and it is highlighted', () => {
  // A disabled column of every other tool next to the one live tool reads as
  // broken chrome — especially on mobile, where the rail is a sibling stacked
  // below the canvas and every dead button's height comes straight out of
  // the cap. v2 (allowedTools set) renders ONLY the tools the step offers.
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      allowedTools={new Set(['text'])} highlightTool="text" />,
  )
  const text = screen.getByText('+ Add text')
  expect(text).not.toBeDisabled()
  expect(text.className).toMatch(/animate-pulse|ring-2/)
  expect(screen.queryByText('↑ Upload image')).not.toBeInTheDocument()
  expect(screen.queryByText('◈ Graphics')).not.toBeInTheDocument()
})

test('IMPORTANT 4: Draw + cap-colour are ABSENT in v2 even though neither is a `Tool`', () => {
  // v2 never lists "draw" or a colourway swatch in allowedTools (they aren't
  // part of the Tool union at all), so they must be gated on
  // `allowedTools !== undefined` too — not just `locked` — otherwise they
  // render (previously: enabled; now: hidden is correct either way) through
  // every v2 step, including ones where the backend's directive is
  // `allowed_tools: []` ("everything locked").
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked={false}
      allowedTools={new Set([])} highlightTool={null} />,
  )
  expect(screen.queryByRole('button', { name: /draw/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Red' })).not.toBeInTheDocument()
})

test('v2 with an empty allowed set renders no tool buttons and no render button', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked={false} hideRender
      allowedTools={new Set([])} highlightTool={null} />,
  )
  expect(screen.queryByRole('button', { name: /add text/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /upload image/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /graphics/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /draw/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Red' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /done designing|design saved/i })).not.toBeInTheDocument()
})

test('v2 with allowedTools={upload}: only Upload image renders; render button absent (mirrors Surface hideRender={isV2})', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked={false} hideRender
      allowedTools={new Set(['upload'])} highlightTool={null} />,
  )
  expect(screen.getByRole('button', { name: /upload image/i })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /upload image/i })).not.toBeDisabled()
  expect(screen.queryByRole('button', { name: /add text/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /graphics/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /draw/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Red' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /done designing|design saved/i })).not.toBeInTheDocument()
})

test('v1 (allowedTools undefined) renders every control, still disabled when locked — v1 is untouched', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[{ name: 'Red', hex: '#c00' }]} onRender={() => {}}
      rendering={false} rendered={false} locked
    />,
  )
  for (const name of [/add text/i, /upload image/i, /graphics/i, /draw/i, /done designing/i]) {
    const btn = screen.getByRole('button', { name })
    expect(btn).toBeInTheDocument()
    expect(btn).toBeDisabled()
  }
  const red = screen.getByRole('button', { name: 'Red' })
  expect(red).toBeInTheDocument()
  expect(red).toBeDisabled()
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
