import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSubmissions, type Submission } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { KpiTile } from '../components/KpiTile'
import { ErrorBanner } from '../components/ErrorBanner'

const STATUSES = ['all', 'pending', 'approved', 'rejected'] as const

function productName(s: Submission): string {
  const ref = s.product_ref as { name?: string; product_id?: string } | null
  return ref?.name ?? ref?.product_id ?? '—'
}

function customer(s: Submission): { name: string; email: string } {
  const c = s.customer as { name?: string; email?: string } | null
  return { name: c?.name ?? 'Anonymous', email: c?.email ?? '—' }
}

function isToday(iso: string | null): boolean {
  if (!iso) return false
  const d = new Date(iso)
  const now = new Date()
  return d.toDateString() === now.toDateString()
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

  const kpis = useMemo(() => ({
    pending: rows.filter((r) => r.review_status === 'pending').length,
    approvedToday: rows.filter((r) => r.review_status === 'approved' && isToday(r.decided_at)).length,
    total: rows.length,
    rejected: rows.filter((r) => r.review_status === 'rejected').length,
  }), [rows])

  const filtered = useMemo(
    () => (filter === 'all' ? rows : rows.filter((r) => r.review_status === filter)),
    [rows, filter],
  )

  const columns: Column<Submission>[] = [
    {
      key: 'customer',
      header: 'Customer',
      render: (r) => {
        const c = customer(r)
        return (
          <div className="flex items-center gap-3">
            <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-[#fff2ea] text-[13px] font-semibold text-[#bf2e00]">
              {(c.name[0] ?? '?').toUpperCase()}
            </span>
            <div className="leading-tight">
              <div className="text-[13px] font-semibold text-[#1a1a2e]">{c.name}</div>
              <div className="text-[10px] text-[#6b6b80]">{c.email}</div>
            </div>
          </div>
        )
      },
    },
    { key: 'product', header: 'Product', render: productName },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.review_status} /> },
    { key: 'created', header: 'Submitted', render: (r) => new Date(r.created_at).toLocaleString() },
  ]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[20px] font-semibold text-[#1a1a2e]">Approval queue</h1>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <KpiTile label="Pending" value={kpis.pending} tone="amber" />
        <KpiTile label="Approved Today" value={kpis.approvedToday} tone="green" />
        <KpiTile label="Total Submissions" value={kpis.total} tone="indigo" />
        <KpiTile label="Rejected" value={kpis.rejected} tone="red" />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[13px] text-[#6b6b80]">{filtered.length} shown</span>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as (typeof STATUSES)[number])}
          className="rounded-lg border border-[#e0e1ea] px-2 py-1 text-sm text-[#1a1a2e]"
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
