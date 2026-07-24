import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSessions, type SessionListItem } from '../adminApi'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'
import { StorePicker } from '../StorePicker'

const PAGE = 30

function Thumb({ url, label }: { url: string | null; label: string }) {
  if (!url) {
    return (
      <div className="flex h-16 w-16 items-center justify-center rounded bg-gray-100 text-[10px] text-gray-400">
        {label}
      </div>
    )
  }
  return <img src={url} alt={label} className="h-16 w-16 rounded object-cover border border-gray-200" />
}

function summary(l: SessionListItem): string {
  const parts = [l.decoration_type, l.placement_zone, l.quantity ? `qty ${l.quantity}` : null].filter(Boolean)
  return parts.length ? parts.join(' · ') : 'No brief details yet'
}

export function LeadsView() {
  const [rows, setRows] = useState<SessionListItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [withContactOnly, setWithContactOnly] = useState(false)
  const [storeId, setStoreId] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    setLoading(true)
    listSessions(PAGE, offset, { storeId: storeId ?? undefined })
      .then((page) => { if (active) { setRows(page.items); setTotal(page.total); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load leads') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [offset, storeId])

  const visible = withContactOnly ? rows.filter((r) => r.customer?.email) : rows
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + PAGE, total)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Leads</h1>
        <div className="flex items-center gap-3 text-sm text-gray-600">
          <StorePicker
            value={storeId}
            onChange={(id) => { setStoreId(id); setOffset(0) }}
            allowAll
          />
          <label className="flex items-center gap-1">
            <input type="checkbox" checked={withContactOnly} onChange={(e) => setWithContactOnly(e.target.checked)} />
            With contact only
          </label>
          <span>{from}–{to} of {total}</span>
          <button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0} className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40">Prev</button>
          <button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= total} className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40">Next</button>
        </div>
      </div>

      {error && <ErrorBanner message={error} />}
      {loading && <div className="py-8 text-center text-sm text-gray-500">Loading…</div>}
      {!loading && visible.length === 0 && <div className="py-8 text-center text-sm text-gray-500">No leads</div>}

      <div className="grid gap-3">
        {visible.map((l) => (
          <button
            key={l.id}
            onClick={() => navigate(`/admin/leads/${l.id}`)}
            className="flex items-center gap-4 rounded-lg border border-gray-200 bg-white p-3 text-left hover:border-gray-400 hover:shadow-sm"
          >
            <Thumb url={l.reference_image_url} label="cap" />
            <Thumb url={l.generated_image_url} label="no design" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="truncate font-medium text-gray-900">
                  {l.customer?.name || l.customer?.email || 'Anonymous visitor'}
                </span>
                {l.customer?.email_verified && <span title="Email verified" className="text-green-600">✅</span>}
                <StatusBadge status={l.state ?? '—'} />
              </div>
              <div className="truncate text-sm text-gray-600">{l.product ?? 'No product'} — {summary(l)}</div>
              <div className="text-xs text-gray-400">
                {l.customer?.email ?? 'no email captured'}
                {l.generation_count > 0 ? ` · ${l.generation_count} generated` : ' · no images'}
                {l.created_at ? ` · ${new Date(l.created_at).toLocaleString()}` : ''}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
