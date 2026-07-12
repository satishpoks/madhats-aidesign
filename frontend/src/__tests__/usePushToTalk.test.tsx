import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'

// Mock the underlying speech hook so we can assert start/stop calls.
const start = vi.fn()
const stop = vi.fn()
let supported = true
vi.mock('../hooks/useSpeechRecognition', () => ({
  useSpeechRecognition: () => ({ supported, listening: false, start, stop }),
}))

import { usePushToTalk } from '../hooks/usePushToTalk'

// The tests run under jsdom, whose navigator is NOT a Mac, so the talk key is
// 'Control'. (The hook falls back to ⌘/'Meta' on macOS.)
function pressTalk(target: Element = document.body, extra: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(target, { key: 'Control', ...extra })
}
function releaseTalk(target: Element = document.body) {
  fireEvent.keyUp(target, { key: 'Control' })
}

describe('usePushToTalk', () => {
  beforeEach(() => {
    start.mockReset()
    stop.mockReset()
    supported = true
    document.body.innerHTML = ''
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })

  it('starts on the talk-key (Ctrl) keydown and stops on keyup', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressTalk()
    expect(start).toHaveBeenCalledTimes(1)
    releaseTalk()
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('ignores auto-repeat keydown (starts once)', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressTalk()
    pressTalk(document.body, { repeat: true })
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('still starts while a text input is focused (Space is free to type)', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    renderHook(() => usePushToTalk(vi.fn()))
    pressTalk(input)
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('does NOT start on the spacebar (Space types normally)', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    fireEvent.keyDown(document.body, { key: ' ', code: 'Space' })
    expect(start).not.toHaveBeenCalled()
  })

  it('aborts the hold if another key is pressed (a shortcut like Ctrl+V)', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressTalk()
    expect(start).toHaveBeenCalledTimes(1)
    fireEvent.keyDown(document.body, { key: 'v' })
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('is a no-op when speech is unsupported', () => {
    supported = false
    renderHook(() => usePushToTalk(vi.fn()))
    pressTalk()
    releaseTalk()
    expect(start).not.toHaveBeenCalled()
    expect(stop).not.toHaveBeenCalled()
  })

  it('does not register listeners when enabled is false', () => {
    renderHook(() => usePushToTalk(vi.fn(), { enabled: false }))
    pressTalk()
    expect(start).not.toHaveBeenCalled()
  })

  it('stops and clears the hold when enabled flips off mid-hold', () => {
    const { rerender } = renderHook(
      ({ enabled }) => usePushToTalk(vi.fn(), { enabled }),
      { initialProps: { enabled: true } },
    )
    pressTalk()
    expect(start).toHaveBeenCalledTimes(1)
    rerender({ enabled: false })
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('exposes a platform key label (Ctrl on non-mac)', () => {
    const { result } = renderHook(() => usePushToTalk(vi.fn()))
    expect(result.current.keyLabel).toBe('Ctrl')
  })
})
