import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useBrandStore } from '../../store/brandStore'
import { useChatStore } from '../../store/chatStore'

/** Mirrors `branding.DEFAULT_REDIRECT_SECONDS`. Used when a store set a URL but
 *  left the duration blank. */
export const DEFAULT_REDIRECT_SECONDS = 30

/** The one chat state that ends a v2 canvas session: `sessions.finalize_canvas`
 *  returns it with the MH-XXXXXX reference in the reply. */
const END_STATE = 'quote_requested'

/**
 * The end-of-session hand-off: the quote is in, so offer the customer their way
 * back to the shop.
 *
 * Self-contained by design — it takes no props and reads both stores itself, so
 * mounting it is a one-liner and no parent has to know the trigger state.
 *
 * A store that configured no `redirect_url` gets NOTHING: no dialog, no timer,
 * no navigation. Absence of the URL is the off switch; there is no separate
 * enabled flag to fall out of step with it.
 */
export function RedirectCountdown() {
  const chatState = useChatStore(s => s.chatState)
  const brand = useBrandStore(s => s.brand)
  const url = brand.redirect_url
  const total = brand.redirect_seconds ?? DEFAULT_REDIRECT_SECONDS

  const shouldOpen = chatState === END_STATE && !!url
  const [cancelled, setCancelled] = useState(false)
  const [left, setLeft] = useState(total)
  const panelRef = useRef<HTMLDivElement>(null)
  const stayRef = useRef<HTMLButtonElement>(null)

  const open = shouldOpen && !cancelled

  // Re-seed whenever the dialog becomes eligible, so a session that somehow
  // re-enters the end state does not resume a half-spent counter.
  useEffect(() => {
    if (shouldOpen) setLeft(total)
  }, [shouldOpen, total])

  // The tick. Cleared on close AND on unmount — a cancelled countdown that kept
  // running would yank the customer away from the design they chose to stay for.
  useEffect(() => {
    if (!open) return
    const id = setInterval(() => {
      setLeft(prev => {
        if (prev <= 1) {
          clearInterval(id)
          if (url) window.location.assign(url)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [open, url])

  // Focus the low-cost control, not the one that navigates away — same rule the
  // ReviewDialog follows for its close button.
  useEffect(() => {
    if (open) stayRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setCancelled(true)
      if (e.key !== 'Tab' || !panelRef.current) return
      const f = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (f.length === 0) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!open || !url) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      // Backdrop dismiss, guarded so a click INSIDE the panel that bubbles here
      // does not close it. Escape alone is not a dismiss on a phone.
      onClick={e => { if (e.target === e.currentTarget) setCancelled(true) }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="redirect-title"
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-6 shadow-xl"
      >
        <h2 id="redirect-title" className="text-base font-semibold text-textPrimary">
          Your request is with our team
        </h2>
        <p className="mt-2 text-sm text-textSub">
          We will take you back to the shop in{' '}
          <strong data-testid="redirect-countdown" className="text-textPrimary">{left}</strong>{' '}
          seconds. You are welcome to stay and look at your design instead.
        </p>
        <div className="mt-5 flex flex-col gap-2 sm:flex-row-reverse">
          <button
            type="button"
            onClick={() => window.location.assign(url)}
            className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accentHover"
          >
            Go to the shop now
          </button>
          <button
            ref={stayRef}
            type="button"
            onClick={() => setCancelled(true)}
            className="rounded-full border border-border px-5 py-2.5 text-sm text-textPrimary hover:border-accent"
          >
            Stay here
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
