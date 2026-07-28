import { useEffect, useState } from 'react'

/** Tailwind's `md` breakpoint. Kept in sync with the `md:` classes in Surface. */
const DESKTOP_QUERY = '(min-width: 768px)'

/**
 * True at `md` and above.
 *
 * Feature-detected, and it falls back to `true` rather than `false`: jsdom
 * ships no `matchMedia` (nor `ResizeObserver` — the same trap the observers in
 * SelectedToolbar guard against), and constructing one unconditionally throws
 * through every test that mounts Surface. Desktop is the right fallback because
 * it is the layout the existing suite expects.
 *
 * Used to mount the Adjust panel in ONE column or the other. Rendering it in
 * both behind `md:hidden` / `hidden md:block` would put two
 * `data-testid="adjust-panel"` nodes in the DOM and break every getByTestId.
 */
export function useIsDesktop(): boolean {
  const supported = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
  const [isDesktop, setIsDesktop] = useState(() =>
    supported ? window.matchMedia(DESKTOP_QUERY).matches : true)

  useEffect(() => {
    if (!supported) return
    const mq = window.matchMedia(DESKTOP_QUERY)
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    setIsDesktop(mq.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [supported])

  return isDesktop
}
