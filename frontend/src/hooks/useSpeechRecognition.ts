import { useCallback, useEffect, useRef, useState } from 'react'

interface UseSpeechRecognition {
  /** True when the browser exposes the Web Speech API. */
  supported: boolean
  /** True while actively listening to the mic. */
  listening: boolean
  start: () => void
  stop: () => void
}

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
  const recognitionRef = useRef<unknown>(null)

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
      onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null
      onend: (() => void) | null
      onerror: (() => void) | null
      start: () => void
      stop: () => void
      abort: () => void
    }
    const rec = new Ctor()
    rec.lang = 'en-AU'
    rec.interimResults = false
    rec.continuous = false
    rec.onresult = e => {
      const transcript = Array.from(e.results)
        .map(r => r[0]?.transcript ?? '')
        .join(' ')
        .trim()
      if (transcript) onResultRef.current(transcript)
    }
    rec.onend = () => setListening(false)
    rec.onerror = () => setListening(false)
    recognitionRef.current = rec
    return () => {
      try {
        rec.abort()
      } catch {
        /* no-op */
      }
    }
  }, [SpeechRecognitionImpl])

  const start = useCallback(() => {
    const rec = recognitionRef.current as { start: () => void } | null
    if (!rec) return
    try {
      rec.start()
      setListening(true)
    } catch {
      /* already started — ignore */
    }
  }, [])

  const stop = useCallback(() => {
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

  return { supported, listening, start, stop }
}
