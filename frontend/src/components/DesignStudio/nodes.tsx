import { useRef, useEffect, useLayoutEffect, useState } from 'react'
import {
  Text, TextPath, Image as KonvaImage, Transformer, Group,
  Rect, Ellipse, RegularPolygon, Star, Line, Arrow,
} from 'react-konva'
import type Konva from 'konva'
import { type CanvasElement, LINE_SHAPES } from '../../store/canvasStore'
import { getCachedImage, loadImage } from '../../lib/imageCache'
import { ensureFont } from '../../lib/fonts'
import {
  boxHalfExtentsPx, centerPosition, topLeftFromCenterPx, drawingBoundsCenter, estimateTextBox,
} from '../../lib/canvasGeometry'

interface NodeProps {
  el: CanvasElement
  stageW: number
  stageH: number
  isSelected: boolean
  onSelect: () => void
  onChange: (patch: Partial<CanvasElement>) => void
}

function useTransformer(isSelected: boolean) {
  const shapeRef = useRef<Konva.Node>(null)
  const trRef = useRef<Konva.Transformer>(null)
  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current])
      trRef.current.getLayer()?.batchDraw()
    }
  }, [isSelected])
  return { shapeRef, trRef }
}

export function TextNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)

  const content = el.content ?? ''
  const fontSize = el.fontSize ?? 36
  const fontFamily = el.font ?? 'Arial'
  const fill = el.colour ?? '#ffffff'
  const curve = el.curve ?? 0

  // Konva paints with whatever the browser has loaded; when the family changes
  // (esp. a Google font that may still be loading), wait for it, then redraw so
  // the glyphs aren't stuck in a fallback face.
  useEffect(() => {
    let cancelled = false
    void ensureFont(fontFamily).then(() => {
      if (!cancelled) shapeRef.current?.getLayer()?.batchDraw()
    })
    return () => { cancelled = true }
  }, [fontFamily, shapeRef])

  const locked = !!el.locked

  // Text auto-sizes to its glyphs, so (unlike shape/image) there's no stored
  // width/height to pivot around. Seed with a heuristic (matches the curved-
  // text arc-span estimate) so the very first paint is already close, then
  // correct it to Konva's real measured bounds once the node is mounted —
  // this measured box is what offsetX/offsetY (the rotate/resize pivot) uses.
  const [box, setBox] = useState(() => estimateTextBox(content, fontSize))
  useLayoutEffect(() => {
    const node = shapeRef.current
    if (!node) return
    const rect = node.getClientRect({ skipTransform: true })
    if (rect.width && rect.height
      && (Math.abs(rect.width - box.w) > 0.5 || Math.abs(rect.height - box.h) > 0.5)) {
      setBox({ w: rect.width, h: rect.height })
    }
    // Re-measure whenever the glyphs/layout that determine the box change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [content, fontSize, fontFamily, curve])

  const halfW = box.w / 2
  const halfH = box.h / 2
  const pos = centerPosition(el.x, el.y, halfW, halfH, stageW, stageH)

  const common = {
    ref: shapeRef as never,
    x: pos.x,
    y: pos.y,
    offsetX: halfW,
    offsetY: halfH,
    rotation: el.rotation,
    fontSize,
    fontFamily,
    fill,
    draggable: !locked,
    onClick: locked ? undefined : onSelect,
    onTap: locked ? undefined : onSelect,
    onDragEnd: (e: Konva.KonvaEventObject<DragEvent>) =>
      onChange(topLeftFromCenterPx(e.target.x(), e.target.y(), halfW, halfH, stageW, stageH)),
    onTransformEnd: (e: Konva.KonvaEventObject<Event>) => {
      const node = e.target as Konva.Text
      // A pure rotation (scaleX===1) leaves node.x()/y() unchanged — they're
      // the pivot — so this reproduces the original x/y exactly; a resize
      // (which changes fontSize, hence the box, next render) recomputes the
      // top-left from the CURRENT half-extents so the centre stays fixed.
      onChange({
        rotation: node.rotation(),
        fontSize: Math.max(8, fontSize * node.scaleX()),
        ...topLeftFromCenterPx(node.x(), node.y(), halfW, halfH, stageW, stageH),
      })
      node.scaleX(1); node.scaleY(1)
    },
  }

  return (
    <Group>
      {curve !== 0 ? (
        // Text along a quadratic-bezier arc. The path spans the approximate text
        // width; a positive curve lifts the mid control point (arch up), negative
        // drops it (arch down). `align="center"` makes Konva centre the glyphs on
        // the path using their real measured width, so the text sits symmetrically
        // over the arc's peak instead of skewing to the left when our width
        // estimate overshoots.
        <TextPath {...common} align="center" text={content} data={curvePath(content, fontSize, curve)} />
      ) : (
        <Text {...common} text={content} />
      )}
      {isSelected && !locked && (
        <Transformer
          ref={trRef as never}
          enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
          rotateEnabled
          centeredScaling
        />
      )}
    </Group>
  )
}

// ---------------------------------------------------------------------------
// Vector shapes (the built-in "Clipart" palette) — recolourable, no images.
// ---------------------------------------------------------------------------

/**
 * Render a shape at local box [0..lw, 0..lh]. Reused by the canvas + thumbnails.
 * `strokeScale` (= thumbnailSize / stageSize) keeps border thickness + arrowheads
 * PROPORTIONAL when drawn small — strokeWidth is in absolute px, so a thumbnail
 * must scale it down to match the geometry (which is already scaled via lw/lh).
 */
export function ShapePrimitive({ el, lw, lh, listening = true, strokeScale = 1 }: { el: CanvasElement; lw: number; lh: number; listening?: boolean; strokeScale?: number }) {
  const kind = el.shapeKind ?? 'rect'
  const cx = lw / 2, cy = lh / 2
  const r = Math.min(lw, lh) / 2
  // Line-like shapes are pure strokes coloured by `fill`; closed shapes honour
  // fill + separate border, and the filled↔outline toggle drops the fill.
  if (LINE_SHAPES.includes(kind)) {
    const colour = el.fill ?? '#111827'
    const sw = Math.max(el.strokeWidth ?? 6, 3) * strokeScale
    if (kind === 'line') {
      return <Line points={[0, cy, lw, cy]} stroke={colour} strokeWidth={sw} lineCap="round" listening={listening} />
    }
    return (
      <Arrow points={[0, cy, lw, cy]} fill={colour} stroke={colour} strokeWidth={sw}
        pointerAtBeginning={kind === 'doubleArrow'}
        pointerLength={Math.min(lw * 0.3, 24 * strokeScale)} pointerWidth={Math.min(Math.max(lh, 12 * strokeScale), 22 * strokeScale)} listening={listening} />
    )
  }
  const fill = el.filled === false ? undefined : (el.fill ?? '#2563eb')
  const stroke = el.stroke
  const strokeWidth = (el.strokeWidth ?? 0) * strokeScale
  const common = { fill, stroke, strokeWidth, listening }
  switch (kind) {
    case 'roundedRect':
      return <Rect width={lw} height={lh} cornerRadius={Math.min(lw, lh) * 0.18} {...common} />
    case 'circle':
    case 'ellipse':
      return <Ellipse x={cx} y={cy} radiusX={lw / 2} radiusY={lh / 2} {...common} />
    case 'triangle':
      return <RegularPolygon x={cx} y={cy} sides={3} radius={r} {...common} />
    case 'diamond':
      return <RegularPolygon x={cx} y={cy} sides={4} radius={r} {...common} />
    case 'pentagon':
      return <RegularPolygon x={cx} y={cy} sides={5} radius={r} {...common} />
    case 'hexagon':
      return <RegularPolygon x={cx} y={cy} sides={6} radius={r} {...common} />
    case 'star':
      return <Star x={cx} y={cy} numPoints={5} innerRadius={r * 0.45} outerRadius={r} {...common} />
    case 'rect':
    case 'square':
    default:
      return <Rect width={lw} height={lh} {...common} />
  }
}

export function ShapeNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const locked = !!el.locked
  const { halfW, halfH } = boxHalfExtentsPx(el.width, el.height, stageW, stageH)
  const lw = halfW * 2
  const lh = halfH * 2
  const pos = centerPosition(el.x, el.y, halfW, halfH, stageW, stageH)
  return (
    <Group>
      <Group
        ref={shapeRef as never}
        x={pos.x}
        y={pos.y}
        offsetX={halfW}
        offsetY={halfH}
        rotation={el.rotation}
        draggable={!locked}
        onClick={locked ? undefined : onSelect}
        onTap={locked ? undefined : onSelect}
        onDragEnd={e => onChange(topLeftFromCenterPx(e.target.x(), e.target.y(), halfW, halfH, stageW, stageH))}
        onTransformEnd={e => {
          const node = e.target as Konva.Group
          const newW = Math.max(0.02, el.width * node.scaleX())
          const newH = Math.max(0.02, el.height * node.scaleY())
          const newHalf = boxHalfExtentsPx(newW, newH, stageW, stageH)
          onChange({
            rotation: node.rotation(),
            width: newW,
            height: newH,
            ...topLeftFromCenterPx(node.x(), node.y(), newHalf.halfW, newHalf.halfH, stageW, stageH),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      >
        <ShapePrimitive el={el} lw={lw} lh={lh} />
      </Group>
      {isSelected && !locked && <Transformer ref={trRef as never} rotateEnabled centeredScaling />}
    </Group>
  )
}

/** Quadratic-bezier arc path for curved text, sized to the text's rough width. */
export function curvePath(content: string, fontSize: number, curve: number): string {
  const w = estimateTextBox(content, fontSize).w
  const bend = (curve / 100) * (w / 2)
  return `M 0 0 Q ${w / 2} ${-bend} ${w} 0`
}

export function ImageNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const locked = !!el.locked
  const imgRef = useRef<HTMLImageElement | null>(null)
  const forceRef = useRef(0)
  if (!imgRef.current && el.assetUrl) {
    const cached = getCachedImage(el.assetUrl)
    if (cached && cached.complete) {
      imgRef.current = cached
    } else {
      loadImage(el.assetUrl).then(img => {
        imgRef.current = img
        forceRef.current++
        shapeRef.current?.getLayer()?.batchDraw()
      }).catch(() => { /* leave imgRef unset; nothing to paint */ })
    }
  }
  const { halfW, halfH } = boxHalfExtentsPx(el.width, el.height, stageW, stageH)
  const pos = centerPosition(el.x, el.y, halfW, halfH, stageW, stageH)
  return (
    <Group>
      <KonvaImage
        ref={shapeRef as never}
        image={imgRef.current ?? undefined}
        x={pos.x}
        y={pos.y}
        width={halfW * 2}
        height={halfH * 2}
        offsetX={halfW}
        offsetY={halfH}
        rotation={el.rotation}
        draggable={!locked}
        onClick={locked ? undefined : onSelect}
        onTap={locked ? undefined : onSelect}
        onDragEnd={e => onChange(topLeftFromCenterPx(e.target.x(), e.target.y(), halfW, halfH, stageW, stageH))}
        onTransformEnd={e => {
          const node = e.target as Konva.Image
          const newW = (node.width() * node.scaleX()) / stageW
          const newH = (node.height() * node.scaleY()) / stageH
          const newHalf = boxHalfExtentsPx(newW, newH, stageW, stageH)
          onChange({
            rotation: node.rotation(),
            width: newW,
            height: newH,
            ...topLeftFromCenterPx(node.x(), node.y(), newHalf.halfW, newHalf.halfH, stageW, stageH),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      />
      {el.removeBg && (
        // Small "background will be removed" badge, pinned at the image's
        // top-left corner. name="export-hide" so it is NEVER baked into any
        // export (layout guide OR the WYSIWYG preview); listening=false so it
        // never steals clicks from the image beneath it.
        <Group name="export-hide" listening={false} x={el.x * stageW} y={el.y * stageH}>
          <Ellipse x={11} y={11} radiusX={10} radiusY={10} fill="#111827" opacity={0.85} />
          <Text x={3} y={5} width={16} align="center" text="✂" fontSize={11} fill="#ffffff" />
        </Group>
      )}
      {isSelected && !locked && <Transformer ref={trRef as never} rotateEnabled centeredScaling />}
    </Group>
  )
}

export function DrawingNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const locked = !!el.locked
  const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * stageW : p * stageH))
  const sw = (el.strokeWidth ?? 0.01) * stageW
  // A drawing has no stored width/height — its stroke's own bounding-box
  // centre stands in for "the box" this pivots around.
  const { cx, cy } = drawingBoundsCenter(pts)
  const pos = centerPosition(el.x, el.y, cx, cy, stageW, stageH)
  return (
    <Group>
      <Group
        ref={shapeRef as never}
        x={pos.x}
        y={pos.y}
        offsetX={cx}
        offsetY={cy}
        rotation={el.rotation}
        draggable={!locked}
        onClick={locked ? undefined : onSelect}
        onTap={locked ? undefined : onSelect}
        onDragEnd={e => onChange(topLeftFromCenterPx(e.target.x(), e.target.y(), cx, cy, stageW, stageH))}
        onTransformEnd={e => {
          // Rotate-only transformer (resize disabled): the pivot is the
          // stroke's own bbox centre, so a pure rotation leaves x/y
          // unchanged — still recomputed defensively from node.x()/y().
          const node = e.target as Konva.Group
          onChange({
            rotation: node.rotation(),
            ...topLeftFromCenterPx(node.x(), node.y(), cx, cy, stageW, stageH),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      >
        <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={sw}
          lineCap="round" lineJoin="round" tension={0.5} hitStrokeWidth={Math.max(sw, 12)} />
      </Group>
      {isSelected && !locked && (
        <Transformer ref={trRef as never} rotateEnabled resizeEnabled={false} enabledAnchors={[]} />
      )}
    </Group>
  )
}
