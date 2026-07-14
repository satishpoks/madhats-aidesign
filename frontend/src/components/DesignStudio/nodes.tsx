import { useRef, useEffect } from 'react'
import {
  Text, TextPath, Image as KonvaImage, Transformer, Group,
  Rect, Ellipse, RegularPolygon, Star, Line, Arrow,
} from 'react-konva'
import type Konva from 'konva'
import { type CanvasElement, LINE_SHAPES } from '../../store/canvasStore'
import { getCachedImage, loadImage } from '../../lib/imageCache'
import { ensureFont } from '../../lib/fonts'

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

  const common = {
    ref: shapeRef as never,
    x: el.x * stageW,
    y: el.y * stageH,
    rotation: el.rotation,
    fontSize,
    fontFamily,
    fill,
    draggable: true,
    onClick: onSelect,
    onTap: onSelect,
    onDragEnd: (e: Konva.KonvaEventObject<DragEvent>) =>
      onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH }),
    onTransformEnd: (e: Konva.KonvaEventObject<Event>) => {
      const node = e.target as Konva.Text
      onChange({ rotation: node.rotation(), fontSize: Math.max(8, fontSize * node.scaleX()) })
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
      {isSelected && (
        <Transformer
          ref={trRef as never}
          enabledAnchors={['top-left', 'top-right', 'bottom-left', 'bottom-right']}
          rotateEnabled
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
  const lw = el.width * stageW
  const lh = el.height * stageH
  return (
    <Group>
      <Group
        ref={shapeRef as never}
        x={el.x * stageW}
        y={el.y * stageH}
        rotation={el.rotation}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          const node = e.target as Konva.Group
          onChange({
            rotation: node.rotation(),
            width: Math.max(0.02, el.width * node.scaleX()),
            height: Math.max(0.02, el.height * node.scaleY()),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      >
        <ShapePrimitive el={el} lw={lw} lh={lh} />
      </Group>
      {isSelected && <Transformer ref={trRef as never} rotateEnabled />}
    </Group>
  )
}

/** Quadratic-bezier arc path for curved text, sized to the text's rough width. */
export function curvePath(content: string, fontSize: number, curve: number): string {
  const w = Math.max(fontSize, content.length * fontSize * 0.55)
  const bend = (curve / 100) * (w / 2)
  return `M 0 0 Q ${w / 2} ${-bend} ${w} 0`
}

export function ImageNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
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
  return (
    <Group>
      <KonvaImage
        ref={shapeRef as never}
        image={imgRef.current ?? undefined}
        x={el.x * stageW}
        y={el.y * stageH}
        width={el.width * stageW}
        height={el.height * stageH}
        rotation={el.rotation}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          const node = e.target as Konva.Image
          onChange({
            rotation: node.rotation(),
            width: (node.width() * node.scaleX()) / stageW,
            height: (node.height() * node.scaleY()) / stageH,
          })
          node.scaleX(1); node.scaleY(1)
        }}
      />
      {isSelected && <Transformer ref={trRef as never} rotateEnabled />}
    </Group>
  )
}

export function DrawingNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * stageW : p * stageH))
  const sw = (el.strokeWidth ?? 0.01) * stageW
  return (
    <Group>
      <Group
        ref={shapeRef as never}
        x={el.x * stageW}
        y={el.y * stageH}
        rotation={el.rotation}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          // Rotate-only transformer: Konva rotates around the stroke's bbox
          // centre by adjusting x/y + rotation together, so persist all three.
          const node = e.target as Konva.Group
          onChange({ x: node.x() / stageW, y: node.y() / stageH, rotation: node.rotation() })
          node.scaleX(1); node.scaleY(1)
        }}
      >
        <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={sw}
          lineCap="round" lineJoin="round" tension={0.5} hitStrokeWidth={Math.max(sw, 12)} />
      </Group>
      {isSelected && (
        <Transformer ref={trRef as never} rotateEnabled resizeEnabled={false} enabledAnchors={[]} />
      )}
    </Group>
  )
}
