import { useSessionStore } from '../../store/sessionStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { StoreHeader } from '../StoreHeader'
import { ChatColumn } from './ChatColumn'
import { MilestoneBar } from './MilestoneBar'
import { useActiveSurface, type ActiveSurface } from '../../lib/useActiveSurface'

/** Ring + glow on the panel the customer should act in; a scrim on the other.
 *  The glow reads `--brand-primary` so it themes per store, the same way
 *  `text-accent` / `bg-accent` already do. */
const ACTIVE_CLASSES =
  'ring-2 ring-accent shadow-[0_0_18px_-4px_var(--brand-primary,#FF5C00)] ' +
  'transition-[opacity,box-shadow] duration-300'
/** Deliberately NOT `pointer-events-none`: dimming is a cue, not a lock. The
 *  real locking is per-affordance (CanvasStage `locked`, ToolRail
 *  `allowedTools`, ChatColumn `inputLocked`). Blocking pointer events here
 *  would also stop the customer scrolling back through the thread or
 *  re-reading the cap, which they must always be able to do. */
const INACTIVE_CLASSES = 'opacity-60 transition-[opacity,box-shadow] duration-300'

function FocusPill({ surface }: { surface: ActiveSurface }) {
  return (
    <div
      role="status"
      className="mx-4 mt-3 self-start inline-flex items-center gap-1.5 rounded-full bg-accent/10 border border-accent px-3 py-1 text-xs font-semibold text-accent"
    >
      <span aria-hidden="true">▶</span>
      {surface === 'canvas' ? 'Your turn — design here' : 'Your turn — answer here'}
    </div>
  )
}

/**
 * CustomiseStudio — the split-screen canvas experience.
 * LEFT: the full interactive canvas studio (DesignStudioSurface).
 * RIGHT: a live chat column (ChatColumn), dormant until "See it rendered"
 *        hydrates the chat store, then driving verify → deliver → refine
 *        in place (no full-screen ChatPanel handoff).
 *
 * The two columns look identical at all times, so a non-technical customer had
 * no cue where to act on a given step. `useActiveSurface` answers that from the
 * backend directive; here it drives a ring + glow on one column and a scrim on
 * the other, plus a named pill (so the cue is never colour-only).
 */
export function CustomiseStudio() {
  const productRef = useSessionStore(s => s.productRef)
  const active = useActiveSurface()
  const canvasActive = active === 'canvas'

  return (
    <div className="h-screen bg-base flex flex-col">
      <StoreHeader subtitle={productRef ? `${productRef.name} › Design` : undefined} />
      <MilestoneBar />

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <div
          data-testid="canvas-column"
          data-active={String(canvasActive)}
          className={`flex-1 flex flex-col min-h-0 min-w-0 ${canvasActive ? ACTIVE_CLASSES : INACTIVE_CLASSES}`}
        >
          {canvasActive && <FocusPill surface="canvas" />}
          <div className="flex-1 flex min-h-0 min-w-0">
            <DesignStudioSurface />
          </div>
        </div>
        {/* Chat width scales with the screen: a laptop/iPad keeps roughly the old
            width (the canvas is tight there), a desktop gives the conversation a
            noticeably bigger share. Mobile (`w-full` + the 45vh split) unchanged. */}
        <div
          data-testid="chat-column-wrap"
          data-active={String(!canvasActive)}
          className={`border-t md:border-t-0 md:border-l border-border flex-shrink-0 w-full md:w-[360px] lg:w-[420px] xl:w-[480px] 2xl:w-[560px] h-[45vh] md:h-auto flex flex-col min-h-0 ${!canvasActive ? ACTIVE_CLASSES : INACTIVE_CLASSES}`}
        >
          {!canvasActive && <FocusPill surface="chat" />}
          <ChatColumn />
        </div>
      </div>
    </div>
  )
}
