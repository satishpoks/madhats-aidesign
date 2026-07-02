import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAdminStore } from './adminStore'

export function RequireAuth({ children }: { children: ReactNode }) {
  const authed = useAdminStore((s) => s.authed)
  const location = useLocation()
  if (!authed) {
    return <Navigate to="/admin/login" state={{ from: location }} replace />
  }
  return <>{children}</>
}
