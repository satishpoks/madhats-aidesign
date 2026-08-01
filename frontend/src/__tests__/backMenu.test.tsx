import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

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

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { useGenerationStore } from '../store/generationStore'
import { ChatColumn } from '../components/CustomiseStudio/ChatColumn'

// The Back menu is entirely store-driven: ChatColumn takes no props (it reads
// the session from useSessionStore), so every test seeds the session id via
// the store rather than a `sessionId` prop.
function seed() {
  useSessionStore.setState({
    sessionId: 's1', shareToken: 't', state: 'greeting',
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
    kickoffDone: true, backTargets: [],
  })
  useGenerationStore.getState().reset()
}

beforeEach(() => { vi.clearAllMocks(); seed() })

describe('backMenu', () => {
  it('renders no Back button when there are no targets', () => {
    useChatStore.setState({ backTargets: [] })
    render(<ChatColumn />)
    expect(screen.queryByText(/Back/)).toBeNull()
  })

  it('opens a list of destinations, newest first', async () => {
    // Order is asserted on the DOM, not just presence: two passes of the same
    // loop can render near-identical labels ("Logo 1 — front" / "Logo 2 —
    // front"), so position is the customer's only disambiguator and picking
    // the wrong one discards work. The backend ships back_targets already
    // sorted newest-first; this pins that the component preserves it.
    useChatStore.setState({ backTargets: [
      { seq: 3, label: 'Logo 2 — back', kind: 'logo' },
      { seq: 2, label: 'Logo 1 — front', kind: 'logo' },
      { seq: 1, label: 'Your name — Satish', kind: 'name' },
    ] })
    render(<ChatColumn />)
    await userEvent.click(screen.getByText(/Back/))
    const labels = screen.getAllByRole('button').map(b => b.textContent)
    const rendered = labels.filter(
      l => l === 'Logo 2 — back' || l === 'Logo 1 — front' || l === 'Your name — Satish')
    expect(rendered).toEqual(['Logo 2 — back', 'Logo 1 — front', 'Your name — Satish'])
  })

  it('picking a destination calls goBackTo with its seq', async () => {
    const spy = vi.fn()
    useChatStore.setState({
      backTargets: [{ seq: 3, label: 'Logo 2 — back', kind: 'logo' }],
      goBackTo: spy,
    })
    render(<ChatColumn />)
    await userEvent.click(screen.getByText(/Back/))
    await userEvent.click(screen.getByText('Logo 2 — back'))
    expect(spy).toHaveBeenCalledWith('s1', 3)
  })

  it('Cancel closes the menu without a request', async () => {
    const spy = vi.fn()
    useChatStore.setState({
      backTargets: [{ seq: 3, label: 'Logo 2 — back', kind: 'logo' }],
      goBackTo: spy,
    })
    render(<ChatColumn />)
    await userEvent.click(screen.getByText(/Back/))
    await userEvent.click(screen.getByText(/Cancel/))
    expect(spy).not.toHaveBeenCalled()
    expect(screen.queryByText('Logo 2 — back')).toBeNull()
  })

  it('hides Back at the email verification gate', () => {
    useChatStore.setState({
      backTargets: [{ seq: 1, label: 'L', kind: 'name' }],
      chatState: 'await_email_verify',
    })
    render(<ChatColumn />)
    expect(screen.queryByText(/Back/)).toBeNull()
  })
})
