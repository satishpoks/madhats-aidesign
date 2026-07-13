import { useRef, useEffect, useState, type RefObject } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect } from 'react-konva'
import type Konva from 'konva'
import { useCanvasStore } from '../../store/canvasStore'
import { TextNode, ImageNode } from './nodes'
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

  return (
    <Stage
      ref={stageRef as never}
      width={STAGE_W}
      height={STAGE_H}
      onMouseDown={e => { if (e.target === e.target.getStage()) select(null) }}
      onTouchStart={e => { if (e.target === e.target.getStage()) select(null) }}
      className="rounded-2xl bg-surface"
    >
      <Layer>
        {bg && <KonvaImage image={bg} width={STAGE_W} height={STAGE_H} listening={false} />}
        {colourway && (
          <Rect width={STAGE_W} height={STAGE_H} fill={colourway.hex}
                globalCompositeOperation="multiply" listening={false} />
        )}
        {els.map(el =>
          el.type === 'text' ? (
            <TextNode key={el.id} el={el} stageW={STAGE_W} stageH={STAGE_H}
              isSelected={el.id === selectedId} onSelect={() => select(el.id)}
              onChange={p => updateElement(el.id, p)} />
          ) : (
            <ImageNode key={el.id} el={el} stageW={STAGE_W} stageH={STAGE_H}
              isSelected={el.id === selectedId} onSelect={() => select(el.id)}
              onChange={p => updateElement(el.id, p)} />
          ),
        )}
      </Layer>
    </Stage>
  )
}
