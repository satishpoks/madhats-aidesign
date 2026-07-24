# SDD progress — admin login + per-store access

Plan: docs/superpowers/plans/2026-07-24-admin-login-per-store-access.md
Spec: docs/superpowers/specs/2026-07-24-admin-login-per-store-access-design.md
Branch: feat/admin-login-per-store
Base (before Task 1): f6f8d22

Tasks:
- T1: migration admin_users + admin_user_stores
- T2: config ADMIN_JWT_SECRET
- T3: service admin_auth (PBKDF2 + JWT)
- T4: service admin_users (DB CRUD)
- T5: deps AdminContext + require_admin_ctx/require_super/assert_store_allowed
- T6: routes /admin/auth/{login,me,change-password}
- T7: routes /admin/users CRUD (super-only)
- T8: enforcement store routes
- T9: enforcement cross-store list routes + diagnostics super-only
- T10: enforcement scoped config routes + settings/backfill super-only
- T11: frontend adminStore + adminApi (bearer/secret + auth endpoints)
- T12: frontend AdminLogin (email/password + secret link)
- T13: frontend profile hydration + nav gating
- T14: frontend Users view + change-password view
- T15: frontend store pickers on operational views

## Progress
Task 1: complete (commits f6f8d22..53120b6, review clean, migration applied). No issues.

Task 2 base (before dispatch): 53120b6
Task 2: complete (commits 53120b6..8cc7b6d, review clean). No issues.

Task 3 base (before dispatch): 8cc7b6d
Task 3: complete (commits 8cc7b6d..918a9de, review Approved). MINOR (final review):
  test suite never exercises the JWT expiry branch directly (relies on PyJWT).

Task 4 base (before dispatch): 918a9de
Task 4: complete (commits 918a9de..479636a, review Approved). All findings Minor +
  brief-inherited: (a) _set_stores delete+N-insert non-transactional (partial reassign
  on mid-loop error); (b) _stores_for fetches whole stores table, filters in Python
  (scale); (c) update_user on missing id returns placeholder dict not None — mitigated
  by Task 7's get_by_id 404 guard; (d) list_users untested.

Task 5 base (before dispatch): 479636a
Task 5: complete (commits 479636a..ec02736, review Approved, full suite 930). Both
  security risks verified false (fail-closed to 401; secret compare constant-time,
  empty-secret short-circuits). MINOR: extra DB read per non-super request (by design).

Task 6 base (before dispatch): ec02736
Task 6: complete (commits ec02736..f365e37, review Approved after 1 fix loop, suite 936).
  Fix closed Important: login timing side-channel (unknown-email path skipped PBKDF2) —
  now verifies against a module-level dummy hash on not-found/disabled path. MINOR:
  password_hash "" fallback relies on verify_password rejecting malformed (safe today).

Task 7 base (before dispatch): f365e37
Task 7: complete (commits f365e37..e1a9722, review Approved, suite 939). All four
  /admin/users routes super-gated via _require_super_dep; 409 dup-email, 404 missing-id.

Task 8 base (before dispatch): e1a9722
Task 8: complete (commits e1a9722..8e95c7d, review Approved, suite 941). All store-
  touching routes guarded; create super-only; list filtered. Collateral (legit): migrated
  branding+logo test fixtures from override[require_admin] → require_admin_ctx (super ctx),
  assertions unchanged — confirmed not diluted. MINOR: only 2 new scoping tests (brief's);
  sync/update/logo assert + list filter covered by source inspection, not tests.

Task 9 base (before dispatch): 8e95c7d
Task 9: complete (commits 8e95c7d..9d6b4d6, review Approved after 1 fix loop, suite 948).
  Fix closed a CRITICAL cross-store leak the PLAN MISSED: GET /admin/generation-logs/{id}
  (get_generation_log) was unscoped — now asserts the row's session store (fail-closed).
  Also fixed Important: list_generations filtered after .limit() (page starvation) → now
  scopes to allowed sessions before limit. Added 5 genuine filter regression tests.
  MINOR (final review): allowed-session lookup unbounded (pre-existing pattern); redundant
  double require_admin_ctx dep (FastAPI caches, inert).
  NOTE FOR FINAL REVIEW: sweep remaining per-item admin read/write routes for unscoped
  access (reviewer flagged submissions.update_submission + others are auth-only by design).

Task 10 base (before dispatch): 9d6b4d6
Task 10: complete (commits 9d6b4d6..feadd2c, review Approved, suite 950). All 15 routes
  across 6 files verified scoped (hat-types/graphics/decoration-types assert_store_allowed;
  settings/backfill super-only; prompt-preview session-store scoped). Retargeted
  test_graphics_routes fixture (adapted, not diluted). No issues.

=== BACKEND COMPLETE (T1-T10), 950 tests passing ===

Task 11 base (before dispatch): feadd2c
Task 11: complete (commits feadd2c..1e1e967, review Approved, adminAuth 2/2 + adminApi 5/5).
  bearer/secret credential + Profile + auth/user API; all 3 multipart helpers use authHeaders;
  adminApi.test updated not gutted. DISCOVERY: pre-existing frontend/src/__tests__/adminAuth.test.tsx
  (.tsx, distinct from new .ts) tests OLD AdminLogin API → 1 failing test; route to Task 12.
  tsc clean except expected AdminLogin.tsx errors (Task 12).

Task 12 base (before dispatch): 1e1e967
Task 12: complete (commits 1e1e967..8588fec, review Approved + 1 test-coverage fix loop,
  AdminLogin 4/4 + adminAuth.test.tsx 2/2). Email/pw login + secret toggle. Justified copy
  tweak (toggle="Use admin secret instead" to avoid /sign in/i query collision). Rewrote stale
  adminAuth.test.tsx preserving RequireAuth coverage + fixed a real infinite-loop hang. Fix added
  3 tests: secret-mode-failure→no-half-authed, email-error→logout, disabled-until-filled.
  MINOR (final): toggling modes doesn't clear the other mode's field (no functional impact).

NOTE: executing Task 14 BEFORE Task 13 — T13's AdminApp imports T14's UsersView/
ChangePasswordView, so T14 must land first to avoid a broken import.

Task 14 base (before dispatch): 8588fec
Task 14: complete (commits 8588fec..3e3a31b, review Approved after 1 fix loop, UsersView 2/2).
  UsersView (list/create/enable-disable/delete + multi-select store assign) + ChangePasswordView.
  Fix closed Important: showed store SLUG not name on checkboxes (UX regression) → restored name,
  disambiguated test via within(); + password field type=password; + clear storeIds on super toggle.
  NOT yet wired into AdminApp/nav (Task 13 does that).

Task 13 base (before dispatch): 3e3a31b
Task 13: complete (commits 3e3a31b..adaaf28, review Approved, AdminLayout 2/2, tsc clean).
  Profile hydration (fetchMe on stored-cred+null-profile, logout on fail, no loop) + nav gating
  (Users/Stores/Diagnostics/Ops/Settings superOnly) + Users/change-password routes wired. All 15
  existing routes preserved. No issues.

Task 15 base (before dispatch): adaaf28
Task 15: complete (commits adaaf28..97beb76, review Approved + 1 UX fix loop, StorePicker 2/2,
  src/admin subset 50 tests, tsc clean). StorePicker (options from profile.stores; All-stores
  super+allowAll only). LeadsView threads real storeId into listSessions. Fix closed Important:
  removed misleading affordance-only pickers from QuoteRequests/Submissions (rows carry no
  store_id; backend already auto-scopes). MINOR (final): StorePicker null-profile path only
  indirectly tested.

=== ALL 15 TASKS COMPLETE (backend 950 tests, frontend admin subset green, tsc clean) ===
Base before Task 1: f6f8d22 → HEAD: 97beb76
FINAL WHOLE-BRANCH REVIEW (opus): swept entire /admin surface. Found ONE Important
cross-store WRITE hole the plan missed: PATCH /admin/submissions/{id} was auth-only
(IDOR — store admin could approve/reject another store's submission). FIXED
(commits 97beb76..25a264f): assert_store_allowed on the submission's session store,
fail-closed; 3 real regression tests (403 cross-store + updated==[], 200 own-store,
200 super bypass). Full suite 953. Re-review Approved. Verdict now: READY TO MERGE.

REMAINING = all Minor/ticket (none blocking):
- JWT not revoked on password change (disable IS immediate) — ticket.
- 403 forces full logout in adminApi (super-only route by URL logs a store admin out) — UX ticket.
- unbounded allowed-session lookups / filter-in-Python (scale) — ticket.
- redundant double require_admin_ctx dep on some routers (FastAPI caches, inert) — cosmetic.
- test gaps: JWT-expiry branch, list_users, update_user-missing-id (mitigated by 404) — ticket.
- _set_stores non-transactional (delete+insert) — ticket.
- login mode toggle doesn't clear other field — no functional impact.
- DEPLOY: apply migrations 20260724000001/2/3 (none startup-applied).

=== FEATURE COMPLETE — READY TO MERGE (HEAD 25a264f, backend 953 passing) ===

Minor findings rolled up for final-review triage:
- T3: JWT expiry branch not directly tested.
- T4: _set_stores non-transactional; _stores_for fetches whole stores table; update_user on
  missing id returns placeholder (mitigated by T7 404 guard); list_users untested.
- T5/T9: redundant double require_admin_ctx dep (FastAPI caches, inert).
- T6: password_hash "" fallback relies on verify_password rejecting malformed (safe).
- T9: allowed-session lookup unbounded (pre-existing pattern). NOTE: sweep remaining per-item
  admin routes for unscoped access (reviewer flagged submissions.update_submission auth-only).
- T12: toggling login modes doesn't clear the other mode's field (no functional impact).
- T14: create-user password field type addressed; ok.
- T15: StorePicker null-profile only indirectly tested.
