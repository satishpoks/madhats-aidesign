import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSpeechRecognition } from '../hooks/useSpeechRecognition'

// A minimal fake SpeechRecognition we can drive from tests.
class FakeRecognition {
  lang = ''
  interimResults = false
  continuous = false
  onresult: ((e: unknown) => void) | null = null
  onend: (() => void) | null = null
  onerror: ((e: { error?: string }) => void) | null = null
  start = vi.fn()
  stop = vi.fn()
  abort = vi.fn()
}

let currentRec: FakeRecognition
const getUserMedia = vi.fn()

beforeEach(() => {
  currentRec = new FakeRecognition()
  ;(window as unknown as Record<string, unknown>).webkitSpeechRecognition = function () {
    return currentRec
  }
  getUserMedia.mockReset()
  // jsdom has no mediaDevices — install a controllable stub.
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia },
  })
})

afterEach(() => {
  delete (window as unknown as Record<string, unknown>).webkitSpeechRecognition
})

describe('useSpeechRecognition', () => {
  it('reports supported when the Web Speech API exists', () => {
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    expect(result.current.supported).toBe(true)
    expect(result.current.error).toBeNull()
  })

  it('requests mic permission then starts recognition on start()', async () => {
    const stop = vi.fn()
    getUserMedia.mockResolvedValue({ getTracks: () => [{ stop }] })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))

    await act(async () => {
      await result.current.start()
    })

    expect(getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(stop).toHaveBeenCalled() // permission-only: mic released immediately
    expect(currentRec.start).toHaveBeenCalledTimes(1)
    expect(result.current.listening).toBe(true)
  })

  it('surfaces a blocked message and does not start when permission is denied', async () => {
    getUserMedia.mockRejectedValue(
      Object.assign(new Error('denied'), { name: 'NotAllowedError' }),
    )
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))

    await act(async () => {
      await result.current.start()
    })

    expect(currentRec.start).not.toHaveBeenCalled()
    expect(result.current.listening).toBe(false)
    expect(result.current.error).toMatch(/blocked/i)
  })

  it('surfaces a blocked message when recognition reports not-allowed', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    // Prime the recognition instance (created in an effect).
    await act(async () => {
      await result.current.start()
    })
    act(() => {
      currentRec.onerror?.({ error: 'not-allowed' })
    })
    expect(result.current.error).toMatch(/blocked/i)
    expect(result.current.listening).toBe(false)
  })

  it('only requests the mic once across repeated starts', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => {
      await result.current.start()
    })
    act(() => result.current.stop())
    await act(async () => {
      await result.current.start()
    })
    expect(getUserMedia).toHaveBeenCalledTimes(1)
  })

  it('uses continuous recognition so a pause does not end the session', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    renderHook(() => useSpeechRecognition(vi.fn()))
    expect(currentRec.continuous).toBe(true)
  })

  it('auto-restarts recognition when it ends while the key is still held', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => {
      await result.current.start()
    })
    expect(currentRec.start).toHaveBeenCalledTimes(1)
    // The browser ends the session after a silent stretch, but the user is
    // still holding — we must restart, not stop.
    act(() => currentRec.onend?.())
    expect(currentRec.start).toHaveBeenCalledTimes(2)
    expect(result.current.listening).toBe(true)
  })

  it('does NOT restart after an explicit stop() (release)', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => {
      await result.current.start()
    })
    act(() => result.current.stop())
    expect(result.current.listening).toBe(false)
    act(() => currentRec.onend?.())
    expect(currentRec.start).toHaveBeenCalledTimes(1) // not restarted
    expect(result.current.listening).toBe(false)
  })

  it('delivers each new final segment once (no duplication in continuous mode)', async () => {
    getUserMedia.mockResolvedValue({ getTracks: () => [] })
    const onResult = vi.fn()
    const { result } = renderHook(() => useSpeechRecognition(onResult))
    await act(async () => {
      await result.current.start()
    })
    act(() =>
      currentRec.onresult?.({
        resultIndex: 0,
        results: [Object.assign([{ transcript: 'hello' }], { isFinal: true })],
      }),
    )
    act(() =>
      currentRec.onresult?.({
        resultIndex: 1,
        results: [
          Object.assign([{ transcript: 'hello' }], { isFinal: true }),
          Object.assign([{ transcript: 'world' }], { isFinal: true }),
        ],
      }),
    )
    expect(onResult).toHaveBeenCalledTimes(2)
    expect(onResult).toHaveBeenNthCalledWith(1, 'hello')
    expect(onResult).toHaveBeenNthCalledWith(2, 'world')
  })
})
