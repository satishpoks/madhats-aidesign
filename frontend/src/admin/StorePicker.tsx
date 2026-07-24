import { useAdminStore } from './adminStore'

/**
 * Store scoping control for admin operational views.
 *
 * Options are always limited to `profile.stores` (the admin's assigned
 * stores). A super admin optionally gets an "All stores" option (value '')
 * when `allowAll` is passed — a store admin never sees it, even if `allowAll`
 * is set, since their results are already restricted server-side to their
 * assigned stores.
 */
export function StorePicker({
  value,
  onChange,
  allowAll = false,
}: {
  value: string | null
  onChange: (id: string | null) => void
  allowAll?: boolean
}) {
  const profile = useAdminStore((s) => s.profile)
  const stores = profile?.stores ?? []
  const showAll = allowAll && (profile?.is_super ?? false)
  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      className="rounded border border-gray-300 px-3 py-1.5 text-sm"
      aria-label="Store"
    >
      {showAll && <option value="">All stores</option>}
      {stores.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  )
}
