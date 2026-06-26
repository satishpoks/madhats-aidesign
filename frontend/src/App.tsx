import { useStudioStore } from './store/studioStore'
import { ProductPicker } from './components/ProductPicker'
import { StudioCanvas } from './components/StudioCanvas'
import { RefineScreen } from './components/RefineScreen'
import { WornScreen } from './components/WornScreen'
import { ConceptModal } from './components/ConceptModal'

export default function App() {
  const view = useStudioStore(s => s.view)

  return (
    <>
      {view === 'picker'  && <ProductPicker />}
      {view === 'studio'  && <StudioCanvas />}
      {view === 'refine'  && <RefineScreen />}
      {view === 'worn'    && <WornScreen />}
      <ConceptModal />
    </>
  )
}
