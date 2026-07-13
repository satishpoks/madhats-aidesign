import { describe, it, test, expect, vi, beforeEach } from 'vitest'
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

test('parses multiselect + selected from data', () => {
  useChatStore.getState().reset()
  useChatStore.getState().hydrate([], 'ask_decoration', {
    options: ['Embroidery', 'Print'], multiselect: true, selected: ['Print'],
  })
  const s = useChatStore.getState()
  expect(s.multiselect).toBe(true)
  expect(s.selected).toEqual(['Print'])
  expect(s.options).toEqual(['Embroidery', 'Print'])
})

describe('chatStore advanceRegeneration', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    vi.resetAllMocks()
  })

  it('advances from regenerating to offer_refine and appends the reply', async () => {
    vi.mocked(api.pollRegeneration).mockResolvedValue({
      reply: 'Happy with it?',
      state: 'offer_refine',
      data: { options: ['Request changes', 'Looks good'] },
    } as never)

    await useChatStore.getState().advanceRegeneration('s1')

    expect(useChatStore.getState().chatState).toBe('offer_refine')
    expect(useChatStore.getState().options).toEqual(['Request changes', 'Looks good'])
    const messages = useChatStore.getState().messages
    expect(messages[messages.length - 1]).toMatchObject({ role: 'assistant', text: 'Happy with it?' })
  })

  it('does nothing when reply is null (not at regenerating)', async () => {
    vi.mocked(api.pollRegeneration).mockResolvedValue({
      reply: null,
      state: 'ask_quantity',
      data: {},
    } as never)

    await useChatStore.getState().advanceRegeneration('s1')

    expect(useChatStore.getState().messages).toEqual([])
    expect(useChatStore.getState().chatState).toBe('')
  })
})
