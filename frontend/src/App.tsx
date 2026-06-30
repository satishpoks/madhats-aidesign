import { useEffect } from 'react'
import { useSessionStore } from './store/sessionStore'
import { ApiProductPicker } from './components/ApiProductPicker'
import { useStudioStore } from './store/studioStore'
import { StudioCanvas } from './components/StudioCanvas'
import { RefineScreen } from './components/RefineScreen'
import { WornScreen } from './components/WornScreen'
import { ConceptModal } from './components/ConceptModal'

/**
 * Minimal placeholder shown when a session was bootstrapped from URL params.
 * The real chat UI is wired in the next task.
 */
function SessionStub() {
  const productRef = useSessionStore(s => s.productRef)
  const state = useSessionStore(s => s.state)

  return (
    <div className="min-h-screen bg-base flex flex-col">
      <header className="border-b border-border px-6 py-4 flex items-center gap-3">
        <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
        <span className="text-border text-xl">|</span>
        <span className="text-textSub text-sm font-medium">AI Design Studio</span>
      </header>
      <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center px-4">
        <p className="text-textPrimary font-semibold text-lg">
          {productRef?.name ?? 'Loading product…'}
        </p>
        {productRef?.colour && (
          <p className="text-textMuted text-sm">{productRef.colour}</p>
        )}
        {state && (
          <p className="text-textSub text-xs font-mono mt-1">{state}</p>
        )}
        <p className="text-textMuted text-xs mt-4 opacity-60">Chat UI coming in next task</p>
      </div>
    </div>
  )
}

export default function App() {
  const sessionView = useSessionStore(s => s.view)
  const bootstrapFromUrl = useSessionStore(s => s.bootstrapFromUrl)
  const studioView = useStudioStore(s => s.view)

  useEffect(() => {
    void bootstrapFromUrl()
  }, [bootstrapFromUrl])

  // Session flow (new chatbot path) takes priority
  if (sessionView === 'session') {
    return <SessionStub />
  }

  // Old studio flow — preserved for existing functionality
  if (studioView !== 'picker') {
    return (
      <>
        {studioView === 'studio' && <StudioCanvas />}
        {studioView === 'refine' && <RefineScreen />}
        {studioView === 'worn' && <WornScreen />}
        <ConceptModal />
      </>
    )
  }

  // Default: new API-driven product picker entry
  return (
    <>
      <ApiProductPicker />
      <ConceptModal />
    </>
  )
}
