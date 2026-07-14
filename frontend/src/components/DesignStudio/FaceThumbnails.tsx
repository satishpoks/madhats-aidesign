import { useEffect, useState } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect, Text, TextPath, Group, Line } from 'react-konva'
import { useCanvasStore, FACES, type Face, type CanvasElement } from '../../store/canvasStore'
import { getCachedImage, loadImage } from '../../lib/imageCache'
import { STAGE_W } from './CanvasStage'
import { curvePath, ShapePrimitive } from './nodes'

const TW = 64
const TH = 64
const SCALE = TW / STAGE_W // element geometry is normalised to the full stage

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }

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

/** One placed element, drawn statically (non-interactive) at thumbnail scale. */
function ElementThumb({ el }: { el: CanvasElement }) {
  const img = useThumbImage(el.type === 'image' ? el.assetUrl : undefined)
  if (el.type === 'shape') {
    return (
      <Group x={el.x * TW} y={el.y * TH} rotation={el.rotation}>
        <ShapePrimitive el={el} lw={el.width * TW} lh={el.height * TH} listening={false} strokeScale={TW / STAGE_W} />
      </Group>
    )
  }
  if (el.type === 'drawing') {
    const pts = (el.points ?? []).map((p, i) => (i % 2 === 0 ? p * TW : p * TH))
    return (
      <Group x={el.x * TW} y={el.y * TH} rotation={el.rotation}>
        <Line points={pts} stroke={el.stroke ?? '#111827'} strokeWidth={(el.strokeWidth ?? 0.01) * TW}
          lineCap="round" lineJoin="round" tension={0.5} listening={false} />
      </Group>
    )
  }
  if (el.type === 'text') {
    const fontSize = (el.fontSize ?? 36) * SCALE
    const common = {
      x: el.x * TW, y: el.y * TH, rotation: el.rotation,
      fontSize, fontFamily: el.font ?? 'Arial', fill: el.colour ?? '#ffffff', listening: false,
    }
    const curve = el.curve ?? 0
    return curve !== 0
      ? <TextPath {...common} align="center" text={el.content ?? ''} data={curvePath(el.content ?? '', fontSize, curve)} />
      : <Text {...common} text={el.content ?? ''} />
  }
  if (!img) return null
  return (
    <KonvaImage image={img} x={el.x * TW} y={el.y * TH}
      width={el.width * TW} height={el.height * TH} rotation={el.rotation} listening={false} />
  )
}

/** Live mini-render of a face: angle photo + colour tint + placed elements. */
function FaceThumbStage({ face, fontsTick }: { face: Face; fontsTick: number }) {
  const els = useCanvasStore(s => s.faces[face])
  const bgUrl = useCanvasStore(s => s.faceImages[face])
  const colourway = useCanvasStore(s => s.colourway)
  const bg = useThumbImage(bgUrl)
  const ordered = [...els].sort((a, b) => a.zIndex - b.zIndex)
  return (
    // fontsTick forces a redraw once web fonts finish loading (Konva won't on its own).
    <Stage width={TW} height={TH} listening={false} key={fontsTick} style={{ pointerEvents: 'none' }}>
      <Layer>
        {bg && <KonvaImage image={bg} width={TW} height={TH} listening={false} />}
        {colourway && (
          <Rect width={TW} height={TH} fill={colourway.hex} globalCompositeOperation="multiply" listening={false} />
        )}
        {ordered.map(el => <ElementThumb key={el.id} el={el} />)}
      </Layer>
    </Stage>
  )
}

/**
 * Left-rail face navigator: a live thumbnail per face showing its actual current
 * design (angle photo + tint + placed text/logos), the active one outlined, a
 * count badge when the face carries elements. Clicking switches the active face.
 */
export function FaceThumbnails() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faces = useCanvasStore(s => s.faces)

  // Bump once web fonts are ready so text thumbnails redraw in the real face.
  const [fontsTick, setFontsTick] = useState(0)
  useEffect(() => {
    let cancelled = false
    document.fonts?.ready?.then(() => { if (!cancelled) setFontsTick(t => t + 1) })
    return () => { cancelled = true }
  }, [])

  return (
    <div className="flex md:flex-col gap-3 p-3">
      {(FACES as Face[]).map(f => {
        const count = faces[f].length
        const active = activeFace === f
        return (
          <button
            key={f}
            onClick={() => setActiveFace(f)}
            aria-label={`${LABELS[f]} face${count ? `, ${count} item${count > 1 ? 's' : ''}` : ''}`}
            aria-pressed={active}
            className="relative flex flex-col items-center gap-1 rounded-xl p-1 transition-colors"
          >
            <div
              className={`relative w-16 h-16 rounded-lg overflow-hidden border-2 bg-surface ${
                active ? 'border-accent' : 'border-border hover:border-textMuted'
              }`}
            >
              <FaceThumbStage face={f} fontsTick={fontsTick} />
            </div>
            {count > 0 && (
              <span className="absolute top-0 right-0 min-w-[18px] h-[18px] px-1 rounded-full bg-accent text-white text-[10px] font-semibold flex items-center justify-center">
                {count}
              </span>
            )}
            <span className={`text-[11px] ${active ? 'text-accent font-semibold' : 'text-textMuted'}`}>{LABELS[f]}</span>
          </button>
        )
      })}
    </div>
  )
}
