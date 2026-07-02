import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listQuoteRequests, type QuoteRequest } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'

export function QuoteRequestsView() {
  const [rows, setRows] = useState<QuoteRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
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
    { key: 'name', header: 'Name', render: (r) => r.name ?? '—' },
    { key: 'email', header: 'Email', render: (r) => r.email ?? '—' },
    { key: 'phone', header: 'Phone', render: (r) => (r.phone ? `${r.phone}${r.notify_by_phone ? ' 📞' : ''}` : '—') },
    { key: 'product', header: 'Product', render: (r) => r.product ?? '—' },
    { key: 'decoration', header: 'Decoration', render: (r) => r.decoration_type ?? '—' },
    { key: 'placement', header: 'Placement', render: (r) => r.placement_zone ?? '—' },
    { key: 'qty', header: 'Qty', render: (r) => (r.quantity ?? '—') },
    { key: 'note', header: 'Note', render: (r) => r.quote_note ?? '—' },
    { key: 'confirmed', header: 'Confirmed', render: (r) => (r.quote_confirmed_at ? new Date(r.quote_confirmed_at).toLocaleString() : '—') },
    {
      key: 'view',
      header: '',
      render: (r) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); navigate(`/admin/leads/${r.session_id}`) }}
          className="rounded bg-gray-900 px-3 py-1 text-xs text-white hover:bg-gray-700"
        >
          View 360°
        </button>
      ),
    },
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Quote requests</h1>
      {error && <ErrorBanner message={error} />}
      <DataTable<QuoteRequest>
        columns={columns}
        rows={rows}
        loading={loading}
        empty="No confirmed quote requests"
        onRowClick={(r) => navigate(`/admin/leads/${r.session_id}`)}
      />
    </div>
  )
}
