import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fetchProducts, createSession, sendChat, getSession, ApiError } from '../lib/api'

// Stub fetch globally for all tests in this file
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

function ok(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  })
}

beforeEach(() => {
  mockFetch.mockReset()
})

describe('fetchProducts', () => {
  it('calls the correct URL with limit and offset', async () => {
    mockFetch.mockReturnValue(ok({ items: [], total: 0, limit: 24, offset: 0 }))
    await fetchProducts(24, 0)
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/products?limit=24&offset=0')
  })

  it('sends X-Store-Key header on every request', async () => {
    mockFetch.mockReturnValue(ok({ items: [], total: 0, limit: 24, offset: 0 }))
    await fetchProducts()
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Store-Key')).toBeDefined()
  })

  it('returns the ProductPage shape', async () => {
    const page = { items: [{ id: 'p1', name: 'Cap' }], total: 1, limit: 24, offset: 0 }
    mockFetch.mockReturnValue(ok(page))
    const result = await fetchProducts()
    expect(result).toEqual(page)
  })

  it('throws ApiError on 404', async () => {
    mockFetch.mockReturnValue(ok({ detail: 'Not found' }, 404))
    await expect(fetchProducts()).rejects.toBeInstanceOf(ApiError)
  })

  it('ApiError carries the status code', async () => {
    mockFetch.mockReturnValue(ok({ detail: 'Server error' }, 500))
    const err = await fetchProducts().catch((e: ApiError) => e)
    expect((err as ApiError).status).toBe(500)
  })
})

describe('createSession', () => {
  it('POSTs to /sessions', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'collecting_brief' }))
    await createSession('prod-1')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/sessions')
  })

  it('sends product_id in JSON body', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'collecting_brief' }))
    await createSession('prod-42')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string) as { product_id: string }
    expect(body.product_id).toBe('prod-42')
  })

  it('sends Content-Type: application/json header for POST', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'collecting_brief' }))
    await createSession('prod-1')
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('Content-Type')).toBe('application/json')
  })
})

describe('sendChat', () => {
  it('POSTs to /chat/{sessionId}', async () => {
    mockFetch.mockReturnValue(ok({ reply: 'Hello', state: 'collecting_brief', data: {} }))
    await sendChat('sess-abc', 'Hi there')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/chat/sess-abc')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
  })

  it('sends message in body', async () => {
    mockFetch.mockReturnValue(ok({ reply: 'OK', state: 'done', data: {} }))
    await sendChat('sess-1', 'A red cap')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string) as { message: string }
    expect(body.message).toBe('A red cap')
  })
})

describe('getSession', () => {
  it('GETs /sessions/{token}', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'done' }))
    await getSession('share-token-xyz')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/sessions/share-token-xyz')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBeUndefined()  // default GET
  })
})
