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
  it('does NOT auto-kickoff on mount (canvas activates chat via finalize/hydrate)', async () => {
    render(<ChatColumn />)
    // give effects a tick
    await new Promise(r => setTimeout(r, 0))
    expect(vi.mocked(sendChat)).not.toHaveBeenCalled()
  })

  it('renders an empty-state hint when there are no messages', () => {
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
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'Yes'))
  })

  it('sends typed input on submit', async () => {
    useChatStore.setState({ chatState: 'offer_refine', kickoffDone: true })
    render(<ChatColumn />)
    fireEvent.change(screen.getByPlaceholderText(/type your message/i), { target: { value: 'hello' } })
    fireEvent.submit(screen.getByRole('button', { name: 'Send' }).closest('form')!)
    await waitFor(() => expect(vi.mocked(sendChat)).toHaveBeenCalledWith('sess-1', 'hello'))
  })
})
