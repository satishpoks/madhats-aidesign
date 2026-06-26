import { useEffect, useRef, useState } from 'react'
import { useStudioStore } from '../../store/studioStore'
import type { ChatMessage, AngleView } from '../../store/studioStore'
import { CapSilhouette } from '../ProductPicker/CapSilhouette'

// ─── Icons ────────────────────────────────────────────────────────────────────

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5" stroke="currentColor" strokeWidth={1.8}>
      <rect x="9" y="2" width="6" height="12" rx="3" fill={active ? 'currentColor' : 'none'} />
      <path d="M5 10a7 7 0 0 0 14 0" strokeLinecap="round" />
      <line x1="12" y1="19" x2="12" y2="22" strokeLinecap="round" />
      <line x1="8" y1="22" x2="16" y2="22" strokeLinecap="round" />
    </svg>
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" className="w-5 h-5" stroke="currentColor" strokeWidth={2}>
      <path d="M22 2L11 13" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M22 2L15 22 11 13 2 9l20-7z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

// ─── Cap view grid ────────────────────────────────────────────────────────────

const ANGLES: { key: AngleView; label: string }[] = [
  { key: 'front', label: 'Front' },
  { key: 'left',  label: 'Left'  },
  { key: 'right', label: 'Right' },
  { key: 'back',  label: 'Back'  },
]

function CapViewGrid() {
  const { viewImages, activeAngle, setActiveAngle, isRefining, generationState } = useStudioStore()
  const isGenerating = generationState === 'generating'

  return (
    <div className="grid grid-cols-2 gap-2 h-full">
      {ANGLES.map(({ key, label }) => {
        const src = viewImages[key]
        const isActive = activeAngle === key
        const loading = !src && (isGenerating || isRefining)

        return (
          <button
            key={key}
            onClick={() => src && setActiveAngle(key)}
            className={`relative rounded-xl overflow-hidden border-2 transition-all ${
              isActive && src
                ? 'border-accent shadow-[0_0_0_1px_#FF5C00]'
                : 'border-border hover:border-textMuted'
            } ${!src ? 'cursor-default' : 'cursor-pointer'}`}
          >
            {src ? (
              <img src={src} alt={label} className="w-full h-full object-cover animate-fadeIn" />
            ) : (
              <div className={`w-full h-full min-h-[100px] ${loading ? 'shimmer' : 'bg-surfaceAlt'} flex items-center justify-center`}>
                {loading && (
                  <div className="w-5 h-5 rounded-full border-2 border-accent border-t-transparent animate-spin" />
                )}
              </div>
            )}
            {/* Angle label */}
            <div className="absolute bottom-0 inset-x-0 bg-gradient-to-t from-black/70 to-transparent px-2 py-1.5">
              <span className={`text-xs font-semibold ${isActive && src ? 'text-accent' : 'text-white/80'}`}>
                {label}
              </span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

// ─── Chat bubbles ─────────────────────────────────────────────────────────────

function Bubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'} animate-fadeIn`}>
      <div className={`w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-xs font-bold mt-0.5 ${
        isUser ? 'bg-accent text-white' : 'bg-surface border border-border text-textMuted'
      }`}>
        {isUser ? 'You' : 'AI'}
      </div>
      <div className={`flex flex-col gap-2 max-w-[80%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-accent text-white rounded-tr-sm'
            : 'bg-surface border border-border text-textPrimary rounded-tl-sm'
        }`}>
          {msg.text}
        </div>
        {msg.imageUrl && (
          <img src={msg.imageUrl} alt="Result" className="w-28 h-20 object-cover rounded-xl border border-border shadow-md" />
        )}
        {msg.latency != null && (
          <span className="text-xs text-textMuted font-mono px-1">{(msg.latency / 1000).toFixed(1)}s · gemini-flash</span>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex gap-3 animate-fadeIn">
      <div className="w-8 h-8 rounded-full shrink-0 bg-surface border border-border flex items-center justify-center text-xs text-textMuted font-bold">AI</div>
      <div className="bg-surface border border-border px-5 py-3.5 rounded-2xl rounded-tl-sm flex gap-1.5 items-center">
        {[0,1,2].map(i => (
          <span key={i} className="w-1.5 h-1.5 rounded-full bg-textMuted animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
        ))}
      </div>
    </div>
  )
}

const SUGGESTIONS = [
  'Make the text bolder',
  'Try a different colour',
  'Move logo to the side',
  'Add a shadow effect',
  'Make it more vintage',
]

// ─── Main ─────────────────────────────────────────────────────────────────────

export function RefineScreen() {
  const {
    selectedProduct, selectedSwatch,
    viewImages, activeAngle, generationMeta, isRefining,
    messages, refineText, setRefineText, triggerRefine,
    triggerGenerateWorn,
    setView, setShowConceptModal, reset,
  } = useStudioStore()

  const [isListening, setIsListening] = useState(false)
  const [voiceSupported] = useState(() =>
    typeof window !== 'undefined' &&
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
  )

  const bottomRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)
  const iterationCount = messages.filter(m => m.role === 'assistant').length
  const allViewsReady = Object.values(viewImages).every(Boolean)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isRefining])

  function handleSend() {
    const text = refineText.trim()
    if (!text || isRefining) return
    triggerRefine(text)
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() }
  }

  function handleSuggestion(s: string) {
    setRefineText(s)
    setTimeout(() => triggerRefine(s), 50)
  }

  function toggleVoice() {
    if (!voiceSupported) return
    if (isListening) { recognitionRef.current?.stop(); setIsListening(false); return }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    const r = new SR()
    r.lang = 'en-AU'; r.continuous = false; r.interimResults = true
    recognitionRef.current = r
    r.onstart = () => setIsListening(true)
    r.onend = () => setIsListening(false)
    r.onresult = (event) => {
      const t = Array.from(event.results).map(res => res[0].transcript).join('')
      setRefineText(t)
      if (event.results[event.results.length - 1].isFinal) setTimeout(() => triggerRefine(t), 200)
    }
    r.start()
  }

  const heroSrc = viewImages[activeAngle] ?? viewImages.front

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
              <div className="w-6 h-6"><CapSilhouette style={selectedProduct.style} colour={selectedSwatch?.hex ?? selectedProduct.defaultColour} /></div>
              <span className="text-textSub text-sm">{selectedProduct.name}</span>
              <span className="text-textMuted text-xs">· {selectedSwatch?.name}</span>
            </div>
          </>
        )}
        <div className="ml-auto flex items-center gap-3">
          <button onClick={() => setView('studio')} className="text-xs text-textMuted hover:text-textPrimary border border-border rounded-lg px-3 py-1.5 transition-colors">
            ← Edit design
          </button>
          <button onClick={reset} className="text-xs text-textMuted hover:text-textPrimary transition-colors">Start over</button>
        </div>
      </header>

      {/* Body */}
      <div className="flex-1 flex overflow-hidden">

        {/* Left — 4-angle grid + actions */}
        <div className="w-[48%] border-r border-border flex flex-col gap-4 p-5">

          {/* Section label */}
          <div className="flex items-center justify-between shrink-0">
            <p className="text-xs text-textMuted uppercase tracking-widest font-medium">4-angle preview</p>
            {generationMeta && allViewsReady && (
              <span className="text-xs text-textMuted font-mono bg-surface border border-border px-2 py-0.5 rounded-full">
                {(generationMeta.latency / 1000).toFixed(1)}s · {generationMeta.model}
              </span>
            )}
          </div>

          {/* 2×2 grid */}
          <div className="flex-1 min-h-0">
            <CapViewGrid />
          </div>

          {/* Version badge */}
          {iterationCount > 1 && (
            <div className="shrink-0 flex justify-center">
              <span className="text-xs text-accent border border-accent/30 bg-accent/10 px-3 py-1 rounded-full">
                v{iterationCount} — {iterationCount} iterations
              </span>
            </div>
          )}

          {/* Actions */}
          <div className="shrink-0 flex flex-col gap-2">
            <button
              onClick={triggerGenerateWorn}
              disabled={!allViewsReady || isRefining}
              className="w-full py-2.5 rounded-xl border border-accent text-accent text-sm font-semibold disabled:opacity-30 disabled:cursor-not-allowed hover:bg-accent hover:text-white transition-all"
            >
              ✦ Generate Worn Mockups (4 angles)
            </button>
            <button
              disabled={!allViewsReady}
              onClick={() => setShowConceptModal(true)}
              className="w-full py-2.5 rounded-xl bg-accent text-white text-sm font-semibold disabled:opacity-30 hover:bg-accentHover transition-colors"
            >
              Request Concept →
            </button>
          </div>
        </div>

        {/* Right — chat */}
        <div className="flex-1 flex flex-col overflow-hidden">

          <div className="shrink-0 px-6 py-4 border-b border-border flex items-center gap-2">
            <div className="w-2 h-2 rounded-full bg-accent animate-pulse" />
            <span className="text-sm font-semibold text-textPrimary">Refine your design</span>
            <span className="ml-auto text-xs text-textMuted bg-surface border border-border px-2.5 py-1 rounded-full">
              {iterationCount} {iterationCount === 1 ? 'version' : 'versions'}
            </span>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-5">
            {messages.map(msg => <Bubble key={msg.id} msg={msg} />)}
            {isRefining && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>

          {!isRefining && messages.length <= 2 && (
            <div className="shrink-0 px-6 pb-3 flex gap-2 flex-wrap">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => handleSuggestion(s)}
                  className="text-xs text-textMuted border border-border rounded-full px-3 py-1.5 hover:border-accent hover:text-textPrimary transition-all">
                  {s}
                </button>
              ))}
            </div>
          )}

          <div className="shrink-0 px-6 pb-5 pt-2">
            <div className={`flex gap-3 items-end bg-surface border rounded-2xl px-4 py-3 transition-colors ${
              isListening ? 'border-accent shadow-[0_0_0_2px_rgba(255,92,0,0.15)]' : 'border-border focus-within:border-accent'
            }`}>
              <textarea
                value={refineText}
                onChange={e => setRefineText(e.target.value)}
                onKeyDown={handleKey}
                placeholder={isListening ? 'Listening…' : 'Describe a change — or tap the mic to speak…'}
                rows={1}
                disabled={isRefining}
                className="flex-1 bg-transparent text-sm text-textPrimary placeholder:text-textMuted resize-none focus:outline-none disabled:opacity-50 leading-relaxed max-h-28"
                onInput={e => {
                  const t = e.currentTarget; t.style.height = 'auto'
                  t.style.height = Math.min(t.scrollHeight, 112) + 'px'
                }}
              />
              <div className="flex gap-2 items-center shrink-0">
                <button onClick={toggleVoice}
                  className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                    isListening ? 'bg-accent text-white shadow-[0_0_14px_rgba(255,92,0,0.4)]'
                      : voiceSupported ? 'text-textMuted hover:text-textPrimary hover:bg-surfaceAlt'
                      : 'text-border cursor-not-allowed'
                  }`}>
                  <MicIcon active={isListening} />
                </button>
                <button onClick={handleSend} disabled={!refineText.trim() || isRefining}
                  className="w-9 h-9 rounded-xl bg-accent flex items-center justify-center text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-accentHover transition-colors">
                  <SendIcon />
                </button>
              </div>
            </div>
            {isListening && (
              <p className="text-xs text-accent mt-2 ml-1 animate-pulse">Listening… speak your change and it will generate automatically</p>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
