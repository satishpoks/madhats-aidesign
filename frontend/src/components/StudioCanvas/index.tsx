import { useStudioStore } from '../../store/studioStore'
import { PreviewPanel } from '../PreviewPanel'
import { CapSilhouette } from '../ProductPicker/CapSilhouette'
import type { PlacementZone, DecorationStyle } from '../../data/products'

const PLACEMENT_ZONES: { value: PlacementZone; label: string }[] = [
  { value: 'front', label: 'Front' },
  { value: 'side', label: 'Side' },
  { value: 'back', label: 'Back' },
  { value: 'under-brim', label: 'Under Brim' },
]

export function StudioCanvas() {
  const {
    selectedProduct, selectedSwatch,
    inputTab, setInputTab,
    promptText, setPromptText,
    uploadedFile, uploadedPreview, setUploadedFile,
    placementZone, setPlacementZone,
    decorationStyle, setDecorationStyle,
    generationState, triggerGenerate,
    setView, reset,
  } = useStudioStore()

  const isGenerating = generationState === 'generating'
  const canGenerate = inputTab === 'describe'
    ? promptText.trim().length > 0
    : uploadedFile !== null

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    setUploadedFile(file, url)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (!file) return
    const url = URL.createObjectURL(file)
    setUploadedFile(file, url)
  }

  const availableZones = selectedProduct
    ? PLACEMENT_ZONES.filter(z => selectedProduct.placementZones.includes(z.value))
    : PLACEMENT_ZONES

  return (
    <div className="min-h-screen bg-base flex flex-col">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
          <span className="text-border text-xl">|</span>
          <span className="text-textSub text-sm font-medium">AI Design Studio</span>
        </div>
        <button
          onClick={reset}
          className="text-xs text-textMuted hover:text-textPrimary transition-colors flex items-center gap-1"
        >
          ← Change style
        </button>
      </header>

      <div className="flex-1 flex flex-col lg:flex-row gap-0">
        {/* Left panel — inputs (40%) */}
        <div className="lg:w-[40%] border-r border-border p-6 flex flex-col gap-5">
          {/* Product chip */}
          {selectedProduct && (
            <div className="flex items-center gap-3 bg-surface border border-border rounded-xl p-3">
              <div className="w-12 h-12 shrink-0">
                <CapSilhouette
                  style={selectedProduct.style}
                  colour={selectedSwatch?.hex ?? selectedProduct.defaultColour}
                />
              </div>
              <div>
                <p className="text-sm font-semibold text-textPrimary">{selectedProduct.name}</p>
                <p className="text-xs text-textMuted">{selectedSwatch?.name} · {selectedProduct.brand}</p>
              </div>
            </div>
          )}

          {/* Tab switcher */}
          <div className="flex bg-surface border border-border rounded-xl p-1">
            {(['describe', 'upload'] as const).map(tab => (
              <button
                key={tab}
                onClick={() => setInputTab(tab)}
                className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${
                  inputTab === tab
                    ? 'bg-accent text-white shadow'
                    : 'text-textMuted hover:text-textPrimary'
                }`}
              >
                {tab === 'describe' ? 'Describe it' : 'Upload logo'}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {inputTab === 'describe' ? (
            <div className="flex flex-col gap-2">
              <textarea
                value={promptText}
                onChange={e => setPromptText(e.target.value)}
                placeholder="e.g. Navy snapback with gold embroidered club crest on the front panel, rope front, vintage feel…"
                rows={5}
                className="w-full bg-surface border border-border rounded-xl p-3 text-sm text-textPrimary placeholder:text-textMuted resize-none focus:outline-none focus:border-accent transition-colors"
              />
              <p className="text-xs text-textMuted">
                Describe placement, style, colours, and mood. Be specific for best results.
              </p>
            </div>
          ) : (
            <div
              onDrop={handleDrop}
              onDragOver={e => e.preventDefault()}
              className="border-2 border-dashed border-border rounded-xl p-6 flex flex-col items-center gap-3 cursor-pointer hover:border-accent transition-colors"
              onClick={() => document.getElementById('file-input')?.click()}
            >
              {uploadedPreview ? (
                <img src={uploadedPreview} alt="Uploaded logo" className="max-h-28 object-contain rounded-lg" />
              ) : (
                <>
                  <div className="w-10 h-10 rounded-full bg-surfaceAlt flex items-center justify-center text-xl">↑</div>
                  <p className="text-sm text-textMuted text-center">
                    Drop your logo here or <span className="text-accent">browse</span>
                  </p>
                  <p className="text-xs text-textMuted">PNG · JPG · SVG · WebP · max 10 MB</p>
                </>
              )}
              <input
                id="file-input"
                type="file"
                accept="image/png,image/jpeg,image/svg+xml,image/webp"
                className="hidden"
                onChange={handleFileChange}
              />
            </div>
          )}

          {/* Placement zone */}
          <div className="flex flex-col gap-2">
            <p className="text-xs text-textMuted uppercase tracking-widest font-medium">Placement zone</p>
            <div className="flex gap-2 flex-wrap">
              {availableZones.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => setPlacementZone(value)}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                    placementZone === value
                      ? 'bg-accent border-accent text-white'
                      : 'border-border text-textMuted hover:border-textSub hover:text-textPrimary'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Decoration style */}
          <div className="flex flex-col gap-2">
            <p className="text-xs text-textMuted uppercase tracking-widest font-medium">Decoration style</p>
            <div className="flex gap-2">
              {(['embroidery', 'print'] as DecorationStyle[]).map(s => (
                <button
                  key={s}
                  onClick={() => setDecorationStyle(s)}
                  disabled={selectedProduct && !selectedProduct.decorationTypes.includes(s)}
                  className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-all disabled:opacity-30 disabled:cursor-not-allowed ${
                    decorationStyle === s
                      ? 'bg-accent border-accent text-white'
                      : 'border-border text-textMuted hover:border-textSub hover:text-textPrimary'
                  }`}
                >
                  {s === 'embroidery' ? '🧵 Embroidery' : '🖨️ Print'}
                </button>
              ))}
            </div>
          </div>

          {/* Generate CTA */}
          <button
            onClick={triggerGenerate}
            disabled={!canGenerate || isGenerating}
            className="w-full py-3.5 rounded-xl bg-accent text-white font-bold text-sm disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accentHover transition-colors mt-auto"
          >
            {isGenerating ? (
              <span className="flex items-center justify-center gap-2">
                <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Generating…
              </span>
            ) : (
              'Generate Preview'
            )}
          </button>
        </div>

        {/* Right panel — preview (60%) */}
        <div className="lg:w-[60%] p-6">
          <PreviewPanel />
        </div>
      </div>
    </div>
  )
}
