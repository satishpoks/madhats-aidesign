import { useEffect, useRef, useState, type ReactNode, type RefObject } from 'react'
import { Stage, Layer, Image as KonvaImage, Rect, Line } from 'react-konva'
import type Konva from 'konva'
import { useCanvasStore } from '../../store/canvasStore'
import { TextNode, ImageNode, ShapeNode, DrawingNode } from './nodes'
import { getCachedImage, loadImage } from '../../lib/imageCache'
import { STAGE_W, STAGE_H } from '../../lib/canvasGeometry'

/**
 * The stage's LOGICAL coordinate space. Every element coordinate is normalised
 * to it, the face thumbnails scale off it, and the flatten exports are sized
 * from it — so this stays a constant 480 forever. Only the stage's *rendered*
 * size responds to the screen, via a uniform Konva scale (see `display` below).
 *
 * It is DEFINED in `lib/canvasGeometry` (Konva-free) and re-exported here so
 * plain-geometry callers can use it without pulling in react-konva; the many
 * existing `from './CanvasStage'` imports keep working unchanged.
 */
export { STAGE_W, STAGE_H }

/**
 * Bounds for the on-screen (scaled) stage edge, in CSS pixels. MIN is a floor
 * on usability, not on fit: on a very short window the cap keeps this size and
 * the column scrolls a little, rather than shrinking to something you can't
 * design on.
 */
const MIN_DISPLAY = 280
const MAX_DISPLAY = 560
/** Breathing room so we never land exactly on the overflow threshold. */
const FIT_MARGIN = 8

/**
 * Height left for the cap in the centre column: the column's own inner height
 * minus everything else sharing it — the instruction callout, the sticky Adjust
 * panel, the Done button and the row gaps.
 *
 * Measured rather than assumed because the Adjust panel appears and disappears
 * with the selection, and a fixed guess is wrong in both directions: too small
 * and the cap is needlessly tiny with nothing selected, too large and selecting
 * an element pushes the cap off the bottom of the screen.
 *
 * `col.clientHeight` is set by the flex row above it (viewport-derived), NOT by
 * its contents, so resizing the stage can never feed back into this number.
 *
 * That precondition is only true while `slot` is the centre column's own child
 * — see the parent-walk warning on `wrapRef` below.
 */
function availableHeight(slot: HTMLElement): number {
  const col = slot.parentElement
  if (!col) return Infinity
  const cs = getComputedStyle(col)
  const gap = parseFloat(cs.rowGap) || 0
  let used = 0
  for (const child of col.children) {
    if (child === slot) continue
    used += child.getBoundingClientRect().height + gap
  }
  const inner = col.clientHeight - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0)
  return inner - used - FIT_MARGIN
}

export function CanvasStage({ stageRef, locked = false, overlay = null }: {
  stageRef: RefObject<Konva.Stage>
  locked?: boolean
  /**
   * Plain-DOM chrome drawn OVER the stage (today: the watermark). Rendered
   * inside this component's own `relative` box, as a SIBLING of the Konva
   * `<Stage>` — never a Konva child, so it can never enter `stage.toDataURL()`
   * and therefore never reaches the layout guide the image model conditions on.
   *
   * It is a prop rather than a wrapper in the caller because any element
   * inserted between `wrapRef` and `canvas-stage-wrap` breaks the parent walk
   * below.
   */
  overlay?: ReactNode
}) {
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

  // Responsive display size: fit the width the column gives us and the height
  // left over beside the panel/callout/Done button, clamped. The scene graph is
  // untouched — `scale` below maps the fixed 480 logical space onto whatever we
  // can afford on screen.
  //
  // WARNING — this sizing walks UP the DOM two levels: `wrapRef` -> its parent
  // (the `canvas-stage-wrap` slot) -> the centre column, whose other children
  // (Adjust panel, instruction callout, Done button) are the budget
  // `availableHeight` subtracts. ANY element inserted between `wrapRef` and
  // `canvas-stage-wrap` silently breaks BOTH halves of that: the sibling budget
  // reads zero (the slot becomes the only child of the injected node), and
  // `col.clientHeight` becomes content-derived — i.e. our own output — so each
  // measure pass shrinks the stage by FIT_MARGIN and the ResizeObserver
  // re-fires, a monotone descent to MIN_DISPLAY. jsdom performs no layout and
  // ships neither observer, so no test can catch it. If you need chrome over
  // the stage, pass it as `overlay` — do not wrap this component.
  const wrapRef = useRef<HTMLDivElement>(null)
  const [display, setDisplay] = useState(STAGE_W)
  useEffect(() => {
    const el = wrapRef.current
    const slot = el?.parentElement
    if (!el || !slot) return
    const measure = () => {
      const w = el.clientWidth || STAGE_W
      const h = availableHeight(slot)
      setDisplay(Math.round(Math.max(MIN_DISPLAY, Math.min(MAX_DISPLAY, w, h))))
    }
    measure()
    const col = slot.parentElement
    // Width/height of the column and of the siblings sharing it (the Adjust
    // panel grows and shrinks with the selected element's controls). Both
    // observers are feature-detected — jsdom ships neither.
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    const observeSiblings = () => {
      if (!ro || !col) return
      for (const child of col.children) if (child !== slot) ro.observe(child)
    }
    ro?.observe(el)
    if (col) ro?.observe(col)
    observeSiblings()
    // The panel/callout/Done button mount and unmount as the flow advances —
    // a ResizeObserver alone never sees a sibling that wasn't there yet.
    const mo = col && typeof MutationObserver !== 'undefined'
      ? new MutationObserver(() => { observeSiblings(); measure() })
      : null
    mo?.observe(col!, { childList: true })
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); mo?.disconnect(); window.removeEventListener('resize', measure) }
  }, [])
  const scale = display / STAGE_W

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
    // getPointerPosition() is in CONTAINER pixels (Konva does not apply the
    // stage transform to it), so normalise against the displayed size — not the
    // 480 logical space the drawn points live in.
    const p = stage?.getPointerPosition()
    return p ? [p.x / display, p.y / display] : null
  }
  function onDown(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (locked) return  // read-only: no select, no draw
    if (!drawMode) { if (e.target === e.target.getStage()) select(null); return }
    e.evt.preventDefault()
    const n = pointerNorm(e.target.getStage())
    if (n) setStroke(n)
  }
  function onMove(e: Konva.KonvaEventObject<MouseEvent | TouchEvent>) {
    if (locked || !drawMode || !stroke) return
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
    <div ref={wrapRef} data-testid="canvas-stage-slot" className="w-full flex justify-center">
    {/* `relative` scopes the overlay's `absolute inset-0` to exactly the stage
        box. It lives INSIDE wrapRef (not around this component) so the
        parent walk above still reaches the centre column — see the warning
        there. It shrink-wraps the stage as a flex item, so the overlay covers
        the cap and nothing else. */}
    <div className="relative">
    <Stage
      ref={stageRef as never}
      width={display}
      height={display}
      scaleX={scale}
      scaleY={scale}
      onMouseDown={onDown}
      onMouseMove={onMove}
      onMouseUp={onUp}
      onTouchStart={onDown}
      onTouchMove={onMove}
      onTouchEnd={onUp}
      style={{ cursor: drawMode && !locked ? 'crosshair' : 'default' }}
      className="rounded-2xl bg-surface"
    >
      {/* Elements stop listening while drawing so every pointer event reaches the
          stage handlers above (start/extend/commit a stroke anywhere on the cap).
          When locked (view-only) they also stop listening — no drag/select/resize. */}
      <Layer listening={!drawMode && !locked}>
        {/* name="flatten-hide" so the layout-guide export (canvasFlatten) drops the
            product photo + colour tint — the guide must carry ONLY the placed
            decorations on a transparent background, or the image model echoes the
            finished-looking mock back instead of re-rendering photorealistically. */}
        {bg && <KonvaImage name="flatten-hide" image={bg} width={STAGE_W} height={STAGE_H} listening={false} />}
        {colourway && (
          <Rect name="flatten-hide" width={STAGE_W} height={STAGE_H} fill={colourway.hex}
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
    {overlay}
    </div>
    </div>
  )
}
