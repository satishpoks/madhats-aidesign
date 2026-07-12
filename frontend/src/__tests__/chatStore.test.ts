import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { useChatStore } from '../store/chatStore'
import { pollGenerationAdvance } from '../lib/api'

beforeEach(() => {
  useChatStore.getState().reset()
  vi.clearAllMocks()
})

describe('advanceGeneration', () => {
  it('appends the reply and advances state when reply is non-null', async () => {
    vi.mocked(pollGenerationAdvance).mockResolvedValue({
      reply: "Putting your design together now.",
      state: 'verify_email',
      data: { progress: { step: 7, total: 7 } },
    })
    await useChatStore.getState().advanceGeneration('sess-1')
    const s = useChatStore.getState()
    expect(s.chatState).toBe('verify_email')
    expect(s.messages[s.messages.length - 1]?.text).toBe('Putting your design together now.')
  })

  it('is a no-op when reply is null (not at generating)', async () => {
    vi.mocked(pollGenerationAdvance).mockResolvedValue({
      reply: null,
      state: 'generating',
      data: {},
    })
    const before = useChatStore.getState().messages.length
    await useChatStore.getState().advanceGeneration('sess-1')
    expect(useChatStore.getState().messages.length).toBe(before)
  })
})
