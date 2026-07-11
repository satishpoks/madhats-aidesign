import { useCallback, useEffect, useRef, useState } from 'react'

interface UseSpeechRecognition {
  /** True when the browser exposes the Web Speech API. */
  supported: boolean
  /** True while actively listening to the mic. */
  listening: boolean
  /**
   * A human-readable message when the mic is unavailable (e.g. permission
   * blocked), else null. The caller surfaces this to the user.
   */
  error: string | null
  start: () => void
  stop: () => void
}

/** Shown when the browser has blocked microphone access for this site. */
const MIC_BLOCKED_MESSAGE =
  'Microphone access is blocked. Click the camera/mic icon in your browser’s ' +
  'address bar to allow it, then press Space to talk again.'

/**
 * Thin wrapper over the browser Web Speech API (SpeechRecognition).
 * `onResult` fires once with the final transcript when the user stops speaking.
 * Degrades gracefully: `supported` is false where the API is unavailable
 * (e.g. Firefox, jsdom) and the caller should fall back to typed input.
 */
export function useSpeechRecognition(
  onResult: (text: string) => void,
): UseSpeechRecognition {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recognitionRef = useRef<unknown>(null)
  // Cache the "permission granted" result so we only pay the getUserMedia
  // round-trip on the first hold; Chrome remembers the grant across calls.
  const micReadyRef = useRef(false)
  // True between start() (key pressed) and stop() (key released). The Web Speech
  // API ends a session on its own after a silent stretch even in continuous
  // mode; while this is true we restart it so recording lasts the whole hold.
  const wantListeningRef = useRef(false)

  // Keep the latest callback without re-creating the recognition instance.
  const onResultRef = useRef(onResult)
  onResultRef.current = onResult

  // Use loose typing — the SpeechRecognition constructor isn't in lib.dom for
  // every TS target, and vendor-prefixed in Chrome.
  const SpeechRecognitionImpl: unknown =
    typeof window !== 'undefined'
      ? (window as unknown as Record<string, unknown>).SpeechRecognition ??
        (window as unknown as Record<string, unknown>).webkitSpeechRecognition
      : undefined

  const supported = Boolean(SpeechRecognitionImpl)

  useEffect(() => {
    if (!SpeechRecognitionImpl) return
    const Ctor = SpeechRecognitionImpl as new () => {
      lang: string
      interimResults: boolean
      continuous: boolean
      onresult:
        | ((e: {
            resultIndex: number
            results: ArrayLike<{ isFinal: boolean } & ArrayLike<{ transcript: string }>>
          }) => void)
        | null
      onend: (() => void) | null
      onerror: ((e: { error?: string }) => void) | null
      start: () => void
      stop: () => void
      abort: () => void
    }
    const rec = new Ctor()
    rec.lang = 'en-AU'
    rec.interimResults = false
    // Keep the mic open across natural pauses — without this the API ends the
    // session after the first utterance, cutting the user off mid-sentence.
    rec.continuous = true
    rec.onresult = e => {
      // Deliver only the NEW final segments (from resultIndex on). In continuous
      // mode e.results accumulates, so re-reading the whole list would duplicate
      // earlier text on every event.
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i]
        if (!res.isFinal) continue
        const transcript = (res[0]?.transcript ?? '').trim()
        if (transcript) onResultRef.current(transcript)
      }
    }
    rec.onend = () => {
      // While the key is still held, an end event is the API timing out on
      // silence — not the user releasing. Restart so recording continues until
      // they actually let go (stop() clears wantListeningRef first).
      if (wantListeningRef.current) {
        try {
          rec.start()
          return
        } catch {
          /* couldn't restart — fall through and report not listening */
        }
      }
      setListening(false)
    }
    rec.onerror = e => {
      // Permission was refused/revoked — stop for real and tell the user how to
      // unblock. Transient errors (no-speech, network) are left to onend, which
      // restarts if the key is still held, so a brief hiccup doesn't cut off.
      if (e?.error === 'not-allowed' || e?.error === 'service-not-allowed') {
        wantListeningRef.current = false
        micReadyRef.current = false
        setError(MIC_BLOCKED_MESSAGE)
        setListening(false)
      }
    }
    recognitionRef.current = rec
    return () => {
      try {
        rec.abort()
      } catch {
        /* no-op */
      }
    }
  }, [SpeechRecognitionImpl])

  const start = useCallback(async () => {
    const rec = recognitionRef.current as { start: () => void } | null
    if (!rec) return
    // Proactively obtain mic permission. SpeechRecognition.start() alone only
    // prompts inconsistently and stays silent when blocked; getUserMedia gives
    // us a real prompt on first use and a clear rejection when access is denied.
    if (!micReadyRef.current) {
      const md = typeof navigator !== 'undefined' ? navigator.mediaDevices : undefined
      if (md?.getUserMedia) {
        try {
          const stream = await md.getUserMedia({ audio: true })
          // We only needed the permission — release the mic immediately.
          stream.getTracks().forEach(t => t.stop())
          micReadyRef.current = true
        } catch {
          setError(MIC_BLOCKED_MESSAGE)
          setListening(false)
          return
        }
      } else {
        // No getUserMedia (older browsers): fall through and let recognition
        // prompt/err on its own; onerror still surfaces a block.
        micReadyRef.current = true
      }
    }
    // Mark intent to listen BEFORE starting, so an immediate onend restarts.
    wantListeningRef.current = true
    try {
      rec.start()
      setListening(true)
      setError(null)
    } catch {
      /* already started — ignore */
    }
  }, [])

  const stop = useCallback(() => {
    // Clear intent first so the ensuing onend does NOT restart recognition.
    wantListeningRef.current = false
    const rec = recognitionRef.current as { stop: () => void } | null
    if (rec) {
      try {
        rec.stop()
      } catch {
        /* no-op */
      }
    }
    setListening(false)
  }, [])

  return { supported, listening, error, start, stop }
}
