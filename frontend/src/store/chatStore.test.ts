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

test('applyResponse appends the reply without wiping history', () => {
  useChatStore.getState().reset()
  useChatStore.setState({ messages: [{ id: 'a', role: 'user', text: 'Sam' }] } as never)
  useChatStore.getState().applyResponse('How would you like this decorated?', 'ask_decoration', {
    options: ['Embroidery'], multiselect: true, selected: [],
  })
  const s = useChatStore.getState()
  expect(s.messages).toHaveLength(2)
  expect(s.messages[1]).toMatchObject({ role: 'assistant', text: 'How would you like this decorated?' })
  expect(s.chatState).toBe('ask_decoration')
  expect(s.multiselect).toBe(true)
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

describe('chatStore sendMessage blank-turn guard', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    vi.resetAllMocks()
  })

  it.each(['', '   ', '\n\t'])('drops a blank turn (%j) — no API call, no message', async (blank) => {
    await useChatStore.getState().sendMessage('s1', blank)
    expect(api.sendChat).not.toHaveBeenCalled()
    expect(useChatStore.getState().messages).toEqual([])
    expect(useChatStore.getState().sending).toBe(false)
  })

  it('still sends a real turn', async () => {
    vi.mocked(api.sendChat).mockResolvedValue({ reply: 'hi', state: 'ask_name', data: {} } as never)
    await useChatStore.getState().sendMessage('s1', 'Satish')
    expect(api.sendChat).toHaveBeenCalledWith('s1', 'Satish', undefined)
  })
})
