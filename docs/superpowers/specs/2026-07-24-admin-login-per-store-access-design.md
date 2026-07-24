# Admin login + per-store access — Design

**Date:** 2026-07-24
**Status:** Approved (brainstorming)
**Author:** Satish Pokhrel (with Claude)

## Problem

Today the admin console is gated by a single shared secret. `require_admin`
(`backend/app/api/deps.py`) constant-time-compares the `X-Admin-Secret` header
against the env var `ADMIN_SECRET`; the frontend (`adminStore.ts`) keeps that
secret in `sessionStorage` and attaches it to every `/admin/*` call. There is
exactly one credential and it sees every store.

We need **named admin users** who each get access to **one or more assigned
stores**, while keeping the env secret as an all-powerful **super admin**.

## Goals

- Env `ADMIN_SECRET` remains the un-deletable **bootstrap super admin**.
- Named admin users log in with **email + password**; sessions are JWTs.
- Each admin user is assigned **1+ stores**; they can only see/manage those.
- `admin_users.is_super` grants named, revocable super admins on top of the env
  secret.
- Disabling or re-assigning a user takes effect **immediately** (per-request DB
  re-check), not just on token expiry.
- **Backward compatible:** the watchdog compose sidecar and quote-render, which
  send `X-Admin-Secret`, keep working unchanged.

## Non-goals (YAGNI)

Email invites; forced password change on first login; password-strength meter;
an audit log of admin actions; extra login rate-limiting beyond the existing
global limiter.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Credentials | Bespoke email + password, stored in our DB |
| Session | HS256 JWT, **12h** expiry |
| Password hashing | **stdlib PBKDF2-HMAC-SHA256** (no native-compiled dep — matters on the Windows dev host) |
| Scoping model | Selected-store context + allow-list check |
| Provisioning | Super admin sets the initial password (shared out-of-band) |
| First-login change | Optional (self-service), not forced |
| DB super admins | Allowed via `is_super` flag; env secret is the bootstrap |
| Revocation | Immediate — verify JWT sig/exp, then re-load user row + assignments per request |

## Data model

One migration, `backend/supabase/migrations/20260724000003_admin_users.sql`
(next after the two unapplied `20260724000001/2` — note those must be applied
too; see Risks).

```sql
create table if not exists admin_users (
  id            uuid primary key default gen_random_uuid(),
  email         text not null,
  password_hash text not null,          -- pbkdf2_sha256$iterations$salt_b64$hash_b64
  is_super      boolean not null default false,
  status        text not null default 'active',   -- active | disabled
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index if not exists idx_admin_users_email on admin_users (lower(email));

create table if not exists admin_user_stores (
  admin_user_id uuid not null references admin_users(id) on delete cascade,
  store_id      uuid not null references stores(id) on delete cascade,
  primary key (admin_user_id, store_id)
);
create index if not exists idx_admin_user_stores_store on admin_user_stores (store_id);
```

No seed row: the env `ADMIN_SECRET` super admin creates the first `admin_users`
record via the Users view.

## Auth mechanism

### Password hashing (`services/admin_auth.py`)
`hash_password(pw) -> "pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>"` using
`hashlib.pbkdf2_hmac("sha256", pw, salt, iterations)` with a per-user random
salt and a high iteration count (e.g. 600_000). `verify_password(pw, stored)`
parses the record and constant-time-compares. Pure stdlib, no new dependency.

### Token
`POST /admin/auth/login { email, password }`:
1. Look up `admin_users` by `lower(email)`, `status = 'active'`.
2. `verify_password`; on failure return a generic 401 (no user-enumeration).
3. Issue HS256 JWT signed with `settings.admin_jwt_secret` (new env var,
   **defaults to `ADMIN_SECRET`** so it works with zero new config). Claims:
   `sub` = user id, `iat`, `exp` = iat + 12h. Deliberately minimal — stores and
   super status are **not** baked in.
4. Return `{ token, profile }` (see Endpoints for `profile` shape).

### Per-request authentication (`require_admin_ctx`)
Resolves an `AdminContext`:

```python
@dataclass
class AdminContext:
    user_id: str | None          # None for the env-secret super
    email: str | None
    is_super: bool
    allowed_store_ids: set[str] | None   # None == all stores (super)
```

- If `X-Admin-Secret` matches `ADMIN_SECRET` → `AdminContext(is_super=True,
  allowed_store_ids=None)`. Stateless; no DB read.
- Else if `Authorization: Bearer <jwt>` present → verify sig + exp, then
  **re-load** the `admin_users` row by `sub`:
  - row missing or `status != 'active'` → 401.
  - `is_super = row.is_super`; `allowed_store_ids` = fresh set from
    `admin_user_stores` (None if `is_super`).
- Neither present / invalid → 401.

This per-request DB re-check is what makes disable/re-assign immediate.

### Authorization helpers
```python
def require_super(ctx) -> None:            # 403 unless ctx.is_super
def assert_store_allowed(ctx, store_id):   # 403 unless super or store_id in allowed
```

## Enforcement — route rules

- **Store-touching routes** resolve the target store id (path param on
  `/admin/stores/{id}` + logo + branding; `X-Store-Key` → `resolve_store` on
  hat-types / graphics / decoration-types; `store_id` query where present) and
  call `assert_store_allowed(ctx, store_id)`.
- **Cross-store list routes** (`/admin/sessions`, `/admin/generations`,
  `/admin/generation-logs`, `/admin/leads`, `/admin/quote-requests`,
  `/admin/submissions`): super → unfiltered (today's behaviour preserved);
  store admin → force `store_id IN allowed_store_ids` in the query. No data
  leakage across stores.
- **`GET /admin/stores`** returns only assigned stores for a store admin, all
  for super. This alone constrains every store dropdown in the UI.
- **Super-only** (`require_super`): `POST /admin/stores` (create),
  `/admin/users/*`, global `GET /admin/diagnostics`,
  `POST /admin/deliveries/backfill`, `POST /admin/generations/reap-stuck`. The
  watchdog authenticates with the env secret (super), so self-heal is
  unaffected.

**Minimal churn:** `require_admin` is kept as a thin wrapper over
`require_admin_ctx` (discards the context) so the ~15 admin routers keep their
`dependencies=[Depends(require_admin)]` authentication unchanged. Only routes
that need scoping add a `ctx: AdminContext = Depends(require_admin_ctx)`
parameter (FastAPI caches the dependency per request, so declaring it at both
router and param level is free) and call the helpers.

## Endpoints

```
POST   /admin/auth/login            { email, password } -> { token, profile }
GET    /admin/auth/me               -> profile          (Bearer or X-Admin-Secret)
POST   /admin/auth/change-password  { current_password, new_password } -> { ok: true }

# super-only
GET    /admin/users                 -> [ { id, email, is_super, status, stores:[{id,name}] } ]
POST   /admin/users                 { email, password, is_super?, store_ids[] } -> user
PATCH  /admin/users/{id}            { is_super?, status?, store_ids?, password? } -> user
DELETE /admin/users/{id}            -> { deleted: true }
```

`profile = { email: str | null, is_super: bool, stores: [{ id, name, public_key }] }`
(for the env super, `email` is null and `stores` is the full list).
`GET /admin/auth/me` hydrates the frontend on reload and validates the stored
token. No admin email in structlog/Sentry — log `sub`/user id only, consistent
with the existing no-PII rule.

`change-password` operates on the authenticated user (`ctx.user_id`); the
env-secret super has no row, so it returns 400 ("env super admin has no
password").

## Frontend

- **`adminStore.ts`** holds `{ kind: 'bearer' | 'secret', credential: string,
  profile: Profile | null }` in `sessionStorage`. `adminApi.request` sends
  `Authorization: Bearer <credential>` when `kind==='bearer'`, else
  `X-Admin-Secret: <credential>`; 401/403 still triggers `logout()`.
- **`AdminLogin`**: email + password form → `POST /admin/auth/login`, stores
  `{kind:'bearer', token, profile}`. A small "Sign in with admin secret" link
  reveals the existing secret field → validates via `/admin/auth/me`, stores
  `{kind:'secret', ...}`.
- **App load:** if a credential is stored, call `/admin/auth/me` to re-hydrate
  `profile` and confirm validity (logout on failure).
- **New Users view** (`/admin/users`, super-only): table of admin users;
  create/edit modal with email, password (create + reset), `is_super` toggle,
  `status` toggle, and a **multi-select store assignment** (checkbox list fed by
  `/admin/stores`). Inline-confirm delete, matching existing view conventions.
- **Store pickers** already read `/admin/stores`, so they auto-limit to assigned
  stores. Add a picker to the operational views that lack one (Leads, Quote
  requests, Submissions); super admin gets an "All stores" default there.
- **Nav gating:** hide **Users**, **Stores** (create), **Diagnostics**, **Ops**
  for non-super (`profile.is_super === false`).
- Optional self-service **Change password** screen (not forced).

## Config

New env var `ADMIN_JWT_SECRET` (documented in `.env.example`), defaulting to
`ADMIN_SECRET` when unset so existing deployments need no change.

## Testing

**Backend**
- `admin_auth`: hash/verify round-trip; verify rejects tampered records.
- Login: success returns token+profile; wrong password → 401; disabled user →
  401; unknown email → 401 (generic).
- Token: valid Bearer authenticates; expired token → 401; garbage → 401;
  `X-Admin-Secret` still authenticates as super.
- Enforcement: store admin hitting an unassigned store (path/X-Store-Key/query)
  → 403; super bypass; `GET /admin/stores` filtered to assignments; a
  cross-store list is filtered for a store admin; `require_super` routes 403 for
  store admins.
- `change-password`: success, wrong current → 400, env super → 400.
- Users CRUD: create/list/patch(reassign stores, toggle super/status)/delete;
  re-assignment reflected on the user's next request (immediate revocation).

**Frontend**
- `AdminLogin` both modes; `adminStore` bearer vs secret plumbing + persistence;
  `adminApi` sends the right header and logs out on 401.
- `RequireAuth` redirect; nav gating by `is_super`; Users view CRUD +
  store-assignment multi-select; store-picker limited to `profile.stores`.

## Risks / notes

- **Unapplied migrations:** `20260724000001_leads_reference_code.sql` and
  `20260724000002_generation_render_notes.sql` are already unapplied on this
  branch. This new migration is additive and independent, but the stack must
  have all pending migrations applied before deploy.
- `ADMIN_JWT_SECRET` defaulting to `ADMIN_SECRET` means rotating `ADMIN_SECRET`
  invalidates outstanding admin JWTs (acceptable — 12h tokens, re-login).
- Per-request DB re-check adds one small query per admin request; the admin
  console is low-traffic, so this is negligible and buys immediate revocation.
- The env-secret super has no `admin_users` row, so it can't change its own
  password (by design — that's an ops/env action).
```
