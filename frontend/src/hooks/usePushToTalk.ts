import { useEffect, useRef } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'

interface PushToTalkOptions {
  /** When false, the global spacebar listeners are not registered. Default true. */
  enabled?: boolean
}

interface UsePushToTalk {
  supported: boolean
  listening: boolean
  start: () => void
  stop: () => void
}

/** True when the currently focused element should swallow the spacebar itself. */
function focusIsInteractive(): boolean {
  const el = document.activeElement as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || tag === 'BUTTON') return true
  if (el.isContentEditable) return true
  return false
}

/**
 * Walkie-talkie voice: hold SPACEBAR to talk, release to send.
 * Wraps useSpeechRecognition and adds global key handling with guards so a
 * held key starts recognition exactly once and typing spaces never triggers it.
 * Falls back cleanly (no listeners) where the Web Speech API is unavailable.
 */
export function usePushToTalk(
  onResult: (text: string) => void,
  opts: PushToTalkOptions = {},
): UsePushToTalk {
  const { supported, listening, start, stop } = useSpeechRecognition(onResult)
  const enabled = opts.enabled !== false

  // Track whether OUR spacebar hold is the active source, so keyup only stops
  // recognition we started.
  const holdingRef = useRef(false)

  useEffect(() => {
    if (!supported || !enabled) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.code !== 'Space' && e.key !== ' ') return
      if (e.repeat) return
      if (focusIsInteractive()) return
      e.preventDefault()
      if (holdingRef.current) return
      holdingRef.current = true
      start()
    }

    function onKeyUp(e: KeyboardEvent) {
      if (e.code !== 'Space' && e.key !== ' ') return
      if (!holdingRef.current) return
      holdingRef.current = false
      e.preventDefault()
      stop()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      if (holdingRef.current) {
        holdingRef.current = false
        stop()
      }
    }
  }, [supported, enabled, start, stop])

  return { supported, listening, start, stop }
}
