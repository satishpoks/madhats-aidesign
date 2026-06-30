import { useEffect } from 'react'
import { useSessionStore } from './store/sessionStore'
import { ApiProductPicker } from './components/ApiProductPicker'
import { useStudioStore } from './store/studioStore'
import { StudioCanvas } from './components/StudioCanvas'
import { RefineScreen } from './components/RefineScreen'
import { WornScreen } from './components/WornScreen'
import { ConceptModal } from './components/ConceptModal'
import { ChatPanel } from './components/ChatPanel'

export default function App() {
  const sessionView = useSessionStore(s => s.view)
  const bootstrapFromUrl = useSessionStore(s => s.bootstrapFromUrl)
  const studioView = useStudioStore(s => s.view)

  useEffect(() => {
    void bootstrapFromUrl()
  }, [bootstrapFromUrl])

  // Session flow (new chatbot path) takes priority
  if (sessionView === 'session') {
    return <ChatPanel />
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
