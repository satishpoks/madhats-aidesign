/**
 * Floating "tools" toggle — mobile only. On a phone the tool rail and the
 * Adjust sheet used to be either always taking up space below/over the cap,
 * or (post 2026-08 fixes) gated behind other panels with no obvious way back.
 * This is a small persistent affordance, bottom-left, that toggles whichever
 * of the two (rail or sheet) is contextually relevant — Surface decides which
 * one `onToggle` actually affects and what `open`/`pulse` mean this turn; this
 * component is a dumb, prop-driven renderer (same contract as ToolRail).
 *
 * Deliberately a plain fixed-position element, NOT portalled: unlike the
 * Adjust sheet (which must dodge CanvasStage's sibling-height walk — see
 * SelectedToolbar's portal comment) this button is rendered as a sibling of
 * the whole Surface root, outside the centre column CanvasStage measures, so
 * there is nothing here for that walk to pick up.
 *
 * `isDesktop` gates rendering ENTIRELY (returns null), not just via a
 * `md:hidden` class — jsdom performs no layout, so a CSS-only hide would still
 * leave the button in the DOM for every desktop-path test to trip over, and
 * the owner was explicit: "Desktop must be completely unchanged."
 */
export function MobileToolsButton({ isDesktop, open, pulse, onToggle }: {
  isDesktop: boolean
  open: boolean
  pulse: boolean
  onToggle: () => void
}) {
  if (isDesktop) return null

  return (
    <button
      type="button"
      data-testid="mobile-tools-toggle"
      onClick={onToggle}
      aria-pressed={open}
      aria-label={open ? 'Hide tools' : 'Show tools'}
      title={open ? 'Hide tools' : 'Show tools'}
      className={`fixed left-3 bottom-3 z-40 flex h-11 w-11 items-center justify-center rounded-full bg-canvasAccent text-white shadow-lg hover:bg-canvasAccentHover transition-colors${
        pulse ? ' ring-2 ring-canvasAccent ring-offset-2 ring-offset-surface animate-pulse' : ''
      }`}
    >
      <span aria-hidden="true" className="text-lg leading-none">{open ? '✕' : '🛠'}</span>
    </button>
  )
}
