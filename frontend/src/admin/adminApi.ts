import { getSecret, logout } from './adminStore'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

export interface Store {
  id: string
  slug: string
  name: string
  public_key: string
  shopify_domain: string | null
  status: string
  created_at?: string
}

export interface CreateStoreBody {
  slug: string
  name: string
  shopify_domain?: string
  allowed_origins?: string[]
  persona_name?: string
  greeting_template?: string
  sales_notification_email?: string
  brand?: Record<string, unknown>
}

export interface SyncResult {
  fetched: number
  imported: number
  skipped: number
}

export interface Submission {
  id: string
  session_id: string
  product_ref: Record<string, unknown> | null
  final_image_urls: string[]
  source_ref: Record<string, unknown> | null
  customer: Record<string, unknown> | null
  review_status: string
  reviewer_notes: string | null
  created_at: string
  decided_at: string | null
}

export interface UpdateSubmissionBody {
  review_status: string
  reviewer_notes?: string
}

export interface QuoteRequest {
  lead_id: string
  session_id: string
  name: string | null
  email: string | null
  phone: string | null
  notify_by_phone: boolean
  quote_note: string | null
  quote_confirmed_at: string | null
  product: string | null
  decoration_type: string | null
  placement_zone: string | null
  quantity: number | null
  share_token: string | null
}

export interface PromptPreview {
  session_id: string
  tier: string
  provider: string
  model: string | null
  reference_image_url: string
  has_uploaded_asset: boolean
  prompt: string
}

export type BackfillResult = Record<string, unknown>

/**
 * Authenticated request: attaches the stored X-Admin-Secret; logs out on 401/403.
 * `storeKey`, when passed, is sent as X-Store-Key — used only by the hat-type
 * admin functions below, which are store-scoped on the backend (require_store).
 * Do not thread this through by default; other admin routes must be unaffected.
 */
async function request<T>(path: string, init: RequestInit = {}, storeKey?: string): Promise<T> {
  const secret = getSecret()
  if (secret === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const headers = new Headers(init.headers as HeadersInit | undefined)
  headers.set('X-Admin-Secret', secret)
  if (storeKey) {
    headers.set('X-Store-Key', storeKey)
  }
  if (init.body !== undefined && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      logout()
    }
    let detail = res.statusText
    try {
      const json = (await res.json()) as { detail?: string; message?: string }
      detail = json.detail ?? json.message ?? detail
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

/** Validate an arbitrary secret WITHOUT mutating the store (used by login). */
export async function validateSecret(secret: string): Promise<boolean> {
  const headers = new Headers()
  headers.set('X-Admin-Secret', secret)
  const res = await fetch(`${BASE_URL}/admin/stores`, { headers })
  return res.ok
}

export function listStores(): Promise<Store[]> {
  return request<Store[]>('/admin/stores')
}

export function createStore(body: CreateStoreBody): Promise<Store> {
  return request<Store>('/admin/stores', { method: 'POST', body: JSON.stringify(body) })
}

export function syncStore(id: string): Promise<SyncResult> {
  return request<SyncResult>(`/admin/stores/${id}/sync`, { method: 'POST' })
}

export function listSubmissions(): Promise<Submission[]> {
  return request<Submission[]>('/admin/submissions')
}

export function updateSubmission(id: string, body: UpdateSubmissionBody): Promise<{ updated: boolean }> {
  return request<{ updated: boolean }>(`/admin/submissions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function listQuoteRequests(): Promise<QuoteRequest[]> {
  return request<QuoteRequest[]>('/admin/quote-requests')
}

export function promptPreview(sessionId: string, tier: 'preview' | 'final'): Promise<PromptPreview> {
  return request<PromptPreview>(`/admin/prompt-preview/${sessionId}?tier=${tier}`)
}

export function backfillDeliveries(limit: number, maxAgeHours: number): Promise<BackfillResult> {
  return request<BackfillResult>(
    `/admin/deliveries/backfill?limit=${limit}&max_age_hours=${maxAgeHours}`,
    { method: 'POST' },
  )
}

// ---------------------------------------------------------------------------
// Diagnostics: session transcripts, generation audit logs, system health
// ---------------------------------------------------------------------------

export interface LeadCustomer {
  name: string | null
  email: string | null
  phone: string | null
  email_verified: boolean
}

export interface SessionListItem {
  id: string
  store_id: string | null
  share_token: string | null
  state: string | null
  status: string | null
  channel: string | null
  entry_path: string | null
  product: string | null
  reference_image_url: string | null
  customer: LeadCustomer | null
  decoration_type: string | null
  placement_zone: string | null
  quantity: number | null
  generated_image_url: string | null
  generation_count: number
  created_at: string | null
}

export interface Paginated<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface ChatMessage {
  role: string
  content: string
  state_before: string
  state_after: string
  created_at: string
}

export interface SessionGeneration {
  id: string
  tier: string
  model: string
  status: string
  image_url: string | null
  watermarked_url: string | null
  cost_usd: number | null
  latency_ms: number | null
  created_at: string
}

export interface SessionLead {
  id: string
  name: string | null
  email: string | null
  phone: string | null
  email_verified: boolean
  verified_at: string | null
  created_at: string
}

export interface SessionDetail {
  id: string
  store_id: string | null
  share_token: string | null
  state: string | null
  status: string | null
  channel: string | null
  entry_path: string | null
  product: string | null
  product_ref: Record<string, unknown> | null
  reference_image_url: string | null
  view_images: Record<string, string>
  collected: Record<string, unknown>
  created_at: string | null
  messages: ChatMessage[]
  generations: SessionGeneration[]
  leads: SessionLead[]
}

export interface GenerationLog {
  id: string
  generation_id: string | null
  job_id: string | null
  session_id: string | null
  attempt: number
  tier: string | null
  status: string
  model: string | null
  full_prompt: string
  params: Record<string, unknown> | null
  reference_image_url: string | null
  uploaded_asset_url: string | null
  output_image_url: string | null
  response_meta: Record<string, unknown> | null
  error: string | null
  latency_ms: number | null
  request_at: string
  response_at: string | null
}

export interface Diagnostics {
  app_env: string
  providers: {
    image_provider_preview: string
    image_provider_final: string
    gemini_preview_model: string
    gemini_final_model: string
    claude_haiku_model: string
    gemini_api_key_set: boolean
    anthropic_api_key_set: boolean
    resend_api_key_set: boolean
    sentry_enabled: boolean
  }
  counts: {
    stores: number
    sessions: number
    generations: number
    generations_failed: number
    leads: number
    leads_verified: number
    submissions_pending: number
  }
}

export function listSessions(
  limit = 50,
  offset = 0,
  opts?: { state?: string; storeId?: string },
): Promise<Paginated<SessionListItem>> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (opts?.state) params.set('state', opts.state)
  if (opts?.storeId) params.set('store_id', opts.storeId)
  return request<Paginated<SessionListItem>>(`/admin/sessions?${params.toString()}`)
}

export function getSessionDetail(id: string): Promise<SessionDetail> {
  return request<SessionDetail>(`/admin/sessions/${id}`)
}

export function listGenerationLogs(
  limit = 100,
  offset = 0,
  opts?: { sessionId?: string; status?: string },
): Promise<Paginated<GenerationLog>> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (opts?.sessionId) params.set('session_id', opts.sessionId)
  if (opts?.status) params.set('status', opts.status)
  return request<Paginated<GenerationLog>>(`/admin/generation-logs?${params.toString()}`)
}

export function getDiagnostics(): Promise<Diagnostics> {
  return request<Diagnostics>('/admin/diagnostics')
}

// ---------------------------------------------------------------------------
// Studio settings: global regen/rate-limit config + FAQ knowledge
// ---------------------------------------------------------------------------

export interface StudioSettings {
  regen_edits_per_session: number
  designs_per_customer_per_day: number
  faq_knowledge: string
}

export function getSettings(): Promise<StudioSettings> {
  return request<StudioSettings>('/admin/settings')
}

export function updateSettings(body: Partial<StudioSettings>): Promise<StudioSettings> {
  return request<StudioSettings>('/admin/settings', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

// ---------------------------------------------------------------------------
// Hat types: blank cap catalogue (per-style angle images, colourways, pricing)
// ---------------------------------------------------------------------------

export interface HatType {
  id: string
  store_id: string | null
  slug: string
  name: string
  style: string
  description: string | null
  blank_view_images: Record<string, string>
  view_images: Record<string, string>
  colours: { name: string; hex: string }[]
  placement_zones: string[]
  decoration_types: string[]
  pricing_slabs: Record<string, unknown>[]
  active: boolean
}

/**
 * Backend hat-type admin routes are store-scoped (require_store): every call
 * needs both X-Admin-Secret (handled by `request`) and X-Store-Key, so every
 * function here takes the selected store's `public_key` as `storeKey`.
 */
export function listHatTypes(storeKey: string): Promise<HatType[]> {
  return request<HatType[]>('/admin/hat-types', {}, storeKey)
}

export function createHatType(
  body: { name: string; slug: string; style?: string; description?: string },
  storeKey: string,
): Promise<HatType> {
  return request<HatType>('/admin/hat-types', { method: 'POST', body: JSON.stringify(body) }, storeKey)
}

export function updateHatType(id: string, body: Partial<HatType>, storeKey: string): Promise<HatType> {
  return request<HatType>(`/admin/hat-types/${id}`, { method: 'PATCH', body: JSON.stringify(body) }, storeKey)
}

export function deleteHatType(id: string, storeKey: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/hat-types/${id}`, { method: 'DELETE' }, storeKey)
}

/**
 * Upload a reference angle image (e.g. "front", "side") for a hat type.
 * Multipart FormData — built and sent directly (not via the JSON `request`
 * helper) so the browser sets the multipart Content-Type + boundary itself.
 */
export async function uploadHatAngle(
  id: string,
  view: string,
  file: File,
  storeKey: string,
): Promise<{ blank_view_images: Record<string, string>; view_images: Record<string, string> }> {
  const secret = getSecret()
  if (secret === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE_URL}/admin/hat-types/${id}/angle/${view}`, {
    method: 'POST',
    headers: { 'X-Admin-Secret': secret, 'X-Store-Key': storeKey },
    body: form,
  })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      logout()
    }
    let detail = res.statusText
    try {
      const json = (await res.json()) as { detail?: string; message?: string }
      detail = json.detail ?? json.message ?? detail
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<{ blank_view_images: Record<string, string>; view_images: Record<string, string> }>
}

// ---------------------------------------------------------------------------
// Decoration types: methods offered to customers after they design
// (embroidery, print, …) — store-scoped
// ---------------------------------------------------------------------------

export interface AdminDecorationType {
  id: string
  name: string
  active: boolean
  sort_order: number
}

export function listDecorationTypes(storeKey: string): Promise<AdminDecorationType[]> {
  return request<AdminDecorationType[]>('/admin/decoration-types', {}, storeKey)
}

export function createDecorationType(name: string, storeKey: string): Promise<AdminDecorationType> {
  return request<AdminDecorationType>('/admin/decoration-types', {
    method: 'POST', body: JSON.stringify({ name }),
  }, storeKey)
}

export function deleteDecorationType(id: string, storeKey: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/decoration-types/${id}`, { method: 'DELETE' }, storeKey)
}

// ---------------------------------------------------------------------------
// Graphics library: admin-managed clipart + company graphics (store-scoped)
// ---------------------------------------------------------------------------

export type GraphicCategory = 'clipart' | 'company'

export interface AdminGraphic {
  id: string
  category: GraphicCategory
  name: string
  active: boolean
  sort_order: number
  url: string
}

export function listGraphics(storeKey: string, category?: GraphicCategory): Promise<AdminGraphic[]> {
  const q = category ? `?category=${category}` : ''
  return request<AdminGraphic[]>(`/admin/graphics${q}`, {}, storeKey)
}

export function deleteGraphic(id: string, storeKey: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/graphics/${id}`, { method: 'DELETE' }, storeKey)
}

/** Upload a graphic (multipart) — like uploadHatAngle, the browser sets the boundary. */
export async function uploadGraphic(
  category: GraphicCategory,
  name: string,
  file: File,
  storeKey: string,
): Promise<AdminGraphic> {
  const secret = getSecret()
  if (secret === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const form = new FormData()
  form.append('category', category)
  form.append('name', name)
  form.append('file', file)
  const res = await fetch(`${BASE_URL}/admin/graphics`, {
    method: 'POST',
    headers: { 'X-Admin-Secret': secret, 'X-Store-Key': storeKey },
    body: form,
  })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      logout()
    }
    let detail = res.statusText
    try {
      const json = (await res.json()) as { detail?: string; message?: string }
      detail = json.detail ?? json.message ?? detail
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<AdminGraphic>
}
