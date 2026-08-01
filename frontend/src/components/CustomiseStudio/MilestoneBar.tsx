import { useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import { restartFlow } from '../../lib/restartFlow'

/**
 * Start-over control, right-aligned in the progress bar.
 *
 * Two-step inline confirm rather than `window.confirm` — a restart discards the
 * whole design, and a native dialog blocks the page (and the browser-automation
 * channel we verify this flow with) until it is dismissed.
 */
function RestartButton() {
  const [confirming, setConfirming] = useState(false)

  if (confirming) {
    return (
      <div className="flex shrink-0 items-center gap-1.5">
        <span className="hidden text-[11px] text-textMuted sm:inline">Discard this design?</span>
        <button
          type="button"
          onClick={restartFlow}
          className="rounded-full bg-accent px-2.5 py-1 text-[11px] font-semibold text-white hover:opacity-90"
        >
          Yes, start over
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded-full border border-border px-2.5 py-1 text-[11px] text-textPrimary hover:bg-border/30"
        >
          Cancel
        </button>
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={() => setConfirming(true)}
      title="Start the whole design again from the beginning"
      className="flex shrink-0 items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[11px] text-textMuted hover:border-accent hover:text-accent"
    >
      <span aria-hidden="true">↻</span>
      Start over
    </button>
  )
}

/**
 * MilestoneBar — a full-width labeled 5-dot stepper for the v2 canvas flow,
 * with a right-aligned "Start over" control.
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
      {/* The stepper keeps its own max-width and stays centred in the leftover
          space; the restart control sits hard right and never shrinks it. */}
      <div className="flex items-center gap-3">
        <ol className="flex flex-1 items-start justify-between gap-1 max-w-3xl mx-auto min-w-0">
        {sections.map((label, i) => {
          const state = i < active ? 'complete' : i === active ? 'current' : 'upcoming'
          const isLast = i === sections.length - 1
          return (
            <li
              key={label}
              data-testid={`milestone-${label}`}
              data-state={state}
              aria-current={state === 'current' ? 'step' : undefined}
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
        <RestartButton />
      </div>
    </nav>
  )
}
