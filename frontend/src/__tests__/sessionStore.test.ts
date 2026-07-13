import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Product } from '../lib/types'

// Mock the api module before importing the store
vi.mock('../lib/api', () => ({
  createSession: vi.fn().mockResolvedValue({
    session_id: 'sess-test-123',
    share_token: 'tok-test-abc',
    state: 'collecting_brief',
  }),
  createBlankSession: vi.fn().mockResolvedValue({
    session_id: 'blank-sess-1',
    share_token: 'blank-tok-1',
    state: 'greeting',
  }),
  fetchProduct: vi.fn().mockResolvedValue({
    id: 'prod-1',
    name: 'Classic Snapback',
    colour: 'Black',
    style: 'snapback',
    reference_image_url: 'https://example.com/cap.jpg',
    view_images: { front: 'https://example.com/front.jpg' },
    placement_zones: ['front'],
    decoration_types: ['embroidery'],
  } satisfies Product),
  createCanvasSession: vi.fn().mockResolvedValue({
    session_id: 'canvas-sess-1',
    share_token: 'canvas-tok-1',
    state: 'canvas_design',
  }),
  getSession: vi.fn().mockResolvedValue({
    session_id: 'sess-resume-1',
    share_token: 'tok-resume-1',
    state: 'upsell_prompt',
    channel: 'web',
    entry_path: 'pick_first',
    product_ref: {
      product_id: 'prod-1',
      name: 'Classic Snapback',
      style: 'snapback',
      colour: 'Black',
      reference_image_url: 'https://example.com/cap.jpg',
    },
    collected: { name: 'Sarah' },
    status: 'draft',
    messages: [
      { role: 'assistant', content: 'Hi! What is your name?', state_before: 'greeting', state_after: 'ask_name', created_at: '2026-01-01T00:00:00Z' },
      { role: 'user', content: 'Sarah', state_before: 'ask_name', state_after: 'ask_name', created_at: '2026-01-01T00:00:01Z' },
    ],
    data: { options: ['Yes, add more', "No, I'm happy"] },
  }),
}))

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'

const mockProduct: Product = {
  id: 'prod-1',
  name: 'Classic Snapback',
  colour: 'Black',
  style: 'snapback',
  reference_image_url: 'https://example.com/cap.jpg',
  view_images: {},
  placement_zones: ['front'],
  decoration_types: ['embroidery'],
}

beforeEach(() => {
  // Reset store to initial state between tests
  useSessionStore.setState({
    sessionId: null,
    shareToken: null,
    state: null,
    productRef: null,
    entryContext: null,
    view: 'picker',
  })
})

describe('sessionStore initial state', () => {
  it('starts in picker view', () => {
    expect(useSessionStore.getState().view).toBe('picker')
  })

  it('starts with null session', () => {
    const { sessionId, shareToken, state, productRef } = useSessionStore.getState()
    expect(sessionId).toBeNull()
    expect(shareToken).toBeNull()
    expect(state).toBeNull()
    expect(productRef).toBeNull()
  })
})

describe('startSession', () => {
  it('sets view to session on success', async () => {
    await useSessionStore.getState().startSession(mockProduct)
    expect(useSessionStore.getState().view).toBe('session')
  })

  it('stores session_id and share_token', async () => {
    await useSessionStore.getState().startSession(mockProduct)
    const { sessionId, shareToken } = useSessionStore.getState()
    expect(sessionId).toBe('sess-test-123')
    expect(shareToken).toBe('tok-test-abc')
  })

  it('stores the conversation state string', async () => {
    await useSessionStore.getState().startSession(mockProduct)
    expect(useSessionStore.getState().state).toBe('collecting_brief')
  })

  it('stores a productRef with the product name and colour', async () => {
    await useSessionStore.getState().startSession(mockProduct)
    const { productRef } = useSessionStore.getState()
    expect(productRef?.name).toBe('Classic Snapback')
    expect(productRef?.colour).toBe('Black')
    expect(productRef?.id).toBe('prod-1')
  })
})

describe('startBlankSession', () => {
  const mockHatType = {
    id: 'hat-1',
    slug: 'five-panel',
    name: '5-Panel',
    style: 'flat',
    view_images: { front: 'https://example.com/blank-front.png', back: 'https://example.com/blank-back.png' },
    colours: [{ name: 'Black', hex: '#000000' }],
    placement_zones: ['front_panel'],
    decoration_types: ['print'],
  }

  it('sets view to session and stores the blank session ids', async () => {
    await useSessionStore.getState().startBlankSession(mockHatType)
    const s = useSessionStore.getState()
    expect(s.view).toBe('session')
    expect(s.sessionId).toBe('blank-sess-1')
    expect(s.shareToken).toBe('blank-tok-1')
  })

  it('populates productRef from the hat type so the viewer loads (regression: was left null)', async () => {
    // Colour is chosen in chat now, so it starts empty on the productRef.
    await useSessionStore.getState().startBlankSession(mockHatType)
    const { productRef } = useSessionStore.getState()
    expect(productRef).not.toBeNull()
    expect(productRef?.name).toBe('5-Panel')
    expect(productRef?.reference_image_url).toBe('https://example.com/blank-front.png')
    expect(productRef?.view_images.back).toBe('https://example.com/blank-back.png')
    expect(productRef?.colour).toBe('')
  })
})

describe('bootstrapFromUrl', () => {
  it('does nothing when product_id is absent from URL', async () => {
    // jsdom URL defaults to about:blank — no query params
    await useSessionStore.getState().bootstrapFromUrl()
    expect(useSessionStore.getState().view).toBe('picker')
    expect(useSessionStore.getState().sessionId).toBeNull()
  })

  it('starts a canvas session when product_id is present in URL', async () => {
    Object.defineProperty(window, 'location', {
      value: { search: '?product_id=prod-1&source=shopify' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()
    expect(useSessionStore.getState().view).toBe('canvas')
    // Restore
    Object.defineProperty(window, 'location', {
      value: { search: '' },
      writable: true,
    })
  })

  it('captures variant_id, colour, and source in entryContext', async () => {
    Object.defineProperty(window, 'location', {
      value: { search: '?product_id=prod-1&variant_id=var-99&colour=red&source=shopify' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()
    const { entryContext } = useSessionStore.getState()
    expect(entryContext?.variantId).toBe('var-99')
    expect(entryContext?.colour).toBe('red')
    expect(entryContext?.source).toBe('shopify')
    // Restore
    Object.defineProperty(window, 'location', {
      value: { search: '' },
      writable: true,
    })
  })

  it('resumes an existing session from a ?session=<token> link (edit CTA)', async () => {
    Object.defineProperty(window, 'location', {
      value: { search: '?session=tok-resume-1' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()

    const s = useSessionStore.getState()
    expect(s.view).toBe('session')
    expect(s.sessionId).toBe('sess-resume-1')
    expect(s.shareToken).toBe('tok-resume-1')
    expect(s.state).toBe('upsell_prompt')
    // Full product (with view_images) is pulled for the left-pane angles.
    expect(s.productRef?.view_images.front).toBe('https://example.com/front.jpg')

    // The chat thread is rehydrated from history, with the resumed state's chips.
    const chat = useChatStore.getState()
    expect(chat.messages.map(m => m.text)).toEqual(['Hi! What is your name?', 'Sarah'])
    expect(chat.chatState).toBe('upsell_prompt')
    expect(chat.options).toEqual(['Yes, add more', "No, I'm happy"])
    expect(chat.kickoffDone).toBe(true) // never re-fire the greeting on resume

    Object.defineProperty(window, 'location', { value: { search: '' }, writable: true })
  })

  it('resumes a BLANK session using the ref angles without hitting /products (regression)', async () => {
    const { getSession, fetchProduct } = await import('../lib/api')
    vi.mocked(getSession).mockResolvedValueOnce({
      session_id: 'blank-resume-1',
      share_token: 'blank-tok-resume',
      state: 'ask_more_elements',
      channel: 'web',
      entry_path: 'blank',
      product_ref: {
        product_id: 'hat-type-uuid', // a hat_type id, NOT a catalogue product
        name: 'Tucker',
        style: 'tucker',
        colour: '',
        reference_image_url: 'http://api/media/front-tok',
        view_images: {
          front: 'http://api/media/front-tok',
          back: 'http://api/media/back-tok',
          left: 'http://api/media/left-tok',
          right: 'http://api/media/right-tok',
        },
      },
      collected: { flow_mode: 'blank', hat_colour: { hex: '#c00202', name: '#c00202' } },
      status: 'draft',
      messages: [],
      data: { tint_ready: true, tint_hex: '#c00202' },
    } as never)
    vi.mocked(fetchProduct).mockClear()

    Object.defineProperty(window, 'location', {
      value: { search: '?session=blank-tok-resume' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()

    const s = useSessionStore.getState()
    expect(s.productRef?.view_images.front).toBe('http://api/media/front-tok')
    expect(s.productRef?.view_images.back).toBe('http://api/media/back-tok')
    expect(s.productRef?.reference_image_url).toBe('http://api/media/front-tok')
    // Must NOT call /products with a hat_type id (that 404s and wiped the viewer).
    expect(vi.mocked(fetchProduct)).not.toHaveBeenCalled()
    // The tint signal is restored so the colour overlay re-composites on resume.
    expect(useChatStore.getState().tintReady).toBe(true)
    expect(useChatStore.getState().tintHex).toBe('#c00202')

    Object.defineProperty(window, 'location', { value: { search: '' }, writable: true })
  })

  it('warns via console.warn when bootstrap fails so broken embed URLs are diagnosable', async () => {
    const { fetchProduct } = await import('../lib/api')
    vi.mocked(fetchProduct).mockRejectedValueOnce(new Error('Backend down'))

    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    Object.defineProperty(window, 'location', {
      value: { search: '?product_id=prod-missing' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()

    expect(warnSpy).toHaveBeenCalledOnce()
    expect(warnSpy.mock.calls[0][0]).toContain('[MadHats] bootstrapFromUrl failed')
    expect(useSessionStore.getState().view).toBe('picker')

    warnSpy.mockRestore()
    Object.defineProperty(window, 'location', {
      value: { search: '' },
      writable: true,
    })
  })

  it('bootstrapFromUrl with ?product_id starts a canvas session', async () => {
    const api = await import('../lib/api')
    vi.spyOn(api, 'fetchProduct').mockResolvedValue({
      id: 'p1', style: 's', colour: 'navy', name: 'Cap', reference_image_url: 'http://x/f.png',
      view_images: { front: 'http://x/f.png' }, placement_zones: [], decoration_types: [],
    } as never)
    vi.spyOn(api, 'createCanvasSession').mockResolvedValue({ session_id: 's1', share_token: 't', state: 'canvas_design' } as never)
    // NOTE: this file's other tests shadow window.location with a plain object via
    // Object.defineProperty, which breaks history.pushState's link to window.location —
    // follow the same convention here rather than pushState (matches brief intent: the
    // store reads window.location.search).
    Object.defineProperty(window, 'location', {
      value: { search: '?product_id=p1' },
      writable: true,
    })
    const { useSessionStore } = await import('../store/sessionStore')
    await useSessionStore.getState().bootstrapFromUrl()
    expect(useSessionStore.getState().view).toBe('canvas')
    Object.defineProperty(window, 'location', {
      value: { search: '' },
      writable: true,
    })
  })
})
