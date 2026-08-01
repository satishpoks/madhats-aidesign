import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'
import { useBrandStore } from '../../store/brandStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { StoreHeader } from '../StoreHeader'
import { ChatColumn } from './ChatColumn'
import { MilestoneBar } from './MilestoneBar'
import { ColumnHeader } from './ColumnHeader'
import { useActiveSurface } from '../../lib/useActiveSurface'

/** Chat states where the chat surface is active (per useActiveSurface) but
 *  there is nothing the customer can actually answer: `await_email_verify`
 *  locks the whole input (ChatColumn's `inputLocked`) behind a waiting panel,
 *  and `generating`/`regenerating` are v1-delegated turns (null directive ->
 *  'chat') with no question pending either. The active card still lifts — the
 *  chat IS where to look — but the "Your turn — answer here" header would
 *  contradict the dead input right below it. The canvas header is unaffected. */
const CHAT_UNANSWERABLE_STATES = new Set(['await_email_verify', 'generating', 'regenerating'])

/** The active card lifts off the desk. No outline and no outward glow: a ring
 *  around a whole column is a developer's cue, and the glow bled into the
 *  neighbouring panel. */
const ACTIVE_CARD = 'shadow-[0_10px_24px_-10px_rgba(28,25,23,0.30),0_2px_6px_-2px_rgba(28,25,23,0.10)] border-border'
const RESTING_CARD = 'bg-surfaceAlt/40'
/** Applied to the resting column's CONTENT, never its container. The old
 *  blanket `opacity-60` faded live text to grey, so the half read as disabled
 *  rather than "not your turn". */
const RESTING_CONTENT = 'opacity-50 transition-opacity duration-300'

/**
 * CustomiseStudio — the split-screen canvas experience.
 * LEFT: the full interactive canvas studio (DesignStudioSurface).
 * RIGHT: a live chat column (ChatColumn), dormant until "See it rendered"
 *        hydrates the chat store, then driving verify → deliver → refine
 *        in place (no full-screen ChatPanel handoff).
 *
 * The two columns look identical at all times, so a non-technical customer had
 * no cue where to act on a given step. `useActiveSurface` answers that from the
 * backend directive; here it drives a permanent header on each column — the
 * active one fills and states the turn, the resting one just names its half.
 */
export function CustomiseStudio() {
  const productRef = useSessionStore(s => s.productRef)
  const active = useActiveSurface()
  const canvasActive = active === 'canvas'
  const chatState = useChatStore(s => s.chatState)
  const chatAnswerable = !CHAT_UNANSWERABLE_STATES.has(chatState)
  const personaName = useBrandStore(s => s.personaName) || 'Ricardo'

  return (
    <div className="h-screen bg-base flex flex-col">
      <StoreHeader title={productRef?.name} />
      <MilestoneBar />

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 bg-base p-2 md:flex-row">
        <div
          data-testid="canvas-column"
          data-active={String(canvasActive)}
          className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 ${canvasActive ? ACTIVE_CARD : RESTING_CARD}`}
        >
          <ColumnHeader name="Your design" instruction="Your turn — design here" active={canvasActive} />
          <div className={`flex min-h-0 min-w-0 flex-1 ${canvasActive ? '' : RESTING_CONTENT}`}>
            <DesignStudioSurface />
          </div>
        </div>

        {/* Chat width scales with the screen: a laptop/iPad keeps roughly the old
            width (the canvas is tight there), a desktop gives the conversation a
            noticeably bigger share. Mobile (`w-full` + the 45vh split) unchanged. */}
        <div
          data-testid="chat-column-wrap"
          data-active={String(!canvasActive)}
          className={`flex h-[45vh] w-full min-h-0 flex-none flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 md:h-auto md:w-[360px] lg:w-[420px] xl:w-[480px] 2xl:w-[560px] ${!canvasActive ? ACTIVE_CARD : RESTING_CARD}`}
        >
          <ColumnHeader
            name={personaName}
            instruction="Your turn — answer here"
            active={!canvasActive && chatAnswerable}
          />
          <div className={`flex min-h-0 flex-1 flex-col ${!canvasActive ? '' : RESTING_CONTENT}`}>
            <ChatColumn />
          </div>
        </div>
      </div>
    </div>
  )
}
