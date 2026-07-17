import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

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
})
