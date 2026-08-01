import { useEffect, useState } from 'react'
import { useCanvasStore, FACES, type Face } from '../../store/canvasStore'
import { FaceStage } from './FaceStage'

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }

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
    <div className="flex md:flex-col gap-2 p-2 lg:p-3">
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
                active ? 'border-canvasAccent' : 'border-border hover:border-textMuted'
              }`}
            >
              <FaceStage face={f} size={64} fontsTick={fontsTick} />
            </div>
            {count > 0 && (
              <span className="absolute top-0 right-0 min-w-[18px] h-[18px] px-1 rounded-full bg-canvasAccent text-white text-[10px] font-semibold flex items-center justify-center">
                {count}
              </span>
            )}
            <span className={`text-[11px] ${active ? 'text-canvasAccent font-semibold' : 'text-textMuted'}`}>{LABELS[f]}</span>
          </button>
        )
      })}
    </div>
  )
}
