import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { FACES, useCanvasStore, type Face } from '../../store/canvasStore'
import { useBrandStore } from '../../store/brandStore'
import { FaceStage } from './FaceStage'
import { Watermark } from './Watermark'

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }
const VIEW_PX = 300

/** Exact chip labels from canvas_steps.REVIEW_DESIGN. resolve_chip matches them
 *  by identity, so a typo here becomes free text the interpreter has to guess
 *  at — which is the whole class of bug Workstream A exists to remove.
 *
 *  Exported because these are BOTH the button text and the message Surface
 *  posts on click. Two independent literals agreed by luck; one edit to either
 *  side would have produced a button that says one thing and sends another. */
export const CONFIRM_LABEL = 'Looks great, send it'
export const REWORK_LABEL = "I'd like to rework it"

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
  // Deliberate initial-focus target — see the block comment above the header
  // close button for why it, not either review action, gets focus on open.
  const closeButtonRef = useRef<HTMLButtonElement>(null)

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
    closeButtonRef.current?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  const decorated = (FACES as Face[]).filter(f => faces[f].length > 0)

  // Portalled to <body>, and that is load-bearing, not tidiness. Its mount
  // point in the tree (DesignStudioSurface) sits inside the resting column's
  // `opacity-50` content wrapper (CustomiseStudio's RESTING_CONTENT), and at
  // review_design the directive hands over no tool — so useActiveSurface always
  // answers 'chat' and the canvas column is ALWAYS resting while this is open.
  // CSS opacity < 1 composites the whole subtree as a group, `position: fixed`
  // descendants included, so in place the backdrop rendered at ~30%, the panel
  // was see-through onto the studio behind it, and the per-face watermark —
  // already rgb(255 255 255 / 0.42) under mix-blend-overlay — was halved again
  // on the exact surface this gate exists to watermark.
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-0 md:p-6"
      // Backdrop click closes — but only when the click ORIGINATED on the
      // backdrop itself. Without the target/currentTarget guard, any click
      // inside the panel (a face thumbnail, the review buttons) bubbles up
      // through this same handler and would close the dialog out from under
      // the action the customer just took.
      //
      // This alone doesn't help on a phone: the panel is `h-full w-full`
      // below `md`, so there is no backdrop showing to tap — hence the
      // header close button below, which is the one that actually matters
      // on the primary touch surface for this canvas studio.
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-dialog-title"
        className="flex h-full w-full flex-col overflow-hidden bg-surface md:h-auto md:max-h-[90vh] md:max-w-3xl md:rounded-2xl"
      >
        <div className="flex flex-none items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div>
            <h2 id="review-dialog-title" className="text-base font-semibold text-textPrimary">
              Review your design
            </h2>
            <p className="mt-1 text-sm text-textMuted">
              Here is every view you have decorated. Check each one before we send it to our team.
            </p>
          </div>
          {/* The touch-accessible close path: the backdrop-click handler above
              is invisible below `md` (the panel fills the screen there), so
              this is the ONLY way a phone user dismisses the dialog without
              picking "Looks great, send it" or "I'd like to rework it" — the
              exact "you must choose" trap the brief forbids for a dialog it
              calls "closable, deliberately."
              It is also the deliberate initial-focus target (see the ref
              above): landing focus on either review action nudges a stray
              Enter toward a business-meaningful outcome (submitting the
              design, or discarding the review to go rework it); landing here
              is inert — reopening on the next arrival costs nothing — so a
              keyboard user who tabs through to read the design, then
              presses Enter without meaning to select anything yet, doesn't
              accidentally commit to either asymmetric-cost action. */}
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="flex-none rounded-full p-1.5 text-lg leading-none text-textMuted hover:bg-surfaceAlt hover:text-textPrimary"
          >
            <span aria-hidden="true">&times;</span>
          </button>
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
    </div>,
    document.body,
  )
}
