import type { Product, ProductPage, CreateSessionResponse, ChatResponse } from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'
const STORE_KEY = (import.meta.env.VITE_STORE_KEY as string | undefined) ?? ''

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers as HeadersInit | undefined)
  headers.set('X-Store-Key', STORE_KEY)

  // For FormData bodies the browser must set Content-Type itself so it can
  // include the multipart boundary. Do NOT set it here.
  // For JSON string bodies, set the header explicitly.
  if (init.body instanceof FormData) {
    headers.delete('Content-Type')
  } else if (init.body !== undefined && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })

  if (!res.ok) {
    let detail = res.statusText
    try {
      const json = (await res.json()) as { detail?: string; message?: string }
      detail = json.detail ?? json.message ?? detail
    } catch {
      // ignore JSON parse failure — keep statusText as detail
    }
    throw new ApiError(res.status, detail)
  }

  return res.json() as Promise<T>
}

export function fetchProducts(limit = 24, offset = 0): Promise<ProductPage> {
  return request<ProductPage>(`/products?limit=${limit}&offset=${offset}`)
}

export function fetchProduct(id: string): Promise<Product> {
  return request<Product>(`/products/${id}`)
}

export function createSession(
  productId: string,
  opts?: { channel?: string; entry_path?: string },
): Promise<CreateSessionResponse> {
  return request<CreateSessionResponse>('/sessions', {
    method: 'POST',
    body: JSON.stringify({ product_id: productId, ...opts }),
  })
}

export function sendChat(sessionId: string, message: string): Promise<ChatResponse> {
  return request<ChatResponse>(`/chat/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify({ message }),
  })
}

export function getSession(token: string): Promise<CreateSessionResponse> {
  return request<CreateSessionResponse>(`/sessions/${token}`)
}

/**
 * Upload a logo image for the given session.
 * Uses multipart/form-data — the browser sets Content-Type and boundary automatically.
 */
export function uploadLogo(
  sessionId: string,
  file: File,
): Promise<{ asset_url: string; asset_hash: string }> {
  const formData = new FormData()
  formData.append('file', file)
  return request<{ asset_url: string; asset_hash: string }>(`/uploads/logo/${sessionId}`, {
    method: 'POST',
    body: formData,
  })
}

/**
 * Save a placement pin annotation for the given session.
 */
export function addPin(
  sessionId: string,
  pin: { view: string; x_pct: number; y_pct: number; comment: string },
): Promise<{ pin_id: string }> {
  return request<{ pin_id: string }>(`/uploads/pin/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify(pin),
  })
}
