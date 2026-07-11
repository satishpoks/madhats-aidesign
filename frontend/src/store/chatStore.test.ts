import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useChatStore } from './chatStore'
import * as api from '../lib/api'

vi.mock('../lib/api')

describe('chatStore progress', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    vi.resetAllMocks()
  })

  it('captures progress from the chat response', async () => {
    vi.mocked(api.sendChat).mockResolvedValue({
      reply: 'ok',
      state: 'ask_quantity',
      data: { progress: { step: 3, total: 9 } },
    } as never)
    await useChatStore.getState().sendMessage('s1', 'hi')
    expect(useChatStore.getState().progress).toEqual({ step: 3, total: 9 })
  })
})
