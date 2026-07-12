import { useEffect, useState } from 'react'
import {
  listHatTypes,
  createHatType,
  updateHatType,
  uploadHatAngle,
  listStores,
  type HatType,
  type Store,
} from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

const VIEWS = ['front', 'back', 'left', 'right'] as const

export function HatTypesView() {
  const [stores, setStores] = useState<Store[]>([])
  const [storeId, setStoreId] = useState('')
  const [hats, setHats] = useState<HatType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [creating, setCreating] = useState(false)

  useEffect(() => {
    listStores()
      .then((data) => {
        setStores(data)
        if (data.length > 0) setStoreId((prev) => prev || data[0].id)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load stores'))
  }, [])

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
  }, [storeKey])

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    if (!storeKey || !name || !slug) return
    setCreating(true)
    setError(null)
    try {
      await createHatType({ name, slug }, storeKey)
      setName('')
      setSlug('')
      reload(storeKey)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  async function onUpload(id: string, view: string, file: File) {
    if (!storeKey) return
    setError(null)
    try {
      await uploadHatAngle(id, view, file, storeKey)
      reload(storeKey)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    }
  }

  async function onToggleActive(h: HatType, active: boolean) {
    if (!storeKey) return
    setError(null)
    try {
      await updateHatType(h.id, { active }, storeKey)
      reload(storeKey)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Update failed')
    }
  }

  const allAngles = (h: HatType) => VIEWS.every((v) => h.blank_view_images[v])

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Hat Types</h1>
      {error && <ErrorBanner message={error} />}

      <label className="block text-sm">
        Store
        <select
          value={storeId}
          onChange={(e) => setStoreId(e.target.value)}
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

      {storeKey && (
        <>
          <form
            onSubmit={onCreate}
            className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4"
          >
            <label className="text-sm">
              Name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
              />
            </label>
            <label className="text-sm">
              Slug
              <input
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                required
                className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
              />
            </label>
            <button
              type="submit"
              disabled={creating}
              className="rounded-lg bg-[#ff5c00] text-white px-4 py-2 text-sm hover:bg-[#e64f00] disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'Add hat type'}
            </button>
          </form>

          {loading && <p className="text-sm text-gray-500">Loading…</p>}
          {!loading && hats.length === 0 && <p className="text-sm text-gray-500">No hat types yet</p>}

          <div className="space-y-4">
            {hats.map((h) => (
              <div key={h.id} className="rounded-lg border border-gray-200 bg-white p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-semibold">
                    {h.name} <span className="font-normal text-gray-400">({h.slug})</span>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={h.active}
                      disabled={!allAngles(h)}
                      onChange={(e) => onToggleActive(h, e.target.checked)}
                    />
                    Active
                    {!allAngles(h) && (
                      <span className="text-xs text-gray-400">(needs all 4 angles)</span>
                    )}
                  </label>
                </div>
                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {VIEWS.map((v) => (
                    <div key={v} className="text-center">
                      <div className="text-xs uppercase text-gray-500">{v}</div>
                      {h.blank_view_images[v] ? (
                        <div className="text-xs text-green-600">uploaded</div>
                      ) : (
                        <div className="text-xs text-gray-300">—</div>
                      )}
                      <input
                        type="file"
                        accept="image/*"
                        onChange={(e) => e.target.files?.[0] && onUpload(h.id, v, e.target.files[0])}
                        className="mt-1 text-xs"
                      />
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
