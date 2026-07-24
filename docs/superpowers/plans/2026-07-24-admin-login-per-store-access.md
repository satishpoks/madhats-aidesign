# Admin login + per-store access — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single shared admin secret with named admin-user logins (email + password) that each have access to one or more assigned stores, while keeping the env `ADMIN_SECRET` as an all-powerful super admin.

**Architecture:** A new `admin_users` + `admin_user_stores` schema backs bespoke email/password auth. Login issues a 12h HS256 JWT; every admin request either presents that JWT (Bearer) or the env secret (`X-Admin-Secret`). A per-request `AdminContext` re-loads the user's status + assigned stores from the DB (immediate revocation), and route-level helpers (`assert_store_allowed`, `require_super`) enforce per-store scoping. The frontend gains a real email/password login, a super-only Users view, and store pickers limited to assigned stores.

**Tech Stack:** FastAPI, Supabase (supabase-py), PyJWT (already a dep), stdlib `hashlib.pbkdf2_hmac`, React 18 / Zustand / react-router-dom, Vitest.

## Global Constraints

- Python 3.12 / FastAPI backend; React 18 / Vite / Zustand frontend.
- No new backend dependency: password hashing uses stdlib `hashlib.pbkdf2_hmac` (PBKDF2-HMAC-SHA256). PyJWT is already in `pyproject.toml`.
- No secrets in code — all via env vars in `app/config.py` (`pydantic-settings`).
- No PII in logs/Sentry: never log an admin user's email; log the user id (`sub`) only.
- DB access via supabase-py service-role client (`app.db.get_supabase`); SQL migrations only (no SQLAlchemy/Alembic), in `backend/supabase/migrations/`.
- Backward compatibility is mandatory: `X-Admin-Secret: <ADMIN_SECRET>` must keep authenticating as super admin (the watchdog sidecar + quote-render depend on it).
- Password hash record format (verbatim): `pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>`, iterations = `600000`.
- JWT: HS256, signed with `settings.admin_jwt_secret` (defaults to `settings.admin_secret`), claims `sub`/`iat`/`exp`, expiry = 12h.
- Run backend tests with `CANVAS_ORCHESTRATOR_V2=false` (repo-root `.env` defaults it to true, which flips 3 unrelated tests). On this Windows host: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`.
- Frontend tests: `cd frontend && npx vitest run <path>` (never `npm test` — it watches/hangs).

---

## File Structure

**Backend — new**
- `backend/supabase/migrations/20260724000003_admin_users.sql` — schema.
- `backend/app/services/admin_auth.py` — password hashing + JWT encode/decode (pure, no DB).
- `backend/app/services/admin_users.py` — admin_users + admin_user_stores DB access.
- `backend/app/api/routes/admin_auth.py` — `/admin/auth/{login,me,change-password}`.
- `backend/app/api/routes/admin_users.py` — super-only `/admin/users` CRUD.
- Tests: `backend/tests/test_admin_auth_service.py`, `test_admin_users_service.py`, `test_admin_auth_routes.py`, `test_admin_users_routes.py`, `test_admin_context_enforcement.py`.

**Backend — modified**
- `backend/app/config.py` — add `admin_jwt_secret`.
- `backend/app/api/deps.py` — `AdminContext`, `require_admin_ctx`, `require_super`, `assert_store_allowed`; keep `require_admin`.
- `backend/app/api/routes/admin_stores.py`, `admin_leads.py`, `admin_diagnostics.py`, `admin_hat_types.py`, `admin_graphics.py`, `admin_decoration_types.py`, `admin_settings.py`, `admin_generations.py`, `admin_deliveries.py`, `admin_prompt.py`, `submissions.py` — enforcement wiring.
- `backend/app/main.py` — register the two new routers.
- `.env.example` — document `ADMIN_JWT_SECRET`.

**Frontend — new**
- `frontend/src/admin/views/UsersView.tsx` — super-only user management.
- `frontend/src/admin/views/ChangePasswordView.tsx` — self-service.
- `frontend/src/admin/StorePicker.tsx` — shared assigned-store picker.
- Tests alongside each (`*.test.tsx`), plus `frontend/src/__tests__/adminAuth.test.ts`.

**Frontend — modified**
- `frontend/src/admin/adminStore.ts` — bearer/secret credential + profile.
- `frontend/src/admin/adminApi.ts` — header logic + auth/user endpoints.
- `frontend/src/admin/AdminLogin.tsx` — email/password + secret link.
- `frontend/src/admin/AdminApp.tsx` — profile hydration, new routes.
- `frontend/src/admin/AdminLayout.tsx` — nav gating by `is_super`.

---

## Task 1: Migration — admin_users + admin_user_stores

**Files:**
- Create: `backend/supabase/migrations/20260724000003_admin_users.sql`

**Interfaces:**
- Produces: tables `admin_users (id, email, password_hash, is_super, status, created_at, updated_at)` and `admin_user_stores (admin_user_id, store_id)`.

- [ ] **Step 1: Write the migration**

```sql
-- Admin authentication + per-store authorization.
-- Named admin users log in with email + password; each is assigned 1+ stores.
-- The env ADMIN_SECRET remains the un-deletable bootstrap super admin (no row).

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

- [ ] **Step 2: Apply the migration locally**

Run: `cd backend && npx supabase db reset` (wipes + re-applies all migrations + seed)
Expected: completes without error; `admin_users` and `admin_user_stores` exist.

> If Docker/Supabase isn't running, skip this step — the migration is verified structurally and the service tests below use a fake DB. Note in the commit that it's unapplied.

- [ ] **Step 3: Commit**

```bash
git add backend/supabase/migrations/20260724000003_admin_users.sql
git commit -m "feat(admin-auth): add admin_users + admin_user_stores schema"
```

---

## Task 2: Config — ADMIN_JWT_SECRET

**Files:**
- Modify: `backend/app/config.py:52` (Security section)
- Modify: `.env.example`

**Interfaces:**
- Produces: `settings.admin_jwt_secret` (str), `settings.admin_jwt_ttl_seconds` (int).

- [ ] **Step 1: Add settings fields**

In `backend/app/config.py`, in the `# --- Security ---` block, after `admin_secret: str`:

```python
    # --- Security ---
    admin_secret: str
    # Signs admin-user login JWTs. Defaults to admin_secret so existing
    # deployments need no new config; set a distinct value to decouple them.
    admin_jwt_secret: str = ""
    admin_jwt_ttl_seconds: int = 43200  # 12h admin session
    rate_limit_rpm: int = 10
```

Then add a property near the other `@property` methods:

```python
    @property
    def admin_jwt_signing_key(self) -> str:
        """Key used to sign/verify admin JWTs — falls back to admin_secret."""
        return self.admin_jwt_secret or self.admin_secret
```

- [ ] **Step 2: Document it in .env.example**

Add under the security section of `.env.example`:

```
# Signs admin-user login sessions (JWT). Optional — defaults to ADMIN_SECRET.
ADMIN_JWT_SECRET=
```

- [ ] **Step 3: Verify import**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -c "from app.config import settings; print(settings.admin_jwt_signing_key[:0] == '')"`
Expected: prints `True` (no crash; property resolves).

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py .env.example
git commit -m "feat(admin-auth): add ADMIN_JWT_SECRET config with admin_secret fallback"
```

---

## Task 3: Service — password hashing + JWT (`admin_auth.py`)

**Files:**
- Create: `backend/app/services/admin_auth.py`
- Test: `backend/tests/test_admin_auth_service.py`

**Interfaces:**
- Produces:
  - `hash_password(password: str) -> str`
  - `verify_password(password: str, stored: str) -> bool`
  - `create_token(user_id: str) -> str`
  - `decode_token(token: str) -> str | None`  (returns the `sub` user id, or None if invalid/expired)

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_auth_service.py`:

```python
from __future__ import annotations

from app.services import admin_auth


def test_hash_then_verify_roundtrip():
    stored = admin_auth.hash_password("hunter2")
    assert stored.startswith("pbkdf2_sha256$600000$")
    assert admin_auth.verify_password("hunter2", stored) is True
    assert admin_auth.verify_password("wrong", stored) is False


def test_hash_is_salted_unique():
    assert admin_auth.hash_password("x") != admin_auth.hash_password("x")


def test_verify_rejects_malformed_record():
    assert admin_auth.verify_password("x", "not-a-real-record") is False
    assert admin_auth.verify_password("x", "") is False


def test_token_roundtrip():
    token = admin_auth.create_token("user-123")
    assert admin_auth.decode_token(token) == "user-123"


def test_decode_rejects_garbage_and_tampered():
    assert admin_auth.decode_token("garbage.token.here") is None
    good = admin_auth.create_token("u1")
    assert admin_auth.decode_token(good + "x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_auth_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.admin_auth'`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/admin_auth.py`:

```python
"""Admin-user auth primitives: PBKDF2 password hashing + HS256 JWT sessions.

Pure functions, no DB. Password records are stdlib PBKDF2-HMAC-SHA256 (no
native dependency). Tokens carry only the user id (`sub`); status and assigned
stores are re-loaded per request (see api/deps.py) for immediate revocation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 600_000
_JWT_ALG = "HS256"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters_s, salt_b64, hash_b64 = stored.split("$")
        if algo != _ALGO:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iters_s)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected)


def create_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.admin_jwt_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_signing_key, algorithm=_JWT_ALG)


def decode_token(token: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.admin_jwt_signing_key, algorithms=[_JWT_ALG])
    except jwt.InvalidTokenError:
        return None
    sub = payload.get("sub")
    return sub if isinstance(sub, str) else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_auth_service.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/admin_auth.py backend/tests/test_admin_auth_service.py
git commit -m "feat(admin-auth): PBKDF2 password hashing + JWT session helpers"
```

---

## Task 4: Service — admin_users DB access (`admin_users.py`)

**Files:**
- Create: `backend/app/services/admin_users.py`
- Test: `backend/tests/test_admin_users_service.py`

**Interfaces:**
- Consumes: `app.db.get_supabase`, `admin_auth.hash_password`.
- Produces:
  - `get_by_email(email: str) -> dict | None`
  - `get_by_id(user_id: str) -> dict | None`
  - `allowed_store_ids(user_id: str) -> set[str]`
  - `list_users() -> list[dict]`  (each: `{id, email, is_super, status, stores:[{id,name}]}`)
  - `create_user(email, password, is_super, store_ids) -> dict`
  - `update_user(user_id, *, is_super=None, status=None, password=None, store_ids=None) -> dict`
  - `delete_user(user_id) -> bool`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_users_service.py`:

```python
from __future__ import annotations

import pytest

from app.services import admin_users


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, db):
        self.table, self.db = table, db
        self._rows = list(db[table])
        self._pending = None

    def select(self, *a, **k):
        return self

    def insert(self, row):
        self._pending = ("insert", row)
        return self

    def update(self, patch):
        self._pending = ("update", patch)
        return self

    def delete(self):
        self._pending = ("delete", None)
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        self._eq = (field, value)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self._pending and self._pending[0] == "insert":
            row = dict(self._pending[1])
            row.setdefault("id", f"id-{len(self.db[self.table]) + 1}")
            self.db[self.table].append(row)
            return _Result([row])
        if self._pending and self._pending[0] == "update":
            for r in self._rows:
                r.update(self._pending[1])
            return _Result(self._rows)
        if self._pending and self._pending[0] == "delete":
            for r in list(self._rows):
                self.db[self.table].remove(r)
            return _Result(self._rows)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, db):
        self.db = db

    def table(self, name):
        self.db.setdefault(name, [])
        return _Query(name, self.db)


@pytest.fixture()
def fake_db(monkeypatch):
    db = {"admin_users": [], "admin_user_stores": []}
    monkeypatch.setattr(admin_users, "get_supabase", lambda: _FakeSB(db))
    return db


def test_create_and_get_by_email(fake_db):
    user = admin_users.create_user("Ops@x.com", "pw", is_super=False, store_ids=["s1", "s2"])
    assert user["is_super"] is False
    got = admin_users.get_by_email("ops@x.com")  # case-insensitive
    assert got is not None and got["id"] == user["id"]
    assert admin_users.allowed_store_ids(user["id"]) == {"s1", "s2"}


def test_update_reassigns_stores_and_password(fake_db):
    user = admin_users.create_user("a@x.com", "pw", is_super=False, store_ids=["s1"])
    admin_users.update_user(user["id"], store_ids=["s2", "s3"])
    assert admin_users.allowed_store_ids(user["id"]) == {"s2", "s3"}


def test_delete_user(fake_db):
    user = admin_users.create_user("a@x.com", "pw", is_super=False, store_ids=[])
    assert admin_users.delete_user(user["id"]) is True
    assert admin_users.get_by_id(user["id"]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_users_service.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.admin_users'`.

- [ ] **Step 3: Write the implementation**

`backend/app/services/admin_users.py`:

```python
"""admin_users + admin_user_stores data access.

The email lookup is case-insensitive (stored lowercased). Store assignments
live in the join table; `allowed_store_ids` is read fresh per admin request so
re-assignment/disable takes effect immediately.
"""
from __future__ import annotations

from app.db import get_supabase
from app.services.admin_auth import hash_password


def get_by_email(email: str) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("admin_users").select("*").eq("email", email.strip().lower())
        .limit(1).execute()
    )
    return res.data[0] if res.data else None


def get_by_id(user_id: str) -> dict | None:
    sb = get_supabase()
    res = sb.table("admin_users").select("*").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def allowed_store_ids(user_id: str) -> set[str]:
    sb = get_supabase()
    res = (
        sb.table("admin_user_stores").select("store_id")
        .eq("admin_user_id", user_id).execute()
    )
    return {r["store_id"] for r in (res.data or [])}


def _set_stores(user_id: str, store_ids: list[str]) -> None:
    sb = get_supabase()
    sb.table("admin_user_stores").delete().eq("admin_user_id", user_id).execute()
    for sid in store_ids:
        sb.table("admin_user_stores").insert(
            {"admin_user_id": user_id, "store_id": sid}
        ).execute()


def _stores_for(user_id: str) -> list[dict]:
    ids = allowed_store_ids(user_id)
    if not ids:
        return []
    sb = get_supabase()
    res = sb.table("stores").select("id, name").execute()
    return [{"id": r["id"], "name": r["name"]} for r in (res.data or []) if r["id"] in ids]


def _public(row: dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "is_super": row.get("is_super", False),
        "status": row.get("status", "active"),
        "stores": _stores_for(row["id"]),
    }


def list_users() -> list[dict]:
    sb = get_supabase()
    res = sb.table("admin_users").select("*").order("created_at").execute()
    return [_public(r) for r in (res.data or [])]


def create_user(email: str, password: str, is_super: bool, store_ids: list[str]) -> dict:
    sb = get_supabase()
    row = {
        "email": email.strip().lower(),
        "password_hash": hash_password(password),
        "is_super": is_super,
        "status": "active",
    }
    res = sb.table("admin_users").insert(row).execute()
    created = res.data[0]
    if store_ids:
        _set_stores(created["id"], store_ids)
    return _public(created)


def update_user(
    user_id: str,
    *,
    is_super: bool | None = None,
    status: str | None = None,
    password: str | None = None,
    store_ids: list[str] | None = None,
) -> dict:
    sb = get_supabase()
    patch: dict = {}
    if is_super is not None:
        patch["is_super"] = is_super
    if status is not None:
        patch["status"] = status
    if password is not None:
        patch["password_hash"] = hash_password(password)
    if patch:
        sb.table("admin_users").update(patch).eq("id", user_id).execute()
    if store_ids is not None:
        _set_stores(user_id, store_ids)
    return _public(get_by_id(user_id) or {"id": user_id, "email": "", "is_super": False, "status": "active"})


def delete_user(user_id: str) -> bool:
    sb = get_supabase()
    res = sb.table("admin_users").delete().eq("id", user_id).execute()
    return bool(res.data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_users_service.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/admin_users.py backend/tests/test_admin_users_service.py
git commit -m "feat(admin-auth): admin_users DB service (CRUD + store assignments)"
```

---

## Task 5: Deps — AdminContext + require_admin_ctx + guards

**Files:**
- Modify: `backend/app/api/deps.py`
- Test: `backend/tests/test_admin_context.py`

**Interfaces:**
- Consumes: `admin_auth.decode_token`, `admin_users.get_by_id`, `admin_users.allowed_store_ids`.
- Produces:
  - `class AdminContext` with `user_id: str | None`, `email: str | None`, `is_super: bool`, `allowed_store_ids: set[str] | None`.
  - `async require_admin_ctx(x_admin_secret, authorization) -> AdminContext`
  - `require_super(ctx: AdminContext) -> None`
  - `assert_store_allowed(ctx: AdminContext, store_id: str | None) -> None`
  - `require_admin` retained (thin wrapper, returns None).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_context.py`:

```python
from __future__ import annotations

import pytest

from app.api import deps
from app.config import settings
from app.services import admin_auth


@pytest.mark.asyncio
async def test_env_secret_is_super(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    ctx = await deps.require_admin_ctx(x_admin_secret="envsecret", authorization=None)
    assert ctx.is_super is True
    assert ctx.allowed_store_ids is None


@pytest.mark.asyncio
async def test_bearer_loads_user(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    monkeypatch.setattr(deps.admin_users, "get_by_id", lambda uid: {"id": uid, "email": "a@x.com", "is_super": False, "status": "active"})
    monkeypatch.setattr(deps.admin_users, "allowed_store_ids", lambda uid: {"s1"})
    token = admin_auth.create_token("u1")
    ctx = await deps.require_admin_ctx(x_admin_secret=None, authorization=f"Bearer {token}")
    assert ctx.is_super is False
    assert ctx.allowed_store_ids == {"s1"}


@pytest.mark.asyncio
async def test_disabled_user_rejected(monkeypatch):
    monkeypatch.setattr(deps.admin_users, "get_by_id", lambda uid: {"id": uid, "email": "a@x.com", "is_super": False, "status": "disabled"})
    token = admin_auth.create_token("u1")
    with pytest.raises(deps.HTTPException) as exc:
        await deps.require_admin_ctx(x_admin_secret=None, authorization=f"Bearer {token}")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_no_credentials_rejected(monkeypatch):
    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with pytest.raises(deps.HTTPException):
        await deps.require_admin_ctx(x_admin_secret=None, authorization=None)


def test_assert_store_allowed():
    superctx = deps.AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)
    deps.assert_store_allowed(superctx, "any")  # no raise
    scoped = deps.AdminContext(user_id="u1", email="a@x.com", is_super=False, allowed_store_ids={"s1"})
    deps.assert_store_allowed(scoped, "s1")  # no raise
    with pytest.raises(deps.HTTPException) as exc:
        deps.assert_store_allowed(scoped, "s2")
    assert exc.value.status_code == 403


def test_require_super():
    scoped = deps.AdminContext(user_id="u1", email="a@x.com", is_super=False, allowed_store_ids={"s1"})
    with pytest.raises(deps.HTTPException) as exc:
        deps.require_super(scoped)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_context.py -q`
Expected: FAIL (`AttributeError: module 'app.api.deps' has no attribute 'require_admin_ctx'`).

- [ ] **Step 3: Write the implementation**

Replace the `require_admin` function in `backend/app/api/deps.py` (keep the imports at top; add the new ones) with:

```python
"""Shared FastAPI dependencies."""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Header, HTTPException, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.db import get_supabase
from app.services import admin_auth, admin_users
from app.services.stores import resolve_store

# Single shared limiter, keyed by client IP. Imported by main.py and routes.
limiter = Limiter(key_func=get_remote_address)


def get_supabase_dep():
    return get_supabase()


async def require_store(x_store_key: str | None = Header(default=None)) -> dict:
    """Resolve the tenant from the X-Store-Key header. 401 if missing/unknown."""
    if not x_store_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Store-Key header",
        )
    store = resolve_store(x_store_key)
    if not store:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown or inactive store key",
        )
    return store


@dataclass
class AdminContext:
    """Who is calling an /admin route and what stores they may touch.

    allowed_store_ids is None for a super admin (== all stores). user_id/email
    are None for the env-secret super (no admin_users row).
    """

    user_id: str | None
    email: str | None
    is_super: bool
    allowed_store_ids: set[str] | None


def _super_from_secret() -> AdminContext:
    return AdminContext(user_id=None, email=None, is_super=True, allowed_store_ids=None)


async def require_admin_ctx(
    x_admin_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> AdminContext:
    """Authenticate an /admin request via X-Admin-Secret (super) or Bearer JWT.

    For a Bearer token the user row + assignments are re-loaded every request so
    disable/re-assignment is immediate.
    """
    expected = settings.admin_secret
    if x_admin_secret and hmac.compare_digest(x_admin_secret, expected):
        return _super_from_secret()

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        user_id = admin_auth.decode_token(token)
        if user_id:
            user = admin_users.get_by_id(user_id)
            if user and user.get("status") == "active":
                is_super = bool(user.get("is_super"))
                return AdminContext(
                    user_id=user["id"],
                    email=user.get("email"),
                    is_super=is_super,
                    allowed_store_ids=None if is_super else admin_users.allowed_store_ids(user["id"]),
                )

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def require_super(ctx: AdminContext) -> None:
    if not ctx.is_super:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Super admin required")


def assert_store_allowed(ctx: AdminContext, store_id: str | None) -> None:
    if ctx.is_super:
        return
    if store_id is None or ctx.allowed_store_ids is None or store_id not in ctx.allowed_store_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this store")


async def require_admin(
    x_admin_secret: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Backward-compatible authentication gate for routers that only need to
    confirm *some* admin is calling (no per-store scoping). Accepts the same
    credentials as require_admin_ctx."""
    await require_admin_ctx(x_admin_secret=x_admin_secret, authorization=authorization)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_context.py -q`
Expected: PASS (6 passed).

- [ ] **Step 5: Run the existing admin suite to confirm no regression**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_settings.py tests/test_admin_hat_types.py tests/test_admin_leads.py -q`
Expected: PASS (existing X-Admin-Secret auth still works through the new `require_admin` wrapper).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_admin_context.py
git commit -m "feat(admin-auth): AdminContext + require_admin_ctx/require_super/assert_store_allowed"
```

---

## Task 6: Routes — /admin/auth/{login,me,change-password}

**Files:**
- Create: `backend/app/api/routes/admin_auth.py`
- Modify: `backend/app/main.py:18-44` (import) and `:116-142` (register)
- Test: `backend/tests/test_admin_auth_routes.py`

**Interfaces:**
- Consumes: `admin_users`, `admin_auth`, `require_admin_ctx`, `AdminContext`.
- Produces routes: `POST /admin/auth/login`, `GET /admin/auth/me`, `POST /admin/auth/change-password`. `profile` shape: `{email, is_super, stores:[{id,name,public_key}]}`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_auth_routes.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import admin_auth as auth_route
from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _stub_user(monkeypatch, *, is_super=False, status="active", password="pw"):
    row = {
        "id": "u1", "email": "ops@x.com", "is_super": is_super, "status": status,
        "password_hash": admin_auth.hash_password(password),
    }
    monkeypatch.setattr(admin_users, "get_by_email", lambda e: row if e.strip().lower() == "ops@x.com" else None)
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row if uid == "u1" else None)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: {"s1"})
    monkeypatch.setattr(auth_route, "_stores_public", lambda ids: [{"id": "s1", "name": "Store 1", "public_key": "pk_1"}])
    return row


def test_login_success_returns_token_and_profile(client, monkeypatch):
    _stub_user(monkeypatch)
    resp = client.post("/admin/auth/login", json={"email": "Ops@x.com", "password": "pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token"]
    assert body["profile"]["is_super"] is False
    assert body["profile"]["stores"][0]["public_key"] == "pk_1"


def test_login_wrong_password(client, monkeypatch):
    _stub_user(monkeypatch)
    resp = client.post("/admin/auth/login", json={"email": "ops@x.com", "password": "nope"})
    assert resp.status_code == 401


def test_login_disabled_user(client, monkeypatch):
    _stub_user(monkeypatch, status="disabled")
    resp = client.post("/admin/auth/login", json={"email": "ops@x.com", "password": "pw"})
    assert resp.status_code == 401


def test_me_with_env_secret_is_super(client):
    resp = client.get("/admin/auth/me", headers={"X-Admin-Secret": "envsecret"})
    assert resp.status_code == 200
    assert resp.json()["is_super"] is True


def test_change_password_env_super_rejected(client):
    resp = client.post(
        "/admin/auth/change-password",
        headers={"X-Admin-Secret": "envsecret"},
        json={"current_password": "x", "new_password": "y"},
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_auth_routes.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.api.routes.admin_auth'`).

- [ ] **Step 3: Write the implementation**

`backend/app/api/routes/admin_auth.py`:

```python
"""Admin-user authentication: login, whoami, change-password.

Login verifies email+password and returns a 12h JWT plus the user's profile
(assigned stores). /me hydrates the frontend on reload. No admin email is ever
logged (structlog would be PII); we log the user id only.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.deps import AdminContext, require_admin_ctx
from app.db import get_supabase
from app.services import admin_auth, admin_users

router = APIRouter(tags=["admin-auth"])
log = structlog.get_logger()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


def _stores_public(store_ids: set[str] | None) -> list[dict]:
    """Resolve store ids to {id,name,public_key}. None == all stores (super)."""
    sb = get_supabase()
    res = sb.table("stores").select("id, name, public_key").order("name").execute()
    rows = res.data or []
    if store_ids is None:
        return [{"id": r["id"], "name": r["name"], "public_key": r["public_key"]} for r in rows]
    return [
        {"id": r["id"], "name": r["name"], "public_key": r["public_key"]}
        for r in rows if r["id"] in store_ids
    ]


def _profile(ctx: AdminContext) -> dict:
    return {
        "email": ctx.email,
        "is_super": ctx.is_super,
        "stores": _stores_public(ctx.allowed_store_ids),
    }


@router.post("/admin/auth/login")
async def login(body: LoginRequest) -> dict:
    user = admin_users.get_by_email(body.email)
    if not user or user.get("status") != "active":
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not admin_auth.verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = admin_auth.create_token(user["id"])
    is_super = bool(user.get("is_super"))
    store_ids = None if is_super else admin_users.allowed_store_ids(user["id"])
    log.info("admin_login", user_id=user["id"])  # no email (PII)
    profile = {
        "email": user["email"],
        "is_super": is_super,
        "stores": _stores_public(store_ids),
    }
    return {"token": token, "profile": profile}


@router.get("/admin/auth/me")
async def me(ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    return _profile(ctx)


@router.post("/admin/auth/change-password")
async def change_password(
    body: ChangePasswordRequest, ctx: AdminContext = Depends(require_admin_ctx)
) -> dict:
    if ctx.user_id is None:
        raise HTTPException(status_code=400, detail="The env super admin has no password to change")
    user = admin_users.get_by_id(ctx.user_id)
    if not user or not admin_auth.verify_password(body.current_password, user.get("password_hash", "")):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    admin_users.update_user(ctx.user_id, password=body.new_password)
    log.info("admin_password_changed", user_id=ctx.user_id)
    return {"ok": True}
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add `admin_auth,` to the `from app.api.routes import (...)` block (alphabetically near `admin_decoration_types`), and add `admin_auth.router,` to the `for router in (...)` tuple.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_auth_routes.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin_auth.py backend/app/main.py backend/tests/test_admin_auth_routes.py
git commit -m "feat(admin-auth): login / me / change-password routes"
```

---

## Task 7: Routes — /admin/users CRUD (super-only)

**Files:**
- Create: `backend/app/api/routes/admin_users.py`
- Modify: `backend/app/main.py` (import + register)
- Test: `backend/tests/test_admin_users_routes.py`

**Interfaces:**
- Consumes: `admin_users` service, `require_admin_ctx`, `require_super`.
- Produces: `GET/POST /admin/users`, `PATCH/DELETE /admin/users/{id}` (all super-only).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_users_routes.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.routes import admin_users as users_route
from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def test_list_requires_super(client, monkeypatch):
    # A store admin (bearer, not super) must get 403.
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: {"s1"})
    token = admin_auth.create_token("u1")
    resp = client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_super_can_create_and_list(client, monkeypatch):
    created = {"id": "u2", "email": "new@x.com", "is_super": False, "status": "active", "stores": []}
    monkeypatch.setattr(users_route.admin_users, "create_user", lambda **k: created)
    monkeypatch.setattr(users_route.admin_users, "list_users", lambda: [created])

    hdr = {"X-Admin-Secret": "envsecret"}
    resp = client.post("/admin/users", headers=hdr, json={
        "email": "new@x.com", "password": "pw", "is_super": False, "store_ids": ["s1"],
    })
    assert resp.status_code == 200
    assert resp.json()["email"] == "new@x.com"

    listed = client.get("/admin/users", headers=hdr)
    assert listed.status_code == 200 and len(listed.json()) == 1


def test_super_can_patch_and_delete(client, monkeypatch):
    monkeypatch.setattr(users_route.admin_users, "update_user", lambda uid, **k: {"id": uid, "email": "a@x.com", "is_super": True, "status": "active", "stores": []})
    monkeypatch.setattr(users_route.admin_users, "delete_user", lambda uid: True)
    hdr = {"X-Admin-Secret": "envsecret"}
    patched = client.patch("/admin/users/u2", headers=hdr, json={"is_super": True})
    assert patched.status_code == 200 and patched.json()["is_super"] is True
    deleted = client.delete("/admin/users/u2", headers=hdr)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_users_routes.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.api.routes.admin_users'`).

- [ ] **Step 3: Write the implementation**

`backend/app/api/routes/admin_users.py`:

```python
"""Super-admin-only management of admin users + their store assignments."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from app.api.deps import AdminContext, require_admin_ctx, require_super
from app.services import admin_users

router = APIRouter(tags=["admin-users"])


def _require_super_dep(ctx: AdminContext = Depends(require_admin_ctx)) -> AdminContext:
    require_super(ctx)
    return ctx


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    is_super: bool = False
    store_ids: list[str] = []


class UpdateUserRequest(BaseModel):
    is_super: bool | None = None
    status: str | None = None
    password: str | None = None
    store_ids: list[str] | None = None


@router.get("/admin/users")
async def list_users(ctx: AdminContext = Depends(_require_super_dep)) -> list[dict]:
    return admin_users.list_users()


@router.post("/admin/users")
async def create_user(body: CreateUserRequest, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    if admin_users.get_by_email(body.email):
        raise HTTPException(status_code=409, detail="An admin with that email already exists")
    return admin_users.create_user(
        email=body.email, password=body.password,
        is_super=body.is_super, store_ids=body.store_ids,
    )


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserRequest, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    if admin_users.get_by_id(user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    return admin_users.update_user(
        user_id, is_super=body.is_super, status=body.status,
        password=body.password, store_ids=body.store_ids,
    )


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, ctx: AdminContext = Depends(_require_super_dep)) -> dict:
    return {"deleted": admin_users.delete_user(user_id)}
```

> Note: the `create_user`/`update_user` tests monkeypatch `get_by_email`/`get_by_id` to their defaults where needed. For `test_super_can_create_and_list`, also stub `get_by_email` to return None so the duplicate check passes:
> add `monkeypatch.setattr(users_route.admin_users, "get_by_email", lambda e: None)` in that test.
> For `test_super_can_patch_and_delete`, add `monkeypatch.setattr(users_route.admin_users, "get_by_id", lambda uid: {"id": uid})`.

- [ ] **Step 4: Add the two stubs noted above to the test, then register the router**

Add `admin_users` (route module) to `main.py` import as `admin_users_routes`? No — the service is `app.services.admin_users`; the route module is `app.api.routes.admin_users`. Import it in `main.py` as:

```python
from app.api.routes import (
    admin_auth,
    admin_decoration_types,
    ...
    admin_users,   # NEW route module
    ...
)
```

and add `admin_users.router,` to the `for router in (...)` tuple.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_users_routes.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin_users.py backend/app/main.py backend/tests/test_admin_users_routes.py
git commit -m "feat(admin-auth): super-only /admin/users CRUD"
```

---

## Task 8: Enforcement — store routes (create super-only, get/patch/logo/sync scoped, list filtered)

**Files:**
- Modify: `backend/app/api/routes/admin_stores.py`
- Test: `backend/tests/test_admin_stores_scoping.py`

**Interfaces:**
- Consumes: `require_admin_ctx`, `require_super`, `assert_store_allowed`, `AdminContext`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_stores_scoping.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _bearer_store_admin(monkeypatch, allowed):
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_cannot_create_store(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.post("/admin/stores", headers=hdr, json={"slug": "x", "name": "X"})
    assert resp.status_code == 403


def test_store_admin_cannot_get_unassigned_store(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.get("/admin/stores/s2", headers=hdr)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_stores_scoping.py -q`
Expected: FAIL (create returns 200/409 not 403; get returns 404/200 not 403).

- [ ] **Step 3: Modify `admin_stores.py`**

Change the router declaration and each route. Replace the top of the file's router line and imports:

```python
from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx, require_super

router = APIRouter(tags=["admin-stores"])
```

`create_store` — super only, and add ctx param:

```python
@router.post("/admin/stores", response_model=StoreResponse)
async def create_store(body: CreateStoreRequest, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    require_super(ctx)
    sb = get_supabase()
    ...  # unchanged body
```

`list_stores` — filter to assigned stores for a store admin:

```python
@router.get("/admin/stores")
async def list_stores(ctx: AdminContext = Depends(require_admin_ctx)) -> list[dict]:
    sb = get_supabase()
    res = sb.table("stores").select(
        "id, slug, name, public_key, shopify_domain, status, created_at"
    ).order("created_at").execute()
    rows = res.data or []
    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        rows = [r for r in rows if r["id"] in allowed]
    return rows
```

`sync_store`, `get_store_admin`, `update_store`, `upload_store_logo` — add `ctx` param and `assert_store_allowed(ctx, store_id)` right after resolving the store row. Example for `get_store_admin`:

```python
@router.get("/admin/stores/{store_id}")
async def get_store_admin(store_id: str, request: Request, ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    assert_store_allowed(ctx, store_id)
    sb = get_supabase()
    ...  # unchanged body
```

Apply the same `ctx` param + `assert_store_allowed(ctx, store_id)` as the first line to `sync_store`, `update_store`, and `upload_store_logo`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_stores_scoping.py tests/test_admin_store_branding.py tests/test_admin_store_logo.py -q`
Expected: PASS (new scoping tests pass; existing branding/logo tests still pass — they use `X-Admin-Secret` = super, which bypasses the checks).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/admin_stores.py backend/tests/test_admin_stores_scoping.py
git commit -m "feat(admin-auth): scope store routes (create super-only, get/patch/sync/logo allow-list, list filtered)"
```

---

## Task 9: Enforcement — cross-store list routes filtered + diagnostics super-only

**Files:**
- Modify: `backend/app/api/routes/admin_diagnostics.py` (list_sessions, list_generation_logs, diagnostics)
- Modify: `backend/app/api/routes/admin_leads.py` (list_quote_requests, components, render)
- Modify: `backend/app/api/routes/submissions.py` (admin list)
- Modify: `backend/app/api/routes/admin_generations.py` (list + reap-stuck super-only)
- Test: `backend/tests/test_admin_list_scoping.py`

**Interfaces:**
- Consumes: `require_admin_ctx`, `require_super`, `assert_store_allowed`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_list_scoping.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _bearer_store_admin(monkeypatch, allowed):
    row = {"id": "u1", "email": "a@x.com", "is_super": False, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_blocked_from_global_diagnostics(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.get("/admin/diagnostics", headers=hdr)
    assert resp.status_code == 403


def test_store_admin_blocked_from_reap_stuck(client, monkeypatch):
    hdr = _bearer_store_admin(monkeypatch, {"s1"})
    resp = client.post("/admin/generations/reap-stuck", headers=hdr)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_list_scoping.py -q`
Expected: FAIL (diagnostics/reap return 200/500 not 403).

- [ ] **Step 3: Modify the routes**

**`admin_diagnostics.py`** — the router currently has `dependencies=[Depends(require_admin)]`. Change to `dependencies=[Depends(require_admin_ctx)]` (still authenticates) and update imports:

```python
from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx, require_super
```

`list_sessions` — add `ctx` and filter. It already has a `store_id` param; enforce it:

```python
async def list_sessions(
    ...,  # existing params
    store_id: str | None = None,
    ctx: AdminContext = Depends(require_admin_ctx),
):
    ...
    if not ctx.is_super:
        allowed = list(ctx.allowed_store_ids or set())
        if store_id is not None:
            assert_store_allowed(ctx, store_id)
            q = q.eq("store_id", store_id)
        elif allowed:
            q = q.in_("store_id", allowed)
        else:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
    elif store_id:
        q = q.eq("store_id", store_id)
    ...
```

Apply the same pattern to `list_generation_logs` (it filters by `session_id`; for a store admin without super, resolve the session's store and `assert_store_allowed`, or restrict to sessions of allowed stores — simplest: require a `session_id` for non-super and assert its store). Implement:

```python
async def list_generation_logs(..., session_id: str | None = None, ctx: AdminContext = Depends(require_admin_ctx)):
    if not ctx.is_super:
        if not session_id:
            raise HTTPException(status_code=403, detail="Select a store/session")
        sess = get_supabase().table("design_sessions").select("store_id").eq("id", session_id).limit(1).execute()
        store_id = (sess.data[0].get("store_id") if sess.data else None)
        assert_store_allowed(ctx, store_id)
    ...
```

`diagnostics` (global counts) — super only:

```python
async def diagnostics(request: Request, ctx: AdminContext = Depends(require_admin_ctx)):
    require_super(ctx)
    ...
```

The single-session detail route `GET /admin/sessions/{id}` — add ctx + assert the session's store:

```python
async def get_session_detail(session_id: str, request: Request, ctx: AdminContext = Depends(require_admin_ctx)):
    ...
    session = res.data[0]  # after fetch
    assert_store_allowed(ctx, session.get("store_id"))
    ...
```

**`admin_leads.py`** — change router to `dependencies=[Depends(require_admin_ctx)]`, import the helpers. `list_quote_requests` filters each row's store; simplest is to filter the output for non-super:

```python
async def list_quote_requests(ctx: AdminContext = Depends(require_admin_ctx)) -> list[dict]:
    ...  # build `out` as today
    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        out = [r for r in out if _store_id_for_session(r["session_id"]) in allowed]
    return out
```

Add a small helper `_store_id_for_session(session_id)` that reads `design_sessions.store_id`. For `render_quote_request` (already store-scoped via `require_store`) add `ctx` and `assert_store_allowed(ctx, store["id"])`. For `list_quote_components`, resolve the lead's session store and `assert_store_allowed`.

**`submissions.py`** — for the admin list route (`GET /admin/submissions`), add `ctx` and filter to allowed store ids (join through session). If submissions carry `session_id`, resolve store per row and filter for non-super, mirroring quote-requests.

**`admin_generations.py`** — router to `require_admin_ctx`; the list route filters to allowed stores (it has `store_id` per row — filter output for non-super); `reap-stuck` is `require_super`:

```python
async def reap_stuck(..., ctx: AdminContext = Depends(require_admin_ctx)):
    require_super(ctx)
    ...
```

- [ ] **Step 4: Run tests**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_list_scoping.py tests/test_admin_generations_list.py tests/test_admin_leads.py -q`
Expected: PASS (new 403 checks pass; existing super-secret tests still pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/admin_diagnostics.py backend/app/api/routes/admin_leads.py backend/app/api/routes/submissions.py backend/app/api/routes/admin_generations.py backend/tests/test_admin_list_scoping.py
git commit -m "feat(admin-auth): scope cross-store list routes; diagnostics + reap-stuck super-only"
```

---

## Task 10: Enforcement — store-scoped config routers + remaining self-heal

**Files:**
- Modify: `backend/app/api/routes/admin_hat_types.py`, `admin_graphics.py`, `admin_decoration_types.py` (these already use `require_store` via `X-Store-Key`)
- Modify: `backend/app/api/routes/admin_settings.py` (super-only), `admin_deliveries.py` (super-only), `admin_prompt.py` (session-store scoped)
- Test: `backend/tests/test_admin_scoped_config.py`

**Interfaces:**
- Consumes: `require_admin_ctx`, `require_super`, `assert_store_allowed`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_admin_scoped_config.py`:

```python
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import admin_auth, admin_users


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "envsecret")
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _bearer(monkeypatch, allowed, is_super=False):
    row = {"id": "u1", "email": "a@x.com", "is_super": is_super, "status": "active"}
    monkeypatch.setattr(admin_users, "get_by_id", lambda uid: row)
    monkeypatch.setattr(admin_users, "allowed_store_ids", lambda uid: set(allowed))
    return {"Authorization": f"Bearer {admin_auth.create_token('u1')}"}


def test_store_admin_blocked_from_settings(client, monkeypatch):
    hdr = _bearer(monkeypatch, {"s1"})
    resp = client.get("/admin/settings", headers=hdr)
    assert resp.status_code == 403


def test_store_admin_blocked_from_backfill(client, monkeypatch):
    hdr = _bearer(monkeypatch, {"s1"})
    resp = client.post("/admin/deliveries/backfill", headers=hdr)
    assert resp.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_scoped_config.py -q`
Expected: FAIL (settings/backfill return 200 not 403).

- [ ] **Step 3: Modify the routes**

**Store-scoped config** (`admin_hat_types.py`, `admin_graphics.py`, `admin_decoration_types.py`): these resolve a store via `require_store` (from `X-Store-Key`). Add an admin context + allow-list check. In each route function that has `store: dict = Depends(require_store)`, add `ctx: AdminContext = Depends(require_admin_ctx)` and, as the first line, `assert_store_allowed(ctx, store["id"])`. Update imports in each file:

```python
from app.api.deps import AdminContext, assert_store_allowed, require_admin, require_admin_ctx, require_store
```

(Keep the router-level `dependencies=[Depends(require_admin)]` as-is for authentication; the per-route `ctx` dependency is what carries scoping. FastAPI caches it per request.)

**`admin_settings.py`** — global app settings, super-only. In both `get_settings` and `patch_settings`, add `ctx: AdminContext = Depends(require_admin_ctx)` and `require_super(ctx)` as the first line. Import `AdminContext, require_admin_ctx, require_super`.

**`admin_deliveries.py`** — backfill is a global self-heal; super-only. Add `ctx` + `require_super(ctx)`.

**`admin_prompt.py`** — `GET /admin/prompt-preview/{session_id}` scoped to the session's store. Add `ctx`, resolve the session's `store_id`, `assert_store_allowed(ctx, store_id)`.

- [ ] **Step 4: Run tests**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_scoped_config.py tests/test_admin_hat_types.py tests/test_admin_settings.py tests/test_admin_prompt.py -q`
Expected: PASS (new 403s pass; existing super-secret tests still pass).

- [ ] **Step 5: Full backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS — all previously-passing tests (880 baseline) plus the new ones. Investigate any failure before committing.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin_hat_types.py backend/app/api/routes/admin_graphics.py backend/app/api/routes/admin_decoration_types.py backend/app/api/routes/admin_settings.py backend/app/api/routes/admin_deliveries.py backend/app/api/routes/admin_prompt.py backend/tests/test_admin_scoped_config.py
git commit -m "feat(admin-auth): allow-list store-scoped config routes; settings/backfill super-only"
```

---

## Task 11: Frontend — adminStore + adminApi (bearer/secret + auth endpoints)

**Files:**
- Modify: `frontend/src/admin/adminStore.ts`
- Modify: `frontend/src/admin/adminApi.ts`
- Test: `frontend/src/__tests__/adminAuth.test.ts`

**Interfaces:**
- Produces:
  - `adminStore` state `{ kind: 'bearer'|'secret', credential: string|null, profile: Profile|null, authed: boolean, loginWith(kind, credential, profile), setProfile(profile), logout() }`
  - `adminApi`: `login(email, password)`, `fetchMe()`, `changePassword(current, next)`, `listUsers()`, `createUser(body)`, `updateUser(id, body)`, `deleteUser(id)`.
  - `Profile = { email: string|null, is_super: boolean, stores: { id: string; name: string; public_key: string }[] }`

- [ ] **Step 1: Write the failing test**

`frontend/src/__tests__/adminAuth.test.ts`:

```typescript
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { useAdminStore } from '../admin/adminStore'

describe('adminStore credential kinds', () => {
  beforeEach(() => {
    sessionStorage.clear()
    useAdminStore.getState().logout()
  })

  it('stores a bearer credential + profile and reports authed', () => {
    useAdminStore.getState().loginWith('bearer', 'jwt-token', {
      email: 'a@x.com', is_super: false, stores: [],
    })
    const s = useAdminStore.getState()
    expect(s.authed).toBe(true)
    expect(s.kind).toBe('bearer')
    expect(s.credential).toBe('jwt-token')
    expect(s.profile?.is_super).toBe(false)
  })

  it('logout clears everything', () => {
    useAdminStore.getState().loginWith('secret', 's3cr3t', { email: null, is_super: true, stores: [] })
    useAdminStore.getState().logout()
    expect(useAdminStore.getState().authed).toBe(false)
    expect(useAdminStore.getState().credential).toBeNull()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/adminAuth.test.ts`
Expected: FAIL (`loginWith is not a function`).

- [ ] **Step 3: Rewrite `adminStore.ts`**

```typescript
import { create } from 'zustand'

const CRED_KEY = 'mh_admin_cred'
const KIND_KEY = 'mh_admin_kind'

export type CredKind = 'bearer' | 'secret'

export interface Profile {
  email: string | null
  is_super: boolean
  stores: { id: string; name: string; public_key: string }[]
}

function read(key: string): string | null {
  try {
    return sessionStorage.getItem(key)
  } catch {
    return null
  }
}

interface AdminState {
  kind: CredKind
  credential: string | null
  profile: Profile | null
  authed: boolean
  loginWith: (kind: CredKind, credential: string, profile: Profile | null) => void
  setProfile: (profile: Profile) => void
  logout: () => void
}

export const useAdminStore = create<AdminState>((set) => {
  const credential = read(CRED_KEY)
  const kind = (read(KIND_KEY) as CredKind) || 'bearer'
  return {
    kind,
    credential,
    profile: null,
    authed: credential !== null,
    loginWith: (k, cred, profile) => {
      try {
        sessionStorage.setItem(CRED_KEY, cred)
        sessionStorage.setItem(KIND_KEY, k)
      } catch {
        // in-memory only
      }
      set({ kind: k, credential: cred, profile, authed: true })
    },
    setProfile: (profile) => set({ profile }),
    logout: () => {
      try {
        sessionStorage.removeItem(CRED_KEY)
        sessionStorage.removeItem(KIND_KEY)
      } catch {
        // ignore
      }
      set({ kind: 'bearer', credential: null, profile: null, authed: false })
    },
  }
})

/** Non-hook accessors for use inside adminApi (outside React render). */
export function getCredential(): { kind: CredKind; credential: string | null } {
  const s = useAdminStore.getState()
  return { kind: s.kind, credential: s.credential }
}

export function logout(): void {
  useAdminStore.getState().logout()
}
```

- [ ] **Step 4: Update `adminApi.ts` header logic + add endpoints**

Replace the top of `adminApi.ts` (imports + `request`'s header block). Change the import line:

```typescript
import { getCredential, logout } from './adminStore'
import type { Brand } from '../lib/types'
import type { Profile } from './adminStore'
```

In `request<T>`, replace the credential/header section:

```typescript
async function request<T>(path: string, init: RequestInit = {}, storeKey?: string): Promise<T> {
  const { kind, credential } = getCredential()
  if (credential === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
  const headers = new Headers(init.headers as HeadersInit | undefined)
  if (kind === 'bearer') {
    headers.set('Authorization', `Bearer ${credential}`)
  } else {
    headers.set('X-Admin-Secret', credential)
  }
  if (storeKey) {
    headers.set('X-Store-Key', storeKey)
  }
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
```

Update the multipart helpers (`uploadHatAngle`, `uploadGraphic`, `uploadStoreLogo`) — they call `getSecret()` today. Replace each `const secret = getSecret()` block with:

```typescript
  const { kind, credential } = getCredential()
  if (credential === null) {
    logout()
    throw new ApiError(401, 'Not authenticated')
  }
```

and in each multipart `headers`, replace `'X-Admin-Secret': secret` with a computed auth header. Define a helper near the top of the file:

```typescript
function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const { kind, credential } = getCredential()
  const h: Record<string, string> = { ...(extra ?? {}) }
  if (credential) {
    if (kind === 'bearer') h['Authorization'] = `Bearer ${credential}`
    else h['X-Admin-Secret'] = credential
  }
  return h
}
```

Then in each multipart fetch use `headers: authHeaders({ 'X-Store-Key': storeKey })` (or without the store key for the logo upload).

Remove `validateSecret` and add the auth endpoints at the end of the file:

```typescript
// ---------------------------------------------------------------------------
// Admin authentication
// ---------------------------------------------------------------------------

export async function login(email: string, password: string): Promise<{ token: string; profile: Profile }> {
  const res = await fetch(`${BASE_URL}/admin/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    let detail = 'Invalid email or password'
    try {
      const j = (await res.json()) as { detail?: string }
      detail = j.detail ?? detail
    } catch {
      // keep default
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<{ token: string; profile: Profile }>
}

/** Validate the stored credential and return the current profile (used on load). */
export function fetchMe(): Promise<Profile> {
  return request<Profile>('/admin/auth/me')
}

export function changePassword(current_password: string, new_password: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>('/admin/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password, new_password }),
  })
}

export interface AdminUser {
  id: string
  email: string
  is_super: boolean
  status: string
  stores: { id: string; name: string }[]
}

export function listUsers(): Promise<AdminUser[]> {
  return request<AdminUser[]>('/admin/users')
}

export function createUser(body: {
  email: string; password: string; is_super: boolean; store_ids: string[]
}): Promise<AdminUser> {
  return request<AdminUser>('/admin/users', { method: 'POST', body: JSON.stringify(body) })
}

export function updateUser(id: string, body: {
  is_super?: boolean; status?: string; password?: string; store_ids?: string[]
}): Promise<AdminUser> {
  return request<AdminUser>(`/admin/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}

export function deleteUser(id: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/users/${id}`, { method: 'DELETE' })
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/adminAuth.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 6: Update the existing `adminApi.test.ts`**

`frontend/src/__tests__/adminApi.test.ts` uses the removed `validateSecret`, the old `useAdminStore.getState().login('secret-123')`, and asserts the `X-Admin-Secret` header. Update it to the new API:
- Remove the `validateSecret` import and its `describe('validateSecret', …)` block (its behaviour is now covered by `login`/`fetchMe`).
- Replace `useAdminStore.getState().login('secret-123')` in the setup with `useAdminStore.getState().loginWith('secret', 'secret-123', { email: null, is_super: true, stores: [] })`.
- The remaining `listStores`/store-key assertions stay valid because a `'secret'`-kind credential still sends `X-Admin-Secret` (assertion at line ~53 passes unchanged). Add one new case asserting a `'bearer'` credential sends `Authorization: Bearer <token>`:

```typescript
it('sends a bearer credential as Authorization header', async () => {
  useAdminStore.getState().loginWith('bearer', 'jwt-123', { email: 'a@x.com', is_super: false, stores: [] })
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify([]), { status: 200 }))
  await listStores()
  const init = fetchMock.mock.calls[0][1]
  expect(init.headers.get('Authorization')).toBe('Bearer jwt-123')
  expect(init.headers.get('X-Admin-Secret')).toBeNull()
})
```

(Adapt `fetchMock` to whatever mock name the existing file uses.)

- [ ] **Step 7: Typecheck + run the updated api tests**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/__tests__/adminApi.test.ts src/__tests__/adminAuth.test.ts`
Expected: no type errors (fix any lingering references to the removed `getSecret`/`validateSecret`); api + auth tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/admin/adminStore.ts frontend/src/admin/adminApi.ts frontend/src/__tests__/adminAuth.test.ts frontend/src/__tests__/adminApi.test.ts
git commit -m "feat(admin-auth): frontend bearer/secret credential store + auth API"
```

---

## Task 12: Frontend — AdminLogin (email/password + secret link)

**Files:**
- Modify: `frontend/src/admin/AdminLogin.tsx`
- Test: `frontend/src/admin/AdminLogin.test.tsx`

**Interfaces:**
- Consumes: `adminApi.login`, `adminApi.fetchMe`, `adminStore.loginWith`.

- [ ] **Step 1: Write the failing test**

`frontend/src/admin/AdminLogin.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminLogin } from './AdminLogin'
import * as api from './adminApi'
import { useAdminStore } from './adminStore'

vi.mock('./adminApi')

describe('AdminLogin', () => {
  beforeEach(() => {
    useAdminStore.getState().logout()
    vi.clearAllMocks()
  })

  it('logs in with email + password', async () => {
    vi.mocked(api.login).mockResolvedValue({
      token: 'jwt', profile: { email: 'a@x.com', is_super: false, stores: [] },
    })
    render(
      <MemoryRouter>
        <AdminLogin />
      </MemoryRouter>,
    )
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))
    await waitFor(() => expect(useAdminStore.getState().credential).toBe('jwt'))
    expect(useAdminStore.getState().kind).toBe('bearer')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/AdminLogin.test.tsx`
Expected: FAIL (email/password fields not found).

- [ ] **Step 3: Rewrite `AdminLogin.tsx`**

```tsx
import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAdminStore } from './adminStore'
import { login as apiLogin, fetchMe, ApiError } from './adminApi'

export function AdminLogin() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [secret, setSecret] = useState('')
  const [useSecret, setUseSecret] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const loginWith = useAdminStore((s) => s.loginWith)
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname ?? '/admin/submissions'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      if (useSecret) {
        // Env super admin: validate the secret via /admin/auth/me.
        loginWith('secret', secret, null)
        const profile = await fetchMe()
        loginWith('secret', secret, profile)
        navigate(from, { replace: true })
      } else {
        const { token, profile } = await apiLogin(email, password)
        loginWith('bearer', token, profile)
        navigate(from, { replace: true })
      }
    } catch (err) {
      useAdminStore.getState().logout()
      setError(err instanceof ApiError ? err.detail : 'Could not sign in — try again')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-100">
      <form onSubmit={onSubmit} className="w-full max-w-sm bg-white rounded-lg shadow p-6 space-y-4">
        <h1 className="text-lg font-semibold text-gray-900">MadHats Admin</h1>
        {!useSecret ? (
          <>
            <label className="block text-sm font-medium text-gray-700">
              Email
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
            <label className="block text-sm font-medium text-gray-700">
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </label>
          </>
        ) : (
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
        )}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={busy || (useSecret ? secret.length === 0 : email.length === 0 || password.length === 0)}
          className="w-full rounded-lg bg-[#ff5c00] text-white py-2 text-sm font-medium hover:bg-[#e64f00] disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Sign in'}
        </button>
        <button
          type="button"
          onClick={() => { setUseSecret(!useSecret); setError(null) }}
          className="w-full text-xs text-gray-500 hover:text-gray-700"
        >
          {useSecret ? 'Sign in with email instead' : 'Sign in with admin secret'}
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/AdminLogin.test.tsx`
Expected: PASS (1 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/AdminLogin.tsx frontend/src/admin/AdminLogin.test.tsx
git commit -m "feat(admin-auth): email/password login with admin-secret fallback"
```

---

## Task 13: Frontend — profile hydration + nav gating

**Files:**
- Modify: `frontend/src/admin/AdminApp.tsx` (hydrate `/admin/auth/me` on load; add Users + change-password routes)
- Modify: `frontend/src/admin/AdminLayout.tsx` (gate nav by `is_super`)
- Test: `frontend/src/admin/AdminLayout.test.tsx`

**Interfaces:**
- Consumes: `adminStore.profile`, `adminApi.fetchMe`.

- [ ] **Step 1: Write the failing test**

`frontend/src/admin/AdminLayout.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AdminLayout } from './AdminLayout'
import { useAdminStore } from './adminStore'

function renderWithProfile(is_super: boolean) {
  useAdminStore.getState().loginWith('bearer', 'jwt', { email: 'a@x.com', is_super, stores: [] })
  return render(
    <MemoryRouter>
      <AdminLayout />
    </MemoryRouter>,
  )
}

describe('AdminLayout nav gating', () => {
  beforeEach(() => useAdminStore.getState().logout())

  it('hides super-only nav for a store admin', () => {
    renderWithProfile(false)
    expect(screen.queryByRole('link', { name: /users/i })).toBeNull()
    expect(screen.queryByRole('link', { name: /diagnostics/i })).toBeNull()
  })

  it('shows super-only nav for a super admin', () => {
    renderWithProfile(true)
    expect(screen.getByRole('link', { name: /users/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /diagnostics/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/AdminLayout.test.tsx`
Expected: FAIL (no Users link exists yet; gating not implemented).

- [ ] **Step 3: Update `AdminLayout.tsx`**

```tsx
import { NavLink, Outlet } from 'react-router-dom'
import { useAdminStore } from './adminStore'

const NAV: { to: string; label: string; superOnly?: boolean }[] = [
  { to: '/admin/submissions', label: 'Approval queue' },
  { to: '/admin/quote-requests', label: 'Quote requests' },
  { to: '/admin/leads', label: 'Leads' },
  { to: '/admin/diagnostics', label: 'Diagnostics', superOnly: true },
  { to: '/admin/stores', label: 'Stores', superOnly: true },
  { to: '/admin/branding', label: 'Branding' },
  { to: '/admin/hat-types', label: 'Hat Types' },
  { to: '/admin/graphics', label: 'Graphics' },
  { to: '/admin/decoration-types', label: 'Decorations' },
  { to: '/admin/ops', label: 'Ops', superOnly: true },
  { to: '/admin/settings', label: 'Settings', superOnly: true },
  { to: '/admin/users', label: 'Users', superOnly: true },
]

export function AdminLayout() {
  const logout = useAdminStore((s) => s.logout)
  const isSuper = useAdminStore((s) => s.profile?.is_super ?? false)
  const items = NAV.filter((n) => !n.superOnly || isSuper)
  return (
    <div className="min-h-screen bg-[#f8f9fa] font-sans text-[#1a1a2e]">
      <header className="sticky top-0 z-20 border-b border-[#e0e1ea] bg-white">
        <div className="flex h-14 items-center gap-6 px-8">
          <span className="text-[18px] font-semibold tracking-tight text-[#ff5c00]">MAD HATS</span>
          <span className="hidden text-[13px] font-medium text-[#6b6b80] sm:inline">Admin</span>
          <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
            {items.map((item) => (
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
```

- [ ] **Step 4: Hydrate profile on load in `AdminApp.tsx`**

Add a hydration effect and the new routes. Wrap the existing app with a small hydrator component:

```tsx
import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { RequireAuth } from './RequireAuth'
import { AdminLayout } from './AdminLayout'
import { AdminLogin } from './AdminLogin'
import { useAdminStore } from './adminStore'
import { fetchMe } from './adminApi'
// ...existing view imports...
import { UsersView } from './views/UsersView'
import { ChangePasswordView } from './views/ChangePasswordView'

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
  }, [credential, profile, setProfile, logout])
  return ready
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
          {/* ...existing routes... */}
          <Route path="users" element={<UsersView />} />
          <Route path="change-password" element={<ChangePasswordView />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

function HydratedLayout() {
  const ready = useHydrateProfile()
  if (!ready) {
    return <div className="p-8 text-sm text-gray-500">Loading…</div>
  }
  return <AdminLayout />
}
```

(Keep all the existing `<Route>` entries; only the two new ones and the `HydratedLayout` wrapper are additions.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/AdminLayout.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/AdminApp.tsx frontend/src/admin/AdminLayout.tsx frontend/src/admin/AdminLayout.test.tsx
git commit -m "feat(admin-auth): hydrate profile on load + gate nav by is_super"
```

---

## Task 14: Frontend — Users view

**Files:**
- Create: `frontend/src/admin/views/UsersView.tsx`
- Create: `frontend/src/admin/views/ChangePasswordView.tsx`
- Test: `frontend/src/admin/views/UsersView.test.tsx`

**Interfaces:**
- Consumes: `adminApi.listUsers/createUser/updateUser/deleteUser`, `adminApi.listStores`, `adminApi.changePassword`.

- [ ] **Step 1: Write the failing test**

`frontend/src/admin/views/UsersView.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { UsersView } from './UsersView'
import * as api from '../adminApi'

vi.mock('../adminApi')

describe('UsersView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists admin users and their assigned stores', async () => {
    vi.mocked(api.listUsers).mockResolvedValue([
      { id: 'u1', email: 'ops@x.com', is_super: false, status: 'active', stores: [{ id: 's1', name: 'Store 1' }] },
    ])
    vi.mocked(api.listStores).mockResolvedValue([
      { id: 's1', slug: 's1', name: 'Store 1', public_key: 'pk', shopify_domain: null, status: 'active' },
    ])
    render(
      <MemoryRouter>
        <UsersView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText('ops@x.com')).toBeInTheDocument())
    expect(screen.getByText(/Store 1/)).toBeInTheDocument()
  })

  it('creates a user', async () => {
    vi.mocked(api.listUsers).mockResolvedValue([])
    vi.mocked(api.listStores).mockResolvedValue([
      { id: 's1', slug: 's1', name: 'Store 1', public_key: 'pk', shopify_domain: null, status: 'active' },
    ])
    vi.mocked(api.createUser).mockResolvedValue({ id: 'u2', email: 'new@x.com', is_super: false, status: 'active', stores: [] })
    render(
      <MemoryRouter>
        <UsersView />
      </MemoryRouter>,
    )
    await waitFor(() => expect(api.listUsers).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'new@x.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'pw' } })
    fireEvent.click(screen.getByLabelText(/Store 1/i))
    fireEvent.click(screen.getByRole('button', { name: /create user/i }))
    await waitFor(() => expect(api.createUser).toHaveBeenCalledWith({
      email: 'new@x.com', password: 'pw', is_super: false, store_ids: ['s1'],
    }))
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/UsersView.test.tsx`
Expected: FAIL (`Cannot find module './UsersView'`).

- [ ] **Step 3: Write `UsersView.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { listUsers, createUser, updateUser, deleteUser, listStores } from '../adminApi'
import type { AdminUser } from '../adminApi'
import type { Store } from '../adminApi'

export function UsersView() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [stores, setStores] = useState<Store[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isSuper, setIsSuper] = useState(false)
  const [storeIds, setStoreIds] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function refresh() {
    setUsers(await listUsers())
  }

  useEffect(() => {
    listStores().then(setStores).catch(() => setStores([]))
    refresh().catch((e) => setError(String(e)))
  }, [])

  function toggleStore(id: string) {
    setStoreIds((prev) => (prev.includes(id) ? prev.filter((s) => s !== id) : [...prev, id]))
  }

  async function onCreate(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await createUser({ email, password, is_super: isSuper, store_ids: storeIds })
      setEmail('')
      setPassword('')
      setIsSuper(false)
      setStoreIds([])
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create user')
    } finally {
      setBusy(false)
    }
  }

  async function onToggleStatus(u: AdminUser) {
    await updateUser(u.id, { status: u.status === 'active' ? 'disabled' : 'active' })
    await refresh()
  }

  async function onDelete(id: string) {
    await deleteUser(id)
    await refresh()
  }

  return (
    <div className="space-y-8">
      <section>
        <h2 className="mb-3 text-base font-semibold">Admin users</h2>
        <table className="w-full text-left text-sm">
          <thead className="text-[#6b6b80]">
            <tr>
              <th className="py-2">Email</th>
              <th>Role</th>
              <th>Stores</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-t border-[#eee]">
                <td className="py-2">{u.email}</td>
                <td>{u.is_super ? 'Super' : 'Store admin'}</td>
                <td>{u.is_super ? 'All' : u.stores.map((s) => s.name).join(', ') || '—'}</td>
                <td>{u.status}</td>
                <td className="space-x-2 text-right">
                  <button className="text-xs text-[#6b6b80] hover:underline" onClick={() => onToggleStatus(u)}>
                    {u.status === 'active' ? 'Disable' : 'Enable'}
                  </button>
                  <button className="text-xs text-red-600 hover:underline" onClick={() => onDelete(u.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="max-w-lg">
        <h2 className="mb-3 text-base font-semibold">Create admin user</h2>
        <form onSubmit={onCreate} className="space-y-3">
          <label className="block text-sm">
            Email
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email"
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
          </label>
          <label className="block text-sm">
            Password
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="text"
              className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isSuper} onChange={(e) => setIsSuper(e.target.checked)} />
            Super admin (all stores)
          </label>
          {!isSuper && (
            <fieldset className="rounded border border-gray-200 p-3">
              <legend className="px-1 text-xs text-[#6b6b80]">Assigned stores</legend>
              {stores.map((s) => (
                <label key={s.id} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={storeIds.includes(s.id)} onChange={() => toggleStore(s.id)} />
                  {s.name}
                </label>
              ))}
            </fieldset>
          )}
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" disabled={busy || !email || !password}
            className="rounded-lg bg-[#ff5c00] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
            Create user
          </button>
        </form>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Write `ChangePasswordView.tsx`**

```tsx
import { useState } from 'react'
import { changePassword } from '../adminApi'

export function ChangePasswordView() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setMsg(null)
    setErr(null)
    try {
      await changePassword(current, next)
      setMsg('Password changed.')
      setCurrent('')
      setNext('')
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : 'Could not change password')
    }
  }

  return (
    <form onSubmit={onSubmit} className="max-w-sm space-y-3">
      <h2 className="text-base font-semibold">Change password</h2>
      <label className="block text-sm">
        Current password
        <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
      </label>
      <label className="block text-sm">
        New password
        <input type="password" value={next} onChange={(e) => setNext(e.target.value)}
          className="mt-1 w-full rounded border border-gray-300 px-3 py-2 text-sm" />
      </label>
      {msg && <p className="text-sm text-green-600">{msg}</p>}
      {err && <p className="text-sm text-red-600">{err}</p>}
      <button type="submit" disabled={!current || !next}
        className="rounded-lg bg-[#ff5c00] px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        Update password
      </button>
    </form>
  )
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/UsersView.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/UsersView.tsx frontend/src/admin/views/ChangePasswordView.tsx frontend/src/admin/views/UsersView.test.tsx
git commit -m "feat(admin-auth): Users management view + self-service change-password"
```

---

## Task 15: Frontend — store pickers on operational views + verification

**Files:**
- Modify: `frontend/src/admin/views/LeadsView.tsx`, `QuoteRequestsView.tsx`, `SubmissionsView.tsx` (add an assigned-store filter where they list cross-store data)
- Create: `frontend/src/admin/StorePicker.tsx`
- Test: `frontend/src/admin/StorePicker.test.tsx`

**Interfaces:**
- Consumes: `adminStore.profile.stores`, `adminApi.listStores`.
- Produces: `<StorePicker value={id|null} onChange={fn} allowAll />` — options limited to `profile.stores`; super admin also gets an "All stores" option when `allowAll`.

- [ ] **Step 1: Write the failing test**

`frontend/src/admin/StorePicker.test.tsx`:

```tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StorePicker } from './StorePicker'
import { useAdminStore } from './adminStore'

describe('StorePicker', () => {
  beforeEach(() => useAdminStore.getState().logout())

  it('lists only the profile stores for a store admin', () => {
    useAdminStore.getState().loginWith('bearer', 'jwt', {
      email: 'a@x.com', is_super: false,
      stores: [{ id: 's1', name: 'Store 1', public_key: 'pk1' }],
    })
    render(<StorePicker value="s1" onChange={() => {}} />)
    expect(screen.getByRole('option', { name: 'Store 1' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /all stores/i })).toBeNull()
  })

  it('offers All stores to a super admin when allowAll', () => {
    useAdminStore.getState().loginWith('secret', 's', {
      email: null, is_super: true,
      stores: [{ id: 's1', name: 'Store 1', public_key: 'pk1' }],
    })
    render(<StorePicker value={null} onChange={() => {}} allowAll />)
    expect(screen.getByRole('option', { name: /all stores/i })).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/StorePicker.test.tsx`
Expected: FAIL (`Cannot find module './StorePicker'`).

- [ ] **Step 3: Write `StorePicker.tsx`**

```tsx
import { useAdminStore } from './adminStore'

export function StorePicker({
  value,
  onChange,
  allowAll = false,
}: {
  value: string | null
  onChange: (id: string | null) => void
  allowAll?: boolean
}) {
  const profile = useAdminStore((s) => s.profile)
  const stores = profile?.stores ?? []
  const showAll = allowAll && (profile?.is_super ?? false)
  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value === '' ? null : e.target.value)}
      className="rounded border border-gray-300 px-3 py-1.5 text-sm"
    >
      {showAll && <option value="">All stores</option>}
      {stores.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name}
        </option>
      ))}
    </select>
  )
}
```

- [ ] **Step 4: Wire the picker into the operational views**

In `LeadsView.tsx`, `QuoteRequestsView.tsx`, and `SubmissionsView.tsx`, add a `StorePicker` at the top of each list and pass the selected store id to the corresponding API list call (these views already fetch admin lists; thread the selected `store_id` into the query where the backend supports it, and rely on the backend's auto-filter otherwise). For views whose backend list doesn't take a `store_id` param, the picker is presentational only until the backend adds it — but the backend already restricts results to the admin's stores, so no data leaks. Keep the change minimal: render the picker and, where a `store_id`/`storeId` option already exists on the API function (e.g. `listSessions`), pass it.

- [ ] **Step 5: Run the picker test + full admin frontend subset**

Run: `cd frontend && npx vitest run src/admin/StorePicker.test.tsx src/admin`
Expected: PASS. (If the pre-existing `adminQuotes` Router-context failures appear, they are unrelated per CLAUDE.md — confirm they are the same 2 known failures and no new ones.)

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/admin/StorePicker.tsx frontend/src/admin/StorePicker.test.tsx frontend/src/admin/views/LeadsView.tsx frontend/src/admin/views/QuoteRequestsView.tsx frontend/src/admin/views/SubmissionsView.tsx
git commit -m "feat(admin-auth): assigned-store picker on operational admin views"
```

---

## Final verification

- [ ] **Backend full suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green (880 baseline + new tests).

- [ ] **Frontend admin subset**

Run: `cd frontend && npx vitest run src/admin src/__tests__/adminAuth.test.ts`
Expected: green except the 2 known pre-existing `adminQuotes` failures.

- [ ] **Manual smoke (if the stack is up)**
  1. Apply migrations: `cd backend && npx supabase db reset`.
  2. Log in at `/admin/login` with the env `ADMIN_SECRET` via the "admin secret" link → Users nav visible.
  3. Create a store admin assigned to one store; sign out; log in as them (email/password).
  4. Confirm: only their store in every picker; `/admin/users`, `/admin/diagnostics`, `/admin/settings` hidden and 403 if hit directly; hitting another store's `/admin/stores/{id}` → 403.
  5. Disable that user as super admin → their next action logs them out (401).

---

## Notes for the implementer

- The `admin_users` **service** module (`app.services.admin_users`) and the **route** module (`app.api.routes.admin_users`) share a name but live in different packages — import carefully (`from app.services import admin_users` vs `from app.api.routes import admin_users`).
- Every enforcement edit follows the same shape: add `ctx: AdminContext = Depends(require_admin_ctx)` to the signature, then either `require_super(ctx)` or `assert_store_allowed(ctx, <store_id>)` as the first line. Existing `X-Admin-Secret` tests keep passing because the env secret yields `is_super=True`, which bypasses both checks.
- Do not remove the router-level `dependencies=[Depends(require_admin)]` where a router has no per-store scoping to add — it still authenticates.
```
