/**
 * The permanent header strip on each half of the split screen.
 *
 * Active: filled with the canvas accent, white text, stating the turn.
 * Resting: a quiet grey label naming the half.
 *
 * A fixed NAME (not a status word) when resting, because it teaches a
 * first-time customer what the two halves are — the accent fill already
 * carries the whose-turn signal, so the label doesn't have to.
 *
 * `role="status"` only when active: the cue must be announced, and must never
 * be colour-only, but two live status regions would announce on every flip.
 */
export function ColumnHeader({ name, instruction, active }: {
  name: string
  instruction: string
  active: boolean
}) {
  return (
    <div
      {...(active ? { role: 'status' } : {})}
      className={`flex h-8 flex-none items-center gap-2 px-4 text-xs font-semibold transition-colors duration-300 ${
        active
          ? 'bg-canvasAccent text-white'
          : 'border-b border-border bg-surfaceAlt text-textMuted'
      }`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 flex-none rounded-full ${
          active ? 'animate-pulse bg-white' : 'bg-border'
        }`}
      />
      {active ? instruction : name}
    </div>
  )
}
