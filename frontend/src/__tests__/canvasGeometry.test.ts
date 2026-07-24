import { describe, expect, test } from 'vitest'
import {
  boxHalfExtentsPx,
  centerPosition,
  topLeftFromCenterPx,
  drawingBoundsCenter,
  estimateTextBox,
} from '../lib/canvasGeometry'

const STAGE_W = 480
const STAGE_H = 480

describe('canvasGeometry — centre-pivot invariants (FIX 1)', () => {
  test('boxHalfExtentsPx is exactly half the pixel box (offsetX/offsetY invariant)', () => {
    const { halfW, halfH } = boxHalfExtentsPx(0.3, 0.12, STAGE_W, STAGE_H)
    expect(halfW).toBeCloseTo((0.3 * STAGE_W) / 2, 6)
    expect(halfH).toBeCloseTo((0.12 * STAGE_H) / 2, 6)
    // The literal invariant the Konva nodes rely on: offsetX === width/2.
    expect(halfW * 2).toBeCloseTo(0.3 * STAGE_W, 6)
    expect(halfH * 2).toBeCloseTo(0.12 * STAGE_H, 6)
  })

  test('centerPosition places the node at the box centre in pixel space', () => {
    const { halfW, halfH } = boxHalfExtentsPx(0.2, 0.1, STAGE_W, STAGE_H)
    const { x, y } = centerPosition(0.4, 0.5, halfW, halfH, STAGE_W, STAGE_H)
    // top-left (0.4*480, 0.5*480) + half extents = centre
    expect(x).toBeCloseTo(0.4 * STAGE_W + halfW, 6)
    expect(y).toBeCloseTo(0.5 * STAGE_H + halfH, 6)
  })

  test('topLeftFromCenterPx is the exact inverse of centerPosition (round-trip)', () => {
    const { halfW, halfH } = boxHalfExtentsPx(0.25, 0.15, STAGE_W, STAGE_H)
    const centre = centerPosition(0.33, 0.61, halfW, halfH, STAGE_W, STAGE_H)
    const back = topLeftFromCenterPx(centre.x, centre.y, halfW, halfH, STAGE_W, STAGE_H)
    expect(back.x).toBeCloseTo(0.33, 6)
    expect(back.y).toBeCloseTo(0.61, 6)
  })

  test('PURE ROTATION invariant: a rotation-only transform leaves stored x/y unchanged', () => {
    // Simulates nodes.tsx's onTransformEnd for a drag that only rotated
    // (scaleX===scaleY===1, so width/height/half-extents are unchanged) —
    // node.x()/node.y() (the pivot) never move during a pure rotation, so
    // converting the SAME centre back to top-left must reproduce the
    // original stored x/y exactly (mirrors the geometric claim in the task).
    const elX = 0.42, elY = 0.17, elW = 0.3, elH = 0.2
    const { halfW, halfH } = boxHalfExtentsPx(elW, elH, STAGE_W, STAGE_H)
    const centreBefore = centerPosition(elX, elY, halfW, halfH, STAGE_W, STAGE_H)
    // "Rotate" happens on the Konva node in place — centre pixel position is
    // untouched by rotation (only .rotation() changes), so re-deriving from
    // the SAME centre must give back the original top-left.
    const after = topLeftFromCenterPx(centreBefore.x, centreBefore.y, halfW, halfH, STAGE_W, STAGE_H)
    expect(after.x).toBeCloseTo(elX, 9)
    expect(after.y).toBeCloseTo(elY, 9)
  })

  test('a centred resize keeps the centre fixed but moves the stored top-left', () => {
    // Box shrinks symmetrically about its centre (centeredScaling) — the
    // pixel centre is unchanged, but el.x/el.y (top-left) must shift.
    const elX = 0.5, elY = 0.5, elW = 0.4, elH = 0.4
    const before = boxHalfExtentsPx(elW, elH, STAGE_W, STAGE_H)
    const centre = centerPosition(elX, elY, before.halfW, before.halfH, STAGE_W, STAGE_H)
    const newW = 0.2, newH = 0.2 // scaled down by half, still centred
    const after = boxHalfExtentsPx(newW, newH, STAGE_W, STAGE_H)
    const newTopLeft = topLeftFromCenterPx(centre.x, centre.y, after.halfW, after.halfH, STAGE_W, STAGE_H)
    // Centre stayed put -> top-left moved inward by (oldHalf - newHalf).
    expect(newTopLeft.x).toBeCloseTo(elX + (before.halfW - after.halfW) / STAGE_W, 6)
    expect(newTopLeft.y).toBeCloseTo(elY + (before.halfH - after.halfH) / STAGE_H, 6)
  })

  test('drag commit: node dragged to a new centre resolves to the matching top-left', () => {
    const elW = 0.3, elH = 0.2
    const { halfW, halfH } = boxHalfExtentsPx(elW, elH, STAGE_W, STAGE_H)
    // Simulate a drag that lands the node's centre at pixel (200, 150).
    const dragged = topLeftFromCenterPx(200, 150, halfW, halfH, STAGE_W, STAGE_H)
    // Round-trip: feeding that top-left back through centerPosition must
    // reproduce the dragged-to pixel centre.
    const back = centerPosition(dragged.x, dragged.y, halfW, halfH, STAGE_W, STAGE_H)
    expect(back.x).toBeCloseTo(200, 6)
    expect(back.y).toBeCloseTo(150, 6)
  })

  test('drawingBoundsCenter finds the midpoint of a stroke\'s bounding box', () => {
    // points: (0,0) (10,0) (10,20) — bbox x:[0,10] y:[0,20] -> centre (5,10)
    const { cx, cy } = drawingBoundsCenter([0, 0, 10, 0, 10, 20])
    expect(cx).toBe(5)
    expect(cy).toBe(10)
  })

  test('drawingBoundsCenter handles a degenerate/empty stroke without throwing', () => {
    expect(drawingBoundsCenter([])).toEqual({ cx: 0, cy: 0 })
  })

  test('estimateTextBox scales with content length and font size', () => {
    const short = estimateTextBox('hi', 36)
    const long = estimateTextBox('hello world this is longer', 36)
    expect(long.w).toBeGreaterThan(short.w)
    expect(short.h).toBeCloseTo(36 * 1.2, 6)
    // Never narrower than the font size itself (single/short glyphs).
    expect(short.w).toBeGreaterThanOrEqual(36)
  })
})
