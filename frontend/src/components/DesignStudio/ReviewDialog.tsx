import { useEffect, useRef } from 'react'
import { FACES, useCanvasStore, type Face } from '../../store/canvasStore'
import { useBrandStore } from '../../store/brandStore'
import { FaceStage } from './FaceStage'
import { Watermark } from './Watermark'

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }
const VIEW_PX = 300

/** Exact chip labels from canvas_steps.REVIEW_DESIGN. resolve_chip matches them
 *  by identity, so a typo here becomes free text the interpreter has to guess
 *  at — which is the whole class of bug Workstream A exists to remove. */
const CONFIRM_LABEL = 'Looks great, send it'
const REWORK_LABEL = "I'd like to rework it"

/**
 * The pre-submit confirm gate: every decorated face, watermarked, in one place.
 *
 * It renders from `canvasStore` through the same `FaceStage` the face rail
 * uses, so it needs no flatten, no upload and no new endpoint, and it can never
 * show something the canvas doesn't.
 *
 * Closable on purpose: the canvas behind it is watermarked in this state
 * (state_machine_v2._WATERMARKED_STEPS), so letting the customer look at it
 * costs nothing, and trapping them in a modal to look at their own design is
 * hostile.
 */
export function ReviewDialog({ open, onConfirm, onRework, onClose }: {
  open: boolean
  onConfirm: () => void
  onRework: () => void
  onClose: () => void
}) {
  const faces = useCanvasStore(s => s.faces)
  const watermarkText = useBrandStore(s => s.watermarkText)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key !== 'Tab' || !panelRef.current) return
      // Focus trap: a modal that lets Tab escape to the page behind it is not
      // a modal for a keyboard or screen-reader user.
      const f = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (f.length === 0) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.querySelector<HTMLElement>('button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  const decorated = (FACES as Face[]).filter(f => faces[f].length > 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-0 md:p-6">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-dialog-title"
        className="flex h-full w-full flex-col overflow-hidden bg-surface md:h-auto md:max-h-[90vh] md:max-w-3xl md:rounded-2xl"
      >
        <div className="flex-none border-b border-border px-5 py-4">
          <h2 id="review-dialog-title" className="text-base font-semibold text-textPrimary">
            Review your design
          </h2>
          <p className="mt-1 text-sm text-textMuted">
            Here is every view you have decorated. Check each one before we send it to our team.
          </p>
        </div>

        {/* Stacked and scrollable on a phone; a grid once there is room. */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {decorated.map(f => (
              <figure key={f} className="m-0">
                <div className="relative mx-auto w-fit overflow-hidden rounded-xl border border-border">
                  <FaceStage face={f} size={VIEW_PX} fontsTick={0} />
                  <Watermark text={watermarkText} />
                </div>
                <figcaption className="mt-2 text-center text-sm font-medium text-textPrimary">
                  {LABELS[f]}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>

        <div className="flex flex-none flex-col gap-2 border-t border-border px-5 py-4 sm:flex-row sm:justify-end">
          <button onClick={onRework}
            className="rounded-full border border-border px-5 py-2 text-sm font-medium text-textPrimary hover:bg-surfaceAlt">
            {REWORK_LABEL}
          </button>
          <button onClick={onConfirm}
            className="rounded-full bg-canvasAccent px-5 py-2 text-sm font-semibold text-white hover:bg-canvasAccentHover">
            {CONFIRM_LABEL}
          </button>
        </div>
      </div>
    </div>
  )
}
