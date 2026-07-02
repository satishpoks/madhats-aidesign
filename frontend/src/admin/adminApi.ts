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

/** Authenticated request: attaches the stored X-Admin-Secret; logs out on 401/403. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const secret = getSecret()
  if (secret === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const headers = new Headers(init.headers as HeadersInit | undefined)
  headers.set('X-Admin-Secret', secret)
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

export interface SessionListItem {
  id: string
  store_id: string | null
  share_token: string | null
  state: string | null
  status: string | null
  channel: string | null
  entry_path: string | null
  product: string | null
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
