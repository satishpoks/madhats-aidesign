import { create } from 'zustand'
import { generatePreview, generationStatus, regenerate } from '../lib/api'

type GenStatus = 'idle' | 'generating' | 'done' | 'error'

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
          const url = res.watermarked_url ?? res.image_url ?? null
          set(state => ({
            status: 'done',
            previewUrl: url,
            designs: url ? [...state.designs, url] : state.designs,
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
          const url = res.watermarked_url ?? res.image_url ?? null
          set(state => ({
            status: 'done',
            previewUrl: url,
            designs: url ? [...state.designs, url] : state.designs,
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
