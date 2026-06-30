import { describe, it, expect, vi, beforeEach } from 'vitest'
import type { Product } from '../lib/types'

// Mock the api module before importing the store
vi.mock('../lib/api', () => ({
  createSession: vi.fn().mockResolvedValue({
    session_id: 'sess-test-123',
    share_token: 'tok-test-abc',
    state: 'collecting_brief',
  }),
  fetchProduct: vi.fn().mockResolvedValue({
    id: 'prod-1',
    name: 'Classic Snapback',
    colour: 'Black',
    style: 'snapback',
    reference_image_url: 'https://example.com/cap.jpg',
    view_images: {},
    placement_zones: ['front'],
    decoration_types: ['embroidery'],
  } satisfies Product),
}))

import { useSessionStore } from '../store/sessionStore'

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

describe('bootstrapFromUrl', () => {
  it('does nothing when product_id is absent from URL', async () => {
    // jsdom URL defaults to about:blank — no query params
    await useSessionStore.getState().bootstrapFromUrl()
    expect(useSessionStore.getState().view).toBe('picker')
    expect(useSessionStore.getState().sessionId).toBeNull()
  })

  it('starts a session when product_id is present in URL', async () => {
    Object.defineProperty(window, 'location', {
      value: { search: '?product_id=prod-1&source=shopify' },
      writable: true,
    })
    await useSessionStore.getState().bootstrapFromUrl()
    expect(useSessionStore.getState().view).toBe('session')
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
})
