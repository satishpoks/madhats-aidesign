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
  uploadLogo: vi.fn().mockResolvedValue({
    asset_url: 'https://cdn.example.com/logo.png',
    asset_hash: 'abc123',
  }),
  addPin: vi.fn().mockResolvedValue({ pin_id: 'pin-1' }),
  generatePreview: vi.fn().mockResolvedValue({ job_id: 'job-1' }),
  generationStatus: vi.fn().mockResolvedValue({
    status: 'complete',
    image_url: 'https://cdn.example.com/clean.png',
    watermarked_url: 'https://cdn.example.com/wm.png',
  }),
  createLead: vi.fn().mockResolvedValue({ lead_id: 'lead-1' }),
  sendVerify: vi.fn().mockResolvedValue({ sent: true }),
}))

import {
  sendChat,
  uploadLogo,
  addPin,
  generatePreview,
  generationStatus,
} from '../lib/api'
import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { useGenerationStore } from '../store/generationStore'
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
      view_images: {
        front: 'https://example.com/front.jpg',
        back: 'https://example.com/back.jpg',
      },
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
  vi.mocked(uploadLogo).mockResolvedValue({
    asset_url: 'https://cdn.example.com/logo.png',
    asset_hash: 'abc123',
  })
  vi.mocked(addPin).mockResolvedValue({ pin_id: 'pin-1' })
  vi.mocked(generatePreview).mockResolvedValue({ job_id: 'job-1' })
  vi.mocked(generationStatus).mockResolvedValue({
    status: 'complete',
    image_url: 'https://cdn.example.com/clean.png',
    watermarked_url: 'https://cdn.example.com/wm.png',
  })
  useGenerationStore.getState().reset()
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
  it('renders the logo file input when state is upload_logo', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Please upload your logo.',
      state: 'upload_logo',
      data: {},
    })
    render(<ChatPanel />)
    await screen.findByText('Please upload your logo.')
    // Real LogoUploader replaces the old placeholder
    expect(document.querySelector('input[type="file"]')).toBeInTheDocument()
  })

  it('triggers generation but does NOT show the design in-chat (email-only delivery)', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Generating your design now…',
      state: 'generating',
      data: { trigger_generation: true },
    })
    render(<ChatPanel />)
    await screen.findByText('Generating your design now…')
    // Generation is kicked off through the API…
    await waitFor(() => expect(generatePreview).toHaveBeenCalledWith('sess-test-123'))
    // …and once complete the customer sees a confirmation, but NEVER the image
    // itself — the finished design is delivered exclusively by email.
    await screen.findByText(/we'll email it to you/i)
    expect(screen.queryByAltText('Generated cap design preview')).not.toBeInTheDocument()
  })

  it('captures the email inline at ask_email — no separate contact form', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'What is your email?',
      state: 'ask_email',
      data: {},
    })
    render(<ChatPanel />)
    await screen.findByText('What is your email?')

    // The redundant name/email/phone form must NOT appear — we already have
    // the customer's name, so the email is typed straight into the chat input.
    expect(screen.queryByLabelText('Your name')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send my design/i })).not.toBeInTheDocument()

    const input = screen.getByRole('textbox')
    fireEvent.change(input, { target: { value: 'sam@example.com' } })
    fireEvent.submit(input.closest('form')!)

    // The email is sent through the normal chat turn, which captures it
    // server-side and advances the conversation.
    await waitFor(() =>
      expect(sendChat).toHaveBeenCalledWith('sess-test-123', 'sam@example.com'),
    )
  })
})

// ---------------------------------------------------------------------------
// Logo upload
// ---------------------------------------------------------------------------

describe('ChatPanel logo upload', () => {
  it('calls uploadLogo when a file is selected and advances via sendChat', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'Please upload your logo.',
        state: 'upload_logo',
        data: {},
      })
      .mockResolvedValueOnce({
        reply: 'Should I remove the background?',
        state: 'ask_remove_bg',
        data: {},
      })

    render(<ChatPanel />)
    await screen.findByText('Please upload your logo.')

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    expect(fileInput).not.toBeNull()

    const file = new File(['logo-data'], 'logo.png', { type: 'image/png' })
    // Provide the file list via the getter so React's SyntheticEvent can read it
    Object.defineProperty(fileInput, 'files', {
      configurable: true,
      get: () => ({ 0: file, length: 1, item: (i: number) => (i === 0 ? file : null) }),
    })
    fireEvent.change(fileInput)

    await waitFor(() => {
      expect(vi.mocked(uploadLogo)).toHaveBeenCalledWith('sess-test-123', file)
    })
    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', 'Uploaded my logo')
    })
  })

  it('shows thumbnail preview while uploading', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Please upload your logo.',
      state: 'upload_logo',
      data: {},
    })
    // Keep uploadLogo pending so we can inspect the uploading state
    let resolveUpload!: () => void
    vi.mocked(uploadLogo).mockReturnValue(
      new Promise(res => {
        resolveUpload = () => res({ asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc' })
      }),
    )

    render(<ChatPanel />)
    await screen.findByText('Please upload your logo.')

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['logo'], 'logo.png', { type: 'image/png' })
    Object.defineProperty(fileInput, 'files', {
      configurable: true,
      get: () => ({ 0: file, length: 1, item: (i: number) => (i === 0 ? file : null) }),
    })
    fireEvent.change(fileInput)

    // Thumbnail uses the blob URL stub from setup.ts
    await waitFor(() => {
      expect(screen.getByAltText('Logo preview')).toBeInTheDocument()
    })
    // "Uploading…" text should be visible
    expect(screen.getByText(/uploading…/i)).toBeInTheDocument()

    // Resolve so the test doesn't leak
    resolveUpload()
  })

  it('shows inline error on upload failure without crashing', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Please upload your logo.',
      state: 'upload_logo',
      data: {},
    })
    vi.mocked(uploadLogo).mockRejectedValue(new Error('Upload failed — server error'))

    render(<ChatPanel />)
    await screen.findByText('Please upload your logo.')

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['logo'], 'logo.png', { type: 'image/png' })
    Object.defineProperty(fileInput, 'files', {
      configurable: true,
      get: () => ({ 0: file, length: 1, item: (i: number) => (i === 0 ? file : null) }),
    })
    fireEvent.change(fileInput)

    await waitFor(() => {
      expect(screen.getByText(/Upload failed — server error/i)).toBeInTheDocument()
    })
    // sendChat must NOT have been called — conversation must not advance on failure
    expect(vi.mocked(sendChat)).toHaveBeenCalledTimes(1) // only kickoff
  })
})

// ---------------------------------------------------------------------------
// Pin annotator
// ---------------------------------------------------------------------------

describe('ChatPanel pin annotator', () => {
  it('renders view image when state is pin_annotate_mode', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Click on the cap to mark a placement spot.',
      state: 'pin_annotate_mode',
      data: {},
    })
    render(<ChatPanel />)
    await screen.findByText('Click on the cap to mark a placement spot.')
    // The PinAnnotator renders the cap image with the active view alt text
    expect(screen.getByAltText(/front view/i)).toBeInTheDocument()
  })

  it('computes x_pct/y_pct from click position and calls addPin', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Click on the cap to mark a placement spot.',
      state: 'pin_annotate_mode',
      data: {},
    })

    render(<ChatPanel />)
    await screen.findByText('Click on the cap to mark a placement spot.')

    const img = screen.getByAltText(/front view/i)
    // Mock getBoundingClientRect so we get deterministic x_pct/y_pct
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue({
      left: 0,
      top: 0,
      width: 400,
      height: 300,
      right: 400,
      bottom: 300,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    // Click at the centre of the (mocked) image
    fireEvent.click(img, { clientX: 200, clientY: 150 })

    // Comment input and Save pin button should appear
    const commentInput = await screen.findByPlaceholderText(/describe this placement/i)
    fireEvent.change(commentInput, { target: { value: 'Logo here' } })

    const saveBtn = screen.getByRole('button', { name: /save pin/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(vi.mocked(addPin)).toHaveBeenCalledWith('sess-test-123', {
        view: 'front',
        x_pct: 50,
        y_pct: 50,
        comment: 'Logo here',
      })
    })
  })

  it('shows "Add another" and "Done — generate" after saving a pin', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Click on the cap to mark a placement spot.',
      state: 'pin_annotate_mode',
      data: {},
    })

    render(<ChatPanel />)
    await screen.findByText('Click on the cap to mark a placement spot.')

    const img = screen.getByAltText(/front view/i)
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 400, height: 300,
      right: 400, bottom: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    fireEvent.click(img, { clientX: 100, clientY: 100 })
    const saveBtn = await screen.findByRole('button', { name: /save pin/i })
    fireEvent.click(saveBtn)

    await screen.findByRole('button', { name: /add another/i })
    expect(screen.getByRole('button', { name: /done/i })).toBeInTheDocument()
  })

  it('"Add another" sends correct message to advance conversation', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'Click on the cap.',
        state: 'pin_annotate_mode',
        data: {},
      })
      .mockResolvedValueOnce({
        reply: 'Sure, add another pin.',
        state: 'pin_annotate_mode',
        data: {},
      })

    render(<ChatPanel />)
    await screen.findByText('Click on the cap.')

    const img = screen.getByAltText(/front view/i)
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 400, height: 300,
      right: 400, bottom: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    fireEvent.click(img, { clientX: 100, clientY: 100 })
    const saveBtn = await screen.findByRole('button', { name: /save pin/i })
    fireEvent.click(saveBtn)

    const addAnotherBtn = await screen.findByRole('button', { name: /add another/i })
    fireEvent.click(addAnotherBtn)

    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', 'add another')
    })
  })

  it('"Done — generate" sends "done" to advance conversation', async () => {
    vi.mocked(sendChat)
      .mockResolvedValueOnce({
        reply: 'Click on the cap.',
        state: 'pin_annotate_mode',
        data: {},
      })
      .mockResolvedValueOnce({
        reply: 'Generating now!',
        state: 'generating',
        data: { trigger_generation: true },
      })

    render(<ChatPanel />)
    await screen.findByText('Click on the cap.')

    const img = screen.getByAltText(/front view/i)
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 400, height: 300,
      right: 400, bottom: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    fireEvent.click(img, { clientX: 100, clientY: 100 })
    const saveBtn = await screen.findByRole('button', { name: /save pin/i })
    fireEvent.click(saveBtn)

    const doneBtn = await screen.findByRole('button', { name: /done/i })
    fireEvent.click(doneBtn)

    await waitFor(() => {
      expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-test-123', 'done')
    })
  })

  it('pin annotator error surfaces via the chatError banner', async () => {
    vi.mocked(sendChat).mockResolvedValueOnce({
      reply: 'Click on the cap.',
      state: 'pin_annotate_mode',
      data: {},
    })
    vi.mocked(addPin).mockRejectedValue(new Error('Pin save failed'))

    render(<ChatPanel />)
    await screen.findByText('Click on the cap.')

    const img = screen.getByAltText(/front view/i)
    vi.spyOn(img, 'getBoundingClientRect').mockReturnValue({
      left: 0, top: 0, width: 400, height: 300,
      right: 400, bottom: 300, x: 0, y: 0,
      toJSON: () => ({}),
    } as DOMRect)

    fireEvent.click(img, { clientX: 100, clientY: 100 })
    const saveBtn = await screen.findByRole('button', { name: /save pin/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByText(/Pin save failed/i)).toBeInTheDocument()
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
