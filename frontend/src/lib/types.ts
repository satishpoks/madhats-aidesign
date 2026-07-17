// Backend DTO mirrors — keep in sync with FastAPI schemas
import type { CanvasDesign } from '../store/canvasStore'

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
  /** Persisted canvas design (placed elements per face + colourway) so a resumed
   *  canvas session can reload the interactive studio. Null for non-canvas. */
  canvas_design?: CanvasDesign | null
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

/** A graphics-library item (clipart / company), served via the /media proxy. */
export interface Graphic {
  id: string
  category: 'clipart' | 'company'
  name: string
  url: string
}

/** A single storefront navigation/menu link. */
export interface MenuItem {
  label: string
  url: string
}

/** Per-store brand config (GET /storefront). All fields optional — unset fields
 *  keep the current MadHats Tailwind fallbacks. */
export interface Brand {
  logo_url?: string
  primary_colour?: string
  header_bg?: string
  header_text?: string
  menu_items?: MenuItem[]
  canvas_intro?: string
}

/** Response shape for GET /storefront — store name, persona name, and brand config. */
export interface Storefront {
  name: string
  persona_name: string
  brand: Brand
}
