import { useEffect, useState } from 'react'
import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'
import { useBrandStore } from '../../store/brandStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { StoreHeader } from '../StoreHeader'
import { ChatColumn } from './ChatColumn'
import { MilestoneBar } from './MilestoneBar'
import { ColumnHeader } from './ColumnHeader'
import { RedirectCountdown } from './RedirectCountdown'
import { useActiveSurface, type ActiveSurface } from '../../lib/useActiveSurface'
import { useIsDesktop } from '../../lib/useIsDesktop'

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
 *  neighbouring panel. Elevation-only — both cards already share the same
 *  `border border-border` on their base container class, so the active card's
 *  border is not "stronger", only its shadow differs. */
const ACTIVE_CARD = 'shadow-[0_10px_24px_-10px_rgba(28,25,23,0.30),0_2px_6px_-2px_rgba(28,25,23,0.10)]'
const RESTING_CARD = 'bg-surfaceAlt/40'
/** Applied to the resting column's CONTENT, never its container. The old
 *  blanket `opacity-60` faded live text to grey, so the half read as disabled
 *  rather than "not your turn". */
const RESTING_CONTENT = 'opacity-50 transition-opacity duration-300'

/** Phone-only panel switcher. Desktop shows both halves side by side and never
 *  renders this. The dot marks the half the FLOW wants, which is only ever
 *  visible after a manual peek — auto-switch keeps them in agreement otherwise. */
function PanelTabs({ tab, wanted, onPick }: {
  tab: ActiveSurface
  wanted: ActiveSurface
  onPick: (t: ActiveSurface) => void
}) {
  const TABS: { id: ActiveSurface; label: string }[] = [
    { id: 'chat', label: 'Chat' },
    { id: 'canvas', label: 'Design' },
  ]
  return (
    <div data-testid="panel-tabs" role="tablist" aria-label="Studio panels"
         className="flex gap-1 border-b border-border bg-base px-2 py-1.5 md:hidden">
      {TABS.map(t => (
        <button
          key={t.id}
          data-testid={`tab-${t.id}`}
          role="tab"
          aria-selected={tab === t.id}
          onClick={() => onPick(t.id)}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
            tab === t.id
              ? 'bg-surface text-textPrimary shadow-sm'
              : 'text-textMuted hover:text-textPrimary'
          }`}
        >
          {t.label}
          {tab !== t.id && wanted === t.id && (
            <span aria-label="needs your attention"
                  className="h-1.5 w-1.5 rounded-full bg-accent" />
          )}
        </button>
      ))}
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
  const isDesktop = useIsDesktop()
  const triggerFinalize = useChatStore(s => s.triggerFinalize)

  // Phone: exactly one panel is shown. `tab` follows the backend-derived active
  // surface, but ONLY when that surface changes — which is what lets a manual
  // peek stick until the flow actually moves on. There is no second source of
  // truth: `active` remains the only thing that drives it automatically.
  const [tab, setTab] = useState<ActiveSurface>('chat')
  useEffect(() => { setTab(active) }, [active])

  // At FINALIZE_CANVAS the directive hands over no tool, so `active` is 'chat'
  // and the canvas would be display:none for the whole multi-face flatten loop
  // in Surface.doRender(). Konva would probably still paint a hidden element,
  // but a silently blank layout guide is catastrophic and hard to attribute —
  // so remove the dependency. It also shows the customer their design while it
  // is being captured. Deliberately NOT folded into useActiveSurface: that hook
  // answers "where should the customer act", a different question from "what
  // must be painted".
  useEffect(() => { if (triggerFinalize) setTab('canvas') }, [triggerFinalize])

  const showCanvas = isDesktop || tab === 'canvas'
  const showChat = isDesktop || tab === 'chat'

  return (
    <div className="h-screen bg-base flex flex-col">
      <StoreHeader title={productRef?.name} />
      <MilestoneBar />
      {!isDesktop && <PanelTabs tab={tab} wanted={active} onPick={setTab} />}

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex min-h-0 flex-1 flex-col gap-2 bg-base p-2 md:flex-row">
        <div
          data-testid="canvas-column"
          data-active={String(canvasActive)}
          className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 ${canvasActive ? ACTIVE_CARD : RESTING_CARD} ${showCanvas ? '' : 'hidden'}`}
        >
          <ColumnHeader name="Your design" instruction="Your turn — design here" active={canvasActive} tone="customer" />
          <div
            data-testid="canvas-column-content"
            className={`flex min-h-0 min-w-0 flex-1 ${canvasActive ? '' : RESTING_CONTENT}`}
          >
            <DesignStudioSurface />
          </div>
        </div>

        {/* Chat width scales with the screen: a laptop/iPad keeps roughly the old
            width (the canvas is tight there), a desktop gives the conversation a
            noticeably bigger share. Mobile: this used to be a hard `basis-[45vh]
            grow-0`, left over from when BOTH halves stacked on one screen at
            once and the chat was deliberately capped so the canvas got the
            rest. Since panels became one-at-a-time on mobile (PanelTabs, the
            other column gets `hidden` and contributes no height), that cap no
            longer has anything to share space WITH — it just pinned the chat
            to 45% of the row and left the other 55% empty under it, which is
            what "messages are barely visible" was reporting. `flex-1` (grow +
            shrink + basis-0) lets the shown panel fill the whole row instead.
            min-h-0 is what lets the flex child shrink below its content size
            at all — without it the message list cannot scroll.
            `md:flex-none` cancels ALL of grow/shrink/basis at md and up (not
            just shrink) so the explicit
            md:w-[360px]/lg:w-[420px]/xl:w-[480px]/2xl:w-[560px] widths are
            exactly what the desktop columns use, unchanged. */}
        <div
          data-testid="chat-column-wrap"
          data-active={String(!canvasActive)}
          className={`flex flex-1 w-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 md:flex-none md:w-[360px] lg:w-[420px] xl:w-[480px] 2xl:w-[560px] ${!canvasActive ? ACTIVE_CARD : RESTING_CARD} ${showChat ? '' : 'hidden'}`}
        >
          <ColumnHeader
            name={personaName}
            instruction="Your turn — answer here"
            active={!canvasActive && chatAnswerable}
            tone="primary"
          />
          <div
            data-testid="chat-column-content"
            className={`flex min-h-0 flex-1 flex-col ${!canvasActive ? '' : RESTING_CONTENT}`}
          >
            <ChatColumn />
          </div>
        </div>
      </div>
      <RedirectCountdown />
    </div>
  )
}
