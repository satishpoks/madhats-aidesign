import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSubmissions, type Submission } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'

const STATUSES = ['all', 'pending', 'approved', 'rejected'] as const

function productName(s: Submission): string {
  const ref = s.product_ref as { name?: string; product_id?: string } | null
  return ref?.name ?? ref?.product_id ?? '—'
}

function customerName(s: Submission): string {
  const c = s.customer as { name?: string } | null
  return c?.name ?? '—'
}

export function SubmissionsView() {
  const [rows, setRows] = useState<Submission[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<(typeof STATUSES)[number]>('all')
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    setLoading(true)
    listSubmissions()
      .then((data) => { if (active) { setRows(data); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load submissions') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const filtered = useMemo(
    () => (filter === 'all' ? rows : rows.filter((r) => r.review_status === filter)),
    [rows, filter],
  )

  const columns: Column<Submission>[] = [
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.review_status} /> },
    { key: 'product', header: 'Product', render: productName },
    { key: 'customer', header: 'Customer', render: customerName },
    { key: 'created', header: 'Created', render: (r) => new Date(r.created_at).toLocaleString() },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Approval queue</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as (typeof STATUSES)[number])}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
          aria-label="Filter by status"
        >
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {error && <ErrorBanner message={error} />}
      <DataTable<Submission>
        columns={columns}
        rows={filtered}
        loading={loading}
        empty="No submissions"
        onRowClick={(r) => navigate(`/admin/submissions/${r.id}`)}
      />
    </div>
  )
}
