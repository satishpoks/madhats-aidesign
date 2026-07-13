import { useCanvasStore, FACES, type Face } from '../../store/canvasStore'

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }

/**
 * Left-rail face navigator: one thumbnail per face (its angle photo, tinted to
 * the chosen colourway), the active one outlined, a count badge when the face
 * carries elements. Clicking a thumbnail switches the active face.
 */
export function FaceThumbnails() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faces = useCanvasStore(s => s.faces)
  const faceImages = useCanvasStore(s => s.faceImages)
  const colourway = useCanvasStore(s => s.colourway)

  return (
    <div className="flex md:flex-col gap-3 p-3">
      {(FACES as Face[]).map(f => {
        const count = faces[f].length
        const img = faceImages[f]
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
              {img ? (
                <img src={img} alt="" crossOrigin="anonymous" className="w-full h-full object-contain" draggable={false} />
              ) : null}
              {colourway && (
                <div className="absolute inset-0" style={{ background: colourway.hex, mixBlendMode: 'multiply' }} aria-hidden="true" />
              )}
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
