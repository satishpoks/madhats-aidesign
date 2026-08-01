import { describe, it, test, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { useChatStore } from '../store/chatStore'
import { useCanvasStore } from '../store/canvasStore'
import { sendChat, pollGenerationAdvance } from '../lib/api'

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

test('sendMessage applies canvas_ops from the response exactly once', async () => {
  useCanvasStore.getState().reset()
  useCanvasStore.getState().addImage('logo.png')
  vi.mocked(sendChat).mockResolvedValue({
    reply: 'Marked it.', state: 'ask_another_logo',
    data: { canvas_ops: [{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }] },
  } as never)
  await useChatStore.getState().sendMessage('s1', 'Yes, remove background')
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBe(true)
})

test('hydrate never applies canvas_ops — a resume must not re-edit the design', () => {
  useCanvasStore.getState().reset()
  useCanvasStore.getState().addImage('logo.png')
  useChatStore.getState().hydrate([], 'ask_another_logo', {
    canvas_ops: [{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }],
  })
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBeFalsy()
})

describe('sendMessage sends the live canvas_design on every turn', () => {
  beforeEach(() => {
    useCanvasStore.getState().reset()
    useCanvasStore.getState().addImage('logo.png')
  })

  it('passes the live canvas_design as the 3rd sendChat arg at describe_changes', async () => {
    useChatStore.setState({ chatState: 'describe_changes' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'Moved it up.', state: 'confirm_canvas_edit', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'move it up more')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', 'move it up more', liveDesign)
  })

  it('passes the live canvas_design at logo_adjust so a self-ticked background is seen', async () => {
    useChatStore.setState({ chatState: 'logo_adjust' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'Noted.', state: 'ask_another_logo', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'Done')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', 'Done', liveDesign)
  })

  it('also passes the live canvas_design on any other state', async () => {
    useChatStore.setState({ chatState: 'offer_refine' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'ok', state: 'offer_refine', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'hello')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', 'hello', liveDesign)
  })

  it('also passes the live canvas_design at ask_logo_bg', async () => {
    useChatStore.setState({ chatState: 'ask_logo_bg' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'ok', state: 'ask_another_logo', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'No, it\'s fine as it is')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', "No, it's fine as it is", liveDesign)
  })
})
