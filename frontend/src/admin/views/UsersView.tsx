import { useEffect, useState } from 'react'
import {
  listUsers, createUser, updateUser, deleteUser, listStores,
  type AdminUser, type Store,
} from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

export function UsersView() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [stores, setStores] = useState<Store[]>([])
  const [loading, setLoading] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSuper, setIsSuper] = useState(false)
  const [storeIds, setStoreIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    try {
      setUsers(await listUsers())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load users')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    listStores().then(setStores).catch(() => setStores([]))
    refresh().catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function toggleStore(id: string) {
    setStoreIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createUser({ email, password, is_super: isSuper, store_ids: storeIds })
      setEmail('')
      setPassword('')
      setIsSuper(false)
      setStoreIds([])
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create user')
    } finally {
      setBusy(false)
    }
  }

  async function onToggleStatus(u: AdminUser) {
    setError(null)
    try {
      await updateUser(u.id, { status: u.status === 'active' ? 'disabled' : 'active' })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update user')
    }
  }

  async function onDelete(id: string) {
    setError(null)
    try {
      await deleteUser(id)
      setConfirmId(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete user')
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-5">
        <h1 className="text-[20px] font-semibold">Admin users</h1>
        {error && <ErrorBanner message={error} />}

        {loading ? (
          <p className="text-[13px] text-[#6b6b80]">Loading…</p>
        ) : users.length === 0 ? (
          <p className="text-[13px] text-[#6b6b80]">No admin users yet — create one below.</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-[#e0e1ea] bg-white">
            <table className="w-full text-left text-[13px]">
              <thead className="text-[#6b6b80]">
                <tr>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Role</th>
                  <th className="px-4 py-2 font-medium">Stores</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-[#e0e1ea]">
                    <td className="px-4 py-2 text-[#1a1a2e]">{u.email}</td>
                    <td className="px-4 py-2">{u.is_super ? 'Super' : 'Store admin'}</td>
                    <td className="px-4 py-2">
                      {u.is_super ? 'All' : u.stores.map((s) => s.name).join(', ') || '—'}
                    </td>
                    <td className="px-4 py-2">{u.status}</td>
                    <td className="px-4 py-2 text-right">
                      <span className="flex justify-end gap-2">
                        <button
                          onClick={() => onToggleStatus(u)}
                          className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px] text-[#6b6b80] hover:bg-gray-50"
                        >
                          {u.status === 'active' ? 'Disable' : 'Enable'}
                        </button>
                        {confirmId === u.id ? (
                          <span className="flex gap-1">
                            <button
                              onClick={() => onDelete(u.id)}
                              className="rounded bg-red-600 px-2 py-1 text-[11px] text-white"
                            >
                              Delete
                            </button>
                            <button
                              onClick={() => setConfirmId(null)}
                              className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px]"
                            >
                              Cancel
                            </button>
                          </span>
                        ) : (
                          <button
                            onClick={() => setConfirmId(u.id)}
                            className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px] text-red-600 hover:bg-red-50"
                          >
                            Delete
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="max-w-lg flex flex-col gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <h2 className="text-[15px] font-semibold">Create admin user</h2>
        <form onSubmit={onCreate} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[13px]">
            Email
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
            />
          </label>
          <label className="flex flex-col gap-1 text-[13px]">
            Password
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="text"
              className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
            />
          </label>
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} />
            Super admin (all stores)
          </label>
          {!isSuper && (
            <fieldset className="rounded-lg border border-[#e0e1ea] p-3">
              <legend className="px-1 text-[11px] text-[#6b6b80]">Assigned stores</legend>
              {stores.length === 0 ? (
                <p className="text-[12px] text-[#9a9ab0]">No stores yet.</p>
              ) : (
                stores.map((s) => (
                  <label key={s.id} className="flex items-center gap-2 py-0.5 text-[13px]" title={s.name}>
                    <input
                      type="checkbox"
                      aria-label={s.name}
                      checked={storeIds.includes(s.id)}
                      onChange={() => toggleStore(s.id)}
                    />
                    {s.slug}
                  </label>
                ))
              )}
            </fieldset>
          )}
          <button
            type="submit"
            disabled={busy || !email || !password}
            className={`self-start rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : 'hover:bg-[#e65300]'} disabled:opacity-50`}
          >
            {busy ? 'Creating…' : 'Create user'}
          </button>
        </form>
      </div>
    </div>
  )
}
