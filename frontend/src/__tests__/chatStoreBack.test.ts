import { test, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
  sendBack: vi.fn(),
}))

import * as api from '../lib/api'
import { useChatStore } from '../store/chatStore'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  vi.clearAllMocks()
})

test('parses back_targets from turn data', () => {
  useChatStore.getState().applyResponse('hi', 'ask_quantity', {
    back_targets: [{ seq: 2, label: 'Logo 1 — front', kind: 'logo' }],
  })
  expect(useChatStore.getState().backTargets).toEqual(
    [{ seq: 2, label: 'Logo 1 — front', kind: 'logo' }])
})

test('defaults backTargets to an empty list when the key is absent', () => {
  useChatStore.getState().applyResponse('hi', 'ask_name', {})
  expect(useChatStore.getState().backTargets).toEqual([])
})

test('goBackTo posts the chosen seq', async () => {
  const spy = vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: {} } as never)
  await useChatStore.getState().goBackTo('s1', 3)
  expect(spy).toHaveBeenCalledWith('s1', 3)
})

test('applies canvas_restore through restoreSnapshot, not fromCanvasDesign', async () => {
  const snap = { colourway: null, faces: { front: [], back: [], left: [], right: [] } }
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: { canvas_restore: snap } } as never)
  await useChatStore.getState().goBackTo('s1', 1)
  expect(restore).toHaveBeenCalledWith(snap)
})

test('leaves the canvas alone when the snapshot carries none', async () => {
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: {} } as never)
  await useChatStore.getState().goBackTo('s1', 1)
  expect(restore).not.toHaveBeenCalled()
})

test('hydrate never applies canvas_restore (a resume must not re-restore)', () => {
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  useChatStore.getState().hydrate([], 'ask_name',
    { canvas_restore: { colourway: null, faces: {} } })
  expect(restore).not.toHaveBeenCalled()
})

test('sends the live canvas on every v2 canvas turn', async () => {
  const spy = vi.spyOn(api, 'sendChat').mockResolvedValue(
    { reply: 'r', state: 'ask_logo_placement', data: {} } as never)
  // A null canvasDirective means "not a v2 turn" (useActiveSurface.ts); a real
  // v2 canvas session always carries one by the time sendMessage runs, because
  // the PREVIOUS response (which set chatState to this v2-owned step) also set
  // the directive. Setting both here is what actually distinguishes this from
  // a plain Q&A turn at the same state name — see the discriminator test below.
  useChatStore.setState({
    chatState: 'ask_logo_placement',
    canvasDirective: {
      allowedTools: ['upload'], targetFace: null, autoOpen: null,
      instructions: null, showDone: false, unlockAll: false,
    },
  })
  await useChatStore.getState().sendMessage('s1', 'front')
  expect(spy.mock.calls[0][2]).toEqual(
    expect.objectContaining({ faces: expect.any(Object) }))
})

test('does NOT send the canvas on a plain Q&A (non-canvas) turn, even at a state name v2 also uses', async () => {
  // canvasDirective stays null for a non-canvas session — v2 is the only
  // orchestrator that emits `data.canvas`. `ask_quantity` is deliberately
  // chosen here because it is a state name SHARED verbatim between the v2
  // canvas registry and the plain Q&A ConversationState enum, so this test
  // would pass for the wrong reason if the gate were keyed on chatState alone.
  const spy = vi.spyOn(api, 'sendChat').mockResolvedValue(
    { reply: 'r', state: 'ask_quantity', data: {} } as never)
  useChatStore.setState({ chatState: 'ask_quantity', canvasDirective: null })
  await useChatStore.getState().sendMessage('s1', '50')
  expect(spy).toHaveBeenCalledWith('s1', '50', undefined)
})

test('drops a blank turn (existing guard, must not regress)', async () => {
  const spy = vi.spyOn(api, 'sendChat')
  await useChatStore.getState().sendMessage('s1', '   ')
  expect(spy).not.toHaveBeenCalled()
})

test('goBackTo REPLACES messages with data.messages, not appends the reply', async () => {
  // Pre-existing thread includes the discarded exchange the restore rewound
  // past — proving the live bug (appended reply, stale exchange still shown)
  // would leave "Yes, I have a logo" / "Which part..." visible.
  useChatStore.setState({
    messages: [
      { id: 'a', role: 'assistant', text: 'Thank you, Satish. Do you have a logo…' },
      { id: 'b', role: 'user', text: 'Yes, I have a logo' },
      { id: 'c', role: 'assistant', text: 'Which part of the cap should it go on?' },
    ],
  })
  vi.spyOn(api, 'sendBack').mockResolvedValue({
    reply: 'Thank you, Satish. Do you have a logo…',
    state: 'ask_name',
    data: {
      messages: [
        { role: 'assistant', content: 'Hi! What is your name?',
          state_before: 'greeting', state_after: 'ask_name', created_at: '1' },
        { role: 'assistant', content: 'Thank you, Satish. Do you have a logo…',
          state_before: 'ask_name', state_after: 'ask_name', created_at: '2' },
      ],
    },
  } as never)

  await useChatStore.getState().goBackTo('s1', 1)

  const texts = useChatStore.getState().messages.map(m => m.text)
  expect(texts).toEqual(['Hi! What is your name?', 'Thank you, Satish. Do you have a logo…'])
  expect(texts).not.toContain('Yes, I have a logo')
  expect(texts).not.toContain('Which part of the cap should it go on?')
  // Not duplicated: the reply appears exactly once, as the last message.
  expect(texts.filter(t => t === 'Thank you, Satish. Do you have a logo…')).toHaveLength(1)
})

test('goBackTo falls back to appending when data.messages is absent', async () => {
  useChatStore.setState({
    messages: [{ id: 'a', role: 'assistant', text: 'earlier message' }],
  })
  vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'restored reply', state: 'ask_name', data: {} } as never)

  await useChatStore.getState().goBackTo('s1', 1)

  const texts = useChatStore.getState().messages.map(m => m.text)
  expect(texts).toEqual(['earlier message', 'restored reply'])
})
