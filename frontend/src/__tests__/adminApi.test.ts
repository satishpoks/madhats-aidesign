import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  listStores,
  createStore,
  updateSubmission,
  ApiError,
} from '../admin/adminApi'
import { useAdminStore } from '../admin/adminStore'

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
  useAdminStore.getState().loginWith('secret', 'secret-123', { email: null, is_super: true, stores: [] })
})

describe('authenticated requests', () => {
  it('listStores sends stored X-Admin-Secret and no X-Store-Key', async () => {
    mockFetch.mockReturnValue(ok([]))
    await listStores()
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Admin-Secret')).toBe('secret-123')
    expect(init.headers.get('X-Store-Key')).toBeNull()
  })

  it('sends a bearer credential as Authorization header', async () => {
    useAdminStore.getState().loginWith('bearer', 'jwt-123', { email: 'a@x.com', is_super: false, stores: [] })
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
    await listStores()
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('Authorization')).toBe('Bearer jwt-123')
    expect(init.headers.get('X-Admin-Secret')).toBeNull()
  })

  it('createStore POSTs JSON body', async () => {
    mockFetch.mockReturnValue(ok({ id: 's1', slug: 'x', name: 'X', public_key: 'k', shopify_domain: null, status: 'active' }))
    await createStore({ slug: 'x', name: 'X' })
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.headers && (init.headers as Headers).get('Content-Type')).toBe('application/json')
  })

  it('updateSubmission PATCHes to the submission id', async () => {
    mockFetch.mockReturnValue(ok({ updated: true }))
    await updateSubmission('sub-1', { review_status: 'approved', reviewer_notes: 'ok' })
    const url = mockFetch.mock.calls[0][0] as string
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(url).toContain('/admin/submissions/sub-1')
    expect(init.method).toBe('PATCH')
  })

  it('throws ApiError and logs out on 401', async () => {
    mockFetch.mockReturnValue(ok({ detail: 'unauthorized' }, 401))
    await expect(listStores()).rejects.toBeInstanceOf(ApiError)
    expect(useAdminStore.getState().authed).toBe(false)
  })
})
