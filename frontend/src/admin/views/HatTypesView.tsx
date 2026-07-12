import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listHatTypes, deleteHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, hatStatus, angleCount, VIEWS, type HatStatus } from './hatTypes/shared'

const STATUS_LABEL: Record<HatStatus, string> = {
  active: 'Active',
  draft: 'Draft',
  needs_images: 'Needs images',
}
const STATUS_CLASS: Record<HatStatus, string> = {
  active: 'bg-green-100 text-green-700',
  draft: 'bg-amber-100 text-amber-700',
  needs_images: 'bg-gray-100 text-gray-500',
}

export function HatTypesView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [hats, setHats] = useState<HatType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)

  // Default the store selection to the first store once loaded.
  useEffect(() => {
    if (!storeId && stores.length > 0) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null

  function reload(key: string) {
    setLoading(true)
    listHatTypes(key)
      .then((data) => {
        setHats(data)
        setError(null)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load hat types'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (storeKey) reload(storeKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeKey])

  const filtered = useMemo(
    () => hats.filter((h) => h.name.toLowerCase().includes(search.toLowerCase())),
    [hats, search],
  )

  async function onDelete(id: string) {
    if (!storeKey) return
    setError(null)
    try {
      await deleteHatType(id, storeKey)
      setConfirmId(null)
      reload(storeKey)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Hat Types</h1>
        {storeId && (
          <Link
            to={`/admin/hat-types/new?store=${storeId}`}
            className="rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00]"
          >
            + Add hat type
          </Link>
        )}
      </div>

      {(error || storesError) && <ErrorBanner message={error ?? storesError!} />}

      <div className="flex flex-wrap items-end gap-4">
        <label className="block text-sm">
          Store
          <select
            value={storeId}
            onChange={(e) => setParams({ store: e.target.value }, { replace: true })}
            className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {stores.length === 0 && <option value="">No stores</option>}
            {stores.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Search
          <input
            value={search}
            placeholder="Search hat types…"
            onChange={(e) => setSearch(e.target.value)}
            className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-gray-500">No hat types yet — add your first.</p>
      )}

      <div className="space-y-3">
        {filtered.map((h) => {
          const status = hatStatus(h)
          return (
            <div
              key={h.id}
              className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-200 bg-white p-3"
            >
              <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded bg-gray-50">
                {h.view_images.front ? (
                  <img src={h.view_images.front} alt={h.name} className="max-h-14 object-contain" />
                ) : (
                  <span className="text-gray-300">—</span>
                )}
              </div>
              <div className="min-w-[8rem] flex-1">
                <div className="font-semibold">{h.name}</div>
                <div className="text-xs text-gray-400">{h.style || '—'}</div>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_CLASS[status]}`}>
                {STATUS_LABEL[status]}
              </span>
              <span className="text-xs text-gray-500">
                {h.colours.length} colour{h.colours.length === 1 ? '' : 's'} · {angleCount(h)}/
                {VIEWS.length} angles
              </span>
              <div className="flex items-center gap-2">
                <Link
                  to={`/admin/hat-types/${h.id}?store=${storeId}`}
                  className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
                >
                  Edit
                </Link>
                {confirmId === h.id ? (
                  <>
                    <button
                      onClick={() => onDelete(h.id)}
                      className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="rounded px-2 py-1 text-sm text-gray-500 hover:text-gray-700"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setConfirmId(h.id)}
                    className="rounded border border-gray-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
