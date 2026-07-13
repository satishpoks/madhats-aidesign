import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  listDecorationTypes, createDecorationType, deleteDecorationType,
  type AdminDecorationType,
} from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores } from './hatTypes/shared'

export function DecorationTypesView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [items, setItems] = useState<AdminDecorationType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    if (stores.length > 0 && !stores.some(s => s.id === storeId)) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  const storeKey = stores.find(s => s.id === storeId)?.public_key ?? null

  function reload(key: string) {
    setLoading(true)
    listDecorationTypes(key)
      .then(data => { setItems(data); setError(null) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (storeKey) reload(storeKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeKey])

  async function onAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!storeKey || !name.trim()) return
    setBusy(true); setError(null)
    try {
      await createDecorationType(name.trim(), storeKey)
      setName('')
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Add failed')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(id: string) {
    if (!storeKey) return
    setError(null)
    try {
      await deleteDecorationType(id, storeKey)
      setConfirmId(null)
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold">Decoration types</h1>
        <select
          value={storeId}
          onChange={e => setParams({ store: e.target.value }, { replace: true })}
          className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-1.5 text-[13px]"
          aria-label="Store"
        >
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <span className="text-[12px] text-[#9a9ab0]">Methods offered to customers after they design (embroidery, print, …).</span>
      </div>

      {(storesError || error) && <ErrorBanner message={storesError || error || ''} />}

      <form onSubmit={onAdd} className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. Embroidery"
          className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
          aria-label="Decoration name"
        />
        <button
          type="submit"
          disabled={busy || !storeKey || !name.trim()}
          className={`rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : 'hover:bg-[#e65300]'} disabled:opacity-50`}
        >
          {busy ? 'Adding…' : 'Add'}
        </button>
      </form>

      {loading ? (
        <p className="text-[13px] text-[#6b6b80]">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-[#6b6b80]">No decoration types yet — add one above.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map(d => (
            <li key={d.id} className="flex items-center justify-between rounded-xl border border-[#e0e1ea] bg-white px-4 py-2">
              <span className="text-[14px] text-[#1a1a2e]">{d.name}</span>
              {confirmId === d.id ? (
                <span className="flex gap-1">
                  <button onClick={() => onDelete(d.id)} className="rounded bg-red-600 px-2 py-1 text-[11px] text-white">Delete</button>
                  <button onClick={() => setConfirmId(null)} className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px]">Cancel</button>
                </span>
              ) : (
                <button onClick={() => setConfirmId(d.id)} className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px] text-red-600 hover:bg-red-50">Delete</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
