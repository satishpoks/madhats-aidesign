import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useBrandStore } from '../../store/brandStore'
import { useChatStore } from '../../store/chatStore'

/** Mirrors `branding.DEFAULT_REDIRECT_SECONDS`. Used when a store set a URL but
 *  left the duration blank. */
export const DEFAULT_REDIRECT_SECONDS = 30

/** Server-validated is not enough to trust blindly: `POST /admin/stores`
 *  (unlike the PATCH route) used to write `body.brand` straight through with
 *  no call to `validate_brand` at all, and `redirect_url` is the first brand
 *  field this component ever hands to `window.location.assign`. The create
 *  route is now fixed to validate too, but this guard stays regardless — it
 *  is what makes "only ever navigates to an http(s) URL" true independent of
 *  which backend route (or version) produced the stored value. */
function isSafeRedirectUrl(url: string | undefined | null): url is string {
  return typeof url === 'string' && /^https?:\/\//i.test(url)
}

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
  // Backend-owned, not a raw chatState comparison: `quote_requested` is a
  // state STRING shared with v1, where it is an answerable yes/no gate, not
  // an ending. Keying this dialog off the same `sessionEnded` flag
  // `ChatColumn` uses for its composer lock is what stops a v1 canvas session
  // (which can still answer) from being yanked to the shop mid-question — the
  // exact bug `session_ended_for_state` was added to close.
  const sessionEnded = useChatStore(s => s.sessionEnded)
  const brand = useBrandStore(s => s.brand)
  const url = isSafeRedirectUrl(brand.redirect_url) ? brand.redirect_url : undefined
  const total = brand.redirect_seconds ?? DEFAULT_REDIRECT_SECONDS

  const shouldOpen = sessionEnded && !!url
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
  // The updater is PURE (no side effect, just the decrement) — React Strict
  // Mode calls a function updater twice in dev to catch impurities, and the
  // previous version's `if (url) window.location.assign(url)` lived INSIDE
  // this updater, so it double-navigated. Navigation is a separate effect
  // below, reacting to `left` hitting 0, which is a genuine update (not the
  // initial mount) and so is not double-invoked.
  useEffect(() => {
    if (!open) return
    const id = setInterval(() => {
      setLeft(prev => (prev > 0 ? prev - 1 : 0))
    }, 1000)
    return () => clearInterval(id)
  }, [open])

  useEffect(() => {
    if (open && left === 0 && url) window.location.assign(url)
  }, [open, left, url])

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
