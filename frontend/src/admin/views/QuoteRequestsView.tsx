import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  listQuoteComponents,
  listQuoteRequests,
  renderQuoteRequest,
  type QuoteComponent,
  type QuoteRequest,
} from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { StorePicker } from '../StorePicker'

export function QuoteRequestsView() {
  const [rows, setRows] = useState<QuoteRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // The backend list endpoint has no store_id param yet (it already
  // auto-restricts results to the admin's assigned stores), so this picker is
  // a scoping affordance only for now.
  const [storeId, setStoreId] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    setLoading(true)
    listQuoteRequests()
      .then((data) => { if (active) { setRows(data); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load quote requests') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const columns: Column<QuoteRequest>[] = [
    { key: 'reference', header: 'Reference', render: (r) => r.reference_code ?? '—' },
    { key: 'name', header: 'Name', render: (r) => r.name ?? '—' },
    { key: 'email', header: 'Email', render: (r) => r.email ?? '—' },
    { key: 'phone', header: 'Phone', render: (r) => (r.phone ? `${r.phone}${r.notify_by_phone ? ' 📞' : ''}` : '—') },
    { key: 'product', header: 'Product', render: (r) => r.product ?? '—' },
    { key: 'decoration', header: 'Decoration', render: (r) => r.decoration_type ?? '—' },
    { key: 'qty', header: 'Qty', render: (r) => (r.quantity ?? '—') },
    { key: 'needed_by', header: 'Needed by', render: (r) => r.needed_by ?? '—' },
    { key: 'purpose', header: 'Purpose', render: (r) => r.purpose ?? '—' },
    { key: 'note', header: 'Note', render: (r) => r.quote_note ?? r.notes ?? '—' },
    { key: 'confirmed', header: 'Confirmed', render: (r) => (r.quote_confirmed_at ? new Date(r.quote_confirmed_at).toLocaleString() : '—') },
    {
      key: 'render',
      header: '',
      render: (r) => <RenderCell leadId={r.lead_id} storeKey={r.store_key ?? null} />,
    },
    {
      key: 'view',
      header: '',
      render: (r) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); navigate(`/admin/leads/${r.session_id}`) }}
          className="rounded-lg bg-[#ff5c00] px-3 py-1 text-xs text-white hover:bg-[#e64f00]"
        >
          View 360°
        </button>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Quote requests</h1>
        <StorePicker value={storeId} onChange={setStoreId} allowAll />
      </div>
      {error && <ErrorBanner message={error} />}
      <DataTable<QuoteRequest>
        columns={columns}
        rows={rows}
        loading={loading}
        empty="No quote requests"
        onRowClick={(r) => navigate(`/admin/leads/${r.session_id}`)}
      />
    </div>
  )
}

/**
 * Per-row actions: list the uploaded components (download links through the
 * /media proxy) and trigger the on-demand photoreal render. The render endpoint
 * is store-scoped, so it needs the row's publishable store key.
 */
function RenderCell({ leadId, storeKey }: { leadId: string; storeKey: string | null }) {
  const [components, setComponents] = useState<QuoteComponent[] | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [cellError, setCellError] = useState<string | null>(null)

  async function loadComponents() {
    setBusy(true)
    setCellError(null)
    try {
      const res = await listQuoteComponents(leadId)
      setComponents(res.components)
    } catch (e: unknown) {
      setCellError(e instanceof Error ? e.message : 'Failed to load components')
    } finally {
      setBusy(false)
    }
  }

  async function triggerRender() {
    if (!storeKey) {
      setCellError('No store key for this request')
      return
    }
    setBusy(true)
    setCellError(null)
    try {
      const res = await renderQuoteRequest(leadId, storeKey)
      setJobId(res.job_id)
    } catch (e: unknown) {
      setCellError(e instanceof Error ? e.message : 'Render failed to start')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex flex-col gap-1" onClick={(e) => e.stopPropagation()}>
      <button
        type="button"
        onClick={loadComponents}
        disabled={busy}
        className="rounded-lg bg-slate-200 px-3 py-1 text-xs hover:bg-slate-300"
      >
        Components
      </button>
      <button
        type="button"
        onClick={triggerRender}
        disabled={busy || !storeKey}
        className="rounded-lg bg-[#ff5c00] px-3 py-1 text-xs text-white hover:bg-[#e64f00] disabled:opacity-50"
      >
        Generate render
      </button>
      {cellError && <span className="text-[10px] text-red-600">{cellError}</span>}
      {jobId && <span className="text-[10px] text-slate-500">render queued: {jobId}</span>}
      {components && (
        <div className="mt-1 space-y-1">
          {components.length === 0 && <span className="text-[10px] text-slate-500">no components</span>}
          {components.map((c) => (
            c.url ? (
              <a
                key={c.label}
                href={c.url}
                download
                className="block text-[10px] text-blue-600 underline"
              >
                {c.label}
              </a>
            ) : (
              <span key={c.label} className="block text-[10px] text-slate-400">{c.label}</span>
            )
          ))}
          {components.some((c) => c.url) && (
            <button
              type="button"
              onClick={() => components.forEach((c) => c.url && window.open(c.url, '_blank'))}
              className="text-[10px] text-blue-700 underline"
            >
              Download all
            </button>
          )}
        </div>
      )}
    </div>
  )
}
