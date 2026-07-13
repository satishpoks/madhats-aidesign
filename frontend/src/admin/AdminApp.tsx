import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
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
import { DecorationTypesView } from './views/DecorationTypesView'
import { OpsView } from './views/OpsView'
import { LeadsView } from './views/LeadsView'
import { LeadDetailView } from './views/LeadDetailView'
import { DiagnosticsView } from './views/DiagnosticsView'
import { SettingsView } from './views/SettingsView'

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
          <Route path="leads" element={<LeadsView />} />
          <Route path="leads/:id" element={<LeadDetailView />} />
          <Route path="diagnostics" element={<DiagnosticsView />} />
          <Route path="stores" element={<StoresView />} />
          <Route path="hat-types/new" element={<HatTypeWizard />} />
          <Route path="hat-types" element={<HatTypesView />} />
          <Route path="hat-types/:id" element={<HatTypeEditView />} />
          <Route path="graphics" element={<GraphicsView />} />
          <Route path="decoration-types" element={<DecorationTypesView />} />
          <Route path="ops" element={<OpsView />} />
          <Route path="settings" element={<SettingsView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
