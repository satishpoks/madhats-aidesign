import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  sendBack: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { pollVerification as pollVerificationApi } from '../lib/api'
import { useChatStore } from '../store/chatStore'

beforeEach(() => {
  useChatStore.getState().reset()
  vi.clearAllMocks()
})

describe('extra_replies', () => {
  it('applyResponse appends the main reply then each extra, in order', () => {
    useChatStore.getState().applyResponse('Your email is confirmed.', 'ask_another_logo', {
      extra_replies: ['Would you like to add another logo?'],
    })
    expect(useChatStore.getState().messages.map(m => m.text)).toEqual([
      'Your email is confirmed.',
      'Would you like to add another logo?',
    ])
  })

  it('applyResponse appends only the reply when there are no extras', () => {
    useChatStore.getState().applyResponse('Just the one.', 'ask_quantity', {})
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('pollVerification appends the ack and the next question as two messages', async () => {
    vi.mocked(pollVerificationApi).mockResolvedValue({
      reply: 'Thank you — your email address is confirmed.',
      state: 'ask_another_logo',
      data: { extra_replies: ['Would you like to add another logo?'] },
    } as never)
    await useChatStore.getState().pollVerification('s1')
    expect(useChatStore.getState().messages.map(m => m.text)).toEqual([
      'Thank you — your email address is confirmed.',
      'Would you like to add another logo?',
    ])
  })
})

describe('finalizeFailed', () => {
  it('defaults to false and is cleared by reset()', () => {
    expect(useChatStore.getState().finalizeFailed).toBe(false)
    useChatStore.setState({ finalizeFailed: true })
    useChatStore.getState().reset()
    expect(useChatStore.getState().finalizeFailed).toBe(false)
  })
})
