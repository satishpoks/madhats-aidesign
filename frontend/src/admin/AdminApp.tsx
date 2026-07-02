import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AdminLayout } from './AdminLayout'
import { AdminLogin } from './AdminLogin'
import { SubmissionsView } from './views/SubmissionsView'
import { SubmissionDetailView } from './views/SubmissionDetailView'
import { QuoteRequestsView } from './views/QuoteRequestsView'
import { StoresView } from './views/StoresView'
import { OpsView } from './views/OpsView'

export default function AdminApp() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route
          path="/admin"
          element={
            <RequireAuth>
              <AdminLayout />
            </RequireAuth>
          }
        >
          <Route index element={<Navigate to="/admin/submissions" replace />} />
          <Route path="submissions" element={<SubmissionsView />} />
          <Route path="submissions/:id" element={<SubmissionDetailView />} />
          <Route path="quote-requests" element={<QuoteRequestsView />} />
          <Route path="stores" element={<StoresView />} />
          <Route path="ops" element={<OpsView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
