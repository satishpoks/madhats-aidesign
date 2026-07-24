import { expect, test } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

function rail(extra: Record<string, unknown> = {}) {
  return render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      {...extra} />,
  )
}

test('upload is enabled but NOT highlighted even when highlightTool="upload"', () => {
  rail({ allowedTools: new Set(['upload']), highlightTool: 'upload' })
  const upload = screen.getByText('↑ Upload image')
  expect(upload).not.toBeDisabled()               // load-bearing unlock preserved
  expect(upload.className).not.toMatch(/animate-pulse|ring-2/) // no emphasis
})

test('a non-upload tool still highlights (text)', () => {
  rail({ allowedTools: new Set(['text']), highlightTool: 'text' })
  const text = screen.getByText('+ Add text')
  expect(text).not.toBeDisabled()
  expect(text.className).toMatch(/animate-pulse|ring-2/)
})
