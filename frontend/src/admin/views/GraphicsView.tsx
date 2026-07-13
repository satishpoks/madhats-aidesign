import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { listGraphics, uploadGraphic, deleteGraphic, type AdminGraphic } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores } from './hatTypes/shared'

// Admin manages only "company" graphics — clipart is a built-in shape palette
// on the customer side, not company-uploaded.
const CATEGORY = 'company' as const

export function GraphicsView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [items, setItems] = useState<AdminGraphic[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  // Default the store to the first one; correct an invalid ?store= too.
  useEffect(() => {
    if (stores.length > 0 && !stores.some(s => s.id === storeId)) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  const storeKey = stores.find(s => s.id === storeId)?.public_key ?? null

  function reload(key: string) {
    setLoading(true)
    listGraphics(key, CATEGORY)
      .then(data => { setItems(data); setError(null) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load graphics'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (storeKey) reload(storeKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeKey])

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !storeKey) return
    setBusy(true); setError(null)
    try {
      await uploadGraphic(CATEGORY, name.trim(), file, storeKey)
      setName('')
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setBusy(false)
      e.target.value = ''
    }
  }

  async function onDelete(id: string) {
    if (!storeKey) return
    setError(null)
    try {
      await deleteGraphic(id, storeKey)
      setConfirmId(null)
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold">Company graphics</h1>
        <select
          value={storeId}
          onChange={e => setParams({ store: e.target.value }, { replace: true })}
          className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-1.5 text-[13px]"
          aria-label="Store"
        >
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <span className="text-[12px] text-[#9a9ab0]">Patterns, logos & graphics customers can drop on their design. (Clipart shapes are built in.)</span>
      </div>

      {(storesError || error) && <ErrorBanner message={storesError || error || ''} />}

      {/* Upload form */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Name (optional)"
          className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
          aria-label="Graphic name"
        />
        <label className={`cursor-pointer rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : 'hover:bg-[#e65300]'}`}>
          {busy ? 'Uploading…' : 'Upload graphic'}
          <input
            ref={fileRef}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            onChange={onUpload}
            disabled={busy || !storeKey}
            className="sr-only"
          />
        </label>
        <span className="text-[12px] text-[#9a9ab0]">PNG/JPG/GIF/WebP · max 10 MB · transparent PNG recommended</span>
      </div>

      {/* Grid */}
      {loading ? (
        <p className="text-[13px] text-[#6b6b80]">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-[#6b6b80]">No company graphics yet — upload one above.</p>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(120px,1fr))] gap-3">
          {items.map(g => (
            <div key={g.id} className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-2">
              <div className="flex aspect-square items-center justify-center rounded-lg bg-[#f8f9fa] p-2">
                <img src={g.url} alt={g.name} className="max-h-full max-w-full object-contain" />
              </div>
              <span className="truncate text-[12px] text-[#1a1a2e]" title={g.name}>{g.name || '—'}</span>
              {confirmId === g.id ? (
                <div className="flex gap-1">
                  <button onClick={() => onDelete(g.id)} className="flex-1 rounded bg-red-600 px-2 py-1 text-[11px] text-white">Delete</button>
                  <button onClick={() => setConfirmId(null)} className="flex-1 rounded border border-[#e0e1ea] px-2 py-1 text-[11px]">Cancel</button>
                </div>
              ) : (
                <button onClick={() => setConfirmId(g.id)} className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px] text-red-600 hover:bg-red-50">Delete</button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
