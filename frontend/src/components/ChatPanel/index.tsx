import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'
import { useGenerationStore } from '../../store/generationStore'
import { ProductViewer } from '../ProductViewer'
import { Modal } from '../Modal'
import { usePushToTalk } from '../../hooks/usePushToTalk'
import { uploadLogo, addPin, postComposite } from '../../lib/api'

// ---------------------------------------------------------------------------
// TypingIndicator
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
// LogoUploader — shown when chatState === 'upload_logo'
// ---------------------------------------------------------------------------

interface LogoUploaderProps {
  sessionId: string
  onDone: () => void
}

function LogoUploader({ sessionId, onDone }: LogoUploaderProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setPreviewUrl(URL.createObjectURL(file))
    setUploading(true)
    setUploadError(null)

    try {
      await uploadLogo(sessionId, file)
      onDone()
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="flex flex-col gap-3 p-4 bg-surface border border-border rounded-xl">
      <p className="text-sm text-textSub font-medium">Upload your logo</p>

      {/* File input — visually styled via label; input is sr-only but accessible */}
      {!previewUrl && (
        <div className="flex items-center gap-3">
          <label
            htmlFor="logo-upload-input"
            className="cursor-pointer px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-lg text-sm font-medium transition-colors"
          >
            Select logo
          </label>
          <input
            id="logo-upload-input"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            onChange={handleFileChange}
            disabled={uploading}
            className="sr-only"
            aria-label="Choose logo file"
          />
          <span className="text-xs text-textMuted">PNG, JPG, GIF or WebP · max 10 MB</span>
        </div>
      )}

      {/* Thumbnail + status */}
      {previewUrl && (
        <div className="flex items-center gap-3">
          <img
            src={previewUrl}
            alt="Logo preview"
            className="w-16 h-16 object-contain rounded-lg border border-border bg-base flex-shrink-0"
          />
          <div className="flex flex-col gap-1">
            {uploading && (
              <span className="text-sm text-textMuted">Uploading…</span>
            )}
            {uploadError && (
              <span className="text-sm text-red-600">{uploadError}</span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// PinAnnotator — shown when chatState === 'pin_annotate_mode'
// ---------------------------------------------------------------------------

interface SavedPin {
  view: string
  x_pct: number
  y_pct: number
}

interface PinAnnotatorProps {
  sessionId: string
  viewImages: Record<string, string>
  fallbackUrl: string
  onSendMessage: (text: string) => void
  onError: (msg: string) => void
}

export function PinAnnotator({
  sessionId,
  viewImages,
  fallbackUrl,
  onSendMessage,
  onError,
}: PinAnnotatorProps) {
  const availableViews = Object.entries(viewImages)
  const defaultView = availableViews[0]?.[0] ?? ''

  const [activeView, setActiveView] = useState(defaultView)
  const [pendingPin, setPendingPin] = useState<{ x_pct: number; y_pct: number } | null>(null)
  const [comment, setComment] = useState('')
  const [savedPins, setSavedPins] = useState<SavedPin[]>([])
  const [saving, setSaving] = useState(false)
  const [postSaveActions, setPostSaveActions] = useState(false)

  const currentImageUrl = viewImages[activeView] ?? fallbackUrl

  function handleImageClick(e: React.MouseEvent<HTMLImageElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const x_pct = Math.min(100, Math.max(0, ((e.clientX - rect.left) / rect.width) * 100))
    const y_pct = Math.min(100, Math.max(0, ((e.clientY - rect.top) / rect.height) * 100))
    setPendingPin({ x_pct, y_pct })
    setPostSaveActions(false)
  }

  async function handleSavePin() {
    if (!pendingPin || saving) return
    setSaving(true)
    try {
      await addPin(sessionId, {
        view: activeView || 'front',
        x_pct: pendingPin.x_pct,
        y_pct: pendingPin.y_pct,
        comment,
      })
      setSavedPins(prev => [...prev, { view: activeView || 'front', ...pendingPin }])
      setPendingPin(null)
      setComment('')
      setPostSaveActions(true)
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Failed to save pin')
    } finally {
      setSaving(false)
    }
  }

  function handleSwitchView(view: string) {
    setActiveView(view)
    setPendingPin(null)
  }

  return (
    <div className="flex flex-col gap-3 p-4 bg-surface border border-border rounded-xl">
      {/* View tabs — only when multiple angles available */}
      {availableViews.length > 1 && (
        <div className="flex gap-2 flex-wrap">
          {availableViews.map(([view]) => (
            <button
              key={view}
              onClick={() => handleSwitchView(view)}
              className={`px-3 py-1 rounded-full text-xs capitalize transition-colors ${
                activeView === view
                  ? 'bg-accent text-white'
                  : 'bg-base border border-border text-textMuted hover:border-accent hover:text-accent'
              }`}
            >
              {view}
            </button>
          ))}
        </div>
      )}

      {/* Cap image with pin overlay */}
      <div className="relative">
        <img
          src={currentImageUrl}
          alt={`${activeView || 'product'} view`}
          className="w-full rounded-lg cursor-crosshair select-none"
          onClick={handleImageClick}
          draggable={false}
        />

        {/* Pending pin (orange) */}
        {pendingPin && (
          <div
            className="absolute w-4 h-4 bg-accent rounded-full border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none shadow"
            style={{ left: `${pendingPin.x_pct}%`, top: `${pendingPin.y_pct}%` }}
            aria-hidden="true"
          />
        )}

        {/* Saved pins (green), filtered to the current view */}
        {savedPins
          .filter(p => p.view === (activeView || 'front'))
          .map((p, i) => (
            <div
              key={i}
              className="absolute w-4 h-4 bg-green-500 rounded-full border-2 border-white -translate-x-1/2 -translate-y-1/2 pointer-events-none shadow"
              style={{ left: `${p.x_pct}%`, top: `${p.y_pct}%` }}
              aria-hidden="true"
            />
          ))}
      </div>

      {/* Comment input + save — shown while a pending pin exists */}
      {pendingPin && (
        <div className="flex gap-2">
          <input
            type="text"
            value={comment}
            onChange={e => setComment(e.target.value)}
            placeholder="Describe this placement…"
            className="flex-1 bg-base border border-border rounded-xl px-3 py-2 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent transition-colors"
          />
          <button
            onClick={() => void handleSavePin()}
            disabled={saving}
            className="px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-xl text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {saving ? 'Saving…' : 'Save pin'}
          </button>
        </div>
      )}

      {/* Post-save actions */}
      {postSaveActions && (
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => {
              setPostSaveActions(false)
              onSendMessage('add another')
            }}
            className="px-4 py-2 bg-surface border border-border rounded-full text-sm text-textPrimary hover:border-accent hover:text-accent transition-colors"
          >
            Add another
          </button>
          <button
            onClick={() => onSendMessage('done')}
            className="px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-medium transition-colors"
          >
            Done — generate
          </button>
        </div>
      )}

      {!pendingPin && !postSaveActions && (
        <p className="text-xs text-textMuted text-center">
          Click anywhere on the cap to drop a placement pin
        </p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// GenerationPanel — shown while/after the design renders (state 'generating')
// ---------------------------------------------------------------------------

function GenerationPanel() {
  const status = useGenerationStore(s => s.status)

  return (
    <div className="flex flex-col gap-3 p-4 bg-surface border border-border rounded-xl">
      {(status === 'generating' || status === 'idle') && (
        <div className="flex items-center gap-3 py-2">
          <span className="w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-textMuted">Generating your design…</span>
        </div>
      )}
      {/* The finished design is intentionally NOT shown in-chat — it's delivered
          only via email once the customer confirms their address. Generation may
          succeed, fail (auto-retried, then ops regenerates), or time out — the
          customer is NEVER told it failed; the design still arrives by email once
          their address is confirmed. `done` and `error` both render the same
          reassurance so a failure is indistinguishable to the customer. */}
      {(status === 'done' || status === 'error') && (
        <div className="flex items-center gap-3 py-2">
          <span className="text-green-500 text-lg leading-none">✓</span>
          <span className="text-sm text-textMuted">
            Your design is ready — we'll email it to you once your address is confirmed.
          </span>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// ChatPanel — main component
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
  const triggerRegeneration = useChatStore(s => s.triggerRegeneration)
  const continuable = useChatStore(s => s.continuable)
  const progress = useChatStore(s => s.progress)
  const sending = useChatStore(s => s.sending)
  const chatError = useChatStore(s => s.chatError)
  const kickoff = useChatStore(s => s.kickoff)
  const sendMessage = useChatStore(s => s.sendMessage)
  const pollVerification = useChatStore(s => s.pollVerification)
  const advanceRegeneration = useChatStore(s => s.advanceRegeneration)
  const advanceGeneration = useChatStore(s => s.advanceGeneration)
  const dismissError = useChatStore(s => s.dismissError)
  const setError = useChatStore(s => s.setError)

  // Generation store
  const startGeneration = useGenerationStore(s => s.startGeneration)
  const startRegeneration = useGenerationStore(s => s.startRegeneration)
  const designs = useGenerationStore(s => s.designs)
  const genStatus = useGenerationStore(s => s.status)

  // The design is delivered by email only once the address is verified — the
  // on-screen viewer must not reveal it any earlier. These are the chat states
  // reachable only after verification + a completed generation.
  const RELEASED_STATES = [
    'email_verified',
    'send_preview_email',
    'show_design',
    'offer_refine',
    'describe_changes',
    'refine_followup',
    'refine_confirm',
    'regenerating',
    'quote_requested',
    'upsell_prompt',
    'session_end',
  ]
  const designReleased = RELEASED_STATES.includes(chatState)

  // The backend only sets data.composite_preview: true for the
  // composite_preview state (see orchestrator.py _state_data_extra), so the
  // chat state name is an equivalent, already-exposed signal — no need to
  // thread the raw `data` payload through the store for this one flag.
  const compositePreview = chatState === 'composite_preview'
  // Blank flow: once a colour is chosen the backend advertises tint_ready +
  // tint_hex on every turn, so the left viewer can show the blank tinted to
  // that colour instantly (no image generation).
  const tintReady = useChatStore(s => s.tintReady)
  const tintHex = useChatStore(s => s.tintHex)
  const colourSwatches = useChatStore(s => s.colourSwatches)
  const colourPicker = useChatStore(s => s.colourPicker)

  // Composited blank-hat views (front/back/left/right). Fetched the moment a
  // colour is chosen (tint_ready), and again at composite_preview (which also
  // overlays the decoration elements). Keyed on colour + purpose so a colour
  // change — or the move to the element-composited preview — re-fetches.
  const [composite, setComposite] = useState<Record<string, string> | null>(null)
  const lastCompositeKey = useRef<string | null>(null)
  useEffect(() => {
    if (!sessionId) return
    if (!tintReady && !compositePreview) {
      if (composite) {
        setComposite(null)
        lastCompositeKey.current = null
      }
      return
    }
    const key = `${compositePreview ? 'preview' : 'tint'}:${tintHex}`
    if (lastCompositeKey.current === key) return
    lastCompositeKey.current = key
    void postComposite(sessionId).then(
      r => setComposite(r.views),
      () => setComposite({}),
    )
  }, [tintReady, tintHex, compositePreview, sessionId, composite])

  const [inputText, setInputText] = useState('')
  // Custom hat colour chosen via the native colour picker (blank-hat colour
  // step). Sent as a hex string, which the backend accepts directly for the tint.
  const [customColour, setCustomColour] = useState('#1e40af')
  // Lets the customer dismiss the logo-upload modal (to type a different reply)
  // without losing the ability to reopen it. Reset whenever we leave the state.
  const [logoModalDismissed, setLogoModalDismissed] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const wasSendingRef = useRef(false)

  // Reset the logo-modal dismissal each time the flow leaves the upload step.
  useEffect(() => {
    if (chatState !== 'upload_logo') setLogoModalDismissed(false)
  }, [chatState])

  // Kick off the conversation once the session ID is available
  useEffect(() => {
    if (sessionId) {
      void kickoff(sessionId)
    }
  }, [sessionId, kickoff])

  // Trigger async generation when the flow reaches the generating state, then
  // advance the chat once it settles (success or failure) so the customer is
  // never stranded at 'generating'. startGeneration() is once-guarded per session.
  useEffect(() => {
    if (sessionId && (triggerGeneration || chatState === 'generating')) {
      void startGeneration(sessionId).then(
        () => advanceGeneration(sessionId),
        () => advanceGeneration(sessionId),
      )
    }
  }, [sessionId, triggerGeneration, chatState, startGeneration, advanceGeneration])

  // Trigger regeneration when the flow reaches the regenerating state (a
  // requested change). Not once-guarded — each edit fires a fresh run. Chains
  // the chat advance (regenerating -> offer_refine) after the regeneration
  // promise settles, success or failure, so the customer is never stranded.
  useEffect(() => {
    if (sessionId && triggerRegeneration) {
      void startRegeneration(sessionId).then(
        () => advanceRegeneration(sessionId),
        () => advanceRegeneration(sessionId),
      )
    }
  }, [sessionId, triggerRegeneration, startRegeneration, advanceRegeneration])

  // While waiting at verify_email, poll for the out-of-band email verification
  // (the customer clicks the emailed link, possibly in another tab/device) and
  // surface the confirmation in the thread the moment it lands.
  useEffect(() => {
    if (!sessionId || chatState !== 'verify_email') return
    const id = setInterval(() => {
      void pollVerification(sessionId)
    }, 4000)
    return () => clearInterval(id)
  }, [sessionId, chatState, pollVerification])

  // Auto-scroll to the newest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' })
  }, [messages, sending])

  // Return focus to the message box once a send completes (the input is
  // disabled while sending, so focus is lost) — so the customer can keep
  // typing the next message without re-clicking. Skipped for the special
  // states whose primary affordance isn't the text box.
  useEffect(() => {
    const justFinished = wasSendingRef.current && !sending
    wasSendingRef.current = sending
    if (justFinished && chatState !== 'upload_logo' && chatState !== 'pin_annotate_mode') {
      inputRef.current?.focus()
    }
  }, [sending, chatState])

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

  // Voice input — hold SPACEBAR (or press-and-hold the mic) to talk; the
  // transcript is dictated INTO the message box so the user can review/edit
  // it before pressing Send (it is not sent automatically). Disabled while a
  // send is in flight so a held space can't fire mid-request.
  const speech = usePushToTalk(
    (transcript: string) => {
      setInputText(prev => (prev ? `${prev} ${transcript}` : transcript))
    },
    { enabled: !sending },
  )

  // Surface a blocked/unavailable mic through the shared error banner so the
  // user learns why "Press Space to Talk" did nothing and how to fix it.
  useEffect(() => {
    if (speech.error) setError(speech.error)
  }, [speech.error, setError])

  const isStatementOnly = continuable && !sending

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="h-screen bg-base flex flex-col">
      {/* App header (Figma: white bar with MAD HATS + product breadcrumb) */}
      <header className="bg-surface border-b border-border px-6 py-3.5 flex items-center gap-3 flex-shrink-0">
        <span className="text-accent font-extrabold text-lg tracking-wide">MAD HATS</span>
        {productRef && (
          <span className="text-sm text-textMuted truncate">
            {productRef.name}
            <span className="mx-1.5 text-textMuted/60">›</span>
            <span className="text-textSub">Customize</span>
          </span>
        )}
      </header>

      {/* Two-pane studio: product views (left) + Ricardo chat (right) */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        {/* LEFT — product viewer, or the pin annotator while marking placement.
            Pin annotation runs here (on the big image) rather than crammed into
            the chat column, using the space the product image already occupies. */}
        <div className="h-72 md:h-auto md:w-1/2 border-b md:border-b-0 md:border-r border-border flex-shrink-0 md:flex-shrink overflow-y-auto">
          {chatState === 'pin_annotate_mode' && sessionId && productRef ? (
            <div className="h-full p-4 md:p-6 bg-base">
              <PinAnnotator
                sessionId={sessionId}
                viewImages={productRef.view_images}
                fallbackUrl={productRef.reference_image_url}
                onSendMessage={text => void sendMessage(sessionId, text)}
                onError={setError}
              />
            </div>
          ) : (
            /* The generated design is shown on-screen only once released —
               email verified AND generation complete — matching the same gate
               as the emailed preview. Before that, the viewer shows only the
               blank product angles. */
            <ProductViewer
              productRef={productRef}
              designUrls={designReleased ? designs : []}
              compositeViews={composite ?? undefined}
              generating={genStatus === 'generating'}
            />
          )}
        </div>

        {/* RIGHT — chat column */}
        <div className="flex-1 md:w-1/2 flex flex-col min-h-0">

      {/* Chat header — Ricardo identity + online status */}
      <div className="flex items-center gap-3 px-4 md:px-6 py-3 border-b border-border bg-surfaceAlt/40 flex-shrink-0">
        <span className="w-9 h-9 rounded-full bg-accent flex-shrink-0" aria-hidden="true" />
        <div className="leading-tight">
          <p className="text-sm font-semibold text-textPrimary">Ricardo — MadHats AI</p>
          <p className="text-xs text-green-600 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
            Online
          </p>
        </div>
        {progress && progress.step < progress.total && (
          <span className="ml-auto text-xs font-medium text-textMuted">
            Step {progress.step} of {progress.total}
          </span>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Error banner                                                        */}
      {/* ------------------------------------------------------------------ */}
      {chatError && (
        <div
          role="alert"
          className="mx-6 mt-4 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 flex-shrink-0"
        >
          <p className="flex-1 text-sm text-red-700">{chatError}</p>
          <button
            aria-label="Dismiss error"
            onClick={dismissError}
            className="flex-shrink-0 text-xs text-red-500 hover:text-red-700 transition-colors"
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
              className={`max-w-[80%] md:max-w-md px-4 py-2.5 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-accent text-white rounded-br-sm'
                  : 'bg-surface text-textPrimary border border-border rounded-bl-sm shadow-sm'
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
      {/* Bottom panel: special states, chips, input                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex-shrink-0 flex flex-col gap-3 px-4 md:px-6 pb-6 pt-4 border-t border-border">
        {/* Special state: logo upload — surfaced as a prominent modal dialog.
            Dismissible so the customer can instead type a different reply (e.g.
            "actually I'll describe it"); a reopen button keeps the uploader
            one tap away while the flow is still on this step. */}
        {sessionId && (
          <Modal
            open={chatState === 'upload_logo' && !logoModalDismissed}
            title="Upload your logo"
            onClose={() => setLogoModalDismissed(true)}
          >
            <LogoUploader
              sessionId={sessionId}
              onDone={() => void sendMessage(sessionId, 'Uploaded my logo')}
            />
          </Modal>
        )}
        {chatState === 'upload_logo' && logoModalDismissed && (
          <button
            onClick={() => setLogoModalDismissed(false)}
            className="self-start px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-medium transition-colors"
          >
            Upload logo
          </button>
        )}

        {/* Special state: pin annotator now renders in the LEFT panel (above);
            here we just show a short prompt in the chat column. */}
        {chatState === 'pin_annotate_mode' && (
          <p className="text-xs text-textMuted text-center">
            Drop a pin on the cap image on the left to mark your placement.
          </p>
        )}

        {/* Special state: generation + preview */}
        {(chatState === 'generating' || triggerGeneration) && <GenerationPanel />}

        {/* Email is captured inline from the chat input (asked in the
            'generating' message) — no separate contact form. */}

        {/* Composited blank-hat preview (front/back/left/right), shown above
            the confirm/tweak chips while at composite_preview. (The colour tint
            also shows continuously in the left viewer via compositeViews.) */}
        {compositePreview && composite && (
          <div className="grid grid-cols-2 gap-2 my-3">
            {(['front', 'back', 'left', 'right'] as const).map(v =>
              composite[v] ? (
                <img
                  key={v}
                  src={composite[v]}
                  alt={`${v} preview`}
                  className="w-full rounded border border-border"
                />
              ) : null,
            )}
          </div>
        )}

        {/* Colour swatches (blank-hat colour step): a real colour dot per
            colourway. Sends the colour name, which the backend maps to its hex
            for the tint. Replaces the plain name chips when present. */}
        {colourSwatches.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {colourSwatches.map(sw => (
              <button
                key={`${sw.hex}-${sw.name}`}
                onClick={() => handleChip(sw.name)}
                disabled={sending}
                aria-label={sw.name}
                className="flex items-center gap-2 px-3 py-2 bg-surface border border-border rounded-full text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <span
                  className="w-4 h-4 rounded-full border border-border flex-shrink-0"
                  style={{ background: sw.hex || '#ccc' }}
                  aria-hidden="true"
                />
                {sw.name}
              </button>
            ))}
          </div>
        )}

        {/* Custom colour picker (blank-hat colour step). Shown alongside any
            preset swatches so the customer can pick an exact colour when their
            hat type has no predefined colourways (or none of them fit). Sends
            the chosen hex, which the backend maps straight to the tint. */}
        {colourPicker && (
          <div className="flex items-center gap-2 flex-wrap">
            <label className="flex items-center gap-2 px-3 py-2 bg-surface border border-border rounded-full text-sm text-textPrimary cursor-pointer">
              <span
                className="w-4 h-4 rounded-full border border-border flex-shrink-0"
                style={{ background: customColour }}
                aria-hidden="true"
              />
              <span>{colourSwatches.length > 0 ? 'Custom colour' : 'Pick a colour'}</span>
              <input
                type="color"
                value={customColour}
                onChange={e => setCustomColour(e.target.value)}
                disabled={sending}
                aria-label="Pick a custom hat colour"
                className="w-6 h-6 p-0 border-0 bg-transparent cursor-pointer"
              />
            </label>
            <button
              onClick={() => handleChip(customColour)}
              disabled={sending}
              className="px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Use this colour
            </button>
          </div>
        )}

        {/* Option chip rows */}
        {options.length > 0 && colourSwatches.length === 0 && (
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

        {/* Voice: centered mic — hold SPACE (or press-and-hold the mic) to talk */}
        {speech.supported && (
          <div className="flex flex-col items-center gap-1.5 pt-1">
            <button
              type="button"
              onPointerDown={e => { e.preventDefault(); if (!sending) speech.start() }}
              onPointerUp={() => speech.stop()}
              onPointerLeave={() => { if (speech.listening) speech.stop() }}
              onPointerCancel={() => speech.stop()}
              disabled={sending}
              aria-label={speech.listening ? 'Listening — release to send' : `Hold ${speech.keyLabel} or press and hold to speak`}
              title={speech.listening ? 'Release to send' : `Hold ${speech.keyLabel} to speak`}
              className="relative flex items-center justify-center w-14 h-14 rounded-full bg-accent text-white shadow-lg shadow-accent/30 transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {/* pulse / halo rings */}
              <span
                className={`absolute inset-0 rounded-full bg-accent/30 ${speech.listening ? 'animate-ping' : ''}`}
                aria-hidden="true"
              />
              <span className="absolute -inset-2 rounded-full border border-accent/20" aria-hidden="true" />
              <span className="absolute -inset-4 rounded-full border border-accent/10" aria-hidden="true" />
              {/* mic icon */}
              <svg viewBox="0 0 24 24" className="relative w-6 h-6" fill="none" stroke="currentColor" strokeWidth={2}>
                <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" stroke="none" />
                <path d="M5 10a7 7 0 0 0 14 0" strokeLinecap="round" />
                <line x1="12" y1="19" x2="12" y2="22" strokeLinecap="round" />
                <line x1="8" y1="22" x2="16" y2="22" strokeLinecap="round" />
              </svg>
            </button>
            <p className="text-sm font-semibold text-textPrimary mt-1.5">
              {speech.listening ? 'Listening… release to send' : `Hold ${speech.keyLabel} to Talk`}
            </p>
            <kbd className="px-2 py-0.5 text-[11px] font-medium border border-border rounded bg-base text-textMuted">
              {speech.keyLabel}
            </kbd>
            <p className="text-xs text-textMuted">or type</p>
          </div>
        )}

        {/* Text input + Send */}
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            value={inputText}
            onChange={e => setInputText(e.target.value)}
            placeholder={speech.listening ? 'Listening…' : 'Type your message…'}
            disabled={sending}
            className="flex-1 bg-surface border border-border rounded-full px-5 py-3 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            disabled={sending || !inputText.trim()}
            className="bg-accent hover:bg-accentHover text-white px-6 py-3 rounded-full text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </div>
        </div>
      </div>
    </div>
  )
}
