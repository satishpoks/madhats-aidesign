import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function TypingIndicator() {
  return (
    <div className="flex justify-start">
      <div className="bg-surface border border-border px-4 py-3 rounded-2xl rounded-bl-sm">
        <div className="flex gap-1 items-center">
          <span
            className="w-2 h-2 bg-textMuted rounded-full animate-bounce"
            style={{ animationDelay: '0ms' }}
          />
          <span
            className="w-2 h-2 bg-textMuted rounded-full animate-bounce"
            style={{ animationDelay: '150ms' }}
          />
          <span
            className="w-2 h-2 bg-textMuted rounded-full animate-bounce"
            style={{ animationDelay: '300ms' }}
          />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ChatPanel() {
  // Session store
  const sessionId = useSessionStore(s => s.sessionId)
  const productRef = useSessionStore(s => s.productRef)

  // Chat store
  const messages = useChatStore(s => s.messages)
  const chatState = useChatStore(s => s.chatState)
  const options = useChatStore(s => s.options)
  const options2 = useChatStore(s => s.options2)
  const triggerGeneration = useChatStore(s => s.triggerGeneration)
  const continuable = useChatStore(s => s.continuable)
  const sending = useChatStore(s => s.sending)
  const chatError = useChatStore(s => s.chatError)
  const kickoff = useChatStore(s => s.kickoff)
  const sendMessage = useChatStore(s => s.sendMessage)
  const dismissError = useChatStore(s => s.dismissError)

  const [inputText, setInputText] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Kick off the conversation once the session ID is available
  useEffect(() => {
    if (sessionId) {
      void kickoff(sessionId)
    }
  }, [sessionId, kickoff])

  // Auto-scroll to the newest message
  useEffect(() => {
    // scrollIntoView may be absent in jsdom; use optional chaining on the method itself
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages, sending])

  // ---------------------------------------------------------------------------
  // Handlers
  // ---------------------------------------------------------------------------

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const text = inputText.trim()
    if (!text || !sessionId || sending) return
    setInputText('')
    void sendMessage(sessionId, text)
  }

  function handleChip(text: string) {
    if (!sessionId || sending) return
    void sendMessage(sessionId, text)
  }

  // Statement-only states are flagged authoritatively by the backend
  // (`data.continuable`). We never infer "no options ⇒ Continue", because
  // free-text states (ask_name, ask_purpose, describe_design) also have no
  // options but expect a typed answer, not a throwaway "ok".
  const isStatementOnly = continuable && !sending

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="min-h-screen bg-base flex flex-col">
      {/* ------------------------------------------------------------------ */}
      {/* App header                                                          */}
      {/* ------------------------------------------------------------------ */}
      <header className="border-b border-border px-6 py-4 flex items-center gap-3 flex-shrink-0">
        <span className="text-accent font-bold text-xl tracking-tight">MadHats</span>
        <span className="text-border text-xl">|</span>
        <span className="text-textSub text-sm font-medium">AI Design Studio</span>
      </header>

      {/* ------------------------------------------------------------------ */}
      {/* Product context strip                                               */}
      {/* ------------------------------------------------------------------ */}
      {productRef && (
        <div className="flex items-center gap-3 px-6 py-3 bg-surface border-b border-border flex-shrink-0">
          {productRef.reference_image_url && (
            <img
              src={productRef.reference_image_url}
              alt={productRef.name}
              className="w-12 h-12 object-cover rounded-lg flex-shrink-0"
              loading="lazy"
            />
          )}
          <div className="min-w-0">
            <p className="text-textPrimary text-sm font-semibold leading-tight truncate">
              {productRef.name}
            </p>
            {productRef.colour && (
              <p className="text-textMuted text-xs mt-0.5">{productRef.colour}</p>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Error banner                                                        */}
      {/* ------------------------------------------------------------------ */}
      {chatError && (
        <div
          role="alert"
          className="mx-6 mt-4 flex items-start gap-3 rounded-xl border border-red-800 bg-red-950/40 px-4 py-3 flex-shrink-0"
        >
          <p className="flex-1 text-sm text-red-300">{chatError}</p>
          <button
            aria-label="Dismiss error"
            onClick={dismissError}
            className="flex-shrink-0 text-xs text-red-400 hover:text-red-200 transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Message list                                                        */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 flex flex-col gap-3 min-h-0">
        {messages.map(msg => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[80%] md:max-w-md px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-accent text-white rounded-br-sm'
                  : 'bg-surface text-textPrimary border border-border rounded-bl-sm'
              }`}
            >
              {msg.text}
            </div>
          </div>
        ))}

        {sending && <TypingIndicator />}

        <div ref={messagesEndRef} />
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Bottom panel: special banners, chips, input                        */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-shrink-0 flex flex-col gap-3 px-4 md:px-6 pb-6 pt-2">
        {/* Special state: logo upload placeholder */}
        {chatState === 'upload_logo' && (
          <p className="text-center text-textMuted text-xs py-2 px-4 bg-surface border border-border rounded-lg">
            Logo upload — coming next
          </p>
        )}

        {/* Special state: generation placeholder */}
        {(chatState === 'generating' || triggerGeneration) && (
          <p className="text-center text-textMuted text-xs py-2 px-4 bg-surface border border-border rounded-lg">
            Generating your design… (preview coming next)
          </p>
        )}

        {/* Option chip rows */}
        {options.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {options.map(opt => (
              <button
                key={opt}
                onClick={() => handleChip(opt)}
                disabled={sending}
                className="px-4 py-2 bg-surface border border-border rounded-full text-sm text-textPrimary hover:border-accent hover:text-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {opt}
              </button>
            ))}
          </div>
        )}

        {options2.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {options2.map(opt => (
              <button
                key={opt}
                onClick={() => handleChip(opt)}
                disabled={sending}
                className="px-4 py-2 bg-surface border border-border rounded-full text-sm text-textPrimary hover:border-accent hover:text-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {opt}
              </button>
            ))}
          </div>
        )}

        {/* Continue affordance for statement-only states */}
        {isStatementOnly && (
          <div className="flex">
            <button
              onClick={() => handleChip('ok')}
              disabled={sending}
              className="px-5 py-2 bg-surface border border-accent rounded-full text-sm text-accent hover:bg-accent hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Continue
            </button>
          </div>
        )}

        {/* Text input */}
        <form onSubmit={handleSubmit} className="flex gap-3">
          <input
            type="text"
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder="Type a message…"
            disabled={sending}
            className="flex-1 bg-surface border border-border rounded-xl px-4 py-3 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            disabled={sending || !inputText.trim()}
            className="bg-accent hover:bg-accentHover text-white px-5 py-3 rounded-xl text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
