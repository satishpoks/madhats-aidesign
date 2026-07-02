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

function pressSpace(target: Element = document.body, extra: Partial<KeyboardEventInit> = {}) {
  fireEvent.keyDown(target, { key: ' ', code: 'Space', ...extra })
}
function releaseSpace(target: Element = document.body) {
  fireEvent.keyUp(target, { key: ' ', code: 'Space' })
}

describe('usePushToTalk', () => {
  beforeEach(() => {
    start.mockReset()
    stop.mockReset()
    supported = true
    document.body.innerHTML = ''
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur()
  })

  it('starts on space keydown and stops on keyup when nothing is focused', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace()
    expect(start).toHaveBeenCalledTimes(1)
    releaseSpace()
    expect(stop).toHaveBeenCalledTimes(1)
  })

  it('ignores auto-repeat keydown (starts once)', () => {
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(document.body)
    pressSpace(document.body, { repeat: true })
    expect(start).toHaveBeenCalledTimes(1)
  })

  it('does not start when an input is focused', () => {
    const input = document.createElement('input')
    document.body.appendChild(input)
    input.focus()
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(input)
    expect(start).not.toHaveBeenCalled()
  })

  it('does not start when a button is focused', () => {
    const btn = document.createElement('button')
    document.body.appendChild(btn)
    btn.focus()
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace(btn)
    expect(start).not.toHaveBeenCalled()
  })

  it('is a no-op when speech is unsupported', () => {
    supported = false
    renderHook(() => usePushToTalk(vi.fn()))
    pressSpace()
    releaseSpace()
    expect(start).not.toHaveBeenCalled()
    expect(stop).not.toHaveBeenCalled()
  })

  it('does not register listeners when enabled is false', () => {
    renderHook(() => usePushToTalk(vi.fn(), { enabled: false }))
    pressSpace()
    expect(start).not.toHaveBeenCalled()
  })

  it('stops and clears the hold when enabled flips off mid-hold', () => {
    const { rerender } = renderHook(
      ({ enabled }) => usePushToTalk(vi.fn(), { enabled }),
      { initialProps: { enabled: true } },
    )
    pressSpace()
    expect(start).toHaveBeenCalledTimes(1)
    rerender({ enabled: false })
    expect(stop).toHaveBeenCalledTimes(1)
  })
})
