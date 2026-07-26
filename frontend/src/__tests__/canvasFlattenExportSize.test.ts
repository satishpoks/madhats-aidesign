import { describe, expect, test, vi } from 'vitest'
import type Konva from 'konva'
import { EXPORT_EDGE_PX, flattenFull, flattenStage } from '../lib/canvasFlatten'

/**
 * The on-screen stage is sized to the viewport (CanvasStage scales the fixed 480
 * logical space to fit), so the flatten exports MUST derive their pixelRatio
 * from the stage's live width. With the old hardcoded `2`, a customer on a short
 * laptop would send the image model a 560px layout guide while a desktop sent
 * 1120px — the same design at two different resolutions.
 */
function fakeStage(width: number) {
  const toDataURL = vi.fn(() => 'data:image/png;base64,AA==')
  return {
    width: () => width,
    find: () => [],
    draw: vi.fn(),
    toDataURL,
  } as unknown as Konva.Stage & { toDataURL: ReturnType<typeof vi.fn> }
}

describe('flatten export resolution', () => {
  test.each([280, 339, 480, 560])('is %ipx on screen but always EXPORT_EDGE_PX out', w => {
    const stage = fakeStage(w)
    flattenStage(stage)
    const ratio = (stage.toDataURL as ReturnType<typeof vi.fn>).mock.calls[0][0].pixelRatio
    expect(ratio * w).toBeCloseTo(EXPORT_EDGE_PX, 6)
  })

  test('the WYSIWYG preview export is pinned to the same edge', () => {
    const stage = fakeStage(339)
    flattenFull(stage)
    const ratio = (stage.toDataURL as ReturnType<typeof vi.fn>).mock.calls[0][0].pixelRatio
    expect(ratio * 339).toBeCloseTo(EXPORT_EDGE_PX, 6)
  })

  test('an explicit pixelRatio still wins', () => {
    const stage = fakeStage(339)
    flattenStage(stage, 3)
    expect((stage.toDataURL as ReturnType<typeof vi.fn>).mock.calls[0][0].pixelRatio).toBe(3)
  })

  test('a stage that reports no width falls back to the 480 logical space', () => {
    const stage = fakeStage(0)
    flattenStage(stage)
    expect((stage.toDataURL as ReturnType<typeof vi.fn>).mock.calls[0][0].pixelRatio).toBe(EXPORT_EDGE_PX / 480)
  })
})
