import { useEffect, useRef } from 'react'
import { useSpeechRecognition } from './useSpeechRecognition'

interface PushToTalkOptions {
  /** When false, the global key listeners are not registered. Default true. */
  enabled?: boolean
}

interface UsePushToTalk {
  supported: boolean
  listening: boolean
  /** Human-readable message when the mic is blocked/unavailable, else null. */
  error: string | null
  /** The hold-to-talk key label for this platform ("Ctrl" or "⌘"). */
  keyLabel: string
  start: () => void
  stop: () => void
}

function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  const s = `${navigator.platform || ''} ${navigator.userAgent || ''}`
  return /Mac|iPhone|iPad|iPod/.test(s)
}

/**
 * Walkie-talkie voice: hold the platform modifier — Ctrl on Windows/Linux, ⌘
 * (Meta) on macOS — to talk, release to send. The modifier is used instead of
 * the spacebar so Space always types normally in the message box; talk works
 * even while the text field is focused.
 *
 * Guards: starts once per hold (ignores auto-repeat); if another key is pressed
 * while the modifier is held it's treated as a keyboard shortcut (e.g. Ctrl+V),
 * so recognition is aborted rather than capturing stray dictation.
 */
export function usePushToTalk(
  onResult: (text: string) => void,
  opts: PushToTalkOptions = {},
): UsePushToTalk {
  const { supported, listening, error, start, stop } = useSpeechRecognition(onResult)
  const enabled = opts.enabled !== false
  const isMac = isMacPlatform()
  const talkKey = isMac ? 'Meta' : 'Control'
  const keyLabel = isMac ? '⌘' : 'Ctrl'

  // Track whether OUR modifier hold is the active source, so keyup only stops
  // recognition we started.
  const holdingRef = useRef(false)

  useEffect(() => {
    if (!supported || !enabled) return

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === talkKey) {
        if (e.repeat || holdingRef.current) return
        holdingRef.current = true
        start()
        return
      }
      // Any other key pressed WHILE holding the talk key means it's a shortcut
      // (e.g. Ctrl+V), not dictation — abort so we never capture stray text.
      if (holdingRef.current) {
        holdingRef.current = false
        stop()
      }
    }

    function onKeyUp(e: KeyboardEvent) {
      if (e.key !== talkKey) return
      if (!holdingRef.current) return
      holdingRef.current = false
      stop()
    }

    // If focus leaves the window mid-hold (e.g. the OS grabs the shortcut) we'd
    // never see keyup — stop on blur so the mic doesn't stay open.
    function onBlur() {
      if (holdingRef.current) {
        holdingRef.current = false
        stop()
      }
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onBlur)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
      if (holdingRef.current) {
        holdingRef.current = false
        stop()
      }
    }
  }, [supported, enabled, talkKey, start, stop])

  return { supported, listening, error, keyLabel, start, stop }
}
