import { useEffect, useState } from 'react'
import { listStores, createStore, syncStore, type Store } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'

export function StoresView() {
  const [rows, setRows] = useState<Store[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [shopifyDomain, setShopifyDomain] = useState('')
  const [creating, setCreating] = useState(false)
  const [syncingId, setSyncingId] = useState<string | null>(null)
  const [syncMsg, setSyncMsg] = useState<Record<string, string>>({})

  function load() {
    setLoading(true)
    listStores()
      .then((data) => { setRows(data); setError(null) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load stores'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    setError(null)
    try {
      const created = await createStore({
        slug,
        name,
        shopify_domain: shopifyDomain || undefined,
      })
      setRows((prev) => [created, ...prev])
      setSlug(''); setName(''); setShopifyDomain('')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Create failed')
    } finally {
      setCreating(false)
    }
  }

  async function onSync(id: string) {
    setSyncingId(id)
    setError(null)
    try {
      const res = await syncStore(id)
      setSyncMsg((prev) => ({ ...prev, [id]: `fetched ${res.fetched}, imported ${res.imported}, skipped ${res.skipped}` }))
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sync failed')
    } finally {
      setSyncingId(null)
    }
  }

  const columns: Column<Store>[] = [
    { key: 'slug', header: 'Slug', render: (r) => r.slug },
    { key: 'name', header: 'Name', render: (r) => r.name },
    {
      key: 'key',
      header: 'Publishable key',
      render: (r) => (
        <button
          type="button"
          onClick={() => navigator.clipboard?.writeText(r.public_key)}
          className="font-mono text-xs text-gray-700 hover:underline"
          title="Copy"
        >
          {r.public_key}
        </button>
      ),
    },
    { key: 'domain', header: 'Shopify domain', render: (r) => r.shopify_domain ?? '—' },
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.status} /> },
    {
      key: 'sync',
      header: '',
      render: (r) => (
        <div className="flex flex-col items-start gap-1">
          <button
            type="button"
            onClick={() => onSync(r.id)}
            disabled={syncingId === r.id}
            className="rounded-lg bg-[#ff5c00] text-white px-3 py-1 text-xs hover:bg-[#e64f00] disabled:opacity-50"
          >
            {syncingId === r.id ? 'Syncing…' : 'Sync catalogue'}
          </button>
          {syncMsg[r.id] && <span className="text-xs text-green-700">{syncMsg[r.id]}</span>}
        </div>
      ),
    },
  ]

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Stores</h1>
      {error && <ErrorBanner message={error} />}

      <form onSubmit={onCreate} className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4">
        <label className="text-sm">
          Slug
          <input value={slug} onChange={(e) => setSlug(e.target.value)} required className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm" />
        </label>
        <label className="text-sm">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm" />
        </label>
        <label className="text-sm">
          Shopify domain
          <input value={shopifyDomain} onChange={(e) => setShopifyDomain(e.target.value)} className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm" />
        </label>
        <button type="submit" disabled={creating} className="rounded-lg bg-[#ff5c00] text-white px-4 py-2 text-sm hover:bg-[#e64f00] disabled:opacity-50">
          {creating ? 'Creating…' : 'Create store'}
        </button>
      </form>

      <DataTable<Store> columns={columns} rows={rows} loading={loading} empty="No stores yet" />
    </div>
  )
}
