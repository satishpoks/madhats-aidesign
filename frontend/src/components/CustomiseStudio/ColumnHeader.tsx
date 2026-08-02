/**
 * The permanent header strip on each half of the split screen.
 *
 * Active: filled with a tone-specific colour, white text, stating the turn.
 * Resting: a quiet grey label naming the half.
 *
 * A fixed NAME (not a status word) when resting, because it teaches a
 * first-time customer what the two halves are — the accent fill already
 * carries the whose-turn signal, so the label doesn't have to.
 *
 * `role="status"` only when active: the cue must be announced, and must never
 * be colour-only, but two live status regions would announce on every flip.
 *
 * The active fill is picked by `tone`, not hardcoded: the assistant half
 * carries the store's brand primary, the customer half carries the
 * customer's own chat bubble colour. Canvas accent belongs to the design
 * tools only and is deliberately never used here.
 */
/** Which colour the ACTIVE fill uses. Two values, not a free class string, so
 *  the palette split is enumerable and a caller cannot invent a third half.
 *  'primary'  = the store's brand primary (--brand-primary) — the assistant.
 *  'customer' = the customer's own chat bubble colour (--chat-user-bubble).
 *  Canvas accent is deliberately absent: it belongs to the design tools. */
export type HeaderTone = 'primary' | 'customer'

const TONE_FILL: Record<HeaderTone, string> = {
  primary: 'bg-accent text-white',
  customer: 'bg-chatUserBubble text-white',
}

export function ColumnHeader({ name, instruction, active, tone }: {
  name: string
  instruction: string
  active: boolean
  tone: HeaderTone
}) {
  return (
    <div
      {...(active ? { role: 'status' } : {})}
      className={`flex h-8 flex-none items-center gap-2 px-4 text-xs font-semibold transition-colors duration-300 ${
        active ? TONE_FILL[tone] : 'border-b border-border bg-surfaceAlt text-textMuted'
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
