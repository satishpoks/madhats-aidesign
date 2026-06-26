import { useState, useRef, useCallback } from 'react'
import { useStudioStore } from '../../store/studioStore'
import { PreviewPanel } from '../PreviewPanel'
import { CapSilhouette } from '../ProductPicker/CapSilhouette'
import type { PlacementZone, DecorationStyle } from '../../data/products'

// Web Speech API types not in default TS lib
declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition
    webkitSpeechRecognition: typeof SpeechRecognition
  }
}

function useSpeechInput(onTranscript: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const recogRef = useRef<SpeechRecognition | null>(null)

  const toggle = useCallback(() => {
    const SR = window.SpeechRecognition ?? window.webkitSpeechRecognition
    if (!SR) return alert('Speech recognition is not supported in this browser.')

    if (listening) {
      recogRef.current?.stop()
      setListening(false)
      return
    }

    const r = new SR()
    r.continuous = true
    r.interimResults = false
    r.lang = 'en-AU'
    r.onresult = (e) => {
      const transcript = Array.from(e.results)
        .slice(e.resultIndex)
        .map(res => res[0].transcript)
        .join(' ')
      onTranscript(transcript.trim())
    }
    r.onend = () => setListening(false)
    r.onerror = () => setListening(false)
    r.start()
    recogRef.current = r
    setListening(true)
  }, [listening, onTranscript])

  return { listening, toggle }
}

const PLACEMENT_ZONES: { value: PlacementZone; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'front', label: 'Front' },
  { value: 'side', label: 'Side' },
  { value: 'back', label: 'Back' },
  { value: 'under-brim', label: 'Under Brim' },
]

const TABS = [
  { value: 'describe', label: 'Describe it' },
  { value: 'upload',   label: 'Upload logo' },
  { value: 'references', label: 'References' },
] as const

export function StudioCanvas() {
  const {
    selectedProduct, selectedSwatch,
    inputTab, setInputTab,
    promptText, setPromptText,
    uploadedFile, uploadedPreview, setUploadedFile,
    referenceFiles, referencePreviews, addReferenceFiles, removeReferenceFile,
    placementZone, setPlacementZone,
    decorationStyle, setDecorationStyle,
    generationState, triggerGenerate,
    setView, reset,
  } = useStudioStore()

  const appendTranscript = useCallback((text: string) => {
    const current = useStudioStore.getState().promptText
    setPromptText(current ? `${current} ${text}` : text)
  }, [setPromptText])

  const { listening, toggle: toggleMic } = useSpeechInput(appendTranscript)

  const isGenerating = generationState === 'generating'
  const canGenerate = inputTab === 'describe'
    ? promptText.trim().length > 0
    : inputTab === 'upload'
      ? uploadedFile !== null
      : referenceFiles.length > 0

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

  function handleRefDrop(e: React.DragEvent) {
    e.preventDefault()
    const dropped = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'))
    if (!dropped.length) return
    const previews = dropped.map(f => URL.createObjectURL(f))
    addReferenceFiles(dropped, previews)
  }

  function handleRefChange(e: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(e.target.files ?? []).filter(f => f.type.startsWith('image/'))
    if (!selected.length) return
    const previews = selected.map(f => URL.createObjectURL(f))
    addReferenceFiles(selected, previews)
    e.target.value = ''
  }

  const availableZones = selectedProduct
    ? [
        { value: 'auto' as PlacementZone, label: 'Auto' },
        ...PLACEMENT_ZONES.filter(z => z.value !== 'auto' && selectedProduct.placementZones.includes(z.value)),
      ]
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
          <div className="flex bg-surface border border-border rounded-xl p-1 gap-0.5">
            {TABS.map(({ value, label }) => (
              <button
                key={value}
                onClick={() => setInputTab(value)}
                className={`flex-1 py-2 text-xs font-medium rounded-lg transition-all ${
                  inputTab === value
                    ? 'bg-accent text-white shadow'
                    : 'text-textMuted hover:text-textPrimary'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {inputTab === 'describe' && (
            <div className="flex flex-col gap-2">
              <div className="relative">
                <textarea
                  value={promptText}
                  onChange={e => setPromptText(e.target.value)}
                  placeholder="e.g. Navy snapback with gold embroidered club crest on the front panel, rope front, vintage feel…"
                  rows={5}
                  className="w-full bg-surface border border-border rounded-xl p-3 pr-12 text-sm text-textPrimary placeholder:text-textMuted resize-none focus:outline-none focus:border-accent transition-colors"
                />
                <button
                  type="button"
                  onClick={toggleMic}
                  title={listening ? 'Stop recording' : 'Speak your idea'}
                  className={`absolute bottom-3 right-3 w-8 h-8 rounded-full flex items-center justify-center transition-all ${
                    listening
                      ? 'bg-red-500 text-white animate-pulse shadow-lg shadow-red-500/40'
                      : 'bg-surfaceAlt text-textMuted hover:text-accent hover:bg-surface border border-border'
                  }`}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                    <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4Z" />
                    <path d="M19 11a1 1 0 1 0-2 0 5 5 0 0 1-10 0 1 1 0 1 0-2 0 7 7 0 0 0 6 6.93V20H9a1 1 0 1 0 0 2h6a1 1 0 1 0 0-2h-2v-2.07A7 7 0 0 0 19 11Z" />
                  </svg>
                </button>
              </div>
              {listening && (
                <p className="text-xs text-red-400 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-red-400 animate-pulse" />
                  Listening… speak your design idea
                </p>
              )}
              {!listening && (
                <p className="text-xs text-textMuted">
                  Describe placement, style, colours, and mood — or tap the mic to speak.
                </p>
              )}
            </div>
          )}

          {inputTab === 'upload' && (
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

          {inputTab === 'references' && (
            <div className="flex flex-col gap-3">
              {/* Uploaded references grid */}
              {referencePreviews.length > 0 && (
                <div className="grid grid-cols-3 gap-2">
                  {referencePreviews.map((src, i) => (
                    <div key={i} className="relative group rounded-lg overflow-hidden border border-border aspect-square bg-surfaceAlt">
                      <img src={src} alt={`Reference ${i + 1}`} className="w-full h-full object-cover" />
                      <button
                        onClick={() => removeReferenceFile(i)}
                        className="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white text-xs flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        ×
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* Drop zone */}
              <div
                onDrop={handleRefDrop}
                onDragOver={e => e.preventDefault()}
                className="border-2 border-dashed border-border rounded-xl p-5 flex flex-col items-center gap-2 cursor-pointer hover:border-accent transition-colors"
                onClick={() => document.getElementById('ref-input')?.click()}
              >
                <div className="w-9 h-9 rounded-full bg-surfaceAlt flex items-center justify-center text-lg">+</div>
                <p className="text-sm text-textMuted text-center">
                  Add reference images or textures
                </p>
                <p className="text-xs text-textMuted">PNG · JPG · WebP · multiple allowed</p>
                <input
                  id="ref-input"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  multiple
                  className="hidden"
                  onChange={handleRefChange}
                />
              </div>
              <p className="text-xs text-textMuted">
                Upload colour swatches, texture samples, or style references. The AI will use these to guide the design.
              </p>
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
                  } ${value === 'auto' ? 'relative' : ''}`}
                >
                  {label}
                  {value === 'auto' && (
                    <span className="ml-1 text-[9px] opacity-70 uppercase tracking-wider">suggest</span>
                  )}
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
