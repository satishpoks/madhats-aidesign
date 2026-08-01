/**
 * Restarting the design flow from the absolute start.
 *
 * A restart must throw away EVERYTHING — the backend session, the chat thread,
 * the canvas blob, any generated designs — so it is deliberately a full page
 * navigation rather than a set of store `reset()` calls: a reload is the only
 * thing that provably clears every store (including ones added later) plus the
 * module-level latches (`sessionStore`'s `bootstrapping`, `Surface`'s finalize
 * refs, `lib/textMetrics`' measurement map) that a manual reset would miss.
 *
 * The entry params are preserved so the customer lands where they came in:
 * `?product_id=…` boots a brand-new canvas session on the same cap, `?mode=blank`
 * returns to the hat picker. The one param that MUST go is `session` — the
 * resume token from the preview email's edit link, which would rehydrate the
 * very session being abandoned.
 */

/** Pure: the URL a restart should navigate to, given the current search string. */
export function restartUrl(pathname: string, search: string): string {
  const params = new URLSearchParams(search)
  params.delete('session')
  const qs = params.toString()
  return qs ? `${pathname}?${qs}` : pathname
}

/** Navigate to a fresh start. `assign` (not `replace`) so Back still works. */
export function restartFlow() {
  window.location.assign(restartUrl(window.location.pathname, window.location.search))
}
