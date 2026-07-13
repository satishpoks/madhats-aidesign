// Backend DTO mirrors — keep in sync with FastAPI schemas

export interface Product {
  id: string
  style: string
  colour: string
  name: string
  description?: string
  store_url?: string
  reference_image_url: string
  view_images: Record<string, string>
  placement_zones: string[]
  decoration_types: string[]
}

export interface ProductPage {
  items: Product[]
  total: number
  limit: number
  offset: number
}

export interface CreateSessionResponse {
  session_id: string
  share_token: string
  state: string
}

export interface ChatResponse {
  reply: string
  state: string
  data: Record<string, unknown>
}

/** One persisted chat turn, as returned by GET /sessions/{token}. */
export interface ChatMessageOut {
  role: 'user' | 'assistant'
  content: string
  state_before: string
  state_after: string
  created_at: string
}

/** Full session detail (GET /sessions/{token}) — used to resume a session. */
export interface SessionDetailResponse {
  session_id: string
  share_token: string
  state: string
  channel: string
  entry_path: string
  product_ref: {
    product_id?: string
    name?: string
    style?: string
    colour?: string
    reference_image_url?: string
    /** Per-angle images (blank-hat sessions carry all four here, proxied). */
    view_images?: Record<string, string>
  } | null
  collected: Record<string, unknown>
  status: string
  messages: ChatMessageOut[]
  data: Record<string, unknown>
  /** Signed design URLs (front→back→…) for a resumed, already-generated session.
   *  Empty until the email is verified. */
  designs?: string[]
}

/** Verification poll (GET /chat/{id}/verification). reply is null until verified. */
export interface VerificationPollResponse {
  reply: string | null
  state: string
  data: Record<string, unknown>
}

export interface GenerationStatus {
  status: string
  image_url: string
  watermarked_url: string
  /**
   * Per-view signed (watermarked) URLs { view: url } for a multi-view design —
   * the front hero plus any decorated back/side view, in front→back→left→right
   * order. Empty for a single-view design.
   */
  view_images?: Record<string, string>
}

export interface CanvasLayoutsResponse {
  views: Record<string, string>
}
