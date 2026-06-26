import { useEffect, useRef, useState } from 'react'
import { useStudioStore } from '../../store/studioStore'
import type { ChatMessage } from '../../store/studioStore'

declare global {
  interface Window {
    SpeechRecognition: typeof SpeechRecognition
    webkitSpeechRecognition: typeof SpeechRecognition
  }
}

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

function Message({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      <div className={`w-7 h-7 rounded-full shrink-0 flex items-center justify-center text-xs font-bold ${
        isUser ? 'bg-accent text-white' : 'bg-surfaceAlt border border-border text-textMuted'
      }`}>
        {isUser ? 'Y' : 'AI'}
      </div>
      <div className={`max-w-[75%] flex flex-col gap-1.5 ${isUser ? 'items-end' : 'items-start'}`}>
        <div className={`px-3.5 py-2.5 rounded-2xl text-sm leading-relaxed ${
          isUser
            ? 'bg-accent text-white rounded-tr-sm'
            : 'bg-surfaceAlt border border-border text-textPrimary rounded-tl-sm'
        }`}>
          {msg.text}
        </div>
        {msg.imageUrl && (
          <img
            src={msg.imageUrl}
            alt="Generated result"
            className="w-32 h-24 object-cover rounded-xl border border-border shadow-lg cursor-pointer hover:scale-105 transition-transform"
          />
        )}
        {msg.latency && (
          <span className="text-xs text-textMuted font-mono">{(msg.latency / 1000).toFixed(1)}s</span>
        )}
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="w-7 h-7 rounded-full shrink-0 bg-surfaceAlt border border-border flex items-center justify-center text-xs font-bold text-textMuted">
        AI
      </div>
      <div className="bg-surfaceAlt border border-border px-4 py-3 rounded-2xl rounded-tl-sm flex gap-1 items-center">
        {[0, 1, 2].map(i => (
          <span
            key={i}
            className="w-1.5 h-1.5 rounded-full bg-textMuted animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  )
}

export function RefineChat() {
  const { messages, refineText, setRefineText, triggerRefine, isRefining } = useStudioStore()
  const [isListening, setIsListening] = useState(false)
  const [voiceSupported] = useState(() =>
    typeof window !== 'undefined' && ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)
  )
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const recognitionRef = useRef<SpeechRecognition | null>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isRefining])

  function handleSend() {
    if (!refineText.trim() || isRefining) return
    triggerRefine(refineText)
  }

  function handleKey(e: React.KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  function toggleVoice() {
    if (!voiceSupported) return

    if (isListening) {
      recognitionRef.current?.stop()
      setIsListening(false)
      return
    }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition
    const recognition = new SR()
    recognition.lang = 'en-AU'
    recognition.continuous = false
    recognition.interimResults = true
    recognitionRef.current = recognition

    recognition.onstart = () => setIsListening(true)
    recognition.onend = () => setIsListening(false)

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map(r => r[0].transcript)
        .join('')
      setRefineText(transcript)
      if (event.results[event.results.length - 1].isFinal) {
        setTimeout(() => {
          triggerRefine(transcript)
        }, 200)
      }
    }

    recognition.start()
  }

  return (
    <div className="flex flex-col border-t border-border bg-base animate-fadeIn">
      {/* Header */}
      <div className="px-5 py-3 flex items-center gap-2 border-b border-border">
        <div className="w-2 h-2 rounded-full bg-accent animate-pulse" />
        <span className="text-xs font-semibold text-textSub uppercase tracking-widest">Refine your design</span>
        <span className="ml-auto text-xs text-textMuted">{messages.length > 0 ? `${Math.ceil(messages.length / 2)} iteration${messages.length > 2 ? 's' : ''}` : ''}</span>
      </div>

      {/* Chat thread */}
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4 max-h-64 min-h-[120px]">
        {messages.map(msg => (
          <Message key={msg.id} msg={msg} />
        ))}
        {isRefining && <TypingIndicator />}
        <div ref={bottomRef} />
      </div>

      {/* Input bar */}
      <div className="px-4 pb-4 pt-2">
        <div className={`flex gap-2 items-end bg-surface border rounded-2xl px-4 py-3 transition-colors ${
          isListening ? 'border-accent shadow-[0_0_0_2px_rgba(255,92,0,0.2)]' : 'border-border focus-within:border-accent'
        }`}>
          <textarea
            ref={inputRef}
            value={refineText}
            onChange={e => setRefineText(e.target.value)}
            onKeyDown={handleKey}
            placeholder={isListening ? 'Listening…' : 'Describe a change, e.g. "make the text gold" or "move logo to the side"…'}
            rows={1}
            disabled={isRefining}
            className="flex-1 bg-transparent text-sm text-textPrimary placeholder:text-textMuted resize-none focus:outline-none disabled:opacity-50 max-h-24 leading-relaxed"
            style={{ height: 'auto' }}
            onInput={e => {
              const t = e.currentTarget
              t.style.height = 'auto'
              t.style.height = Math.min(t.scrollHeight, 96) + 'px'
            }}
          />

          <div className="flex gap-2 items-center shrink-0 pb-0.5">
            {/* Mic button */}
            <button
              onClick={toggleVoice}
              title={voiceSupported ? (isListening ? 'Stop listening' : 'Speak your changes') : 'Voice not supported in this browser'}
              className={`w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                isListening
                  ? 'bg-accent text-white shadow-[0_0_12px_rgba(255,92,0,0.5)]'
                  : voiceSupported
                    ? 'text-textMuted hover:text-textPrimary hover:bg-surfaceAlt'
                    : 'text-border cursor-not-allowed'
              }`}
            >
              <MicIcon active={isListening} />
            </button>

            {/* Send button */}
            <button
              onClick={handleSend}
              disabled={!refineText.trim() || isRefining}
              className="w-9 h-9 rounded-xl bg-accent flex items-center justify-center text-white disabled:opacity-30 disabled:cursor-not-allowed hover:bg-accentHover transition-colors"
            >
              <SendIcon />
            </button>
          </div>
        </div>

        {isListening && (
          <p className="text-xs text-accent mt-1.5 ml-1 animate-pulse">
            Listening — speak your change, then it will generate automatically
          </p>
        )}
      </div>
    </div>
  )
}
