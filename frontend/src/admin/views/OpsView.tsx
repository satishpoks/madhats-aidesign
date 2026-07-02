import { useState } from 'react'
import { promptPreview, backfillDeliveries, type PromptPreview } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

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
