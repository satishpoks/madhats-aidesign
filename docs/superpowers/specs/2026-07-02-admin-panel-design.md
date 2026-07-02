# Admin Panel — Design

**Date:** 2026-07-02
**Status:** Approved (design phase)

---

## 1. Problem & Goal

The backend already exposes a full set of admin/ops endpoints (all gated by the
`X-Admin-Secret` header), but there is **no UI** for them — ops today would have
to hit the API by hand (curl / Swagger). We want a single admin panel, served
from the existing frontend app, that lets the MadHats team:

1. Review and approve/reject submitted design concepts (approval queue).
2. See customers who confirmed a quote request.
3. Onboard and manage stores (tenants) and trigger Shopify catalogue sync.
4. Run ops/diagnostics: preview the exact Gemini prompt for a session, and
   trigger the delivery backfill/retry sweep.

The panel is internal-only, distinct from the customer-facing Ricardo chatbot.

---

## 2. Decisions (locked)

| # | Decision |
|---|----------|
| App structure | **Route in the existing frontend** (`frontend/src/admin/`). Shares build + Railway service with the customer widget. |
| Routing | **`react-router-dom`** with per-tab URLs (`/admin/submissions`, `/admin/quote-requests`, `/admin/stores`, `/admin/ops`) + a `/admin/submissions/:id` detail route and `/admin/login`. |
| Auth | **Secret entry + `sessionStorage`.** Admin pastes `X-Admin-Secret`; validated by a live `GET /admin/stores` call; stored in `sessionStorage`; attached to all admin requests. Cleared on tab close or on any 401/403. |
| Backend changes | **None.** All five endpoint groups already exist; secret validation reuses `GET /admin/stores`. |
| Feature scope | Approval queue, Quote requests, Store management, Ops/diagnostics. |
| Styling | Tailwind, clean utilitarian dashboard (sidebar + content), light theme — deliberately distinct from the chat UI. |

---

## 3. Backend Endpoints Consumed (existing)

| Endpoint | Method | Used by |
|---|---|---|
| `/admin/stores` | GET | Store list **+ secret validation on login** |
| `/admin/stores` | POST | Create store |
| `/admin/stores/{id}/sync` | POST | Sync catalogue |
| `/admin/submissions` | GET | Approval queue list |
| `/admin/submissions/{id}` | PATCH | Approve/reject + reviewer notes |
| `/admin/quote-requests` | GET | Quote requests list |
| `/admin/prompt-preview/{session_id}?tier=` | GET | Ops: prompt preview |
| `/admin/deliveries/backfill?limit=&max_age_hours=` | POST | Ops: delivery backfill |

All require header `X-Admin-Secret`. None require `X-Store-Key`.

---

## 4. Architecture

### 4.1 File layout

```
frontend/src/admin/
  AdminApp.tsx           BrowserRouter-scoped routes + auth guard
  AdminLayout.tsx        sidebar (NavLink) + <Outlet>
  AdminLogin.tsx         secret entry + validation
  RequireAuth.tsx        guard: redirect to /admin/login when not authed
  adminStore.ts          zustand: secret (sessionStorage), authed, logout()
  adminApi.ts            fetch helper w/ X-Admin-Secret + ApiError
  components/
    DataTable.tsx        thin reusable table (columns + rows + empty/loading)
    ErrorBanner.tsx      inline error display
    StatusBadge.tsx      pill for submission/store status
  views/
    SubmissionsView.tsx      list + status filter
    SubmissionDetailView.tsx concept images, customer, approve/reject + notes
    QuoteRequestsView.tsx    confirmed-quote table
    StoresView.tsx           list + create form + per-row sync
    OpsView.tsx              prompt-preview + delivery backfill panels
```

### 4.2 Entry point

`App.tsx`, before the existing session/studio logic:

```tsx
if (window.location.pathname.startsWith('/admin')) {
  return <AdminApp />
}
```

`AdminApp` renders a `<BrowserRouter>` with routes:

```
/admin              → <Navigate to="/admin/submissions" replace />
/admin/login        → <AdminLogin />
/admin/*            → <RequireAuth><AdminLayout/></RequireAuth> with child routes:
    submissions           → <SubmissionsView />
    submissions/:id       → <SubmissionDetailView />
    quote-requests        → <QuoteRequestsView />
    stores                → <StoresView />
    ops                   → <OpsView />
```

### 4.3 Auth flow

- `adminStore` (zustand) holds `secret: string | null` and `authed: boolean`,
  hydrated from `sessionStorage` on init.
- `AdminLogin`: on submit, call `validateSecret(secret)` → `GET /admin/stores`
  with the entered secret. On 200: persist secret to `sessionStorage`, set
  `authed = true`, redirect to the page the user came from (or
  `/admin/submissions`). On 401/403: show "invalid secret". On other errors:
  show a generic error, do not store.
- `RequireAuth`: if `!authed`, `<Navigate to="/admin/login" state={{ from }} />`.
- `adminApi` throws `ApiError`; a shared response interceptor calls
  `adminStore.logout()` (clears secret + sessionStorage) on 401/403, so an
  expired/rotated secret bounces the user back to login.

### 4.4 adminApi

Mirrors `lib/api.ts` `request<T>` but:
- Reads the secret from `adminStore.getState().secret`; throws early if absent.
- Sets `X-Admin-Secret` (never `X-Store-Key`).
- On 401/403 → `adminStore.getState().logout()` then throw `ApiError`.
- Typed functions: `listStores`, `createStore`, `syncStore`, `listSubmissions`,
  `updateSubmission`, `listQuoteRequests`, `promptPreview`, `backfillDeliveries`.

---

## 5. Per-View Behaviour

Each view fetches on mount via `adminApi`, holds local `loading / error / data`
state (`useState` + `useEffect`), and renders `ErrorBanner` on failure.

### 5.1 SubmissionsView + SubmissionDetailView
- List: columns = status (badge), product, customer name, created_at; a status
  filter (all / pending / approved / rejected). Row click → `/admin/submissions/:id`.
- Detail: renders `final_image_urls` as images, plus `source_ref`, `customer`,
  `session_id`, `review_status`, existing `reviewer_notes`. A reviewer-notes
  textarea + **Approve** / **Reject** buttons → `PATCH /admin/submissions/{id}`
  with `{ review_status, reviewer_notes }`; on success return to the list.

### 5.2 QuoteRequestsView
- Table from `GET /admin/quote-requests`: name, email, phone, `notify_by_phone`
  (badge), product, decoration_type, placement_zone, quantity, quote_note,
  quote_confirmed_at. Read-only. Optional link to the session share token.

### 5.3 StoresView
- Table: slug, name, publishable key (with a copy-to-clipboard button),
  shopify_domain, status (badge), created_at.
- Create-store form (fields per `CreateStoreRequest`: slug, name,
  shopify_domain, allowed_origins, persona_name, greeting_template,
  sales_notification_email, brand) → `POST /admin/stores`; on success prepend
  the new row and surface the generated `public_key`.
- Per-row **Sync catalogue** button → `POST /admin/stores/{id}/sync`; shows the
  returned counts (and disables while in flight).

### 5.4 OpsView
- **Prompt preview** panel: session-id input + tier select (preview/final) →
  `GET /admin/prompt-preview/{session_id}?tier=` → render provider, model,
  reference image URL, `has_uploaded_asset`, and the full prompt in a monospace
  block.
- **Delivery backfill** panel: `limit` + `max_age_hours` inputs + **Run
  backfill** button → `POST /admin/deliveries/backfill` → render the returned
  result object (counts). Confirm before running (it sends real emails).

---

## 6. Error Handling

- `adminApi` normalises failures into `ApiError(status, detail)` (same shape as
  `lib/api.ts`).
- 401/403 → force logout + redirect to `/admin/login`.
- Other errors → per-view `ErrorBanner` with the `detail` message and a retry
  affordance. No PII is logged to the console.

---

## 7. Infra Note (SPA fallback)

Client-side routing means a hard refresh at a deep link (e.g.
`/admin/stores`) must serve `index.html`. Vite dev does this automatically.
**The production static host serving the built frontend needs a catch-all
rewrite to `index.html`.** This must be confirmed/added for the Railway
frontend service; flagged for the Infra owner. (Does not block local dev.)

---

## 8. Testing (vitest, following existing `__tests__` patterns)

- `adminStore`: hydrates from `sessionStorage`; `logout()` clears it.
- `AdminLogin`: valid secret → stores secret + sets authed + redirects; invalid
  secret (mock 403) → error, nothing stored.
- `RequireAuth`: unauthed → redirects to `/admin/login`.
- `SubmissionsView` / `SubmissionDetailView`: renders rows from mocked
  `adminApi`; Approve issues the PATCH with notes.
- `StoresView`: renders rows; create-store form issues POST; sync button issues
  POST and shows counts.
- `QuoteRequestsView`: renders rows from mocked data.
- `OpsView`: prompt-preview fetch renders the prompt; backfill button issues POST.

`adminApi` is mocked in all view tests (no live network).

---

## 9. Out of Scope (YAGNI)

- Proper login endpoint / token exchange / multi-user admin accounts.
- Raw leads / generation-audit-log browser (can be a later addition).
- Dashboard summary tiles / analytics.
- Editing submissions beyond status + reviewer notes.
- SMS sending for quote follow-ups (backend already capture-only).
