import { useCallback, useEffect, useRef, useState } from 'react'
import {
  promptPreview, backfillDeliveries, listGenerations, reapStuck,
  type PromptPreview, type GenerationJobs,
} from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { KpiTile } from '../components/KpiTile'
import { StatusBadge } from '../components/StatusBadge'

function humanAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const m = Math.floor(seconds / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  return h < 24 ? `${h}h ${m % 60}m` : `${Math.floor(h / 24)}d ${h % 24}h`
}

const STATUS_FILTERS = ['all', 'pending', 'failed', 'complete'] as const
type StatusFilter = (typeof STATUS_FILTERS)[number]

// ---------------------------------------------------------------------------
// Generation jobs — live triage table + bulk "Reap stuck now".
// ---------------------------------------------------------------------------

function GenerationJobsSection() {
  const [jobs, setJobs] = useState<GenerationJobs | null>(null)
  const [filter, setFilter] = useState<StatusFilter>('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [reapBusy, setReapBusy] = useState(false)
  const [reapResult, setReapResult] = useState<string | null>(null)
  // Keep the latest filter for the interval callback without re-arming the timer.
  const filterRef = useRef<StatusFilter>(filter)
  filterRef.current = filter

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const f = filterRef.current
      setJobs(await listGenerations(f === 'all' ? undefined : f))
      setErr(null)
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Failed to load generation jobs')
    } finally {
      setLoading(false)
    }
  }, [])

  // Reload whenever the filter changes (and on mount).
  useEffect(() => {
    void load()
  }, [filter, load])

  // Auto-refresh poll (~10s) while enabled.
  useEffect(() => {
    if (!autoRefresh) return
    const id = setInterval(() => void load(), 10_000)
    return () => clearInterval(id)
  }, [autoRefresh, load])

  async function onReap() {
    if (!window.confirm('Reap all stalled jobs and re-enqueue fresh renders? This starts real generations.')) return
    setReapBusy(true)
    setReapResult(null)
    try {
      const r = await reapStuck()
      setReapResult(`Reaped ${r.reaped} · retried ${r.retried} · gave up ${r.gave_up}`)
      await load()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : 'Reap failed')
    } finally {
      setReapBusy(false)
    }
  }

  const s = jobs?.summary
  const stuckMin = jobs?.stuck_minutes ?? 8

  return (
    <section className="space-y-4 rounded-lg border border-gray-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-medium">Generation jobs</h2>
        <div className="flex items-center gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
            Auto-refresh
          </label>
          <button onClick={() => void load()} disabled={loading} className="rounded border border-gray-300 px-3 py-1.5 hover:bg-gray-50 disabled:opacity-50">
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
          <button onClick={() => void onReap()} disabled={reapBusy} className="rounded-lg bg-[#ff5c00] text-white px-4 py-1.5 hover:bg-[#e64f00] disabled:opacity-50">
            {reapBusy ? 'Reaping…' : 'Reap stuck now'}
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-500">A job is “stalled” when it’s still pending past {stuckMin} min. Reaping marks stalled jobs failed and re-enqueues fresh renders (bounded per session).</p>

      {s && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiTile label="Pending" value={s.pending} tone="neutral" />
          <KpiTile label="Stalled" value={s.stalled} tone={s.stalled > 0 ? 'red' : 'neutral'} />
          <KpiTile label="Failed" value={s.failed} tone={s.failed > 0 ? 'amber' : 'neutral'} />
          <KpiTile label="Complete" value={s.complete} tone="green" />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>
          Status
          <select value={filter} onChange={(e) => setFilter(e.target.value as StatusFilter)} className="ml-2 rounded border border-gray-300 px-2 py-1">
            {STATUS_FILTERS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </label>
        {reapResult && <span className="text-gray-600">{reapResult}</span>}
      </div>

      {err && <ErrorBanner message={err} />}

      {jobs && jobs.items.length === 0 && (
        <p className="text-sm text-gray-500">No generation jobs in this window.</p>
      )}

      {jobs && jobs.items.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Age</th>
                <th className="py-2 pr-3">Tier</th>
                <th className="py-2 pr-3">Model</th>
                <th className="py-2 pr-3">Session</th>
                <th className="py-2 pr-3">Attempts</th>
                <th className="py-2">Error</th>
              </tr>
            </thead>
            <tbody>
              {jobs.items.map((j) => (
                <tr key={j.job_id} className={`border-b border-gray-100 ${j.stalled ? 'bg-[#fff2cc]' : ''}`}>
                  <td className="py-2 pr-3">
                    <StatusBadge status={j.status} />
                    {j.stalled && <span className="ml-1 text-[11px] font-semibold text-[#bf0d0d]">stalled</span>}
                  </td>
                  <td className="py-2 pr-3 whitespace-nowrap">{humanAge(j.age_seconds)}</td>
                  <td className="py-2 pr-3">{j.tier}</td>
                  <td className="py-2 pr-3 whitespace-nowrap">{j.model}</td>
                  <td className="py-2 pr-3 font-mono text-xs" title={j.session_id}>{j.session_id.slice(0, 8)}…</td>
                  <td className="py-2 pr-3">{j.attempts}</td>
                  <td className="py-2 text-xs text-gray-600 max-w-xs truncate" title={j.error ?? ''}>{j.error ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export function OpsView() {
  // Prompt preview state
  const [sessionId, setSessionId] = useState('')
  const [tier, setTier] = useState<'preview' | 'final'>('preview')
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)

  // Backfill state
  const [limit, setLimit] = useState(100)
  const [maxAge, setMaxAge] = useState(72)
  const [backfillResult, setBackfillResult] = useState<string | null>(null)
  const [backfillErr, setBackfillErr] = useState<string | null>(null)
  const [backfillBusy, setBackfillBusy] = useState(false)

  async function onPreview() {
    if (!sessionId) return
    setPreviewBusy(true)
    setPreviewErr(null)
    try {
      setPreview(await promptPreview(sessionId, tier))
    } catch (e: unknown) {
      setPreview(null)
      setPreviewErr(e instanceof Error ? e.message : 'Prompt preview failed')
    } finally {
      setPreviewBusy(false)
    }
  }

  async function onBackfill() {
    setBackfillBusy(true)
    setBackfillErr(null)
    try {
      const res = await backfillDeliveries(limit, maxAge)
      setBackfillResult(JSON.stringify(res, null, 2))
    } catch (e: unknown) {
      setBackfillResult(null)
      setBackfillErr(e instanceof Error ? e.message : 'Backfill failed')
    } finally {
      setBackfillBusy(false)
    }
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <h1 className="text-xl font-semibold">Ops &amp; diagnostics</h1>

      <GenerationJobsSection />

      <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-medium">Prompt preview</h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Session ID
            <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} className="mt-1 block w-72 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-sm">
            Tier
            <select value={tier} onChange={(e) => setTier(e.target.value as 'preview' | 'final')} className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm">
              <option value="preview">preview</option>
              <option value="final">final</option>
            </select>
          </label>
          <button onClick={onPreview} disabled={previewBusy || !sessionId} className="rounded-lg bg-[#ff5c00] text-white px-4 py-2 text-sm hover:bg-[#e64f00] disabled:opacity-50">
            {previewBusy ? 'Loading…' : 'Preview prompt'}
          </button>
        </div>
        {previewErr && <ErrorBanner message={previewErr} />}
        {preview && (
          <div className="space-y-2 text-sm">
            <div className="text-gray-600">
              {preview.provider} · {preview.model ?? 'unknown model'} · asset: {preview.has_uploaded_asset ? 'yes' : 'no'}
            </div>
            <pre className="whitespace-pre-wrap rounded bg-gray-900 text-gray-100 p-3 text-xs">{preview.prompt}</pre>
          </div>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-medium">Delivery backfill</h2>
        <p className="text-sm text-gray-600">Retries verified-but-undelivered previews. This sends real emails.</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Limit
            <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="mt-1 block w-24 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-sm">
            Max age (hours)
            <input type="number" value={maxAge} onChange={(e) => setMaxAge(Number(e.target.value))} className="mt-1 block w-28 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <button onClick={onBackfill} disabled={backfillBusy} className="rounded-lg bg-[#ff5c00] text-white px-4 py-2 text-sm hover:bg-[#e64f00] disabled:opacity-50">
            {backfillBusy ? 'Running…' : 'Run backfill'}
          </button>
        </div>
        {backfillErr && <ErrorBanner message={backfillErr} />}
        {backfillResult && <pre className="whitespace-pre-wrap rounded bg-gray-50 border border-gray-200 p-3 text-xs">{backfillResult}</pre>}
      </section>
    </div>
  )
}
