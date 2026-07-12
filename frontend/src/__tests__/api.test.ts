import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  fetchProducts,
  createSession,
  sendChat,
  getSession,
  uploadLogo,
  addPin,
  listHatTypes,
  createBlankSession,
  postComposite,
  ApiError,
} from '../lib/api'

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

// ---------------------------------------------------------------------------
// uploadLogo
// ---------------------------------------------------------------------------

describe('uploadLogo', () => {
  it('POSTs FormData to /uploads/logo/{sessionId}', async () => {
    mockFetch.mockReturnValue(ok({ asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc123' }))
    const file = new File(['content'], 'logo.png', { type: 'image/png' })
    await uploadLogo('sess-1', file)
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/uploads/logo/sess-1')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.body).toBeInstanceOf(FormData)
  })

  it('does NOT set Content-Type header (lets browser handle multipart boundary)', async () => {
    mockFetch.mockReturnValue(ok({ asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc123' }))
    const file = new File(['content'], 'logo.png', { type: 'image/png' })
    await uploadLogo('sess-1', file)
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    // Must be null — not 'multipart/form-data' and not 'application/json'
    expect(init.headers.get('Content-Type')).toBeNull()
  })

  it('still sends X-Store-Key header with FormData body', async () => {
    mockFetch.mockReturnValue(ok({ asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc123' }))
    const file = new File(['content'], 'logo.png', { type: 'image/png' })
    await uploadLogo('sess-1', file)
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    // X-Store-Key must always be present regardless of body type
    expect(init.headers.get('X-Store-Key')).not.toBeNull()
  })

  it('returns asset_url and asset_hash', async () => {
    const data = { asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc123' }
    mockFetch.mockReturnValue(ok(data))
    const file = new File(['content'], 'logo.png', { type: 'image/png' })
    const result = await uploadLogo('sess-1', file)
    expect(result).toEqual(data)
  })

  it('appends the file under the "file" field name', async () => {
    mockFetch.mockReturnValue(ok({ asset_url: 'https://cdn.example.com/logo.png', asset_hash: 'abc' }))
    const file = new File(['content'], 'logo.png', { type: 'image/png' })
    await uploadLogo('sess-1', file)
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const fd = init.body as FormData
    expect(fd.get('file')).toBe(file)
  })
})

// ---------------------------------------------------------------------------
// addPin
// ---------------------------------------------------------------------------

describe('addPin', () => {
  it('POSTs to /uploads/pin/{sessionId}', async () => {
    mockFetch.mockReturnValue(ok({ pin_id: 'pin-1' }))
    await addPin('sess-1', { view: 'front', x_pct: 50, y_pct: 30, comment: 'Logo here' })
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/uploads/pin/sess-1')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
  })

  it('sends X-Store-Key header', async () => {
    mockFetch.mockReturnValue(ok({ pin_id: 'pin-1' }))
    await addPin('sess-1', { view: 'front', x_pct: 50, y_pct: 30, comment: '' })
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Store-Key')).not.toBeNull()
  })

  it('sends Content-Type: application/json header', async () => {
    mockFetch.mockReturnValue(ok({ pin_id: 'pin-1' }))
    await addPin('sess-1', { view: 'front', x_pct: 50, y_pct: 30, comment: '' })
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('Content-Type')).toBe('application/json')
  })

  it('sends pin data as JSON body', async () => {
    mockFetch.mockReturnValue(ok({ pin_id: 'pin-1' }))
    const pin = { view: 'front', x_pct: 50, y_pct: 30, comment: 'Logo here' }
    await addPin('sess-1', pin)
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string) as typeof pin
    expect(body).toEqual(pin)
  })

  it('returns pin_id', async () => {
    mockFetch.mockReturnValue(ok({ pin_id: 'pin-42' }))
    const result = await addPin('sess-1', { view: 'back', x_pct: 20, y_pct: 80, comment: '' })
    expect(result.pin_id).toBe('pin-42')
  })
})

// ---------------------------------------------------------------------------
// listHatTypes / createBlankSession / postComposite
// ---------------------------------------------------------------------------

describe('listHatTypes', () => {
  it('GETs /hat-types with store key', async () => {
    mockFetch.mockReturnValue(
      ok([{ id: 'h1', slug: '5-panel', name: '5-Panel', style: 'snapback', view_images: {}, colours: [], placement_zones: [], decoration_types: [] }]),
    )
    const out = await listHatTypes()
    expect(out[0].name).toBe('5-Panel')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/hat-types')
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Store-Key')).not.toBeNull()
  })
})

describe('createBlankSession', () => {
  it('POSTs just hat_type_id to /sessions/blank when no colour is given', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'collecting_brief' }))
    await createBlankSession('h1')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/sessions/blank')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    const body = JSON.parse(init.body as string) as { hat_type_id: string; colour?: unknown }
    expect(body).toEqual({ hat_type_id: 'h1' })
    expect('colour' in body).toBe(false)
  })

  it('includes colour when explicitly provided (back-compat)', async () => {
    mockFetch.mockReturnValue(ok({ session_id: 's1', share_token: 'tok', state: 'collecting_brief' }))
    const colour = { name: 'Black', hex: '#000000' }
    await createBlankSession('h1', colour)
    const init = mockFetch.mock.calls[0][1] as RequestInit
    const body = JSON.parse(init.body as string) as { hat_type_id: string; colour: typeof colour }
    expect(body).toEqual({ hat_type_id: 'h1', colour })
  })
})

describe('postComposite', () => {
  it('POSTs /composite/{id}', async () => {
    mockFetch.mockReturnValue(ok({ views: { front: 'u' } }))
    const out = await postComposite('s1')
    expect(out.views.front).toBe('u')
    const url: string = mockFetch.mock.calls[0][0] as string
    expect(url).toContain('/composite/s1')
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
  })
})
