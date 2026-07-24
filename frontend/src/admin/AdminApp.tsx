import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AdminLayout } from './AdminLayout'
import { AdminLogin } from './AdminLogin'
import { SubmissionsView } from './views/SubmissionsView'
import { SubmissionDetailView } from './views/SubmissionDetailView'
import { QuoteRequestsView } from './views/QuoteRequestsView'
import { StoresView } from './views/StoresView'
import { HatTypesView } from './views/HatTypesView'
import { HatTypeWizard } from './views/HatTypeWizard'
import { HatTypeEditView } from './views/HatTypeEditView'
import { GraphicsView } from './views/GraphicsView'
import { BrandingView } from './views/BrandingView'
import { DecorationTypesView } from './views/DecorationTypesView'
import { OpsView } from './views/OpsView'
import { SessionsView } from './views/SessionsView'
import { SessionDetailView } from './views/SessionDetailView'
import { DiagnosticsView } from './views/DiagnosticsView'
import { SettingsView } from './views/SettingsView'
import { UsersView } from './views/UsersView'
import { ChangePasswordView } from './views/ChangePasswordView'
import { useAdminStore } from './adminStore'
import { fetchMe } from './adminApi'

// Legacy /admin/leads/:id → /admin/sessions/:id (preserve the id for bookmarks)
function LegacyLeadRedirect() {
  const { id } = useParams()
  return <Navigate to={`/admin/sessions/${id}`} replace />
}

function useHydrateProfile() {
  const credential = useAdminStore((s) => s.credential)
  const profile = useAdminStore((s) => s.profile)
  const setProfile = useAdminStore((s) => s.setProfile)
  const logout = useAdminStore((s) => s.logout)
  const [ready, setReady] = useState(profile !== null || credential === null)
  useEffect(() => {
    if (credential && !profile) {
      fetchMe().then(setProfile).catch(() => logout()).finally(() => setReady(true))
    } else {
      setReady(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [credential, profile])
  return ready
}

function HydratedLayout() {
  const ready = useHydrateProfile()
  if (!ready) {
    return <div className="p-8 text-sm text-gray-500">Loading…</div>
  }
  return <AdminLayout />
}

export default function AdminApp() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route
          path="/admin"
          element={
            <RequireAuth>
              <HydratedLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/admin/submissions" replace />} />
          <Route path="submissions" element={<SubmissionsView />} />
          <Route path="submissions/:id" element={<SubmissionDetailView />} />
          <Route path="quote-requests" element={<QuoteRequestsView />} />
          <Route path="sessions" element={<SessionsView />} />
          <Route path="sessions/:id" element={<SessionDetailView />} />
          {/* Legacy /admin/leads paths → redirect to the renamed Sessions route */}
          <Route path="leads" element={<Navigate to="/admin/sessions" replace />} />
          <Route path="leads/:id" element={<LegacyLeadRedirect />} />
          <Route path="diagnostics" element={<DiagnosticsView />} />
          <Route path="stores" element={<StoresView />} />
          <Route path="branding" element={<BrandingView />} />
          <Route path="hat-types/new" element={<HatTypeWizard />} />
          <Route path="hat-types" element={<HatTypesView />} />
          <Route path="hat-types/:id" element={<HatTypeEditView />} />
          <Route path="graphics" element={<GraphicsView />} />
          <Route path="decoration-types" element={<DecorationTypesView />} />
          <Route path="ops" element={<OpsView />} />
          <Route path="settings" element={<SettingsView />} />
          <Route path="users" element={<UsersView />} />
          <Route path="change-password" element={<ChangePasswordView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
