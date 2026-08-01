import { useEffect, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect, Text, TextPath, Group, Line } from 'react-konva'
import { useCanvasStore, type Face, type CanvasElement } from '../../store/canvasStore'
import { getCachedImage, loadImage } from '../../lib/imageCache'
import { STAGE_W } from './CanvasStage'
import { curvePath, ShapePrimitive } from './nodes'
import {
  boxHalfExtentsPx, centerPosition, drawingBoundsCenter, estimateTextBox,
} from '../../lib/canvasGeometry'

/** Load a cached image for a thumbnail, re-rendering once it's ready. */
function useThumbImage(url: string | undefined): HTMLImageElement | null {
  const [img, setImg] = useState<HTMLImageElement | null>(() => {
    const c = url ? getCachedImage(url) : undefined
    return c && c.complete ? c : null
  })
  useEffect(() => {
    if (!url) { setImg(null); return }
    const c = getCachedImage(url)
    if (c && c.complete) { setImg(c); return }
    let cancelled = false
    loadImage(url).then(i => { if (!cancelled) setImg(i) }).catch(() => { /* nothing to paint */ })
    return () => { cancelled = true }
  }, [url])
  return img
}

/**
 * One placed element, drawn statically (non-interactive) at the requested scale.
 *
 * Centring mirrors nodes.tsx exactly (offsetX/offsetY = half the box,
 * positioned at the box centre) — this never mounts a Transformer, but
 * a rotated element still needs to render at the SAME visual position/
 * orientation here as on the live canvas (which now pivots at centre), or a
 * rotated element would visibly diverge between the two. Text uses the
 * same heuristic box estimate as the live canvas's first-paint fallback —
 * an approximation is fine here since this is a small, read-only
 * preview, never the layout guide sent to the image model (that comes from
 * the live Konva stage's real measured text box, via canvasFlatten).
 */
function ElementThumb({ el, size }: { el: CanvasElement; size: number }) {
  const TW = size, TH = size, SCALE = size / STAGE_W
  const img = useThumbImage(el.type === 'image' ? el.assetUrl : undefined)
  if (el.type === 'shape') {
    const { halfW, halfH } = boxHalfExtentsPx(el.width, el.height, TW, TH)
    const pos = centerPosition(el.x, el.y, halfW, halfH, TW, TH)
    return (
      <Group x={pos.x} y={pos.y} offsetX={halfW} offsetY={halfH} rotation={el.rotation}>
        <ShapePrimitive el={el} lw={halfW * 2} lh={halfH * 2} listening={false} strokeScale={TW / STAGE_W} />
      </Group>
    )
  }
  if (el.type === 'drawing') {
    const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * TW : p * TH))
    const { cx, cy } = drawingBoundsCenter(pts)
    const pos = centerPosition(el.x, el.y, cx, cy, TW, TH)
    return (
      <Group x={pos.x} y={pos.y} offsetX={cx} offsetY={cy} rotation={el.rotation}>
        <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={(el.strokeWidth ?? 0.01) * TW}
          lineCap="round" lineJoin="round" tension={0.5} listening={false} />
      </Group>
    )
  }
  if (el.type === 'text') {
    const fontSize = (el.fontSize ?? 36) * SCALE
    const content = el.content ?? ''
    const { w, h } = estimateTextBox(content, fontSize)
    const halfW = w / 2, halfH = h / 2
    const pos = centerPosition(el.x, el.y, halfW, halfH, TW, TH)
    const common = {
      x: pos.x, y: pos.y, offsetX: halfW, offsetY: halfH, rotation: el.rotation,
      fontSize, fontFamily: el.font ?? 'Arial', fill: el.colour ?? '#ffffff', listening: false,
    }
    const curve = el.curve ?? 0
    return curve !== 0
      ? <TextPath {...common} align="center" text={content} data={curvePath(content, fontSize, curve)} />
      : <Text {...common} text={content} />
  }
  if (!img) return null
  const { halfW, halfH } = boxHalfExtentsPx(el.width, el.height, TW, TH)
  const pos = centerPosition(el.x, el.y, halfW, halfH, TW, TH)
  return (
    <KonvaImage image={img} x={pos.x} y={pos.y}
      width={halfW * 2} height={halfH * 2} offsetX={halfW} offsetY={halfH}
      rotation={el.rotation} listening={false} />
  )
}

/**
 * Live static mini-render of a face: angle photo + colour tint + placed
 * elements, at whatever `size` the caller needs. Shared by the left-rail
 * thumbnails (64px) and the review dialog (~320px) — parameterised rather
 * than duplicated, so the two can never drift apart.
 */
export function FaceStage({ face, size, fontsTick }: { face: Face; size: number; fontsTick: number }) {
  const els = useCanvasStore(s => s.faces[face])
  const bgUrl = useCanvasStore(s => s.faceImages[face])
  const colourway = useCanvasStore(s => s.colourway)
  const bg = useThumbImage(bgUrl)
  const ordered = [...els].sort((a, b) => a.zIndex - b.zIndex)
  return (
    // fontsTick forces a redraw once web fonts finish loading (Konva won't on its own).
    <Stage width={size} height={size} listening={false} key={fontsTick} style={{ pointerEvents: 'none' }}>
      <Layer>
        {bg && <KonvaImage image={bg} width={size} height={size} listening={false} />}
        {colourway && (
          <Rect width={size} height={size} fill={colourway.hex} globalCompositeOperation="multiply" listening={false} />
        )}
        {ordered.map(el => <ElementThumb key={el.id} el={el} size={size} />)}
      </Layer>
    </Stage>
  )
}
