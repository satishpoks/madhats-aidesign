import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSessions, type SessionListItem } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'

const PAGE = 50

export function SessionsView() {
  const [rows, setRows] = useState<SessionListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    setLoading(true)
    listSessions(PAGE, offset)
      .then((page) => { if (active) { setRows(page.items); setTotal(page.total); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load sessions') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [offset])

  const columns: Column<SessionListItem>[] = [
    { key: 'state', header: 'State', render: (r) => <StatusBadge status={r.state ?? '—'} /> },
    { key: 'status', header: 'Status', render: (r) => r.status ?? '—' },
    { key: 'product', header: 'Product', render: (r) => r.product ?? '—' },
    { key: 'channel', header: 'Channel', render: (r) => r.channel ?? '—' },
    { key: 'entry', header: 'Entry', render: (r) => r.entry_path ?? '—' },
    { key: 'created', header: 'Created', render: (r) => (r.created_at ? new Date(r.created_at).toLocaleString() : '—') },
    { key: 'id', header: 'Session', render: (r) => <span className="font-mono text-xs text-gray-500">{r.id.slice(0, 8)}</span> },
  ]

  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + PAGE, total)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Design sessions</h1>
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span>{from}–{to} of {total}</span>
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE))}
            disabled={offset === 0}
            className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
          >
            Prev
          </button>
          <button
            onClick={() => setOffset(offset + PAGE)}
            disabled={offset + PAGE >= total}
            className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
      {error && <ErrorBanner message={error} />}
      <DataTable<SessionListItem>
        columns={columns}
        rows={rows}
        loading={loading}
        empty="No sessions"
        onRowClick={(r) => navigate(`/admin/sessions/${r.id}`)}
      />
    </div>
  )
}
