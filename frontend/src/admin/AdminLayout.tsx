import { NavLink, Outlet } from 'react-router-dom'
import { useAdminStore } from './adminStore'

const NAV = [
  { to: '/admin/submissions', label: 'Approval queue' },
  { to: '/admin/quote-requests', label: 'Quote requests' },
  { to: '/admin/leads', label: 'Leads' },
  { to: '/admin/diagnostics', label: 'Diagnostics' },
  { to: '/admin/stores', label: 'Stores' },
  { to: '/admin/branding', label: 'Branding' },
  { to: '/admin/hat-types', label: 'Hat Types' },
  { to: '/admin/graphics', label: 'Graphics' },
  { to: '/admin/decoration-types', label: 'Decorations' },
  { to: '/admin/ops', label: 'Ops' },
  { to: '/admin/settings', label: 'Settings' },
]

export function AdminLayout() {
  const logout = useAdminStore((s) => s.logout)
  return (
    <div className="min-h-screen bg-[#f8f9fa] font-sans text-[#1a1a2e]">
      <header className="sticky top-0 z-20 border-b border-[#e0e1ea] bg-white">
        <div className="flex h-14 items-center gap-6 px-8">
          <span className="text-[18px] font-semibold tracking-tight text-[#ff5c00]">MAD HATS</span>
          <span className="hidden text-[13px] font-medium text-[#6b6b80] sm:inline">Admin</span>
          <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    isActive
                      ? 'bg-[#fff2ea] text-[#ff5c00]'
                      : 'text-[#6b6b80] hover:bg-[#f0f1f5] hover:text-[#1a1a2e]'
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <button
            onClick={logout}
            className="whitespace-nowrap rounded-full border border-[#e0e1ea] bg-[#f0f1f5] px-3 py-1.5 text-[12px] text-[#6b6b80] hover:bg-[#e8e9ef]"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-8 py-6">
        <Outlet />
      </main>
    </div>
  )
}
