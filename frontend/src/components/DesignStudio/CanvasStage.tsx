import { useEffect, useState, type RefObject } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect, Line } from 'react-konva'
import type Konva from 'konva'
import { useCanvasStore } from '../../store/canvasStore'
import { TextNode, ImageNode, ShapeNode, DrawingNode } from './nodes'
import { getCachedImage, loadImage } from '../../lib/imageCache'

export const STAGE_W = 480
export const STAGE_H = 480

export function CanvasStage({ stageRef }: { stageRef: RefObject<Konva.Stage> }) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const faceImages = useCanvasStore(s => s.faceImages)
  const selectedId = useCanvasStore(s => s.selectedId)
  const select = useCanvasStore(s => s.select)
  const updateElement = useCanvasStore(s => s.updateElement)
  const colourway = useCanvasStore(s => s.colourway)
  const drawMode = useCanvasStore(s => s.drawMode)
  const drawColour = useCanvasStore(s => s.drawColour)
  const drawWidth = useCanvasStore(s => s.drawWidth)
  const addDrawing = useCanvasStore(s => s.addDrawing)

  const [stroke, setStroke] = useState<number[] | null>(null)

  const bgUrl = faceImages[activeFace]
  const [bg, setBg] = useState<HTMLImageElement | null>(() => {
    const cached = getCachedImage(bgUrl)
    return cached && cached.complete ? cached : null
  })
  useEffect(() => {
    if (!bgUrl) { setBg(null); return }
    const cached = getCachedImage(bgUrl)
    if (cached && cached.complete) { setBg(cached); return }
    let cancelled = false
    loadImage(bgUrl).then(img => { if (!cancelled) setBg(img) })
    return () => { cancelled = true }
  }, [bgUrl])

  const els = [...faces[activeFace]].sort((a, b) => a.zIndex - b.zIndex)

  useEffect(() => { setStroke(null) }, [activeFace])

  function pointerNorm(stage: Konva.Stage | null): number[] | null {
    const p = stage?.getPointerPosition()
    return p ? [p.x / STAGE_W, p.y / STAGE_H] : null
  }
  function onDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!drawMode) { if (e.target === e.target.getStage()) select(null); return }
    e.evt.preventDefault()
    const n = pointerNorm(e.target.getStage())
    if (n) setStroke(n)
  }
  function onMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (!drawMode || !stroke) return
    e.evt.preventDefault()
    const n = pointerNorm(e.target.getStage())
    if (n) setStroke(prev => (prev ? [...prev, ...n] : n))
  }
  function onUp() {
    if (!drawMode || !stroke) return
    if (stroke.length >= 4) addDrawing(stroke) // ≥ 2 points
    setStroke(null)
  }

  const livePts = stroke ? stroke.map((p, i) => (i % 2 === 0 ? p * STAGE_W : p * STAGE_H)) : []

  return (
    <Stage
      ref={stageRef as never}
      width={STAGE_W}
      height={STAGE_H}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onTouchStart={onDown}
      onTouchMove={onMove}
      onTouchEnd={onUp}
      style={{ cursor: drawMode ? 'crosshair' : 'default' }}
      className="rounded-2xl bg-surface"
    >
      {/* Elements stop listening while drawing so every pointer event reaches the
          stage handlers above (start/extend/commit a stroke anywhere on the cap). */}
      <Layer listening={!drawMode}>
        {bg && <KonvaImage image={bg} width={STAGE_W} height={STAGE_H} listening={false} />}
        {colourway && (
          <Rect width={STAGE_W} height={STAGE_H} fill={colourway.hex}
                globalCompositeOperation="multiply" listening={false} />
        )}
        {els.map(el => {
          const props = {
            el, stageW: STAGE_W, stageH: STAGE_H,
            isSelected: el.id === selectedId,
            onSelect: () => select(el.id),
            onChange: (p: Partial<typeof el>) => updateElement(el.id, p),
          }
          if (el.type === 'text') return <TextNode key={el.id} {...props} />
          if (el.type === 'shape') return <ShapeNode key={el.id} {...props} />
          if (el.type === 'drawing') return <DrawingNode key={el.id} {...props} />
          return <ImageNode key={el.id} {...props} />
        })}
        {stroke && stroke.length >= 4 && (
          <Line points={livePts} stroke={drawColour} strokeWidth={drawWidth * STAGE_W}
            lineCap="round" lineJoin="round" tension={0.5} listening={false} />
        )}
      </Layer>
    </Stage>
  )
}
