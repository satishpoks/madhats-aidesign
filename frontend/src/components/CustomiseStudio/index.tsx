import { useSessionStore } from '../../store/sessionStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { StoreHeader } from '../StoreHeader'
import { ChatColumn } from './ChatColumn'

/**
 * CustomiseStudio — the split-screen canvas experience.
 * LEFT: the full interactive canvas studio (DesignStudioSurface).
 * RIGHT: a live chat column (ChatColumn), dormant until "See it rendered"
 *        hydrates the chat store, then driving verify → deliver → refine
 *        in place (no full-screen ChatPanel handoff).
 */
export function CustomiseStudio() {
  const productRef = useSessionStore(s => s.productRef)

  return (
    <div className="h-screen bg-base flex flex-col">
      <StoreHeader subtitle={productRef ? `${productRef.name} › Design` : undefined} />

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <div className="flex-1 flex min-h-0 min-w-0">
          <DesignStudioSurface />
        </div>
        <div className="border-t md:border-t-0 md:border-l border-border flex-shrink-0 w-full md:w-[380px] h-[45vh] md:h-auto flex flex-col min-h-0">
          <ChatColumn />
        </div>
      </div>
    </div>
  )
}
