import { type ReactNode, useEffect } from 'react'

interface ModalProps {
  /** Whether the dialog is shown. */
  open: boolean
  /** Heading shown at the top of the dialog. */
  title: string
  /** Called when the user dismisses via the backdrop, the ✕, or Escape.
   *  Omit to make the dialog non-dismissible (must act via its own controls). */
  onClose?: () => void
  children: ReactNode
}

/**
 * Lightweight centred modal dialog. Renders a dimmed backdrop and a card in the
 * middle of the viewport. Used to surface contextual steps (e.g. logo upload) as
 * a prominent dialog rather than an easy-to-miss inline panel. No portal — a
 * high z-index fixed overlay is enough for this single-column app.
 */
export function Modal({ open, title, onClose, children }: ModalProps) {
  // Close on Escape when dismissible.
  useEffect(() => {
    if (!open || !onClose) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Card */}
      <div className="relative z-10 w-full max-w-md rounded-2xl bg-surface border border-border shadow-xl">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border">
          <h2 className="text-sm font-semibold text-textPrimary">{title}</h2>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close"
              className="text-textMuted hover:text-textPrimary transition-colors text-lg leading-none"
            >
              ✕
            </button>
          )}
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
