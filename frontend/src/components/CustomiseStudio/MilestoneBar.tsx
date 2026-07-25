import { useChatStore } from '../../store/chatStore'

/**
 * MilestoneBar — a full-width labeled 5-dot stepper for the v2 canvas flow.
 *
 * It reads progress from the chat store and self-hides unless
 * `progress.sections` is present. Only the v2 orchestrator
 * (state_machine_v2.progress_for) emits `sections`, so this renders for v2
 * canvas sessions only — v1 and non-canvas flows fall through to null.
 */
export function MilestoneBar() {
  const progress = useChatStore(s => s.progress)
  if (!progress?.sections || progress.sections.length === 0) return null

  const sections = progress.sections
  const active = progress.section ?? 0

  return (
    <nav
      aria-label="Design progress"
      className="w-full border-b border-border bg-base px-4 py-3"
    >
      <ol className="flex items-start justify-between gap-1 max-w-3xl mx-auto">
        {sections.map((label, i) => {
          const state = i < active ? 'complete' : i === active ? 'current' : 'upcoming'
          const isLast = i === sections.length - 1
          return (
            <li
              key={label}
              data-testid={`milestone-${label}`}
              data-state={state}
              className="relative flex flex-1 flex-col items-center min-w-0"
            >
              {/* Connector track to the NEXT dot; filled if this dot is done. */}
              {!isLast && (
                <span
                  aria-hidden
                  className={`absolute top-2.5 left-1/2 h-0.5 w-full ${
                    i < active ? 'bg-accent' : 'bg-border'
                  }`}
                />
              )}
              {/* Dot */}
              <span
                aria-hidden
                className={`relative z-10 flex h-5 w-5 items-center justify-center rounded-full border-2 text-[10px] font-bold ${
                  state === 'complete'
                    ? 'border-accent bg-accent text-white'
                    : state === 'current'
                    ? 'border-accent bg-base text-accent ring-4 ring-accent/20'
                    : 'border-border bg-base text-textMuted'
                }`}
              >
                {state === 'complete' ? '✓' : i + 1}
              </span>
              {/* Label */}
              <span
                className={`mt-1.5 text-center text-[10px] sm:text-xs leading-tight ${
                  state === 'upcoming'
                    ? 'text-textMuted'
                    : 'text-textPrimary font-medium'
                }`}
              >
                {label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
