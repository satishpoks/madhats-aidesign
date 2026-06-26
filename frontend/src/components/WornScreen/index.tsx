import { useStudioStore } from '../../store/studioStore'
import type { AngleView } from '../../store/studioStore'
import { CapSilhouette } from '../ProductPicker/CapSilhouette'

const ANGLES: { key: AngleView; label: string; desc: string }[] = [
  { key: 'front', label: 'Front',  desc: 'Facing forward' },
  { key: 'left',  label: 'Left',   desc: '45° left profile' },
  { key: 'right', label: 'Right',  desc: '45° right profile' },
  { key: 'back',  label: 'Back',   desc: 'Rear view' },
]

function MockupCard({ angleKey, label, desc }: { angleKey: AngleView; label: string; desc: string }) {
  const { wornImages, isGeneratingWorn } = useStudioStore()
  const src = wornImages[angleKey]
  const loading = !src && isGeneratingWorn

  return (
    <div className="relative rounded-2xl overflow-hidden border border-border bg-surfaceAlt aspect-[3/4]">
      {src ? (
        <>
          <img src={src} alt={label} className="w-full h-full object-cover animate-fadeIn" />
          {/* Overlay label */}
          <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/80 via-black/30 to-transparent px-4 py-4">
            <p className="text-white font-semibold text-sm">{label}</p>
            <p className="text-white/60 text-xs">{desc}</p>
          </div>
        </>
      ) : (
        <div className={`w-full h-full flex flex-col items-center justify-center gap-3 ${loading ? 'shimmer' : ''}`}>
          {loading ? (
            <div className="w-8 h-8 rounded-full border-2 border-accent border-t-transparent animate-spin" />
          ) : (
            <div className="text-textMuted text-xs">{label}</div>
          )}
        </div>
      )}
    </div>
  )
}

export function WornScreen() {
  const {
    selectedProduct, selectedSwatch,
    wornImages, isGeneratingWorn,
    setView, setShowConceptModal, reset,
  } = useStudioStore()

  const allDone = Object.values(wornImages).every(Boolean) && !isGeneratingWorn
  const anyDone = Object.values(wornImages).some(Boolean)

  return (
    <div className="h-screen bg-base flex flex-col overflow-hidden">

      {/* Header */}
      <header className="shrink-0 border-b border-border px-6 py-3.5 flex items-center gap-3">
        <span className="text-accent font-bold text-lg tracking-tight">MadHats</span>
        <span className="text-border">|</span>
        <span className="text-textMuted text-sm">AI Design Studio</span>
        {selectedProduct && (
          <>
            <span className="text-border">·</span>
            <div className="flex items-center gap-2">
              <div className="w-6 h-6">
                <CapSilhouette style={selectedProduct.style} colour={selectedSwatch?.hex ?? selectedProduct.defaultColour} />
              </div>
              <span className="text-textSub text-sm">{selectedProduct.name}</span>
              <span className="text-textMuted text-xs">· {selectedSwatch?.name}</span>
            </div>
          </>
        )}
        <div className="ml-auto flex items-center gap-3">
          <button onClick={() => setView('refine')} className="text-xs text-textMuted hover:text-textPrimary border border-border rounded-lg px-3 py-1.5 transition-colors">
            ← Back to design
          </button>
          <button onClick={reset} className="text-xs text-textMuted hover:text-textPrimary transition-colors">Start over</button>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 flex flex-col overflow-hidden p-6 gap-5">

        {/* Title row */}
        <div className="shrink-0 flex items-end justify-between">
          <div>
            <h2 className="text-xl font-bold text-textPrimary">
              Worn mockups
              {isGeneratingWorn && (
                <span className="ml-3 text-sm font-normal text-accent animate-pulse">Generating…</span>
              )}
              {allDone && (
                <span className="ml-3 text-sm font-normal text-green-400">Complete</span>
              )}
            </h2>
            <p className="text-sm text-textMuted mt-0.5">
              AI-generated model wearing your design — 4 angles, generic model only
            </p>
          </div>

          {anyDone && (
            <button
              disabled={!allDone}
              onClick={() => setShowConceptModal(true)}
              className="py-2 px-6 rounded-xl bg-accent text-white text-sm font-semibold disabled:opacity-40 hover:bg-accentHover transition-colors"
            >
              Request This Concept →
            </button>
          )}
        </div>

        {/* 4-card grid */}
        <div className="flex-1 min-h-0 grid grid-cols-4 gap-4">
          {ANGLES.map(a => (
            <MockupCard key={a.key} angleKey={a.key} label={a.label} desc={a.desc} />
          ))}
        </div>

        {/* Footer note */}
        <p className="shrink-0 text-xs text-textMuted text-center">
          These are AI-generated previews using a generic model. Your design team reviews before any production artwork is created.
        </p>
      </div>
    </div>
  )
}
