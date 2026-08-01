import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_name', data: {} }),
  createSession: vi.fn(),
  fetchProducts: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 24, offset: 0 }),
  fetchProduct: vi.fn(),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  addPin: vi.fn(),
  generatePreview: vi.fn().mockResolvedValue({ job_id: 'j' }),
  generationStatus: vi.fn().mockResolvedValue({ status: 'complete', image_url: 'i', watermarked_url: 'w' }),
  createLead: vi.fn(),
  sendVerify: vi.fn(),
  postComposite: vi.fn().mockResolvedValue({ views: {} }),
  pollVerification: vi.fn().mockResolvedValue({ verified: false }),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { sendChat } from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { useGenerationStore } from '../store/generationStore'
import { ChatColumn } from '../components/CustomiseStudio/ChatColumn'

function seed() {
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  })
  useChatStore.setState({
    messages: [], chatState: '', options: [], options2: [],
    triggerGeneration: false, continuable: false, tintReady: false, tintHex: '',
    colourSwatches: [], colourPicker: false, sending: false, chatError: null,
    kickoffDone: false,
  })
  useGenerationStore.getState().reset()
}

beforeEach(() => { vi.clearAllMocks(); seed() })

describe('ChatColumn', () => {
  it('auto-kicks off the intro on mount for a fresh canvas session', async () => {
    render(<ChatColumn />)
    await waitFor(() => expect(sendChat).toHaveBeenCalledWith('sess-1', ''))
  })

  it('renders an empty-state hint when there are no messages', () => {
    // Bypass kickoff (simulates a resumed session with an empty thread) so this
    // test isolates the empty-state UI rather than racing the kickoff effect.
    useChatStore.setState({ kickoffDone: true })
    render(<ChatColumn />)
    expect(screen.getByText(/design.*chat|chat.*here|render/i)).toBeInTheDocument()
  })

  it('renders hydrated messages', () => {
    useChatStore.setState({
      messages: [{ id: 'm1', role: 'assistant', text: 'Your design is on its way' }],
      chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    expect(screen.getByText('Your design is on its way')).toBeInTheDocument()
  })

  it("uses bg-chatUserBubble for the customer's own message bubble, not bg-accent", () => {
    useChatStore.setState({
      messages: [
        { id: 'a1', role: 'assistant', text: 'Hi there' },
        { id: 'u1', role: 'user', text: 'My reply' },
      ],
      chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    const bubble = screen.getByText('My reply')
    expect(bubble.className).toContain('bg-chatUserBubble')
    expect(bubble.className).not.toContain('bg-accent ')
    expect(bubble.className.split(' ')).not.toContain('bg-accent')
  })

  it('sends a chip click through chatStore.sendMessage', async () => {
    useChatStore.setState({
      messages: [{ id: 'm1', role: 'assistant', text: 'Pick one' }],
      options: ['Yes', 'No'], chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    // The live canvas now rides every turn (feeds the backend's Back
    // checkpoint snapshot), so the 3rd arg is a canvas_design object, not
    // undefined — see chatStoreBack.test.ts for the store-level coverage.
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'Yes', expect.any(Object)))
  })

  it('sends typed input on submit', async () => {
    useChatStore.setState({ chatState: 'offer_refine', kickoffDone: true })
    render(<ChatColumn />)
    fireEvent.change(screen.getByPlaceholderText(/type your message/i), { target: { value: 'hello' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!)
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'hello', expect.any(Object)))
  })

  it('ask_decoration shows a multi-select with cost caveat once 2+ chosen', async () => {
    useChatStore.getState().hydrate([], 'ask_decoration', {
      options: ['Embroidery', 'Print'], multiselect: true, selected: [],
    })
    useSessionStore.setState({ sessionId: 's1' } as never)
    render(<ChatColumn />)

    fireEvent.click(screen.getByRole('button', { name: 'Embroidery' }))
    fireEvent.click(screen.getByRole('button', { name: 'Print' }))
    expect(screen.getByText(/adds to the cost/i)).toBeInTheDocument()
  })

  it('ask_decoration with no configured options still shows Continue and submits "none"', async () => {
    useChatStore.getState().hydrate([], 'ask_decoration', { options: [], multiselect: true, selected: [] })
    render(<ChatColumn />)
    const cont = await screen.findByRole('button', { name: 'Continue' })
    fireEvent.click(cont)
    await waitFor(() => expect(sendChat).toHaveBeenCalledWith('sess-1', 'none', expect.any(Object)))
  })

  // The full checkpoint-picker menu (multiple named restore targets) is a
  // follow-up task (backMenu.test.tsx); this pins only that ChatColumn still
  // compiles and wires a Back tap through to the new store action.
  it('Back restores the newest checkpoint via goBackTo', async () => {
    const goBackTo = vi.fn()
    useChatStore.setState({
      backTargets: [{ seq: 3, label: 'Logo 1 — front', kind: 'logo' }],
      sending: false, kickoffDone: true, goBackTo,
    })
    render(<ChatColumn />)
    fireEvent.click(screen.getByText('↩ Back'))
    expect(goBackTo).toHaveBeenCalledWith('sess-1', 3)
  })

  it('hides Back when there are no checkpoints to restore', () => {
    useChatStore.setState({ backTargets: [], sending: false, kickoffDone: true })
    render(<ChatColumn />)
    expect(screen.queryByText('↩ Back')).not.toBeInTheDocument()
  })

  describe('await_email_verify (the double opt-in gate)', () => {
    // The backend's gate step declares no slots, so nothing the customer sends
    // can advance it. The UI must not invite them to try.
    function atTheGate() {
      useChatStore.getState().hydrate(
        [{ role: 'assistant', content: 'I have sent a verification link' }] as never,
        'await_email_verify',
        { canvas: { allowed_tools: [] } },
      )
    }

    it('locks the composer and refuses to send anything', async () => {
      atTheGate()
      render(<ChatColumn />)

      const input = screen.getByPlaceholderText(/type your message/i)
      expect(input).toBeDisabled()
      expect(screen.getByRole('button', { name: 'Send' })).toBeDisabled()

      // Belt and braces: even if the disabled attribute were bypassed, the
      // submit handler must drop the turn.
      fireEvent.change(input, { target: { value: 'let me through' } })
      fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!)
      await waitFor(() => expect(sendChat).not.toHaveBeenCalled())
    })

    it('explains what to do, and hides Back so the flow cannot be rewound past it', () => {
      atTheGate()
      useChatStore.setState({ backTargets: [{ seq: 1, label: 'Your name', kind: 'name' }] })
      render(<ChatColumn />)

      expect(screen.getByRole('status')).toHaveTextContent(/confirm your email/i)
      expect(screen.getByText(/spam folder/i)).toBeInTheDocument()
      expect(screen.queryByText('↩ Back')).not.toBeInTheDocument()
    })

    it('polls for the out-of-band verification while it waits', async () => {
      vi.useFakeTimers()
      try {
        atTheGate()
        const poll = vi.fn()
        useChatStore.setState({ pollVerification: poll })
        render(<ChatColumn />)
        expect(poll).not.toHaveBeenCalled()
        act(() => { vi.advanceTimersByTime(4000) })
        expect(poll).toHaveBeenCalledWith('sess-1')
      } finally {
        vi.useRealTimers()
      }
    })

    it('re-enables the composer once verification releases the gate', () => {
      atTheGate()
      const { rerender } = render(<ChatColumn />)
      expect(screen.getByPlaceholderText(/type your message/i)).toBeDisabled()

      act(() => { useChatStore.setState({ chatState: 'ask_another_logo' }) })
      rerender(<ChatColumn />)

      expect(screen.getByPlaceholderText(/type your message/i)).not.toBeDisabled()
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
  })

  it('Back stays available across a chat state change while checkpoints remain', () => {
    const goBackTo = vi.fn()
    useChatStore.setState({
      backTargets: [{ seq: 2, label: 'Logo 1 — front', kind: 'logo' }],
      sending: false, kickoffDone: true, goBackTo,
      chatState: 'ask_logo_bg',
    })
    render(<ChatColumn />)
    expect(screen.getByText('↩ Back')).toBeInTheDocument()

    act(() => { useChatStore.setState({ chatState: 'logo_adjust' }) })

    expect(screen.getByText('↩ Back')).toBeInTheDocument()
  })
})
