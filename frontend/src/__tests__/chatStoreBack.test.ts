import { test, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
  sendBack: vi.fn(),
}))

import { useChatStore } from '../store/chatStore'
import { sendBack } from '../lib/api'

beforeEach(() => {
  useChatStore.getState().reset()
  vi.clearAllMocks()
})

test('applyResponse sets canGoBack true when data.can_go_back is true', () => {
  useChatStore.getState().applyResponse('r', 'ask_quantity', { can_go_back: true })
  expect(useChatStore.getState().canGoBack).toBe(true)
})

test('applyResponse sets canGoBack false when can_go_back is absent', () => {
  useChatStore.getState().applyResponse('r', 'ask_quantity', {})
  expect(useChatStore.getState().canGoBack).toBe(false)
})

test('goBack calls sendBack(id) and applies its response', async () => {
  vi.mocked(sendBack).mockResolvedValue({
    reply: 'Sure, what would you like to change?',
    state: 'ask_quantity',
    data: { can_go_back: false },
  } as never)

  await useChatStore.getState().goBack('sess-1')

  expect(sendBack).toHaveBeenCalledWith('sess-1')
  const s = useChatStore.getState()
  expect(s.chatState).toBe('ask_quantity')
  expect(s.messages[s.messages.length - 1]?.text).toBe('Sure, what would you like to change?')
  expect(s.canGoBack).toBe(false)
  expect(s.sending).toBe(false)
})

test('goBack is a no-op while a send is already in flight', async () => {
  useChatStore.setState({ sending: true })
  await useChatStore.getState().goBack('sess-1')
  expect(sendBack).not.toHaveBeenCalled()
})
