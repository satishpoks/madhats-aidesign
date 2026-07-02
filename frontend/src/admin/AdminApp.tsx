import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AdminLayout } from './AdminLayout'
import { AdminLogin } from './AdminLogin'
import { SubmissionsView } from './views/SubmissionsView'
import { SubmissionDetailView } from './views/SubmissionDetailView'
import { QuoteRequestsView } from './views/QuoteRequestsView'
import { StoresView } from './views/StoresView'
import { OpsView } from './views/OpsView'
import { SessionsView } from './views/SessionsView'
import { SessionTranscriptView } from './views/SessionTranscriptView'
import { DiagnosticsView } from './views/DiagnosticsView'

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
          <Route path="sessions" element={<SessionsView />} />
          <Route path="sessions/:id" element={<SessionTranscriptView />} />
          <Route path="diagnostics" element={<DiagnosticsView />} />
          <Route path="stores" element={<StoresView />} />
          <Route path="ops" element={<OpsView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
