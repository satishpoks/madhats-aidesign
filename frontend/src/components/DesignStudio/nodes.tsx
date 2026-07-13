import { useRef, useEffect } from 'react'
import { Text, Image as KonvaImage, Transformer, Group } from 'react-konva'
import type Konva from 'konva'
import type { CanvasElement } from '../../store/canvasStore'

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
  return (
    <Group>
      <Text
        ref={shapeRef as never}
        text={el.content ?? ''}
        x={el.x * stageW}
        y={el.y * stageH}
        rotation={el.rotation}
        fontSize={el.fontSize ?? 36}
        fontFamily={el.font ?? 'Arial'}
        fill={el.colour ?? '#ffffff'}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          const node = e.target as Konva.Text
          onChange({
            rotation: node.rotation(),
            fontSize: Math.max(8, (el.fontSize ?? 36) * node.scaleX()),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      />
      {isSelected && <Transformer ref={trRef as never} enabledAnchors={['top-left','top-right','bottom-left','bottom-right']} rotateEnabled />}
    </Group>
  )
}

export function ImageNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const forceRef = useRef(0)
  if (!imgRef.current && el.assetUrl) {
    const img = new window.Image()
    img.crossOrigin = 'anonymous' // required so stage.toDataURL() isn't tainted
    img.src = el.assetUrl
    img.onload = () => { forceRef.current++; shapeRef.current?.getLayer()?.batchDraw() }
    imgRef.current = img
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
