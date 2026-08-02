import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useSessionStore } from '../../store/sessionStore'
import { useChatStore } from '../../store/chatStore'
import { useGenerationStore } from '../../store/generationStore'
import { useBrandStore } from '../../store/brandStore'
import { Modal } from '../Modal'
import { usePushToTalk } from '../../hooks/usePushToTalk'
import { uploadLogo, postComposite } from '../../lib/api'
import { linkify } from '../../lib/linkify'

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
// ChatColumn — self-contained reusable chat column (no props, no outer
// screen/header, no auto-kickoff). Meant to sit inside a fixed-width right
// panel of the split-screen customise studio; the canvas flow activates the
// conversation via finalizeCanvas -> chatStore.hydrate().
// ---------------------------------------------------------------------------

export function ChatColumn() {
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
  const sendMessage = useChatStore(s => s.sendMessage)
  const backTargets = useChatStore(s => s.backTargets)
  const goBackTo = useChatStore(s => s.goBackTo)
  const pollVerification = useChatStore(s => s.pollVerification)
  const advanceRegeneration = useChatStore(s => s.advanceRegeneration)
  const advanceGeneration = useChatStore(s => s.advanceGeneration)
  const dismissError = useChatStore(s => s.dismissError)
  const setError = useChatStore(s => s.setError)
  const kickoff = useChatStore(s => s.kickoff)
  const multiselect = useChatStore(s => s.multiselect)
  const selected = useChatStore(s => s.selected)
  const quoteUrl = useChatStore(s => s.quoteUrl)
  const messagesLen = useChatStore(s => s.messages.length)
  const kickoffDone = useChatStore(s => s.kickoffDone)

  // Per-store persona, used as the assistant's name-line label (Task 9's
  // precedent in CustomiseStudio/index.tsx): falls back to 'Ricardo' before
  // /storefront resolves or for an unconfigured store.
  const personaName = useBrandStore(s => s.personaName) || 'Ricardo'

  // Generation store
  const startGeneration = useGenerationStore(s => s.startGeneration)
  const startRegeneration = useGenerationStore(s => s.startRegeneration)
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

  // Design generated but not yet released (email unverified): the viewer must
  // reveal nothing of it. Covers the just-generated turn (genStatus 'done') and
  // a session resumed while still parked at the verification step.
  const awaitingVerification =
    !designReleased && (genStatus === 'done' || chatState === 'verify_email')

  // v2 canvas: the double opt-in gate. The verification link has gone out and
  // the flow is PARKED mid-design until the customer opens it — the backend's
  // gate step declares no slots, so nothing typed here can advance it. Locking
  // the composer is what makes that honest: an enabled box invites the customer
  // to answer a question that no longer moves, which reads as a broken bot.
  // Only pollVerification (above) releases it.
  const awaitingEmailVerify = chatState === 'await_email_verify'
  const inputLocked = sending || awaitingEmailVerify

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
  // Structured Back: whether the checkpoint-picker menu is open. Closed
  // whenever backTargets changes (a completed restore, or any forward turn)
  // so it never lingers over a stale list.
  const [backMenuOpen, setBackMenuOpen] = useState(false)
  useEffect(() => { setBackMenuOpen(false) }, [backTargets])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const wasSendingRef = useRef(false)

  // Decoration multi-select (ask_decoration): locally tracked toggle state,
  // re-seeded from the backend's `selected` whenever it changes (e.g. resuming
  // a session already at ask_decoration).
  const [decoSel, setDecoSel] = useState<string[]>([])
  useEffect(() => { setDecoSel(selected) }, [selected])

  function toggleDeco(name: string) {
    setDecoSel(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name])
  }

  function submitDeco() {
    if (!sessionId || sending) return
    void sendMessage(sessionId, decoSel.length ? decoSel.join(', ') : 'none')
  }

  // Reset the logo-modal dismissal each time the flow leaves the upload step.
  useEffect(() => {
    if (chatState !== 'upload_logo') setLogoModalDismissed(false)
  }, [chatState])

  // Canvas sessions run the intro Q&A in this column, so kick off the greeting
  // on mount. Resumed sessions hydrate with kickoffDone=true and are skipped.
  useEffect(() => {
    if (sessionId && messagesLen === 0 && !kickoffDone) {
      void kickoff(sessionId)
    }
  }, [sessionId, messagesLen, kickoffDone, kickoff])

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

  // While waiting for the emailed link, poll for the out-of-band verification
  // (the customer clicks it, possibly in another tab/device) and surface the
  // confirmation in the thread the moment it lands. Two states wait on it:
  // v1's post-generation 'verify_email', and the v2 canvas flow's mid-design
  // 'await_email_verify' — which is a HARD gate (see awaitingEmailVerify), so
  // this poll is the only thing that can move the conversation on.
  useEffect(() => {
    if (!sessionId) return
    if (chatState !== 'verify_email' && chatState !== 'await_email_verify') return
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
    if (!text || !sessionId || inputLocked) return
    setInputText('')
    void sendMessage(sessionId, text)
  }

  function handleChip(text: string) {
    if (!sessionId || inputLocked) return
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
    { enabled: !inputLocked },
  )

  // Surface a blocked/unavailable mic through the shared error banner so the
  // user learns why "Press Space to Talk" did nothing and how to fix it.
  useEffect(() => {
    if (speech.error) setError(speech.error)
  }, [speech.error, setError])

  const isStatementOnly = continuable && !sending && !awaitingEmailVerify

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="flex flex-col min-h-0 h-full">
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
        {progress && !progress.sections && progress.step < progress.total && (
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
        {messages.length === 0 && !sending && (
          <p className="m-auto max-w-xs text-center text-sm text-textMuted">
            Design your cap on the left. Once you hit “See it rendered”, we’ll chat with you here to finish up and send it over.
          </p>
        )}
        {messages.map((msg, i) => {
          const mine = msg.role === 'user'
          // The LANE is on every message — it is the per-message identifier.
          // The NAME only when the speaker changes: v2 routinely emits several
          // assistant bubbles per turn (data.extra_replies, plus the
          // reply/instruction split), and repeating an identical header on
          // consecutive bubbles reads as padding, especially on a phone.
          const startsRun = i === 0 || messages[i - 1].role !== msg.role
          return (
            <div key={msg.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div
                data-testid="msg-lane"
                className={`flex max-w-[88%] flex-col gap-1 md:max-w-md ${
                  mine
                    ? 'items-end border-r-2 border-chatUserBubble pr-2'
                    : 'items-start border-l-2 border-canvasAccent pl-2'
                }`}
              >
                {startsRun && (
                  <span className="text-[11px] font-semibold leading-none text-textMuted">
                    {mine ? 'You' : (
                      <>
                        {personaName}
                        <span className="font-normal text-textMuted/70"> · Design assistant</span>
                      </>
                    )}
                  </span>
                )}
                <div
                  className={`whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                    mine
                      ? 'rounded-br-sm bg-chatUserBubble text-white'
                      : 'rounded-bl-sm border border-border bg-surface text-textPrimary shadow-sm'
                  }`}
                >
                  {linkify(msg.text)}
                </div>
              </div>
            </div>
          )
        })}

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

        {/* v2 canvas: the email-verification gate. Everything below is disabled
            while this shows, so it has to say what the customer must do and that
            it resolves by itself — the poll picks the click up within seconds. */}
        {awaitingEmailVerify && (
          <div
            role="status"
            className="flex items-start gap-3 p-4 bg-surface border border-border rounded-xl"
          >
            <span className="mt-0.5 w-4 h-4 flex-shrink-0 border-2 border-accent border-t-transparent rounded-full animate-spin" />
            <div className="flex flex-col gap-1">
              <p className="text-sm font-medium text-textPrimary">
                Waiting for you to confirm your email
              </p>
              <p className="text-xs text-textMuted">
                Open the verification link we've just sent you and we'll carry on
                from here — no need to reload. If it hasn't arrived, please check
                your spam folder.
              </p>
            </div>
          </div>
        )}

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
                disabled={inputLocked}
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
                disabled={inputLocked}
                aria-label="Pick a custom hat colour"
                className="w-6 h-6 p-0 border-0 bg-transparent cursor-pointer"
              />
            </label>
            <button
              onClick={() => handleChip(customColour)}
              disabled={inputLocked}
              className="px-4 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Use this colour
            </button>
          </div>
        )}

        {/* Decoration multi-select (ask_decoration). Renders whenever the step
            is a multi-select, even with zero configured options, so Continue
            (which sends 'none') is always reachable — otherwise a store with
            no decoration types soft-locks the flow. */}
        {multiselect && (
          <div className="flex flex-col gap-2">
            {options.length > 0 && (
              <div className="flex flex-wrap gap-2">
                {options.map(opt => {
                  const on = decoSel.includes(opt)
                  return (
                    <button
                      key={opt}
                      onClick={() => toggleDeco(opt)}
                      disabled={inputLocked}
                      aria-pressed={on}
                      className={`px-4 py-2 rounded-full text-sm transition-colors disabled:opacity-50 ${
                        on
                          ? 'bg-accent text-white border border-accent'
                          : 'bg-surface border border-border text-textPrimary hover:border-accent'
                      }`}
                    >
                      {on ? '✓ ' : ''}{opt}
                    </button>
                  )
                })}
              </div>
            )}
            {decoSel.length > 1 && (
              <p className="text-xs text-amber-600">
                Heads up — each extra decoration adds to the cost, so pick only what you need.
              </p>
            )}
            <button
              onClick={submitDeco}
              disabled={inputLocked}
              className="self-start px-5 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors"
            >
              Continue
            </button>
          </div>
        )}

        {/* Quote handoff: the customer asked to request a quote — open the
            /quote page (same link as the email) in a new tab. A button (not an
            auto-popup) so browsers don't block it. */}
        {quoteUrl && (
          <a
            href={quoteUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="self-start px-5 py-2.5 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold transition-colors"
          >
            Open quote form →
          </a>
        )}

        {/* Structured Back: a menu of named checkpoints. The list ships on
            every turn (data.back_targets), already filtered server-side, so
            opening it costs no round trip and it can never be stale. No
            targets => no button, which is how "no going back after the design
            is agreed" is expressed — there is no separate disable flag. */}
        {sessionId && backTargets.length > 0 && !sending && !awaitingEmailVerify && (
          backMenuOpen ? (
            <div className="self-start flex flex-col gap-1.5">
              <span className="text-xs text-textMuted">
                Where would you like to go back to?
              </span>
              {backTargets.map(t => (
                <button
                  key={t.seq}
                  onClick={() => { setBackMenuOpen(false); void goBackTo(sessionId, t.seq) }}
                  className="self-start rounded-full border border-border px-3 py-1 text-xs
                             text-textPrimary hover:border-accent hover:text-accent"
                >
                  {t.label}
                </button>
              ))}
              <button
                onClick={() => setBackMenuOpen(false)}
                className="self-start text-xs text-textMuted hover:underline underline-offset-2"
              >
                Cancel — stay here
              </button>
            </div>
          ) : (
            <button
              onClick={() => setBackMenuOpen(true)}
              className="self-start text-xs text-textMuted hover:text-accent underline underline-offset-2"
            >
              ↩ Back
            </button>
          )
        )}

        {/* Option chip rows */}
        {options.length > 0 && colourSwatches.length === 0 && !multiselect && (
          <div className="flex flex-wrap gap-2">
            {options.map(opt => (
              <button
                key={opt}
                onClick={() => handleChip(opt)}
                disabled={inputLocked}
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
                disabled={inputLocked}
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
              disabled={inputLocked}
              className="px-5 py-2 bg-surface border border-accent rounded-full text-sm text-accent hover:bg-accent hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Continue
            </button>
          </div>
        )}

        {/* Voice: hold the key (or press-and-hold the mic) to talk. Deliberately a
            single compact ROW — as a centred stack with halo rings, a big label,
            a kbd chip and an "or type" line it ate ~140px of the chat column,
            which is the scarcest space on this screen. */}
        {speech.supported && (
          <div className="flex items-center justify-center gap-2">
            <button
              type="button"
              onPointerDown={e => { e.preventDefault(); if (!inputLocked) speech.start() }}
              onPointerUp={() => speech.stop()}
              onPointerLeave={() => { if (speech.listening) speech.stop() }}
              onPointerCancel={() => speech.stop()}
              disabled={inputLocked}
              aria-label={speech.listening ? 'Listening — release to send' : `Hold ${speech.keyLabel} or press and hold to speak`}
              title={speech.listening ? 'Release to send' : `Hold ${speech.keyLabel} to speak`}
              className="relative flex items-center justify-center w-7 h-7 flex-shrink-0 rounded-full bg-accent text-white shadow shadow-accent/30 transition-transform active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {/* pulse halo — only while listening, so it costs no idle space */}
              <span
                className={`absolute inset-0 rounded-full bg-accent/30 ${speech.listening ? 'animate-ping' : ''}`}
                aria-hidden="true"
              />
              {/* mic icon */}
              <svg viewBox="0 0 24 24" className="relative w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2}>
                <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" stroke="none" />
                <path d="M5 10a7 7 0 0 0 14 0" strokeLinecap="round" />
                <line x1="12" y1="19" x2="12" y2="22" strokeLinecap="round" />
                <line x1="8" y1="22" x2="16" y2="22" strokeLinecap="round" />
              </svg>
            </button>
            {speech.listening ? (
              <p className="text-xs font-semibold text-textPrimary">Listening… release to send</p>
            ) : (
              <p className="text-xs text-textMuted">
                Hold{' '}
                <kbd className="px-1.5 py-0.5 text-[10px] font-medium border border-border rounded bg-base text-textMuted">
                  {speech.keyLabel}
                </kbd>{' '}
                to talk, or type
              </p>
            )}
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
            disabled={inputLocked}
            className="flex-1 bg-surface border border-border rounded-full px-5 py-3 text-sm text-textPrimary placeholder:text-textMuted focus:outline-none focus:border-accent disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            disabled={inputLocked || !inputText.trim()}
            className="bg-accent hover:bg-accentHover text-white px-6 py-3 rounded-full text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  )
}
