import type {
  Product,
  ProductPage,
  CreateSessionResponse,
  ChatResponse,
  GenerationStatus,
  SessionDetailResponse,
  VerificationPollResponse,
  Storefront,
} from './types'
import type { CanvasDesign } from '../store/canvasStore'

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

/** Fetch the current store's branding + persona (GET /storefront). */
export function getStorefront(): Promise<Storefront> {
  return request<Storefront>('/storefront')
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

export function sendChat(sessionId: string, message: string, canvasDesign?: CanvasDesign): Promise<ChatResponse> {
  return request<ChatResponse>(`/chat/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify(canvasDesign ? { message, canvas_design: canvasDesign } : { message }),
  })
}

export function getSession(token: string): Promise<SessionDetailResponse> {
  return request<SessionDetailResponse>(`/sessions/${token}`)
}

/**
 * Poll for out-of-band email verification while the chat waits at verify_email.
 * `reply` is null until the customer clicks the emailed link; then it carries
 * Ricardo's confirmation and `state` has advanced.
 */
export function pollVerification(sessionId: string): Promise<VerificationPollResponse> {
  return request<VerificationPollResponse>(`/chat/${sessionId}/verification`)
}

/**
 * One-shot advance of the chat after a regeneration settles. Called exactly
 * once by the frontend right after startRegeneration(sessionId) resolves
 * (success or failure) — not a timed poll — so there's no completion race.
 * `reply` is null if the session wasn't at regenerating; otherwise it carries
 * Ricardo's reply and `state` has advanced to offer_refine.
 */
export function pollRegeneration(sessionId: string): Promise<VerificationPollResponse> {
  return request<VerificationPollResponse>(`/chat/${sessionId}/regeneration`)
}

/**
 * One-shot advance of the chat after preview generation settles. Called exactly
 * once by the frontend right after startGeneration(sessionId) resolves (success
 * or failure). `reply` is null if the session wasn't at generating; otherwise it
 * carries Ricardo's reply and `state` has advanced.
 */
export function pollGenerationAdvance(sessionId: string): Promise<VerificationPollResponse> {
  return request<VerificationPollResponse>(`/chat/${sessionId}/generation-advance`)
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

/** Kick off an async preview generation. Returns the job id to poll. */
export function generatePreview(sessionId: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/generate/preview/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify({ tier: 'preview' }),
  })
}

/** Poll a generation job. image_url/watermarked_url are signed URLs once complete. */
export function generationStatus(jobId: string): Promise<GenerationStatus> {
  return request<GenerationStatus>(`/generate/status/${jobId}`)
}

/** Regenerate the design with the latest requested change. */
export function regenerate(sessionId: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/generate/regenerate/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify({ tier: 'edit' }),
  })
}

/** Create a lead (contact capture) for the session. */
export function createLead(
  sessionId: string,
  lead: { name: string; email: string; phone?: string },
): Promise<{ lead_id: string }> {
  return request<{ lead_id: string }>('/leads', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, ...lead }),
  })
}

/** Trigger the verification email for a lead. */
export function sendVerify(leadId: string): Promise<{ sent: boolean }> {
  return request<{ sent: boolean }>('/leads/verify/send', {
    method: 'POST',
    body: JSON.stringify({ lead_id: leadId }),
  })
}

// ---------------------------------------------------------------------------
// Blank-hat flow: hat type catalogue, blank session creation, compositing
// ---------------------------------------------------------------------------

export interface HatColour {
  name: string
  hex: string
}

export interface HatType {
  id: string
  slug: string
  name: string
  style: string
  view_images: Record<string, string>
  colours: HatColour[]
  placement_zones: string[]
  decoration_types: string[]
}

/** List the active hat-type catalogue (blank cap silhouettes + colourways). */
export function listHatTypes(): Promise<HatType[]> {
  return request<HatType[]>('/hat-types')
}

/** List the active graphics library (clipart / company) for the current store. */
export function listGraphics(category?: 'clipart' | 'company'): Promise<import('./types').Graphic[]> {
  const q = category ? `?category=${category}` : ''
  return request<import('./types').Graphic[]>(`/graphics${q}`)
}

/** List the active decoration types (embroidery/print/…) for the current store. */
export function getDecorationTypes(): Promise<{ id: string; name: string }[]> {
  return request<{ id: string; name: string }[]>('/decoration-types')
}

/** Create a new design session for a blank hat type (no product photo).
 *  Colour is optional — the customer now chooses it in chat (after quantity),
 *  so the landing picker only selects the hat type. */
export function createBlankSession(
  hatTypeId: string,
  colour?: HatColour,
): Promise<{ session_id: string; share_token: string; state: string }> {
  const body: Record<string, unknown> = { hat_type_id: hatTypeId }
  if (colour) body.colour = colour
  return request<{ session_id: string; share_token: string; state: string }>('/sessions/blank', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Composite the collected design elements onto the blank hat views for a session. */
export function postComposite(
  sessionId: string,
): Promise<{ views: Record<string, string>; error?: string }> {
  return request<{ views: Record<string, string>; error?: string }>(`/composite/${sessionId}`, {
    method: 'POST',
  })
}

// ---------------------------------------------------------------------------
// Canvas flow: session creation, layout uploads, finalization
// ---------------------------------------------------------------------------

export function createCanvasSession(
  opts: { productId?: string; hatTypeId?: string; colour?: HatColour },
): Promise<CreateSessionResponse> {
  const body: Record<string, unknown> = {}
  if (opts.productId) body.product_id = opts.productId
  if (opts.hatTypeId) body.hat_type_id = opts.hatTypeId
  if (opts.colour) body.colour = opts.colour
  return request<CreateSessionResponse>('/sessions/canvas', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export function uploadCanvasLayouts(
  sessionId: string, layouts: { face: string; file: File }[],
  kind: 'layout' | 'preview' = 'layout',
): Promise<{ views: Record<string, string> }> {
  const fd = new FormData()
  for (const { face, file } of layouts) {
    fd.append('faces', face)
    fd.append('files', file)
  }
  fd.append('kind', kind)
  return request<{ views: Record<string, string> }>(`/sessions/${sessionId}/canvas-layouts`, {
    method: 'POST', body: fd,
  })
}

export function finalizeCanvas(
  sessionId: string, body: { canvas_design: unknown; email?: string; name?: string },
): Promise<ChatResponse> {
  return request<ChatResponse>(`/sessions/${sessionId}/canvas-finalize`, {
    method: 'POST', body: JSON.stringify(body),
  })
}
