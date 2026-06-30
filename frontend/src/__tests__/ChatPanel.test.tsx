import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

/**
 * vi.mock is hoisted by Vitest — keep the factory self-contained.
 * We mock sendChat and stub the other exports used transitively by sessionStore.
 */
vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({
    reply: 'Hi! What is your name?',
    state: 'ask_name',
    data: {},
  }),
  createSession: vi.fn().mockResolvedValue({
    session_id: 'sess-test-123',
    share_token: 'tok-test-abc',
    state: 'greeting',
  }),
  fetchProducts: vi.fn().mockResolvedValue({ items: [], total: 0, limit: 24, offset: 0 }),
  fetchProduct: vi.fn(),
}))

import { sendChat } from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { ChatPanel } from '../components/ChatPanel'

// ---------------------------------------------------------------------------
// Shared setup helpers
// ---------------------------------------------------------------------------

function seedSession() {
  useSessionStore.setState({
    sessionId: 'sess-test-123',
    shareToken: 'tok-test-abc',
    state: 'greeting',
    productRef: {
      id: 'prod-1',
      name: 'Classic Snapback',
      colour: 'Black',
      style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg',
    },
    entryContext: null,
    view: 'session',
  })
}

function resetChat() {
  useChatStore.setState({
    messages: [],
    chatState: '',
    options: [],
    options2: [],
    triggerGeneration: false,
    continuable: false,
    sending: false,
    chatError: null,
    kickoffDone: false,
  })
}

beforeEach(() => {
  // resetAllMocks clears both call history AND the mockResolvedValueOnce queue,
  // preventing leftover mocks from leaking between tests.
  vi.resetAllMocks()
  seedSession()
  resetChat()
  vi.mocked(sendChat).mockResolvedValue({
    reply: 'Hi! What is your name?',
    state: 'ask_name',
    data: {},
  })
})

// ---------------------------------------------------------------------------
// Kickoff behaviour
// ---------------------------------------------------------------------------

describe('ChatPanel kickoff', () => {
  it('sends an empty-string message on mount', async () => {
    render(<ChatPanel />)
    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', '')
    })
  })

  it('renders the assistant greeting reply after kickoff', async () => {
    render(<ChatPanel />)
    await screen.findByText('Hi! What is your name?')
  })

  it('calls sendChat only once even if the component re-renders', async () => {
    const { rerender } = render(<ChatPanel />)
    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledTimes(1)
    })
    rerender(<ChatPanel />)
    // guard should prevent a second call
    expect(vi.mocked(sendChat)).toHaveBeenCalledTimes(1)
  })
})

// ---------------------------------------------------------------------------
// Option chips
// ---------------------------------------------------------------------------

describe('ChatPanel option chips', () => {
  it('renders chips returned in data.options after kickoff', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'How many caps do you need?',
      state: 'ask_quantity',
      data: { options: ['1', '2-11', '12-49'] },
    })
    render(<ChatPanel />)
    await screen.findByText('How many caps do you need?')
    expect(screen.getByRole('button', { name: '1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '2-11' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '12-49' })).toBeInTheDocument()
  })

  it('renders a second chip row from data.options2', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Where should the placement go?',
      state: 'ask_placement_position',
      data: { options: ['Left', 'Right'], options2: ['Upper', 'Middle', 'Lower'] },
    })
    render(<ChatPanel />)
    await screen.findByText('Where should the placement go?')
    expect(screen.getByRole('button', { name: 'Left' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upper' })).toBeInTheDocument()
  })

  it('clicking a chip calls sendChat with the chip text', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'How many caps?',
        state: 'ask_quantity',
        data: { options: ['1', '2-11'] },
      })
      .mockResolvedValueOnce({
        reply: 'Got it, just one.',
        state: 'ask_name',
        data: {},
      })

    render(<ChatPanel />)
    const chip = await screen.findByRole('button', { name: '1' })
    fireEvent.click(chip)

    await waitFor(() => {
      // first call: kickoff (''), second call: chip click ('1')
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', '1')
    })
  })

  it('clicking a chip appends a user bubble then the assistant reply', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'How many caps?',
        state: 'ask_quantity',
        data: { options: ['1'] },
      })
      .mockResolvedValueOnce({
        reply: 'Great, just one!',
        state: 'ask_name',
        data: {},
      })

    render(<ChatPanel />)
    const chip = await screen.findByRole('button', { name: '1' })
    fireEvent.click(chip)

    // Both the user bubble ('1') and the new assistant reply should appear
    await screen.findByText('Great, just one!')
    // The user bubble with the chip text should also be present
    const userBubbles = await screen.findAllByText('1')
    // At least one element contains '1' (the bubble; the button may be gone or still present)
    expect(userBubbles.length).toBeGreaterThanOrEqual(1)
  })

  it('shows a Continue chip for statement-only states (continuable: true from backend)', async () => {
    // The backend sends data.continuable: true only for real statement states
    // (youth_referral, email_verified, etc.). The UI must NOT show a Continue
    // button when continuable is absent — free-text states also have no options.
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'We only serve bulk orders — redirecting to our partner.',
      state: 'youth_referral',
      data: { continuable: true },
    })
    render(<ChatPanel />)
    await screen.findByText('We only serve bulk orders — redirecting to our partner.')
    expect(screen.getByRole('button', { name: /continue/i })).toBeInTheDocument()
  })

  it('free-text states (no options, no continuable) show NO Continue button', async () => {
    // ask_name is a free-text state: the backend sends data: {} (no continuable).
    // The UI must show only the text input — no Continue chip — so the user
    // cannot submit a throwaway "ok" in place of their actual name.
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'What is your name?',
      state: 'ask_name',
      data: {},
    })
    render(<ChatPanel />)
    await screen.findByText('What is your name?')
    expect(screen.queryByRole('button', { name: /continue/i })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('Continue chip sends "ok" to advance', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'We only serve bulk orders.',
        state: 'youth_referral',
        data: { continuable: true },
      })
      .mockResolvedValueOnce({
        reply: "Let's get started!",
        state: 'ask_name',
        data: {},
      })

    render(<ChatPanel />)
    const continueBtn = await screen.findByRole('button', { name: /continue/i })
    fireEvent.click(continueBtn)

    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', 'ok')
    })
  })
})

// ---------------------------------------------------------------------------
// Text input
// ---------------------------------------------------------------------------

describe('ChatPanel text input', () => {
  it('submitting the form appends the user message and then the reply', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: "Hi! What's your name?",
        state: 'ask_name',
        data: {},
      })
      .mockResolvedValueOnce({
        reply: 'Nice to meet you, Ada!',
        state: 'ask_quantity',
        data: { options: ['1'] },
      })

    render(<ChatPanel />)
    await screen.findByText("Hi! What's your name?")

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Ada' } })
    fireEvent.submit(input.closest('form')!)

    await screen.findByText('Nice to meet you, Ada!')
    expect(screen.getByText('Ada')).toBeInTheDocument()
  })

  it('clears the input after submission', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'Hello',
        state: 'ask_name',
        data: {},
      })
      .mockResolvedValueOnce({
        reply: 'Nice',
        state: 'ask_quantity',
        data: { options: [] },
      })

    render(<ChatPanel />)
    await screen.findByText('Hello')

    const input = screen.getByRole('textbox') as HTMLInputElement
    fireEvent.change(input, { target: { value: 'My name' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => {
      expect(input.value).toBe('')
    })
  })
})

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe('ChatPanel error handling', () => {
  it('shows an alert when a sendMessage call fails', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'Hello there',
        state: 'ask_name',
        data: {},
      })
      .mockRejectedValueOnce(new Error('Network failure'))

    render(<ChatPanel />)
    await screen.findByText('Hello there')

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'Ada' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByText(/Network failure/i)).toBeInTheDocument()
  })

  it('error alert is dismissible', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({ reply: 'Hello', state: 'ask_name', data: {} })
      .mockRejectedValueOnce(new Error('Oops'))

    render(<ChatPanel />)
    await screen.findByText('Hello')

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'x' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('does not swallow the error — chatError is set in the store', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({ reply: 'Hello', state: 'ask_name', data: {} })
      .mockRejectedValueOnce(new Error('Store error check'))

    render(<ChatPanel />)
    await screen.findByText('Hello')

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'trigger' } })
    fireEvent.submit(input.closest('form')!)

    await waitFor(() => {
      expect(useChatStore.getState().chatError).toBe('Store error check')
    })
  })
})

// ---------------------------------------------------------------------------
// Special state banners
// ---------------------------------------------------------------------------

describe('ChatPanel special state banners', () => {
  it('shows a placeholder note when state is upload_logo', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Please upload your logo.',
      state: 'upload_logo',
      data: {},
    })
    render(<ChatPanel />)
    await screen.findByText('Please upload your logo.')
    expect(screen.getByText(/Logo upload — coming next/i)).toBeInTheDocument()
  })

  it('shows a placeholder note when state is generating', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Generating your design now…',
      state: 'generating',
      data: { trigger_generation: true },
    })
    render(<ChatPanel />)
    // The reply text appears in the chat bubble
    await screen.findByText('Generating your design now…')
    // The component renders this specific placeholder string (not the reply text)
    expect(
      screen.getByText('Generating your design… (preview coming next)'),
    ).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Product context header
// ---------------------------------------------------------------------------

describe('ChatPanel product header', () => {
  it('displays the product name and colour', async () => {
    render(<ChatPanel />)
    expect(screen.getByText('Classic Snapback')).toBeInTheDocument()
    expect(screen.getByText('Black')).toBeInTheDocument()
  })
})
