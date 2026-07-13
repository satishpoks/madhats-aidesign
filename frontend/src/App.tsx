import { useEffect } from 'react'
import { useSessionStore } from './store/sessionStore'
import { ApiProductPicker } from './components/ApiProductPicker'
import { BlankHatPicker } from './components/BlankHatPicker'
import { DesignStudio } from './components/DesignStudio'
import { useStudioStore } from './store/studioStore'
import { StudioCanvas } from './components/StudioCanvas'
import { RefineScreen } from './components/RefineScreen'
import { WornScreen } from './components/WornScreen'
import { ConceptModal } from './components/ConceptModal'
import { ChatPanel } from './components/ChatPanel'
import AdminApp from './admin/AdminApp'

export default function App() {
  if (typeof window !== 'undefined' && window.location.pathname.startsWith('/admin')) {
    return <AdminApp />
  }

  const sessionView = useSessionStore(s => s.view)
  const bootstrapFromUrl = useSessionStore(s => s.bootstrapFromUrl)
  const studioView = useStudioStore(s => s.view)

  useEffect(() => {
    void bootstrapFromUrl()
  }, [bootstrapFromUrl])

  if (sessionView === 'canvas') {
    return <DesignStudio />
  }

  // Session flow (new chatbot path) takes priority
  if (sessionView === 'session') {
    return <ChatPanel />
  }

  if (sessionView === 'blank') {
    return <BlankHatPicker />
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
