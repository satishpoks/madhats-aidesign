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

  it('sends a chip click through chatStore.sendMessage', async () => {
    useChatStore.setState({
      messages: [{ id: 'm1', role: 'assistant', text: 'Pick one' }],
      options: ['Yes', 'No'], chatState: 'offer_refine', kickoffDone: true,
    })
    render(<ChatColumn />)
    fireEvent.click(screen.getByRole('button', { name: 'Yes' }))
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'Yes', undefined))
  })

  it('sends typed input on submit', async () => {
    useChatStore.setState({ chatState: 'offer_refine', kickoffDone: true })
    render(<ChatColumn />)
    fireEvent.change(screen.getByPlaceholderText(/type your message/i), { target: { value: 'hello' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!)
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'hello', undefined))
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
    await waitFor(() => expect(sendChat).toHaveBeenCalledWith('sess-1', 'none', undefined))
  })

  it('Back shows a confirm and only removes on confirm when backRemovesElement', async () => {
    const goBack = vi.fn()
    useChatStore.setState({
      canGoBack: true, backRemovesElement: true, sending: false, kickoffDone: true, goBack,
    })
    render(<ChatColumn />)

    fireEvent.click(screen.getByText('↩ Back'))
    expect(goBack).not.toHaveBeenCalled() // confirm first, no immediate back
    expect(screen.getByText(/start it over/i)).toBeInTheDocument()

    fireEvent.click(screen.getByText('Keep going'))
    expect(goBack).not.toHaveBeenCalled() // declined

    fireEvent.click(screen.getByText('↩ Back'))
    fireEvent.click(screen.getByText('Remove & start over'))
    expect(goBack).toHaveBeenCalledTimes(1)
  })

  it('Back goes straight through when backRemovesElement is false', async () => {
    const goBack = vi.fn()
    useChatStore.setState({
      canGoBack: true, backRemovesElement: false, sending: false, kickoffDone: true, goBack,
    })
    render(<ChatColumn />)
    fireEvent.click(screen.getByText('↩ Back'))
    expect(goBack).toHaveBeenCalledTimes(1) // no confirm step
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
      useChatStore.setState({ canGoBack: true, backRemovesElement: false })
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

  it('resets an open Back confirm when the chat state changes, so it cannot reappear unbidden later', async () => {
    const goBack = vi.fn()
    useChatStore.setState({
      canGoBack: true, backRemovesElement: true, sending: false, kickoffDone: true, goBack,
      chatState: 'ask_logo_bg',
    })
    render(<ChatColumn />)

    fireEvent.click(screen.getByText('↩ Back'))
    expect(screen.getByText(/start it over/i)).toBeInTheDocument()

    // Advance the step without answering the confirm (e.g. the customer tapped
    // a still-visible chip instead). The confirm must not survive the step change.
    act(() => { useChatStore.setState({ chatState: 'logo_adjust' }) })

    expect(screen.queryByText(/start it over/i)).not.toBeInTheDocument()
    expect(screen.getByText('↩ Back')).toBeInTheDocument()
  })
})
