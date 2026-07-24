/**
 * Centre-pivot geometry for react-konva canvas elements.
 *
 * canvasStore stores every element's `x`/`y` as the normalised (0–1)
 * TOP-LEFT of its box — that storage format is unchanged by this module.
 * What changes is how a node is POSITIONED in Konva: instead of registering
 * the node at its own top-left (offsetX/offsetY = 0, the default — which is
 * why rotating/resizing used to pivot around the top-left corner), each node
 * is registered at its own CENTRE (offsetX/offsetY = half its pixel size)
 * and positioned at that centre in pixel space. Konva always rotates/scales
 * a node around its registration point, so this makes the Transformer pivot
 * at the element's centre, exactly like every mainstream design tool.
 *
 * These are pure functions (no Konva/React import) so the geometry is
 * unit-testable without mounting a real <Stage> — jsdom has no <canvas> 2D
 * backend, so a real Konva Stage can't render in a fast, Windows-stall-safe
 * test run. `nodes.tsx` and `FaceThumbnails.tsx` both call into this module
 * so the live canvas, the face-thumbnail rail, and the flattened export
 * (which reads the SAME live Konva stage as the canvas, so it inherits this
 * automatically) all place a rotated/resized element identically.
 */

/** Half-width/half-height of a normalised box, in pixels. */
export function boxHalfExtentsPx(
  width: number,
  height: number,
  stageW: number,
  stageH: number,
): { halfW: number; halfH: number } {
  return { halfW: (width * stageW) / 2, halfH: (height * stageH) / 2 }
}

/**
 * Pixel position for a node registered at local origin (originX, originY)
 * — i.e. where to put `x`/`y` so that, combined with `offsetX=originX,
 * offsetY=originY`, the node's on-screen TOP-LEFT still lands at
 * (elX*stageW, elY*stageH) when unrotated (rotation/scale pivot at the
 * origin point without moving it).
 */
export function centerPosition(
  elX: number,
  elY: number,
  originX: number,
  originY: number,
  stageW: number,
  stageH: number,
): { x: number; y: number } {
  return { x: elX * stageW + originX, y: elY * stageH + originY }
}

/**
 * Inverse of `centerPosition`: given a node's post-drag/-transform pixel
 * position (its registration point, in the parent's coordinate space) and
 * the origin offset that was applied, recover the normalised TOP-LEFT to
 * commit back into canvasStore.
 *
 * For a PURE rotation (no scale change) the registration point never moves
 * — Konva rotates a node about its own offset point in place — so feeding
 * the unchanged pixel position + unchanged half-extents back through this
 * function reproduces the original x/y exactly. That is the geometric
 * invariant Fix 1 relies on: a placed element's committed x/y must be
 * unchanged by a pure rotation.
 */
export function topLeftFromCenterPx(
  centerXPx: number,
  centerYPx: number,
  originX: number,
  originY: number,
  stageW: number,
  stageH: number,
): { x: number; y: number } {
  return { x: (centerXPx - originX) / stageW, y: (centerYPx - originY) / stageH }
}

/**
 * Local (un-translated) bounding-box centre of a freehand drawing's flat
 * points list `[x0,y0,x1,y1,…]` (already in the same pixel units the points
 * are rendered in). A drawing has no explicit width/height — its stroke
 * extent stands in for "the box" the same way it already did for the
 * pre-Fix-1 rotate-only Transformer (see nodes.tsx `DrawingNode`).
 */
export function drawingBoundsCenter(pts: number[]): { cx: number; cy: number } {
  if (pts.length < 2) return { cx: 0, cy: 0 }
  let minX = pts[0], maxX = pts[0], minY = pts[1], maxY = pts[1]
  for (let i = 0; i < pts.length; i += 2) {
    minX = Math.min(minX, pts[i]); maxX = Math.max(maxX, pts[i])
    minY = Math.min(minY, pts[i + 1]); maxY = Math.max(maxY, pts[i + 1])
  }
  return { cx: (minX + maxX) / 2, cy: (minY + maxY) / 2 }
}

/**
 * Rough text box estimate — used as TextNode's first-paint fallback (before
 * a real Konva `getClientRect` measurement lands) and by the non-interactive
 * face thumbnails, which never mount a measurable node. Mirrors the width
 * heuristic `nodes.tsx: curvePath` already used for the curved-text arc span,
 * so straight and curved text share one estimate.
 */
export function estimateTextBox(content: string, fontSize: number): { w: number; h: number } {
  const w = Math.max(fontSize, content.length * fontSize * 0.55)
  return { w, h: fontSize * 1.2 }
}
