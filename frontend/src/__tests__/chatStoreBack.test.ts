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
  useChatStore.setState({ chatState: 'ask_logo_placement' })
  await useChatStore.getState().sendMessage('s1', 'front')
  expect(spy.mock.calls[0][2]).toBeTruthy()   // canvas_design attached
})

test('drops a blank turn (existing guard, must not regress)', async () => {
  const spy = vi.spyOn(api, 'sendChat')
  await useChatStore.getState().sendMessage('s1', '   ')
  expect(spy).not.toHaveBeenCalled()
})
