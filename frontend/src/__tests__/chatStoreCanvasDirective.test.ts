import { expect, test, beforeEach } from 'vitest'
import { useChatStore } from '../store/chatStore'

beforeEach(() => useChatStore.getState().reset())

test('parses canvas directive from applyResponse', () => {
  useChatStore.getState().applyResponse('hi', 'ask_logo_placement', {
    canvas: { allowed_tools: ['upload'], target_face: 'front', auto_open: 'upload', instructions: 'tip', show_done: false },
  })
  const d = useChatStore.getState().canvasDirective
  expect(d?.allowedTools).toEqual(['upload'])
  expect(d?.targetFace).toBe('front')
  expect(d?.autoOpen).toBe('upload')
  expect(d?.instructions).toBe('tip')
  expect(d?.showDone).toBe(false)
})

test('parses trigger_finalize', () => {
  useChatStore.getState().applyResponse('go', 'finalize_canvas', { trigger_finalize: true })
  expect(useChatStore.getState().triggerFinalize).toBe(true)
})

test('canvas directive resets to null on subsequent response without canvas key', () => {
  // First response has a canvas directive
  useChatStore.getState().applyResponse('hi', 'ask_logo_placement', {
    canvas: { allowed_tools: ['upload'], target_face: 'front', auto_open: 'upload', instructions: 'tip', show_done: false },
  })
  expect(useChatStore.getState().canvasDirective).not.toBeNull()

  // Second response without canvas key should reset canvasDirective to null
  useChatStore.getState().applyResponse('next step', 'some_state', {})
  expect(useChatStore.getState().canvasDirective).toBeNull()
})
