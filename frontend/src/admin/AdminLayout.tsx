import { NavLink, Outlet } from 'react-router-dom'
import { useAdminStore } from './adminStore'

const NAV = [
  { to: '/admin/submissions', label: 'Approval queue' },
  { to: '/admin/quote-requests', label: 'Quote requests' },
  { to: '/admin/leads', label: 'Leads' },
  { to: '/admin/diagnostics', label: 'Diagnostics' },
  { to: '/admin/stores', label: 'Stores' },
  { to: '/admin/ops', label: 'Ops' },
]

export function AdminLayout() {
  const logout = useAdminStore((s) => s.logout)
  return (
    <div className="min-h-screen flex bg-gray-100 text-gray-900">
      <aside className="w-56 shrink-0 bg-white border-r border-gray-200 flex flex-col">
        <div className="px-4 py-4 font-semibold border-b border-gray-200">MadHats Admin</div>
        <nav className="flex-1 p-2 space-y-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${isActive ? 'bg-gray-900 text-white' : 'text-gray-700 hover:bg-gray-100'}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <button
          onClick={logout}
          className="m-2 rounded px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 text-left"
        >
          Sign out
        </button>
      </aside>
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
