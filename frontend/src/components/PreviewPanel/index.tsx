import { useStudioStore } from '../../store/studioStore'
import { CapSilhouette } from '../ProductPicker/CapSilhouette'

export function PreviewPanel() {
  const {
    generationState,
    generationMeta,
    viewImages,
    selectedProduct,
    selectedSwatch,
    setShowConceptModal,
  } = useStudioStore()

  const isGenerating = generationState === 'generating'
  const frontImage = viewImages.front
  const hasResult = generationState === 'done' && !!frontImage

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 relative rounded-2xl overflow-hidden bg-surfaceAlt border border-border min-h-[340px] flex items-center justify-center">
        {isGenerating && (
          <div className="absolute inset-0 shimmer rounded-2xl flex flex-col items-center justify-center gap-3">
            <div className="w-8 h-8 rounded-full border-2 border-accent border-t-transparent animate-spin" />
            <p className="text-textMuted text-sm">Generating 4 views…</p>
          </div>
        )}

        {hasResult && frontImage && (
          <img
            src={frontImage}
            alt="Generated cap mockup — front view"
            className="w-full h-full object-cover animate-fadeIn rounded-2xl"
          />
        )}

        {generationState === 'idle' && selectedProduct && (
          <div className="flex flex-col items-center gap-4 p-8 opacity-40">
            <div className="w-40 h-40">
              <CapSilhouette
                style={selectedProduct.style}
                colour={selectedSwatch?.hex ?? selectedProduct.defaultColour}
              />
            </div>
            <p className="text-textMuted text-sm text-center">Your design will appear here</p>
          </div>
        )}

        {hasResult && generationMeta && (
          <div className="absolute top-3 right-3 bg-black/60 backdrop-blur-sm border border-border rounded-lg px-3 py-1.5">
            <p className="text-xs text-textMuted font-mono">
              {generationMeta.model} · {(generationMeta.latency / 1000).toFixed(1)}s
            </p>
          </div>
        )}
      </div>

      <div className="mt-4">
        <button
          disabled={!hasResult}
          onClick={() => setShowConceptModal(true)}
          className="w-full py-2.5 rounded-xl bg-accent text-white text-sm font-semibold disabled:opacity-30 disabled:cursor-not-allowed hover:bg-accentHover transition-colors"
        >
          Request This Concept →
        </button>
      </div>
    </div>
  )
}
