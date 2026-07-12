import { create } from 'zustand'
import { generatePreview, generationStatus, regenerate } from '../lib/api'
import type { GenerationStatus } from '../lib/types'

type GenStatus = 'idle' | 'generating' | 'done' | 'error'

const VIEW_ORDER = ['front', 'back', 'left', 'right'] as const

/**
 * A completed design may have rendered several angles (front hero + decorated
 * back/side views). Return every rendered view URL in canonical order; fall back
 * to the single hero URL for a single-view design.
 */
function completedUrls(res: GenerationStatus): string[] {
  const views = res.view_images ?? {}
  const ordered = VIEW_ORDER.map(v => views[v]).filter((u): u is string => Boolean(u))
  if (ordered.length) return ordered
  const hero = res.watermarked_url ?? res.image_url ?? null
  return hero ? [hero] : []
}

interface GenerationStoreState {
  /**
   * Internal/diagnostic only. `error` covers backend `failed`, poll timeout, and
   * hard network failures alike. Generation is decoupled + gated-by-email on the
   * backend (auto-retried, then ops-alerted on permanent failure — the design is
   * still emailed once it exists and the address is verified), so the UI must
   * NEVER surface this as a customer-facing failure. `GenerationPanel` renders
   * the same reassurance for `done` and `error`.
   */
  status: GenStatus
  jobId: string | null
  /** Watermarked preview URL (customer-facing), or the clean URL as fallback. */
  previewUrl: string | null
  /** Completed design URLs (watermarked), in completion order. Only shown on-screen once released (email verified + complete). */
  designs: string[]
  /** Diagnostic only (e.g. Sentry/telemetry) — never rendered to the customer. */
  error: string | null
  /** Guards so generation is kicked off at most once per session. */
  startedForSession: string | null

  startGeneration: (sessionId: string) => Promise<void>
  /** Fire a fresh regeneration after a requested change. Not once-guarded — each edit reruns. */
  startRegeneration: (sessionId: string) => Promise<void>
  /** Seed the already-generated design when resuming a session (no new render). */
  hydrateDesigns: (urls: string[]) => void
  reset: () => void
}

const POLL_INTERVAL_MS = 1200
const MAX_POLLS = 25

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export const useGenerationStore = create<GenerationStoreState>((set, get) => ({
  status: 'idle',
  jobId: null,
  previewUrl: null,
  designs: [],
  error: null,
  startedForSession: null,

  startGeneration: async (sessionId: string) => {
    // Once-guard: never re-trigger for a session already in flight or done.
    if (get().startedForSession === sessionId) return
    set({ startedForSession: sessionId, status: 'generating', error: null, previewUrl: null })

    try {
      const { job_id } = await generatePreview(sessionId)
      set({ jobId: job_id })

      for (let i = 0; i < MAX_POLLS; i++) {
        const res = await generationStatus(job_id)
        if (res.status === 'complete') {
          const urls = completedUrls(res)
          set(state => ({
            status: 'done',
            previewUrl: urls[0] ?? null,
            designs: urls.length ? [...state.designs, ...urls] : state.designs,
          }))
          return
        }
        if (res.status === 'failed') {
          set({ status: 'error', error: 'Generation failed. Please try again.' })
          return
        }
        await delay(POLL_INTERVAL_MS)
      }
      set({ status: 'error', error: 'Generation timed out. Please try again.' })
    } catch (err) {
      set({
        status: 'error',
        error: err instanceof Error ? err.message : 'Generation failed',
        // Allow a retry after a hard failure.
        startedForSession: null,
      })
    }
  },

  startRegeneration: async (sessionId: string) => {
    set({ status: 'generating', error: null })
    try {
      const { job_id } = await regenerate(sessionId)
      set({ jobId: job_id })
      for (let i = 0; i < MAX_POLLS; i++) {
        const res = await generationStatus(job_id)
        if (res.status === 'complete') {
          const urls = completedUrls(res)
          set(state => ({
            status: 'done',
            previewUrl: urls[0] ?? null,
            designs: urls.length ? [...state.designs, ...urls] : state.designs,
          }))
          return
        }
        if (res.status === 'failed') { set({ status: 'error' }); return }
        await delay(POLL_INTERVAL_MS)
      }
      set({ status: 'error' })
    } catch (err) {
      set({ status: 'error', error: err instanceof Error ? err.message : 'Regeneration failed' })
    }
  },

  hydrateDesigns: (urls: string[]) => {
    if (!urls.length) return
    // Mark the session as already-generated so startGeneration's once-guard
    // doesn't kick off a duplicate render for a design we just rehydrated.
    set({ status: 'done', designs: urls, previewUrl: urls[0] })
  },

  reset: () =>
    set({
      status: 'idle',
      jobId: null,
      previewUrl: null,
      designs: [],
      error: null,
      startedForSession: null,
    }),
}))
