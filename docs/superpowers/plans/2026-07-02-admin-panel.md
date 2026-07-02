# Admin Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an internal admin panel inside the existing React frontend that surfaces the already-existing `/admin/*` backend endpoints (approval queue, quote requests, store management, ops/diagnostics).

**Architecture:** A `/admin` route tree served by the same Vite app, using `react-router-dom`. A zustand store holds the `X-Admin-Secret` (persisted in `sessionStorage`); an `adminApi` fetch helper attaches it to every admin request and forces logout on 401/403. Auth is a login screen that validates the pasted secret against `GET /admin/stores`. No backend changes.

**Tech Stack:** React 18, TypeScript (strict), `react-router-dom` v6, Zustand, Tailwind CSS 3, Vitest + Testing Library.

## Global Constraints

- Frontend lives in `frontend/`; run commands from there.
- TypeScript is **strict** and the build runs `tsc && vite build` — all code must type-check with no `any` leaks and no unused vars.
- Tests: `npx vitest run` (NOT `npm test` — that is watch mode and hangs). Test files live in `frontend/src/__tests__/`.
- Admin requests send header `X-Admin-Secret` and **never** `X-Store-Key`.
- API base URL comes from `import.meta.env.VITE_API_BASE_URL` (fallback `http://localhost:8000`), matching `src/lib/api.ts`.
- No PII (customer name/email) written to `console`.
- Commit after each task with the shown message.
- sessionStorage key for the admin secret: `mh_admin_secret`.

---

## File Structure

```
frontend/src/admin/
  AdminApp.tsx              BrowserRouter + route table
  AdminLayout.tsx           sidebar nav (NavLink) + <Outlet>
  AdminLogin.tsx            secret entry + validation
  RequireAuth.tsx           guard: redirect to /admin/login when not authed
  adminStore.ts             zustand: secret (sessionStorage), authed, login/logout
  adminApi.ts               fetch helper (X-Admin-Secret) + typed endpoint fns + types
  components/
    DataTable.tsx           reusable table (columns + rows + loading/empty)
    ErrorBanner.tsx         inline error display
    StatusBadge.tsx         status pill
  views/
    SubmissionsView.tsx     approval queue list + status filter
    SubmissionDetailView.tsx concept images + approve/reject + notes
    QuoteRequestsView.tsx   confirmed-quote table
    StoresView.tsx          store list + create form + per-row sync
    OpsView.tsx             prompt-preview + delivery backfill
frontend/src/App.tsx        MODIFIED: route to <AdminApp/> when path starts /admin
```

---

## Task 1: Auth foundation — adminStore + adminApi

**Files:**
- Create: `frontend/src/admin/adminStore.ts`
- Create: `frontend/src/admin/adminApi.ts`
- Test: `frontend/src/__tests__/adminApi.test.ts`

**Interfaces:**
- Consumes: nothing (foundation).
- Produces (relied on by every later task):
  - `adminStore.ts`: `useAdminStore` (zustand hook) with state `{ secret: string | null; authed: boolean; login(secret: string): void; logout(): void }`. Also exports non-hook accessors `getSecret(): string | null` and `logout(): void` for use inside `adminApi`.
  - `adminApi.ts` types: `Store`, `CreateStoreBody`, `SyncResult`, `Submission`, `UpdateSubmissionBody`, `QuoteRequest`, `PromptPreview`, `BackfillResult`, and `class ApiError`.
  - `adminApi.ts` functions: `validateSecret(secret: string): Promise<boolean>`, `listStores(): Promise<Store[]>`, `createStore(body: CreateStoreBody): Promise<Store>`, `syncStore(id: string): Promise<SyncResult>`, `listSubmissions(): Promise<Submission[]>`, `updateSubmission(id: string, body: UpdateSubmissionBody): Promise<{ updated: boolean }>`, `listQuoteRequests(): Promise<QuoteRequest[]>`, `promptPreview(sessionId: string, tier: 'preview' | 'final'): Promise<PromptPreview>`, `backfillDeliveries(limit: number, maxAgeHours: number): Promise<BackfillResult>`.

- [ ] **Step 1: Write `adminStore.ts`**

```ts
import { create } from 'zustand'

const STORAGE_KEY = 'mh_admin_secret'

function readStored(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

interface AdminState {
  secret: string | null
  authed: boolean
  login: (secret: string) => void
  logout: () => void
}

export const useAdminStore = create<AdminState>((set) => {
  const stored = readStored()
  return {
    secret: stored,
    authed: stored !== null,
    login: (secret: string) => {
      try {
        sessionStorage.setItem(STORAGE_KEY, secret)
      } catch {
        // sessionStorage unavailable — keep in-memory only
      }
      set({ secret, authed: true })
    },
    logout: () => {
      try {
        sessionStorage.removeItem(STORAGE_KEY)
      } catch {
        // ignore
      }
      set({ secret: null, authed: false })
    },
  }
})

/** Non-hook accessors for use inside adminApi (outside React render). */
export function getSecret(): string | null {
  return useAdminStore.getState().secret
}

export function logout(): void {
  useAdminStore.getState().logout()
}
```

- [ ] **Step 2: Write the failing test** `frontend/src/__tests__/adminApi.test.ts`

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  validateSecret,
  listStores,
  createStore,
  updateSubmission,
  ApiError,
} from '../admin/adminApi'
import { useAdminStore } from '../admin/adminStore'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

function ok(data: unknown, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: () => Promise.resolve(data),
  })
}

beforeEach(() => {
  mockFetch.mockReset()
  useAdminStore.getState().login('secret-123')
})

describe('validateSecret', () => {
  it('returns true on 200', async () => {
    mockFetch.mockReturnValue(ok([]))
    await expect(validateSecret('abc')).resolves.toBe(true)
  })

  it('sends the given secret as X-Admin-Secret', async () => {
    mockFetch.mockReturnValue(ok([]))
    await validateSecret('my-secret')
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Admin-Secret')).toBe('my-secret')
  })

  it('returns false on 403 without logging out', async () => {
    mockFetch.mockReturnValue(ok({ detail: 'forbidden' }, 403))
    await expect(validateSecret('bad')).resolves.toBe(false)
    expect(useAdminStore.getState().authed).toBe(true)
  })
})

describe('authenticated requests', () => {
  it('listStores sends stored X-Admin-Secret and no X-Store-Key', async () => {
    mockFetch.mockReturnValue(ok([]))
    await listStores()
    const init = mockFetch.mock.calls[0][1] as { headers: Headers }
    expect(init.headers.get('X-Admin-Secret')).toBe('secret-123')
    expect(init.headers.get('X-Store-Key')).toBeNull()
  })

  it('createStore POSTs JSON body', async () => {
    mockFetch.mockReturnValue(ok({ id: 's1', slug: 'x', name: 'X', public_key: 'k', shopify_domain: null, status: 'active' }))
    await createStore({ slug: 'x', name: 'X' })
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(init.method).toBe('POST')
    expect(init.headers && (init.headers as Headers).get('Content-Type')).toBe('application/json')
  })

  it('updateSubmission PATCHes to the submission id', async () => {
    mockFetch.mockReturnValue(ok({ updated: true }))
    await updateSubmission('sub-1', { review_status: 'approved', reviewer_notes: 'ok' })
    const url = mockFetch.mock.calls[0][0] as string
    const init = mockFetch.mock.calls[0][1] as RequestInit
    expect(url).toContain('/admin/submissions/sub-1')
    expect(init.method).toBe('PATCH')
  })

  it('throws ApiError and logs out on 401', async () => {
    mockFetch.mockReturnValue(ok({ detail: 'unauthorized' }, 401))
    await expect(listStores()).rejects.toBeInstanceOf(ApiError)
    expect(useAdminStore.getState().authed).toBe(false)
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminApi.test.ts`
Expected: FAIL — cannot resolve `../admin/adminApi`.

- [ ] **Step 4: Write `adminApi.ts`**

```ts
import { getSecret, logout } from './adminStore'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000'

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

export interface Store {
  id: string
  slug: string
  name: string
  public_key: string
  shopify_domain: string | null
  status: string
  created_at?: string
}

export interface CreateStoreBody {
  slug: string
  name: string
  shopify_domain?: string
  allowed_origins?: string[]
  persona_name?: string
  greeting_template?: string
  sales_notification_email?: string
  brand?: Record<string, unknown>
}

export interface SyncResult {
  fetched: number
  imported: number
  skipped: number
}

export interface Submission {
  id: string
  session_id: string
  product_ref: Record<string, unknown> | null
  final_image_urls: string[]
  source_ref: Record<string, unknown> | null
  customer: Record<string, unknown> | null
  review_status: string
  reviewer_notes: string | null
  created_at: string
  decided_at: string | null
}

export interface UpdateSubmissionBody {
  review_status: string
  reviewer_notes?: string
}

export interface QuoteRequest {
  lead_id: string
  session_id: string
  name: string | null
  email: string | null
  phone: string | null
  notify_by_phone: boolean
  quote_note: string | null
  quote_confirmed_at: string | null
  product: string | null
  decoration_type: string | null
  placement_zone: string | null
  quantity: number | null
  share_token: string | null
}

export interface PromptPreview {
  session_id: string
  tier: string
  provider: string
  model: string | null
  reference_image_url: string
  has_uploaded_asset: boolean
  prompt: string
}

export type BackfillResult = Record<string, unknown>

/** Authenticated request: attaches the stored X-Admin-Secret; logs out on 401/403. */
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const secret = getSecret()
  if (secret === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const headers = new Headers(init.headers as HeadersInit | undefined)
  headers.set('X-Admin-Secret', secret)
  if (init.body !== undefined && typeof init.body === 'string') {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) {
      logout()
    }
    let detail = res.statusText
    try {
      const json = (await res.json()) as { detail?: string; message?: string }
      detail = json.detail ?? json.message ?? detail
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

/** Validate an arbitrary secret WITHOUT mutating the store (used by login). */
export async function validateSecret(secret: string): Promise<boolean> {
  const headers = new Headers()
  headers.set('X-Admin-Secret', secret)
  const res = await fetch(`${BASE_URL}/admin/stores`, { headers })
  return res.ok
}

export function listStores(): Promise<Store[]> {
  return request<Store[]>('/admin/stores')
}

export function createStore(body: CreateStoreBody): Promise<Store> {
  return request<Store>('/admin/stores', { method: 'POST', body: JSON.stringify(body) })
}

export function syncStore(id: string): Promise<SyncResult> {
  return request<SyncResult>(`/admin/stores/${id}/sync`, { method: 'POST' })
}

export function listSubmissions(): Promise<Submission[]> {
  return request<Submission[]>('/admin/submissions')
}

export function updateSubmission(id: string, body: UpdateSubmissionBody): Promise<{ updated: boolean }> {
  return request<{ updated: boolean }>(`/admin/submissions/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function listQuoteRequests(): Promise<QuoteRequest[]> {
  return request<QuoteRequest[]>('/admin/quote-requests')
}

export function promptPreview(sessionId: string, tier: 'preview' | 'final'): Promise<PromptPreview> {
  return request<PromptPreview>(`/admin/prompt-preview/${sessionId}?tier=${tier}`)
}

export function backfillDeliveries(limit: number, maxAgeHours: number): Promise<BackfillResult> {
  return request<BackfillResult>(
    `/admin/deliveries/backfill?limit=${limit}&max_age_hours=${maxAgeHours}`,
    { method: 'POST' },
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminApi.test.ts`
Expected: PASS (all cases).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/adminStore.ts frontend/src/admin/adminApi.ts frontend/src/__tests__/adminApi.test.ts
git commit -m "feat(admin): auth store + admin API client"
```

---

## Task 2: Routing shell, auth guard, and login

**Files:**
- Modify: `frontend/package.json` (add `react-router-dom`)
- Create: `frontend/src/admin/AdminApp.tsx`
- Create: `frontend/src/admin/AdminLayout.tsx`
- Create: `frontend/src/admin/RequireAuth.tsx`
- Create: `frontend/src/admin/AdminLogin.tsx`
- Modify: `frontend/src/App.tsx:11-13` (route into `AdminApp` when path starts `/admin`)
- Test: `frontend/src/__tests__/adminAuth.test.tsx`

**Interfaces:**
- Consumes: `useAdminStore` (`authed`, `login`), `validateSecret` (Task 1).
- Produces: `<AdminApp/>` (default export) mounting all `/admin/*` routes; `<RequireAuth>` guard; the child-route slots for Tasks 4–7. Child route paths: `submissions`, `submissions/:id`, `quote-requests`, `stores`, `ops`.

- [ ] **Step 1: Install react-router-dom**

Run: `cd frontend && npm install react-router-dom@^6.26.0`
Expected: adds dependency; `package.json` updated.

- [ ] **Step 2: Write the failing test** `frontend/src/__tests__/adminAuth.test.tsx`

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../admin/adminApi', () => ({
  validateSecret: vi.fn(),
}))

import { validateSecret } from '../admin/adminApi'
import { AdminLogin } from '../admin/AdminLogin'
import { RequireAuth } from '../admin/RequireAuth'
import { useAdminStore } from '../admin/adminStore'

beforeEach(() => {
  useAdminStore.getState().logout()
  vi.mocked(validateSecret).mockReset()
})

describe('AdminLogin', () => {
  it('stores the secret and sets authed on a valid secret', async () => {
    vi.mocked(validateSecret).mockResolvedValue(true)
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/admin secret/i), { target: { value: 'good-secret' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(useAdminStore.getState().authed).toBe(true))
    expect(useAdminStore.getState().secret).toBe('good-secret')
  })

  it('shows an error and does not authenticate on an invalid secret', async () => {
    vi.mocked(validateSecret).mockResolvedValue(false)
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/admin secret/i), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(screen.getByText(/invalid admin secret/i)).toBeInTheDocument())
    expect(useAdminStore.getState().authed).toBe(false)
  })
})

describe('RequireAuth', () => {
  it('redirects to the login route when not authed', () => {
    render(
      <MemoryRouter initialEntries={['/admin/stores']}>
        <RequireAuth>
          <div>secret content</div>
        </RequireAuth>
      </MemoryRouter>,
    )
    expect(screen.queryByText('secret content')).not.toBeInTheDocument()
  })

  it('renders children when authed', () => {
    useAdminStore.getState().login('s')
    render(
      <MemoryRouter initialEntries={['/admin/stores']}>
        <RequireAuth>
          <div>secret content</div>
        </RequireAuth>
      </MemoryRouter>,
    )
    expect(screen.getByText('secret content')).toBeInTheDocument()
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminAuth.test.tsx`
Expected: FAIL — modules `AdminLogin`/`RequireAuth` not found.

- [ ] **Step 4: Write `RequireAuth.tsx`**

```tsx
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
```

- [ ] **Step 5: Write `AdminLogin.tsx`**

```tsx
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminStore } from './adminStore'
import { validateSecret } from './adminApi'

export function AdminLogin() {
  const [secret, setSecret] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const login = useAdminStore((s) => s.login)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/admin/submissions'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const valid = await validateSecret(secret)
      if (valid) {
        login(secret)
        navigate(from, { replace: true })
      } else {
        setError('Invalid admin secret')
      }
    } catch {
      setError('Could not reach the server — try again')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white rounded-lg shadow p-6 space-y-4">
        <h1 className="text-lg font-semibold text-gray-900">MadHats Admin</h1>
        <label className="block text-sm font-medium text-gray-700">
          Admin secret
          <input
            type="password"
            autoComplete="off"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || secret.length === 0}
          className="w-full rounded bg-gray-900 text-white py-2 text-sm font-medium disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 6: Write `AdminLayout.tsx`**

```tsx
import { NavLink, Outlet } from 'react-router-dom'
import { useAdminStore } from './adminStore'

const NAV = [
  { to: '/admin/submissions', label: 'Approval queue' },
  { to: '/admin/quote-requests', label: 'Quote requests' },
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
```

- [ ] **Step 7: Write `AdminApp.tsx`** (views imported here are created in Tasks 4–7; import them now — the files will exist after those tasks. To keep this task independently runnable, use placeholder inline elements that Tasks 4–7 replace.)

```tsx
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
```

> NOTE FOR IMPLEMENTER: Tasks 4–7 create the five view files imported above. To let THIS task build and its test pass in isolation, first create the five view files as one-line stubs (e.g. `export function SubmissionsView() { return <div>Submissions</div> }`), then Tasks 4–7 replace each stub with the real implementation. Create all five stubs now:
> - `frontend/src/admin/views/SubmissionsView.tsx` → `export function SubmissionsView() { return <div>Submissions</div> }`
> - `frontend/src/admin/views/SubmissionDetailView.tsx` → `export function SubmissionDetailView() { return <div>Detail</div> }`
> - `frontend/src/admin/views/QuoteRequestsView.tsx` → `export function QuoteRequestsView() { return <div>Quotes</div> }`
> - `frontend/src/admin/views/StoresView.tsx` → `export function StoresView() { return <div>Stores</div> }`
> - `frontend/src/admin/views/OpsView.tsx` → `export function OpsView() { return <div>Ops</div> }`

- [ ] **Step 8: Modify `App.tsx`** — add the admin branch. Change the imports block and the top of the component.

Replace lines 1-9 (import block) by appending after line 9:

```tsx
import AdminApp from './admin/AdminApp'
```

Then, immediately inside `export default function App() {` (before the existing `const sessionView = ...` line), add:

```tsx
  if (typeof window !== 'undefined' && window.location.pathname.startsWith('/admin')) {
    return <AdminApp />
  }
```

- [ ] **Step 9: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminAuth.test.tsx`
Expected: PASS.

- [ ] **Step 10: Verify the build type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/admin frontend/src/App.tsx frontend/src/__tests__/adminAuth.test.tsx
git commit -m "feat(admin): routing shell, auth guard, login screen"
```

---

## Task 3: Shared UI components

**Files:**
- Create: `frontend/src/admin/components/ErrorBanner.tsx`
- Create: `frontend/src/admin/components/StatusBadge.tsx`
- Create: `frontend/src/admin/components/DataTable.tsx`
- Test: `frontend/src/__tests__/adminComponents.test.tsx`

**Interfaces:**
- Produces:
  - `ErrorBanner`: `({ message }: { message: string }) => JSX.Element`.
  - `StatusBadge`: `({ status }: { status: string }) => JSX.Element`.
  - `DataTable<T>`: `({ columns, rows, loading, empty, onRowClick }: { columns: Column<T>[]; rows: T[]; loading?: boolean; empty?: string; onRowClick?: (row: T) => void }) => JSX.Element` where `Column<T> = { key: string; header: string; render: (row: T) => ReactNode }`. Both `Column` and `DataTable` are exported.

- [ ] **Step 1: Write the failing test** `frontend/src/__tests__/adminComponents.test.tsx`

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { DataTable } from '../admin/components/DataTable'
import { ErrorBanner } from '../admin/components/ErrorBanner'
import { StatusBadge } from '../admin/components/StatusBadge'

describe('ErrorBanner', () => {
  it('renders the message', () => {
    render(<ErrorBanner message="Boom" />)
    expect(screen.getByText('Boom')).toBeInTheDocument()
  })
})

describe('StatusBadge', () => {
  it('renders the status text', () => {
    render(<StatusBadge status="pending" />)
    expect(screen.getByText('pending')).toBeInTheDocument()
  })
})

describe('DataTable', () => {
  interface Row { id: string; name: string }
  const columns = [
    { key: 'name', header: 'Name', render: (r: Row) => r.name },
  ]

  it('renders a loading state', () => {
    render(<DataTable<Row> columns={columns} rows={[]} loading />)
    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders the empty message when there are no rows', () => {
    render(<DataTable<Row> columns={columns} rows={[]} empty="Nothing here" />)
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
  })

  it('renders one row per item', () => {
    render(<DataTable<Row> columns={columns} rows={[{ id: '1', name: 'Alice' }, { id: '2', name: 'Bob' }]} />)
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminComponents.test.tsx`
Expected: FAIL — component modules not found.

- [ ] **Step 3: Write `ErrorBanner.tsx`**

```tsx
export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
      {message}
    </div>
  )
}
```

- [ ] **Step 4: Write `StatusBadge.tsx`**

```tsx
const STYLES: Record<string, string> = {
  pending: 'bg-amber-100 text-amber-800',
  approved: 'bg-green-100 text-green-800',
  active: 'bg-green-100 text-green-800',
  rejected: 'bg-red-100 text-red-800',
}

export function StatusBadge({ status }: { status: string }) {
  const cls = STYLES[status] ?? 'bg-gray-100 text-gray-700'
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>
}
```

- [ ] **Step 5: Write `DataTable.tsx`**

```tsx
import type { ReactNode } from 'react'

export interface Column<T> {
  key: string
  header: string
  render: (row: T) => ReactNode
}

interface DataTableProps<T> {
  columns: Column<T>[]
  rows: T[]
  loading?: boolean
  empty?: string
  onRowClick?: (row: T) => void
}

export function DataTable<T>({ columns, rows, loading, empty, onRowClick }: DataTableProps<T>) {
  if (loading) {
    return <div className="py-8 text-center text-sm text-gray-500">Loading…</div>
  }
  if (rows.length === 0) {
    return <div className="py-8 text-center text-sm text-gray-500">{empty ?? 'No records'}</div>
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200 text-sm">
        <thead className="bg-gray-50">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="px-4 py-2 text-left font-medium text-gray-600">{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={onRowClick ? 'cursor-pointer hover:bg-gray-50' : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className="px-4 py-2 text-gray-800">{c.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminComponents.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/admin/components frontend/src/__tests__/adminComponents.test.tsx
git commit -m "feat(admin): shared DataTable, ErrorBanner, StatusBadge"
```

---

## Task 4: Approval queue (SubmissionsView + SubmissionDetailView)

**Files:**
- Modify (replace stub): `frontend/src/admin/views/SubmissionsView.tsx`
- Modify (replace stub): `frontend/src/admin/views/SubmissionDetailView.tsx`
- Test: `frontend/src/__tests__/adminSubmissions.test.tsx`

**Interfaces:**
- Consumes: `listSubmissions`, `updateSubmission`, `Submission` (Task 1); `DataTable`, `Column`, `StatusBadge`, `ErrorBanner` (Task 3); `useParams`, `useNavigate` from react-router-dom.
- Produces: `SubmissionsView` and `SubmissionDetailView` (named exports) matching the imports already in `AdminApp.tsx`.

- [ ] **Step 1: Write the failing test** `frontend/src/__tests__/adminSubmissions.test.tsx`

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../admin/adminApi', () => ({
  listSubmissions: vi.fn(),
  updateSubmission: vi.fn(),
}))

import { listSubmissions, updateSubmission } from '../admin/adminApi'
import { SubmissionsView } from '../admin/views/SubmissionsView'
import { SubmissionDetailView } from '../admin/views/SubmissionDetailView'

const sub = {
  id: 'sub-1',
  session_id: 'sess-1',
  product_ref: { name: 'Classic Cap' },
  final_image_urls: ['https://img/1.png'],
  source_ref: null,
  customer: { name: 'Jane' },
  review_status: 'pending',
  reviewer_notes: null,
  created_at: '2026-07-01T00:00:00Z',
  decided_at: null,
}

beforeEach(() => {
  vi.mocked(listSubmissions).mockReset()
  vi.mocked(updateSubmission).mockReset()
})

describe('SubmissionsView', () => {
  it('lists submissions from the API', async () => {
    vi.mocked(listSubmissions).mockResolvedValue([sub])
    render(
      <MemoryRouter>
        <SubmissionsView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('Classic Cap')).toBeInTheDocument())
  })

  it('shows an error banner when the fetch fails', async () => {
    vi.mocked(listSubmissions).mockRejectedValue(new Error('nope'))
    render(
      <MemoryRouter>
        <SubmissionsView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})

describe('SubmissionDetailView', () => {
  it('approves with reviewer notes', async () => {
    vi.mocked(listSubmissions).mockResolvedValue([sub])
    vi.mocked(updateSubmission).mockResolvedValue({ updated: true })
    render(
      <MemoryRouter initialEntries={['/admin/submissions/sub-1']}>
        <Routes>
          <Route path="/admin/submissions/:id" element={<SubmissionDetailView />} />
          <Route path="/admin/submissions" element={<div>list</div>} />
        </Routes>
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/Jane/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/reviewer notes/i), { target: { value: 'looks good' } })
    fireEvent.click(screen.getByRole('button', { name: /approve/i }))
    await waitFor(() =>
      expect(updateSubmission).toHaveBeenCalledWith('sub-1', {
        review_status: 'approved',
        reviewer_notes: 'looks good',
      }),
    )
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminSubmissions.test.tsx`
Expected: FAIL — stub views don't render the expected content / calls.

- [ ] **Step 3: Write `SubmissionsView.tsx`**

```tsx
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listSubmissions, type Submission } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { StatusBadge } from '../components/StatusBadge'
import { ErrorBanner } from '../components/ErrorBanner'

const STATUSES = ['all', 'pending', 'approved', 'rejected'] as const

function productName(s: Submission): string {
  const ref = s.product_ref as { name?: string; product_id?: string } | null
  return ref?.name ?? ref?.product_id ?? '—'
}

function customerName(s: Submission): string {
  const c = s.customer as { name?: string } | null
  return c?.name ?? '—'
}

export function SubmissionsView() {
  const [rows, setRows] = useState<Submission[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<(typeof STATUSES)[number]>('all')
  const navigate = useNavigate()

  useEffect(() => {
    let active = true
    setLoading(true)
    listSubmissions()
      .then((data) => { if (active) { setRows(data); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load submissions') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const filtered = useMemo(
    () => (filter === 'all' ? rows : rows.filter((r) => r.review_status === filter)),
    [rows, filter],
  )

  const columns: Column<Submission>[] = [
    { key: 'status', header: 'Status', render: (r) => <StatusBadge status={r.review_status} /> },
    { key: 'product', header: 'Product', render: productName },
    { key: 'customer', header: 'Customer', render: customerName },
    { key: 'created', header: 'Created', render: (r) => new Date(r.created_at).toLocaleString() },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Approval queue</h1>
        <select
          value={filter}
          onChange={(e) => setFilter(e.target.value as (typeof STATUSES)[number])}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
          aria-label="Filter by status"
        >
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>
      {error && <ErrorBanner message={error} />}
      <DataTable<Submission>
        columns={columns}
        rows={filtered}
        loading={loading}
        empty="No submissions"
        onRowClick={(r) => navigate(`/admin/submissions/${r.id}`)}
      />
    </div>
  )
}
```

- [ ] **Step 4: Write `SubmissionDetailView.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { listSubmissions, updateSubmission, type Submission } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'

export function SubmissionDetailView() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [sub, setSub] = useState<Submission | null>(null)
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let active = true
    // No single-submission GET exists; fetch the list and pick the row.
    listSubmissions()
      .then((data) => {
        if (!active) return
        const found = data.find((s) => s.id === id) ?? null
        setSub(found)
        setNotes(found?.reviewer_notes ?? '')
        setError(found ? null : 'Submission not found')
      })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load') })
    return () => { active = false }
  }, [id])

  async function decide(status: 'approved' | 'rejected') {
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      await updateSubmission(id, { review_status: status, reviewer_notes: notes })
      navigate('/admin/submissions')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Update failed')
    } finally {
      setBusy(false)
    }
  }

  if (error && !sub) return <ErrorBanner message={error} />
  if (!sub) return <div className="py-8 text-sm text-gray-500">Loading…</div>

  const customer = sub.customer as { name?: string; email?: string } | null

  return (
    <div className="space-y-4 max-w-3xl">
      <button onClick={() => navigate('/admin/submissions')} className="text-sm text-gray-500 hover:underline">
        ← Back to queue
      </button>
      <div className="flex items-center gap-3">
        <h1 className="text-xl font-semibold">Submission</h1>
        <StatusBadge status={sub.review_status} />
      </div>
      {error && <ErrorBanner message={error} />}

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div><span className="text-gray-500">Session:</span> {sub.session_id}</div>
        <div><span className="text-gray-500">Customer:</span> {customer?.name ?? '—'}</div>
      </div>

      <div className="flex flex-wrap gap-3">
        {sub.final_image_urls.map((url) => (
          <img key={url} src={url} alt="concept" className="w-48 rounded border border-gray-200" />
        ))}
      </div>

      <label className="block text-sm font-medium text-gray-700">
        Reviewer notes
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
        />
      </label>

      <div className="flex gap-2">
        <button
          onClick={() => decide('approved')}
          disabled={busy}
          className="rounded bg-green-600 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Approve
        </button>
        <button
          onClick={() => decide('rejected')}
          disabled={busy}
          className="rounded bg-red-600 text-white px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminSubmissions.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/SubmissionsView.tsx frontend/src/admin/views/SubmissionDetailView.tsx frontend/src/__tests__/adminSubmissions.test.tsx
git commit -m "feat(admin): approval queue list + detail with approve/reject"
```

---

## Task 5: Quote requests view

**Files:**
- Modify (replace stub): `frontend/src/admin/views/QuoteRequestsView.tsx`
- Test: `frontend/src/__tests__/adminQuotes.test.tsx`

**Interfaces:**
- Consumes: `listQuoteRequests`, `QuoteRequest` (Task 1); `DataTable`, `Column`, `ErrorBanner` (Task 3).
- Produces: `QuoteRequestsView` (named export).

- [ ] **Step 1: Write the failing test** `frontend/src/__tests__/adminQuotes.test.tsx`

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({ listQuoteRequests: vi.fn() }))

import { listQuoteRequests } from '../admin/adminApi'
import { QuoteRequestsView } from '../admin/views/QuoteRequestsView'

beforeEach(() => vi.mocked(listQuoteRequests).mockReset())

describe('QuoteRequestsView', () => {
  it('renders quote request rows', async () => {
    vi.mocked(listQuoteRequests).mockResolvedValue([
      {
        lead_id: 'l1', session_id: 's1', name: 'Jane', email: 'jane@x.com', phone: '123',
        notify_by_phone: true, quote_note: 'rush', quote_confirmed_at: '2026-07-01T00:00:00Z',
        product: 'Classic Cap', decoration_type: 'embroidery', placement_zone: 'front',
        quantity: 50, share_token: 'tok',
      },
    ])
    render(<QuoteRequestsView />)
    await waitFor(() => expect(screen.getByText('jane@x.com')).toBeInTheDocument())
    expect(screen.getByText('Classic Cap')).toBeInTheDocument()
  })

  it('shows an error banner on failure', async () => {
    vi.mocked(listQuoteRequests).mockRejectedValue(new Error('boom'))
    render(<QuoteRequestsView />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminQuotes.test.tsx`
Expected: FAIL — stub renders `Quotes`, not the data.

- [ ] **Step 3: Write `QuoteRequestsView.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { listQuoteRequests, type QuoteRequest } from '../adminApi'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'

export function QuoteRequestsView() {
  const [rows, setRows] = useState<QuoteRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setLoading(true)
    listQuoteRequests()
      .then((data) => { if (active) { setRows(data); setError(null) } })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : 'Failed to load quote requests') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  const columns: Column<QuoteRequest>[] = [
    { key: 'name', header: 'Name', render: (r) => r.name ?? '—' },
    { key: 'email', header: 'Email', render: (r) => r.email ?? '—' },
    { key: 'phone', header: 'Phone', render: (r) => (r.phone ? `${r.phone}${r.notify_by_phone ? ' 📞' : ''}` : '—') },
    { key: 'product', header: 'Product', render: (r) => r.product ?? '—' },
    { key: 'decoration', header: 'Decoration', render: (r) => r.decoration_type ?? '—' },
    { key: 'placement', header: 'Placement', render: (r) => r.placement_zone ?? '—' },
    { key: 'qty', header: 'Qty', render: (r) => (r.quantity ?? '—') },
    { key: 'note', header: 'Note', render: (r) => r.quote_note ?? '—' },
    { key: 'confirmed', header: 'Confirmed', render: (r) => (r.quote_confirmed_at ? new Date(r.quote_confirmed_at).toLocaleString() : '—') },
  ]

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Quote requests</h1>
      {error && <ErrorBanner message={error} />}
      <DataTable<QuoteRequest> columns={columns} rows={rows} loading={loading} empty="No confirmed quote requests" />
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminQuotes.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/QuoteRequestsView.tsx frontend/src/__tests__/adminQuotes.test.tsx
git commit -m "feat(admin): quote requests view"
```

---

## Task 6: Stores view (list + create + sync)

**Files:**
- Modify (replace stub): `frontend/src/admin/views/StoresView.tsx`
- Test: `frontend/src/__tests__/adminStores.test.tsx`

**Interfaces:**
- Consumes: `listStores`, `createStore`, `syncStore`, `Store`, `CreateStoreBody`, `SyncResult` (Task 1); `DataTable`, `Column`, `StatusBadge`, `ErrorBanner` (Task 3).
- Produces: `StoresView` (named export).

- [ ] **Step 1: Write the failing test** `frontend/src/__tests__/adminStores.test.tsx`

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({
  listStores: vi.fn(),
  createStore: vi.fn(),
  syncStore: vi.fn(),
}))

import { listStores, createStore, syncStore } from '../admin/adminApi'
import { StoresView } from '../admin/views/StoresView'

const store = { id: 'st-1', slug: 'madhats', name: 'MadHats', public_key: 'mh_pk_x', shopify_domain: null, status: 'active', created_at: '2026-07-01T00:00:00Z' }

beforeEach(() => {
  vi.mocked(listStores).mockReset()
  vi.mocked(createStore).mockReset()
  vi.mocked(syncStore).mockReset()
})

describe('StoresView', () => {
  it('lists stores', async () => {
    vi.mocked(listStores).mockResolvedValue([store])
    render(<StoresView />)
    await waitFor(() => expect(screen.getByText('madhats')).toBeInTheDocument())
    expect(screen.getByText('mh_pk_x')).toBeInTheDocument()
  })

  it('creates a store from the form', async () => {
    vi.mocked(listStores).mockResolvedValue([])
    vi.mocked(createStore).mockResolvedValue(store)
    render(<StoresView />)
    await waitFor(() => expect(listStores).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText(/slug/i), { target: { value: 'madhats' } })
    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'MadHats' } })
    fireEvent.click(screen.getByRole('button', { name: /create store/i }))
    await waitFor(() => expect(createStore).toHaveBeenCalledWith(
      expect.objectContaining({ slug: 'madhats', name: 'MadHats' }),
    ))
  })

  it('syncs a store and shows counts', async () => {
    vi.mocked(listStores).mockResolvedValue([store])
    vi.mocked(syncStore).mockResolvedValue({ fetched: 10, imported: 8, skipped: 2 })
    render(<StoresView />)
    await waitFor(() => expect(screen.getByText('madhats')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /sync/i }))
    await waitFor(() => expect(syncStore).toHaveBeenCalledWith('st-1'))
    await waitFor(() => expect(screen.getByText(/imported 8/i)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminStores.test.tsx`
Expected: FAIL — stub renders `Stores` only.

- [ ] **Step 3: Write `StoresView.tsx`**

```tsx
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
            className="rounded bg-gray-900 text-white px-3 py-1 text-xs disabled:opacity-50"
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
        <button type="submit" disabled={creating} className="rounded bg-gray-900 text-white px-4 py-2 text-sm disabled:opacity-50">
          {creating ? 'Creating…' : 'Create store'}
        </button>
      </form>

      <DataTable<Store> columns={columns} rows={rows} loading={loading} empty="No stores yet" />
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminStores.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/StoresView.tsx frontend/src/__tests__/adminStores.test.tsx
git commit -m "feat(admin): stores list, create form, catalogue sync"
```

---

## Task 7: Ops view (prompt preview + delivery backfill)

**Files:**
- Modify (replace stub): `frontend/src/admin/views/OpsView.tsx`
- Test: `frontend/src/__tests__/adminOps.test.tsx`

**Interfaces:**
- Consumes: `promptPreview`, `backfillDeliveries`, `PromptPreview` (Task 1); `ErrorBanner` (Task 3).
- Produces: `OpsView` (named export).

- [ ] **Step 1: Write the failing test** `frontend/src/__tests__/adminOps.test.tsx`

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../admin/adminApi', () => ({
  promptPreview: vi.fn(),
  backfillDeliveries: vi.fn(),
}))

import { promptPreview, backfillDeliveries } from '../admin/adminApi'
import { OpsView } from '../admin/views/OpsView'

beforeEach(() => {
  vi.mocked(promptPreview).mockReset()
  vi.mocked(backfillDeliveries).mockReset()
})

describe('OpsView prompt preview', () => {
  it('fetches and displays the prompt', async () => {
    vi.mocked(promptPreview).mockResolvedValue({
      session_id: 'sess-1', tier: 'preview', provider: 'GeminiFlash', model: 'gemini-2.5-flash-image',
      reference_image_url: 'https://img/ref.png', has_uploaded_asset: false, prompt: 'DO THIS AND THAT',
    })
    render(<OpsView />)
    fireEvent.change(screen.getByLabelText(/session id/i), { target: { value: 'sess-1' } })
    fireEvent.click(screen.getByRole('button', { name: /preview prompt/i }))
    await waitFor(() => expect(screen.getByText('DO THIS AND THAT')).toBeInTheDocument())
    expect(promptPreview).toHaveBeenCalledWith('sess-1', 'preview')
  })
})

describe('OpsView delivery backfill', () => {
  it('runs the backfill and shows the result', async () => {
    vi.mocked(backfillDeliveries).mockResolvedValue({ retried: 3, sent: 2 })
    render(<OpsView />)
    fireEvent.click(screen.getByRole('button', { name: /run backfill/i }))
    await waitFor(() => expect(backfillDeliveries).toHaveBeenCalledWith(100, 72))
    await waitFor(() => expect(screen.getByText(/"retried": 3/)).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminOps.test.tsx`
Expected: FAIL — stub renders `Ops` only.

- [ ] **Step 3: Write `OpsView.tsx`**

```tsx
import { useState } from 'react'
import { promptPreview, backfillDeliveries, type PromptPreview } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

export function OpsView() {
  // Prompt preview state
  const [sessionId, setSessionId] = useState('')
  const [tier, setTier] = useState<'preview' | 'final'>('preview')
  const [preview, setPreview] = useState<PromptPreview | null>(null)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)

  // Backfill state
  const [limit, setLimit] = useState(100)
  const [maxAge, setMaxAge] = useState(72)
  const [backfillResult, setBackfillResult] = useState<string | null>(null)
  const [backfillErr, setBackfillErr] = useState<string | null>(null)
  const [backfillBusy, setBackfillBusy] = useState(false)

  async function onPreview() {
    if (!sessionId) return
    setPreviewBusy(true)
    setPreviewErr(null)
    try {
      setPreview(await promptPreview(sessionId, tier))
    } catch (e: unknown) {
      setPreview(null)
      setPreviewErr(e instanceof Error ? e.message : 'Prompt preview failed')
    } finally {
      setPreviewBusy(false)
    }
  }

  async function onBackfill() {
    setBackfillBusy(true)
    setBackfillErr(null)
    try {
      const res = await backfillDeliveries(limit, maxAge)
      setBackfillResult(JSON.stringify(res, null, 2))
    } catch (e: unknown) {
      setBackfillResult(null)
      setBackfillErr(e instanceof Error ? e.message : 'Backfill failed')
    } finally {
      setBackfillBusy(false)
    }
  }

  return (
    <div className="space-y-8 max-w-3xl">
      <h1 className="text-xl font-semibold">Ops &amp; diagnostics</h1>

      <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-medium">Prompt preview</h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Session ID
            <input value={sessionId} onChange={(e) => setSessionId(e.target.value)} className="mt-1 block w-72 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-sm">
            Tier
            <select value={tier} onChange={(e) => setTier(e.target.value as 'preview' | 'final')} className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm">
              <option value="preview">preview</option>
              <option value="final">final</option>
            </select>
          </label>
          <button onClick={onPreview} disabled={previewBusy || !sessionId} className="rounded bg-gray-900 text-white px-4 py-2 text-sm disabled:opacity-50">
            {previewBusy ? 'Loading…' : 'Preview prompt'}
          </button>
        </div>
        {previewErr && <ErrorBanner message={previewErr} />}
        {preview && (
          <div className="space-y-2 text-sm">
            <div className="text-gray-600">
              {preview.provider} · {preview.model ?? 'unknown model'} · asset: {preview.has_uploaded_asset ? 'yes' : 'no'}
            </div>
            <pre className="whitespace-pre-wrap rounded bg-gray-900 text-gray-100 p-3 text-xs">{preview.prompt}</pre>
          </div>
        )}
      </section>

      <section className="space-y-3 rounded-lg border border-gray-200 bg-white p-4">
        <h2 className="font-medium">Delivery backfill</h2>
        <p className="text-sm text-gray-600">Retries verified-but-undelivered previews. This sends real emails.</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            Limit
            <input type="number" value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="mt-1 block w-24 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <label className="text-sm">
            Max age (hours)
            <input type="number" value={maxAge} onChange={(e) => setMaxAge(Number(e.target.value))} className="mt-1 block w-28 rounded border border-gray-300 px-2 py-1 text-sm" />
          </label>
          <button onClick={onBackfill} disabled={backfillBusy} className="rounded bg-gray-900 text-white px-4 py-2 text-sm disabled:opacity-50">
            {backfillBusy ? 'Running…' : 'Run backfill'}
          </button>
        </div>
        {backfillErr && <ErrorBanner message={backfillErr} />}
        {backfillResult && <pre className="whitespace-pre-wrap rounded bg-gray-50 border border-gray-200 p-3 text-xs">{backfillResult}</pre>}
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminOps.test.tsx`
Expected: PASS.

- [ ] **Step 5: Full suite + type-check + build**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all tests pass (existing 65 + new admin tests), no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/OpsView.tsx frontend/src/__tests__/adminOps.test.tsx
git commit -m "feat(admin): ops view — prompt preview + delivery backfill"
```

---

## Task 8: Documentation + infra follow-up

**Files:**
- Modify: `CLAUDE.md` (§13 "Current implementation state" — note the admin panel)
- Create: `docs/superpowers/plans/2026-07-02-admin-panel-INFRA-NOTE.md` (SPA fallback follow-up for Infra owner)

**Interfaces:** none (docs only).

- [ ] **Step 1: Append admin panel note to `CLAUDE.md` §13**

Add a bullet under "Current implementation state":

```markdown
- **Admin panel** (`frontend/src/admin/`, route `/admin/*`): internal UI over the existing `/admin/*` endpoints — approval queue (review/approve/reject), quote requests, store onboarding + catalogue sync, and ops (prompt-preview + delivery backfill). Auth: paste `X-Admin-Secret` at `/admin/login` (validated against `GET /admin/stores`, held in `sessionStorage`). No backend changes. **Infra TODO:** production static host must serve `index.html` for `/admin/*` deep links (SPA fallback).
```

- [ ] **Step 2: Write the infra follow-up note**

```markdown
# Infra follow-up: SPA fallback for /admin/* deep links

The admin panel uses client-side routing (`react-router-dom`). A hard refresh at
a deep link (e.g. `/admin/stores`) requires the static host serving the built
frontend to return `index.html` rather than 404.

- **Vite dev**: handled automatically — no action.
- **Production (Railway frontend service)**: add a catch-all rewrite to
  `index.html`. If served via `vite preview`/a static server, configure the
  SPA fallback there. Confirm with the Infra owner before the panel is used in
  production.

Not required for local development or for the tests in this plan.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-07-02-admin-panel-INFRA-NOTE.md
git commit -m "docs(admin): note admin panel + SPA fallback infra follow-up"
```

---

## Self-Review Notes

- **Spec coverage:** §3 endpoints → Tasks 1/4/5/6/7; §4.1 file layout → Tasks 1–3 + views; §4.2 entry point → Task 2 Step 8; §4.3 auth flow → Tasks 1–2; §4.4 adminApi → Task 1; §5 per-view behaviour → Tasks 4–7; §6 error handling → Task 1 (logout on 401/403) + per-view ErrorBanner; §7 infra note → Task 8; §8 testing → each task's test file. All covered.
- **Type consistency:** `adminApi` function names/types defined in Task 1 are consumed verbatim in Tasks 4–7 (`listSubmissions`, `updateSubmission({ review_status, reviewer_notes })`, `syncStore` → `SyncResult{fetched,imported,skipped}`, `promptPreview(sessionId, tier)`, `backfillDeliveries(limit, maxAgeHours)`). `Column<T>`/`DataTable<T>` signature from Task 3 matches all view usages.
- **No placeholders:** every code step contains full implementations; the one deliberate scaffold (view stubs in Task 2) is explicit and replaced in Tasks 4–7.
```
