# Blank-Hat Design Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second design flow where a customer designs a full custom hat from an admin-uploaded blank (white) canvas — selectable colour, decorations placed across all four faces, an on-screen 4-angle composite preview before the AI render.

**Architecture:** Approach A — extend the existing conversation state machine with a `flow_mode` (`customise` | `blank`) branch rather than forking the engine. A new admin-managed `hat_types` catalogue supplies blank angle images + colour options. Blank sessions reuse the existing `product_ref` jsonb as the generation reference. Two new `flow_mode`-gated states (`ASK_HAT_COLOUR` fallback, `COMPOSITE_PREVIEW`) are added; a Pillow composite service renders the 4-angle preview; a blank-mode prompt variant permits recolouring the cap body. Only the front hero is AI-rendered.

**Tech Stack:** Python 3.12 / FastAPI, supabase-py (service-role), Pillow (compositing), Supabase Storage (private bucket + signed/proxy URLs), React 18 / Vite / Tailwind / Zustand, pytest + vitest.

## Global Constraints

- Composite onto the real reference photo; never synthesize cap geometry. The blank hat photo IS the reference. (CLAUDE.md §2)
- No secrets in code; all provider keys via env. (§2, §8)
- All stored images are private-bucket; browser-facing URLs are signed/proxied, never raw public paths. TTL = `SIGNED_URL_TTL`. (§8.3)
- Uploaded files: validate MIME via magic bytes + 10 MB size cap before processing. (§8.2)
- `/admin/*` gated by `X-Admin-Secret` header (`require_admin`). Tenant routes gated by `X-Store-Key` (`require_store`). (§8.7, §3b)
- No PII (name/email/notes) in logs or Sentry. (§8.10)
- DB access via supabase-py only; SQL migrations in `backend/supabase/migrations/` (no SQLAlchemy/Alembic).
- Hat types are tenant-scoped (`store_id`), mirroring `product_references`.
- Do not change customise-flow behaviour, prompts, or routing. Every new branch is gated on `flow_mode == 'blank'`.
- Model IDs come from env vars; never hardcode.

---

## File Structure

**Backend — create**
- `backend/supabase/migrations/20260712000001_hat_types.sql` — `hat_types` table + `design_sessions.flow_mode` column
- `backend/app/models/hat_type.py` — pydantic request/response models
- `backend/app/services/hat_types.py` — DB access for hat types
- `backend/app/services/upload_validation.py` — shared magic-byte/size validation (extracted from `uploads.py`)
- `backend/app/api/routes/admin_hat_types.py` — admin CRUD + angle upload
- `backend/app/api/routes/hat_types.py` — customer `GET /hat-types`
- `backend/app/services/composite.py` — Pillow tint + overlay 4-angle preview
- `backend/app/api/routes/composite.py` — `POST /composite/{session_id}`

**Backend — modify**
- `backend/app/api/routes/uploads.py` — use shared `upload_validation`
- `backend/app/api/routes/sessions.py` — add `POST /sessions/blank`
- `backend/app/models/session.py` — blank session request model
- `backend/app/services/conversation/state_machine.py` — new states, transitions, progress
- `backend/app/services/conversation/goal_planner.py` — blank branch (colour fallback + composite gateway)
- `backend/app/services/conversation/orchestrator.py` — COMPOSITE_PREVIEW / ASK_HAT_COLOUR handling + `_public_data`
- `backend/app/services/prompt_builder.py` — blank-mode recolour prompt
- `backend/app/prompts.py` — blank prompt template + state/canned copy
- `backend/app/storage.py` — `write_composite` helper
- `backend/app/main.py` — register new routers

**Frontend — create**
- `frontend/src/components/BlankHatPicker/index.tsx`
- `frontend/src/admin/views/HatTypesView.tsx`

**Frontend — modify**
- `frontend/src/lib/api.ts` — hat-type + blank-session + composite calls
- `frontend/src/admin/adminApi.ts` — admin hat-type calls
- `frontend/src/store/sessionStore.ts` — `mode=blank` bootstrap + blank session start
- `frontend/src/App.tsx` — render `BlankHatPicker` in blank mode
- `frontend/src/admin/AdminLayout.tsx` — nav entry
- `frontend/src/components/ChatPanel/index.tsx` — composite-preview rendering
- `frontend/src/components/ProductViewer/index.tsx` — composite angle display

---

## Task 1: Migration — `hat_types` table + `flow_mode` column

**Files:**
- Create: `backend/supabase/migrations/20260712000001_hat_types.sql`

**Interfaces:**
- Produces: table `hat_types(id, store_id, slug, name, style, description, blank_view_images jsonb, colours jsonb, placement_zones text[], decoration_types text[], pricing_slabs jsonb, active bool, created_at, updated_at)`; column `design_sessions.flow_mode text not null default 'customise'`.

- [ ] **Step 1: Write the migration SQL**

```sql
-- Blank-hat design flow: admin-managed blank hat catalogue + session flow_mode.

create table if not exists hat_types (
  id                uuid primary key default gen_random_uuid(),
  store_id          uuid references stores(id) on delete cascade,
  slug              text not null,
  name              text not null,
  style             text not null default '',
  description       text,
  blank_view_images jsonb not null default '{}'::jsonb,   -- {front,back,left,right} storage paths
  colours           jsonb not null default '[]'::jsonb,   -- [{name, hex}]
  placement_zones   text[] not null default '{}',
  decoration_types  text[] not null default '{}',
  pricing_slabs     jsonb not null default '[]'::jsonb,
  active            bool not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (store_id, slug)
);
create index if not exists idx_hat_types_store on hat_types(store_id);

alter table design_sessions
  add column if not exists flow_mode text not null default 'customise';

-- RLS: service_role full (BYPASSRLS); anon may read only ACTIVE hat types.
alter table hat_types enable row level security;
drop policy if exists hat_types_read_anon on hat_types;
create policy hat_types_read_anon on hat_types
  for select to anon, authenticated using (active = true);

grant select on hat_types to anon, authenticated;
grant all privileges on hat_types to service_role;
```

- [ ] **Step 2: Apply the migration locally**

Run: `cd backend && npx supabase db reset`
Expected: reset completes, all migrations apply with no error; `hat_types` listed.

- [ ] **Step 3: Verify the schema**

Run: `cd backend && npx supabase db reset && echo "select column_name from information_schema.columns where table_name='design_sessions' and column_name='flow_mode';" | npx supabase db execute --stdin 2>/dev/null || echo "verify in Studio"`
Expected: migration applies cleanly (verify `flow_mode` + `hat_types` exist in Studio at http://localhost:54323 if the CLI execute form is unavailable).

- [ ] **Step 4: Commit**

```bash
git add backend/supabase/migrations/20260712000001_hat_types.sql
git commit -m "feat(db): hat_types table + design_sessions.flow_mode"
```

---

## Task 2: Hat-type models

**Files:**
- Create: `backend/app/models/hat_type.py`
- Test: `backend/tests/test_hat_type_models.py`

**Interfaces:**
- Produces: `HatColour(name:str, hex:str)`, `CreateHatTypeRequest`, `UpdateHatTypeRequest`, `HatTypeAdmin`, `HatTypePublic`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hat_type_models.py
from app.models.hat_type import CreateHatTypeRequest, HatTypePublic


def test_create_defaults():
    req = CreateHatTypeRequest(name="5-Panel", slug="five-panel")
    assert req.style == ""
    assert req.colours == []
    assert req.placement_zones == []


def test_public_shape_has_signed_view_urls():
    pub = HatTypePublic(
        id="h1", name="5-Panel", style="", slug="five-panel",
        view_images={"front": "https://x/front"}, colours=[{"name": "Black", "hex": "#000000"}],
        placement_zones=["front_panel"], decoration_types=["print"],
    )
    assert pub.view_images["front"].startswith("https://")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_hat_type_models.py -v`
Expected: FAIL with `ModuleNotFoundError: app.models.hat_type`.

- [ ] **Step 3: Write the models**

```python
# backend/app/models/hat_type.py
from __future__ import annotations

from pydantic import BaseModel, Field


class HatColour(BaseModel):
    name: str
    hex: str


class CreateHatTypeRequest(BaseModel):
    name: str
    slug: str
    style: str = ""
    description: str | None = None
    colours: list[HatColour] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
    pricing_slabs: list[dict] = Field(default_factory=list)


class UpdateHatTypeRequest(BaseModel):
    name: str | None = None
    style: str | None = None
    description: str | None = None
    colours: list[HatColour] | None = None
    placement_zones: list[str] | None = None
    decoration_types: list[str] | None = None
    pricing_slabs: list[dict] | None = None
    active: bool | None = None


class HatTypeAdmin(BaseModel):
    id: str
    store_id: str | None = None
    slug: str
    name: str
    style: str = ""
    description: str | None = None
    blank_view_images: dict[str, str] = Field(default_factory=dict)
    colours: list[dict] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
    pricing_slabs: list[dict] = Field(default_factory=list)
    active: bool = False


class HatTypePublic(BaseModel):
    id: str
    slug: str
    name: str
    style: str = ""
    view_images: dict[str, str] = Field(default_factory=dict)  # browser-loadable URLs
    colours: list[dict] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_hat_type_models.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/hat_type.py backend/tests/test_hat_type_models.py
git commit -m "feat(models): hat_type request/response models"
```

---

## Task 3: Hat-type service (DB access)

**Files:**
- Create: `backend/app/services/hat_types.py`
- Test: `backend/tests/test_hat_types_service.py`

**Interfaces:**
- Consumes: `app.db.get_supabase`.
- Produces:
  - `create_hat_type(store_id: str, body: dict) -> dict`
  - `list_hat_types(store_id: str, active_only: bool=False) -> list[dict]`
  - `get_hat_type(hat_type_id: str, store_id: str | None=None) -> dict | None`
  - `update_hat_type(hat_type_id: str, patch: dict) -> dict | None`
  - `delete_hat_type(hat_type_id: str) -> None`
  - `set_angle(hat_type_id: str, view: str, path: str) -> dict` — merges into `blank_view_images`, and if all 4 views now present leaves `active` untouched (activation is explicit)
  - `all_angles_present(row: dict) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hat_types_service.py
from app.services import hat_types


class _Result:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, rows, store):
        self._rows, self._store = rows, store
        self._insert = None
        self._update = None
    def select(self, *a, **k): return self
    def eq(self, f, v):
        self._rows = [r for r in self._rows if r.get(f) == v]; return self
    def order(self, *a, **k): return self
    def limit(self, n):
        self._rows = self._rows[:n]; return self
    def insert(self, row):
        self._insert = {**row, "id": "new-id"}; return self
    def update(self, patch):
        self._update = patch; return self
    def execute(self):
        if self._insert is not None: return _Result([self._insert])
        if self._update is not None:
            for r in self._rows: r.update(self._update)
            return _Result(self._rows)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, rows): self._rows = rows
    def table(self, name): return _Query(list(self._rows), None)


def test_all_angles_present():
    assert hat_types.all_angles_present({"blank_view_images": {
        "front": "a", "back": "b", "left": "c", "right": "d"}}) is True
    assert hat_types.all_angles_present({"blank_view_images": {"front": "a"}}) is False


def test_list_active_only_filters(monkeypatch):
    rows = [{"id": "1", "active": True}, {"id": "2", "active": False}]
    monkeypatch.setattr(hat_types, "get_supabase", lambda: _FakeSB(rows))
    out = hat_types.list_hat_types("store-1", active_only=True)
    assert [r["id"] for r in out] == ["1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_hat_types_service.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.hat_types`.

- [ ] **Step 3: Write the service**

```python
# backend/app/services/hat_types.py
"""Hat-type catalogue access (blank-hat design flow). supabase-py only."""
from __future__ import annotations

from datetime import datetime, timezone

from app.db import get_supabase

_VIEWS = ("front", "back", "left", "right")


def all_angles_present(row: dict) -> bool:
    imgs = row.get("blank_view_images") or {}
    return all(imgs.get(v) for v in _VIEWS)


def create_hat_type(store_id: str, body: dict) -> dict:
    row = {**body, "store_id": store_id}
    res = get_supabase().table("hat_types").insert(row).execute()
    return res.data[0]


def list_hat_types(store_id: str, active_only: bool = False) -> list[dict]:
    q = get_supabase().table("hat_types").select("*").eq("store_id", store_id)
    if active_only:
        q = q.eq("active", True)
    return q.order("name").execute().data or []


def get_hat_type(hat_type_id: str, store_id: str | None = None) -> dict | None:
    q = get_supabase().table("hat_types").select("*").eq("id", hat_type_id)
    if store_id:
        q = q.eq("store_id", store_id)
    res = q.limit(1).execute()
    return res.data[0] if res.data else None


def update_hat_type(hat_type_id: str, patch: dict) -> dict | None:
    patch = {**patch, "updated_at": datetime.now(timezone.utc).isoformat()}
    res = get_supabase().table("hat_types").update(patch).eq("id", hat_type_id).execute()
    return res.data[0] if res.data else None


def delete_hat_type(hat_type_id: str) -> None:
    get_supabase().table("hat_types").delete().eq("id", hat_type_id).execute()


def set_angle(hat_type_id: str, view: str, path: str) -> dict:
    row = get_hat_type(hat_type_id)
    if row is None:
        raise ValueError("hat type not found")
    imgs = dict(row.get("blank_view_images") or {})
    imgs[view] = path
    return update_hat_type(hat_type_id, {"blank_view_images": imgs})
```

Note: `_Query` in the test lacks `.delete()`; only the tested paths need mocking. Add a no-op `delete` to `_Query` if you extend coverage.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_hat_types_service.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/hat_types.py backend/tests/test_hat_types_service.py
git commit -m "feat(service): hat_types DB access"
```

---

## Task 4: Shared upload validation + admin hat-type routes

**Files:**
- Create: `backend/app/services/upload_validation.py`
- Modify: `backend/app/api/routes/uploads.py:16-34` (use shared validation)
- Create: `backend/app/api/routes/admin_hat_types.py`
- Modify: `backend/app/main.py:18-35,93-111` (register router)
- Test: `backend/tests/test_admin_hat_types.py`

**Interfaces:**
- Consumes: `hat_types` service, `upload_asset`, `require_admin`, `require_store`.
- Produces routes (all `require_admin`):
  - `POST /admin/hat-types` → `HatTypeAdmin`
  - `GET /admin/hat-types` (store scope via `X-Store-Key` too) → `list[HatTypeAdmin]`
  - `PATCH /admin/hat-types/{id}` → `HatTypeAdmin`
  - `DELETE /admin/hat-types/{id}` → `{deleted: true}`
  - `POST /admin/hat-types/{id}/angle/{view}` (multipart file) → `{blank_view_images: {...}}`
- Produces: `upload_validation.sniff_image_mime(data) -> str | None`, `upload_validation.MAX_UPLOAD_BYTES`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_hat_types.py
import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


@pytest.fixture()
def client(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "admin_secret", "s3cr3t")
    # store resolution for X-Store-Key
    monkeypatch.setattr(
        "app.api.deps.resolve_store", lambda k: {"id": "store-1"} if k else None
    )
    store = {"hat_types": []}

    def _create(store_id, body):
        row = {"id": "h1", "store_id": store_id, "blank_view_images": {}, "active": False, **body}
        store["hat_types"].append(row)
        return row

    monkeypatch.setattr(svc, "create_hat_type", _create)
    monkeypatch.setattr(svc, "list_hat_types", lambda s, active_only=False: store["hat_types"])
    from app.main import create_app
    return TestClient(create_app())


def test_create_requires_admin(client):
    r = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 401  # missing X-Admin-Secret


def test_create_and_list(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    r = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "5P"
    r2 = client.get("/admin/hat-types", headers=h)
    assert r2.status_code == 200 and len(r2.json()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_admin_hat_types.py -v`
Expected: FAIL (route not registered → 404, or import error).

- [ ] **Step 3a: Create shared upload validation**

```python
# backend/app/services/upload_validation.py
"""Shared image upload validation (magic-byte sniff + size cap)."""
from __future__ import annotations

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB

_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
}


def sniff_image_mime(data: bytes) -> str | None:
    for sig, mime in _MAGIC.items():
        if data.startswith(sig):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
```

- [ ] **Step 3b: Refactor `uploads.py` to use it**

Replace the inline `_MAX_BYTES`/`_MAGIC`/`_sniff_mime` (lines 16–34) with an import and delegate:

```python
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
```

Then in `upload_logo`, replace `_MAX_BYTES` → `MAX_UPLOAD_BYTES` and `_sniff_mime(data)` → `sniff_image_mime(data)`. Delete the now-unused `_MAX_BYTES`, `_MAGIC`, `_sniff_mime`.

- [ ] **Step 3c: Create the admin routes**

```python
# backend/app/api/routes/admin_hat_types.py
"""Admin blank-hat catalogue management. Gated by X-Admin-Secret."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import require_admin, require_store
from app.models.hat_type import CreateHatTypeRequest, HatTypeAdmin, UpdateHatTypeRequest
from app.services import hat_types as svc
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import upload_asset

router = APIRouter(tags=["admin-hat-types"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()

_VIEWS = {"front", "back", "left", "right"}


@router.post("/admin/hat-types", response_model=HatTypeAdmin)
async def create_hat_type(body: CreateHatTypeRequest, store: dict = Depends(require_store)) -> dict:
    payload = body.model_dump()
    payload["colours"] = [c if isinstance(c, dict) else c.model_dump() for c in payload.get("colours", [])]
    return svc.create_hat_type(store["id"], payload)


@router.get("/admin/hat-types", response_model=list[HatTypeAdmin])
async def list_hat_types(store: dict = Depends(require_store)) -> list[dict]:
    return svc.list_hat_types(store["id"])


@router.patch("/admin/hat-types/{hat_type_id}", response_model=HatTypeAdmin)
async def update_hat_type(hat_type_id: str, body: UpdateHatTypeRequest) -> dict:
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "colours" in patch:
        patch["colours"] = [c if isinstance(c, dict) else dict(c) for c in patch["colours"]]
    row = svc.get_hat_type(hat_type_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    if patch.get("active") and not svc.all_angles_present(row):
        raise HTTPException(status_code=400, detail="All four angle images required before activating")
    updated = svc.update_hat_type(hat_type_id, patch)
    if updated is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    return updated


@router.delete("/admin/hat-types/{hat_type_id}")
async def delete_hat_type(hat_type_id: str) -> dict:
    svc.delete_hat_type(hat_type_id)
    return {"deleted": True}


@router.post("/admin/hat-types/{hat_type_id}/angle/{view}")
async def upload_angle(hat_type_id: str, view: str, file: UploadFile = File(...)) -> dict:
    if view not in _VIEWS:
        raise HTTPException(status_code=400, detail="view must be front|back|left|right")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "blank", mime)
    updated = svc.set_angle(hat_type_id, view, path)
    return {"blank_view_images": updated["blank_view_images"]}
```

- [ ] **Step 3d: Register the router in `main.py`**

Add `admin_hat_types` to the import block (line ~18) and to the `for router in (...)` tuple (line ~93).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_admin_hat_types.py tests/test_prompts.py -q`
Expected: PASS (new admin tests + `uploads.py` refactor didn't break imports).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/upload_validation.py backend/app/api/routes/admin_hat_types.py backend/app/api/routes/uploads.py backend/app/main.py backend/tests/test_admin_hat_types.py
git commit -m "feat(admin): hat-type CRUD + angle uploads; share upload validation"
```

---

## Task 5: Customer `GET /hat-types` route

**Files:**
- Create: `backend/app/api/routes/hat_types.py`
- Modify: `backend/app/main.py` (register)
- Test: `backend/tests/test_hat_types_route.py`

**Interfaces:**
- Consumes: `hat_types` service, `require_store`, `media_url`.
- Produces: `GET /hat-types` → `list[HatTypePublic]` — active only, angle paths converted to browser-loadable proxy URLs via `media_url(path, request.base_url)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_hat_types_route.py
import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "list_hat_types", lambda s, active_only=False: [{
        "id": "h1", "slug": "5p", "name": "5-Panel", "style": "",
        "blank_view_images": {"front": "generated/blank/front.png"},
        "colours": [{"name": "Black", "hex": "#000000"}],
        "placement_zones": ["front_panel"], "decoration_types": ["print"], "active": True,
    }])
    from app.main import create_app
    return TestClient(create_app())


def test_requires_store_key(client):
    assert client.get("/hat-types").status_code == 401


def test_lists_active_with_proxied_urls(client):
    r = client.get("/hat-types", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body[0]["name"] == "5-Panel"
    # a private storage path becomes a /media/ proxy URL
    assert "/media/" in body[0]["view_images"]["front"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_hat_types_route.py -v`
Expected: FAIL (404 / route missing).

- [ ] **Step 3: Write the route + register**

```python
# backend/app/api/routes/hat_types.py
"""Customer-facing blank-hat catalogue (tenant-scoped via X-Store-Key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.models.hat_type import HatTypePublic
from app.services import hat_types as svc
from app.storage import media_url

router = APIRouter(tags=["hat-types"])


@router.get("/hat-types", response_model=list[HatTypePublic])
async def list_hat_types(request: Request, store: dict = Depends(require_store)) -> list[dict]:
    base = str(request.base_url)
    out = []
    for row in svc.list_hat_types(store["id"], active_only=True):
        imgs = row.get("blank_view_images") or {}
        out.append({
            "id": row["id"], "slug": row["slug"], "name": row["name"], "style": row.get("style", ""),
            "view_images": {v: media_url(p, base) for v, p in imgs.items() if p},
            "colours": row.get("colours") or [],
            "placement_zones": row.get("placement_zones") or [],
            "decoration_types": row.get("decoration_types") or [],
        })
    return out
```

Register `hat_types` in `main.py` (import + router tuple).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_hat_types_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/hat_types.py backend/app/main.py backend/tests/test_hat_types_route.py
git commit -m "feat(api): customer GET /hat-types with proxied angle URLs"
```

---

## Task 6: Blank session creation — `POST /sessions/blank`

**Files:**
- Modify: `backend/app/models/session.py` (add `CreateBlankSessionRequest`)
- Modify: `backend/app/api/routes/sessions.py`
- Test: `backend/tests/test_blank_session.py`

**Interfaces:**
- Consumes: `hat_types.get_hat_type`, `require_store`.
- Produces: `POST /sessions/blank` accepting `{hat_type_id, colour}` (`colour` = `{name, hex}` or bare hex string). Builds `product_ref` from the hat type (front blank as `reference_image_url`, all blanks as `view_images`, chosen `colour`, `product_id`=hat_type_id), sets `flow_mode='blank'` column, seeds `collected.flow_mode`, `collected.hat_type_id`, `collected.hat_colour`, `placement_zones`, `decoration_types`. Returns `SessionResponse`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_blank_session.py
import pytest
from fastapi.testclient import TestClient

from app.services import hat_types as svc


class _Result:
    def __init__(self, data): self.data = data


class _Ins:
    def __init__(self): self.captured = None
    def insert(self, row): self.captured = row; return self
    def execute(self): return _Result([{**self.captured, "id": "sess-1"}])


class _FakeSB:
    def __init__(self): self.ins = _Ins()
    def table(self, name): return self.ins


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "get_hat_type", lambda hid, store_id=None: {
        "id": hid, "slug": "5p", "name": "5-Panel", "style": "flat",
        "blank_view_images": {"front": "b/front.png", "back": "b/back.png",
                              "left": "b/left.png", "right": "b/right.png"},
        "placement_zones": ["front_panel", "back"], "decoration_types": ["print"],
    })
    fake = _FakeSB()
    monkeypatch.setattr("app.api.routes.sessions.get_supabase", lambda: fake)
    from app.main import create_app
    client = TestClient(create_app())
    client._fake = fake
    return client


def test_blank_session_sets_flow_mode_and_ref(client):
    r = client.post("/sessions/blank",
                    json={"hat_type_id": "h1", "colour": {"name": "Navy", "hex": "#1a2b5c"}},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    row = client._fake.ins.captured
    assert row["flow_mode"] == "blank"
    assert row["product_ref"]["reference_image_url"] == "b/front.png"
    assert row["collected"]["flow_mode"] == "blank"
    assert row["collected"]["hat_colour"]["hex"] == "#1a2b5c"
    assert row["collected"]["placement_zones"] == ["front_panel", "back"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_blank_session.py -v`
Expected: FAIL (404 — route missing).

- [ ] **Step 3a: Add the request model to `session.py`**

```python
class CreateBlankSessionRequest(BaseModel):
    hat_type_id: str
    colour: dict | str
    channel: str = "web"
    entry_path: str = "blank_first"
```

- [ ] **Step 3b: Add the route to `sessions.py`**

```python
# imports at top
import secrets
from app.models.session import CreateBlankSessionRequest
from app.services import hat_types as hat_types_service


@router.post("/sessions/blank", response_model=SessionResponse)
async def create_blank_session(
    body: CreateBlankSessionRequest, store: dict = Depends(require_store)
) -> SessionResponse:
    hat = hat_types_service.get_hat_type(body.hat_type_id, store_id=store["id"])
    if not hat:
        raise HTTPException(status_code=404, detail="Unknown hat_type_id for this store")

    colour = body.colour if isinstance(body.colour, dict) else {"name": body.colour, "hex": body.colour}
    blanks = hat.get("blank_view_images") or {}
    share_token = secrets.token_urlsafe(16)
    product_ref = {
        "product_id": hat["id"],
        "style": hat.get("style", ""),
        "colour": colour.get("name") or colour.get("hex"),
        "name": hat["name"],
        "reference_image_url": blanks.get("front", ""),
        "view_images": blanks,
    }
    collected = {
        "flow_mode": "blank",
        "hat_type_id": hat["id"],
        "hat_colour": colour,
        "placement_zones": hat.get("placement_zones") or [],
        "decoration_types": hat.get("decoration_types") or [],
    }
    sb = get_supabase()
    res = sb.table("design_sessions").insert({
        "store_id": store["id"],
        "share_token": share_token,
        "state": "greeting",
        "channel": body.channel,
        "entry_path": body.entry_path,
        "flow_mode": "blank",
        "product_ref": product_ref,
        "collected": collected,
        "status": "draft",
    }).execute()
    row = res.data[0]
    return SessionResponse(session_id=row["id"], share_token=share_token, state=row["state"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_blank_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/session.py backend/app/api/routes/sessions.py backend/tests/test_blank_session.py
git commit -m "feat(api): POST /sessions/blank creates a blank-mode session"
```

---

## Task 7: Conversation states — `ASK_HAT_COLOUR` + `COMPOSITE_PREVIEW`

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py`
- Test: `backend/tests/test_state_machine.py` (add cases)

**Interfaces:**
- Produces: `ConversationState.ASK_HAT_COLOUR`, `ConversationState.COMPOSITE_PREVIEW`; `advance_state` handles `COMPOSITE_PREVIEW` → `GENERATING` when `composite_confirmed` else `ASK_MORE_ELEMENTS`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_state_machine.py
from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation.state_machine import advance_state


def test_composite_preview_confirm_goes_to_generating():
    assert advance_state(S.COMPOSITE_PREVIEW, {"composite_confirmed": True}) is S.GENERATING


def test_composite_preview_tweak_goes_back_to_more_elements():
    assert advance_state(S.COMPOSITE_PREVIEW, {"composite_confirmed": False}) is S.ASK_MORE_ELEMENTS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_state_machine.py -k composite -v`
Expected: FAIL with `AttributeError: COMPOSITE_PREVIEW`.

- [ ] **Step 3: Add states + transitions + branch**

In `state_machine.py`:
- Add to the `ConversationState` enum (near `GENERATING`):

```python
    ASK_HAT_COLOUR = "ask_hat_colour"
    COMPOSITE_PREVIEW = "composite_preview"
```

- Add to `TRANSITIONS`:

```python
    S.ASK_HAT_COLOUR: [S.ASK_MORE_ELEMENTS, S.GENERATING],
    S.COMPOSITE_PREVIEW: [S.GENERATING, S.ASK_MORE_ELEMENTS],
```

- Add to `ALLOWED_BACKTRACKS`:

```python
    S.COMPOSITE_PREVIEW: [S.ASK_MORE_ELEMENTS],
```

- In `advance_state`, before the `# --- Default` block:

```python
    if current is S.COMPOSITE_PREVIEW:
        return S.GENERATING if collected.get("composite_confirmed") else S.ASK_MORE_ELEMENTS
```

- Add `COMPOSITE_PREVIEW` to `_POST_QUESTION_STATES`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_state_machine.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(convo): ASK_HAT_COLOUR + COMPOSITE_PREVIEW states"
```

---

## Task 8: Goal planner blank branch + orchestrator wiring

**Files:**
- Modify: `backend/app/services/conversation/goal_planner.py`
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: `backend/tests/test_goal_planner.py` (add), `backend/tests/test_blank_flow_orchestration.py` (new)

**Interfaces:**
- Consumes: `state_machine` states from Task 7.
- Produces: `next_goal` returns `ASK_HAT_COLOUR` when `flow_mode=='blank'` and no `hat_colour` (and not asked); returns `COMPOSITE_PREVIEW` (instead of `GENERATING`) when `flow_mode=='blank'` and `composite_confirmed` is falsey; `COMPOSITE_PREVIEW` added to `GATE_STATES`. Orchestrator derives `composite_confirmed` at `COMPOSITE_PREVIEW`, `hat_colour` at `ASK_HAT_COLOUR`; `_public_data` returns UI payloads for both.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_goal_planner.py
def test_blank_colour_fallback():
    c = {"name": "Al", "purpose_asked": True, "flow_mode": "blank"}
    assert next_goal(c) is S.ASK_HAT_COLOUR
    c["hat_colour"] = {"name": "Navy", "hex": "#1a2b5c"}
    assert next_goal(c) is not S.ASK_HAT_COLOUR


def test_blank_reaches_composite_preview_before_generating():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24, "flow_mode": "blank",
         "hat_colour": {"hex": "#000"}, "decoration_type": "print", "has_logo": False,
         "elements": [{"type": "text", "content": "GO"}],
         "email_prompt_shown": True, "elements_offered": True}
    assert next_goal(c) is S.COMPOSITE_PREVIEW
    c["composite_confirmed"] = True
    assert next_goal(c) is S.GENERATING


def test_customise_still_reaches_generating_directly():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "print", "has_logo": False,
         "elements": [{"type": "text", "content": "GO"}],
         "email_prompt_shown": True, "elements_offered": True}
    assert next_goal(c) is S.GENERATING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_goal_planner.py -k "blank or customise_still" -v`
Expected: FAIL.

- [ ] **Step 3a: Edit `goal_planner.py`**

Add `S.COMPOSITE_PREVIEW` and `S.ASK_HAT_COLOUR` to `GATE_STATES` (COMPOSITE_PREVIEW is a branch gate; ASK_HAT_COLOUR is a plain question so it does NOT go in GATE_STATES — only COMPOSITE_PREVIEW).

In `next_goal`, add the colour fallback right after the decoration goal (after step 4, before 4b):

```python
    # 4a. blank-mode hat colour (fallback if not captured at the landing picker)
    if collected.get("flow_mode") == "blank" and not collected.get("hat_colour") \
            and not collected.get("hat_colour_asked"):
        return S.ASK_HAT_COLOUR
```

Replace the final `return S.GENERATING` with a gateway:

```python
    # 6. generation gateway — blank mode shows the composite preview first.
    if collected.get("flow_mode") == "blank" and not collected.get("composite_confirmed"):
        return S.COMPOSITE_PREVIEW
    return S.GENERATING
```

- [ ] **Step 3b: Edit `orchestrator.py` `_apply_fields`**

Add near the other confirmation-state derivations:

```python
    if state is S.COMPOSITE_PREVIEW:
        collected["composite_confirmed"] = is_affirmative(message) and not is_negative(message)
    if state is S.ASK_HAT_COLOUR:
        collected["hat_colour_asked"] = True
        # a hex or colour name typed in chat
        val = message.strip()
        if val and "?" not in val:
            collected["hat_colour"] = {"name": val, "hex": val} if val.startswith("#") else {"name": val, "hex": ""}
```

- [ ] **Step 3c: Edit `orchestrator.py` `_public_data`**

Add before the final `return {}`:

```python
    if state is S.ASK_HAT_COLOUR:
        return {"colour_picker": True}
    if state is S.COMPOSITE_PREVIEW:
        return {"options": ["Looks right — generate", "Tweak something"], "composite_preview": True}
```

- [ ] **Step 3d: Write the orchestration integration test**

```python
# backend/tests/test_blank_flow_orchestration.py
from app.services.conversation.goal_planner import GATE_STATES, next_goal
from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState as S


def test_composite_preview_is_a_gate():
    assert S.COMPOSITE_PREVIEW in GATE_STATES


def test_public_data_composite_preview():
    data = _public_data(S.COMPOSITE_PREVIEW, {"flow_mode": "blank"})
    assert data["composite_preview"] is True
    assert "Tweak something" in data["options"]


def test_public_data_colour_picker():
    assert _public_data(S.ASK_HAT_COLOUR, {"flow_mode": "blank"})["colour_picker"] is True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_goal_planner.py tests/test_blank_flow_orchestration.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/goal_planner.py backend/app/services/conversation/orchestrator.py backend/tests/test_goal_planner.py backend/tests/test_blank_flow_orchestration.py
git commit -m "feat(convo): blank-mode colour fallback + composite-preview gateway"
```

---

## Task 9: Prompt copy for new states

**Files:**
- Modify: `backend/app/prompts.py` (add `STATE_PROMPTS` + `CANNED_REPLIES` entries)
- Test: `backend/tests/test_prompts.py` (add)

**Interfaces:**
- Produces: `STATE_PROMPTS["ask_hat_colour"]`, `STATE_PROMPTS["composite_preview"]`, and matching `CANNED_REPLIES` keys.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_prompts.py
from app.prompts import CANNED_REPLIES, STATE_PROMPTS


def test_new_state_copy_present():
    for key in ("ask_hat_colour", "composite_preview"):
        assert key in STATE_PROMPTS
        assert key in CANNED_REPLIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_prompts.py -k new_state -v`
Expected: FAIL (KeyError / assertion).

- [ ] **Step 3: Add the copy**

In `STATE_PROMPTS`:

```python
    "ask_hat_colour": "Ask what colour they'd like the hat itself to be.",
    "composite_preview": "Tell them here's a quick on-screen mock-up of the design across "
    "all four angles, and ask if it looks right to generate or they'd like to tweak something.",
```

In `CANNED_REPLIES`:

```python
    "ask_hat_colour": "What colour would you like the hat itself to be?",
    "composite_preview": (
        "Here's a quick mock-up of your design across the front, back and sides. "
        "Happy for me to generate it, or would you like to tweak something?"
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_prompts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/tests/test_prompts.py
git commit -m "feat(convo): copy for ask_hat_colour + composite_preview"
```

---

## Task 10: Composite service (Pillow tint + overlay)

**Files:**
- Modify: `backend/app/storage.py` (add `write_composite`)
- Create: `backend/app/services/composite.py`
- Test: `backend/tests/test_composite.py`

**Interfaces:**
- Consumes: `generate_signed_url`, `write_composite`, `httpx`, Pillow.
- Produces:
  - `tint_image(img: Image, hex_colour: str) -> Image` — luminance-multiply recolour (pure)
  - `zone_box(view: str, zone: str, position: str, size: tuple[int,int]) -> tuple[int,int,int,int]` — pixel bbox (pure)
  - `render_composite_views(view_paths: dict[str,str], colour_hex: str, elements: list[dict]) -> dict[str,str]` — IO orchestration returning `{view: storage_path}`

- [ ] **Step 1: Add `write_composite` to `storage.py`**

```python
def write_composite(image_bytes: bytes, content_type: str = "image/png") -> str:
    """Store a composited preview image and return its storage path."""
    path = f"composite/{uuid.uuid4().hex}.png"
    _bucket().upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "false"},
    )
    return path
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_composite.py
from PIL import Image

from app.services import composite


def test_tint_darkens_white_toward_colour():
    white = Image.new("RGB", (10, 10), (255, 255, 255))
    tinted = composite.tint_image(white, "#1a2b5c")
    # a white pixel multiplied by the colour becomes the colour
    assert tinted.getpixel((5, 5)) == (0x1a, 0x2b, 0x5c)


def test_tint_preserves_black_shadows():
    black = Image.new("RGB", (10, 10), (0, 0, 0))
    tinted = composite.tint_image(black, "#1a2b5c")
    assert tinted.getpixel((5, 5)) == (0, 0, 0)


def test_zone_box_front_panel_centre_is_upper_middle():
    x, y, w, h = composite.zone_box("front", "front_panel", "centre", (400, 400))
    assert 0 < x < 400 and 0 < y < 400 and w > 0 and h > 0


def test_render_composite_views_returns_a_path_per_view(monkeypatch):
    # Stub the IO: image download returns a white square; upload returns a fake path.
    white = Image.new("RGB", (400, 400), (255, 255, 255))
    monkeypatch.setattr(composite, "_load_image", lambda path: white.copy())
    saved = []
    def _save(img):
        saved.append(img); return f"composite/{len(saved)}.png"
    monkeypatch.setattr(composite, "_save_image", _save)
    out = composite.render_composite_views(
        {"front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"},
        "#1a2b5c",
        [{"type": "text", "content": "GO", "placement_zone": "front_panel", "placement_position": "centre"}],
    )
    assert set(out.keys()) == {"front", "back", "left", "right"}
    assert all(v.startswith("composite/") for v in out.values())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_composite.py -v`
Expected: FAIL (`ModuleNotFoundError: app.services.composite`).

- [ ] **Step 4: Write the composite service**

```python
# backend/app/services/composite.py
"""Flat 4-angle composite preview for the blank-hat flow (Pillow).

Deterministic, no model call: tint the white blank to the chosen colour and
overlay text/logo elements at approximate per-zone boxes. Used for the on-screen
COMPOSITE_PREVIEW confirmation before the real AI render.
"""
from __future__ import annotations

import io

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont

from app.storage import generate_signed_url, write_composite

log = structlog.get_logger()

_VIEWS = ("front", "back", "left", "right")


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = (hex_colour or "#808080").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (128, 128, 128)


def tint_image(img: Image.Image, hex_colour: str) -> Image.Image:
    """Multiply the target colour over the blank's luminance (keeps shadows)."""
    r, g, b = _hex_to_rgb(hex_colour)
    rgb = img.convert("RGB")
    lum = rgb.convert("L")
    solid = Image.new("RGB", rgb.size, (r, g, b))
    return Image.composite(solid, Image.new("RGB", rgb.size, (0, 0, 0)), lum)


# Approximate bounding boxes as fractions of the image, per (view, zone).
_ZONE_FRAC = {
    ("front", "front_panel"): (0.30, 0.32, 0.40, 0.22),
    ("front", "under_brim"): (0.30, 0.66, 0.40, 0.12),
    ("back", "back"): (0.30, 0.34, 0.40, 0.22),
    ("left", "side"): (0.28, 0.36, 0.44, 0.20),
    ("right", "side"): (0.28, 0.36, 0.44, 0.20),
}
_DEFAULT_FRAC = (0.30, 0.34, 0.40, 0.22)


def zone_box(view: str, zone: str, position: str, size: tuple[int, int]) -> tuple[int, int, int, int]:
    fx, fy, fw, fh = _ZONE_FRAC.get((view, zone), _DEFAULT_FRAC)
    w, h = size
    x, y, bw, bh = int(fx * w), int(fy * h), int(fw * w), int(fh * h)
    if position == "left":
        x -= int(0.12 * w)
    elif position == "right":
        x += int(0.12 * w)
    return (max(0, x), max(0, y), bw, bh)


def _element_view(el: dict) -> str:
    zone = el.get("placement_zone") or "front_panel"
    return {"back": "back", "side": "left", "front_panel": "front", "under_brim": "front"}.get(zone, "front")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_element(img: Image.Image, el: dict, view: str) -> None:
    box = zone_box(view, el.get("placement_zone") or "front_panel",
                   el.get("placement_position") or "centre", img.size)
    x, y, w, h = box
    etype = el.get("type")
    if etype in ("text",):
        draw = ImageDraw.Draw(img)
        draw.text((x, y), el.get("content", "")[:40], fill=(255, 255, 255), font=_font(max(16, h // 2)))
    elif etype in ("logo", "graphic") and el.get("asset_path"):
        try:
            logo = _load_image(el["asset_path"]).convert("RGBA")
            logo.thumbnail((w, h))
            img.paste(logo, (x, y), logo)
        except Exception as exc:  # noqa: BLE001
            log.warning("composite_logo_skip", error=str(exc))
    else:  # graphic described in words -> label placeholder
        draw = ImageDraw.Draw(img)
        draw.rectangle([x, y, x + w, y + h], outline=(255, 255, 255), width=2)
        draw.text((x + 4, y + 4), (el.get("content", "graphic"))[:24], fill=(255, 255, 255), font=_font(14))


def _load_image(path: str) -> Image.Image:
    url = generate_signed_url(path) if not path.startswith("http") else path
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def _save_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return write_composite(buf.getvalue())


def render_composite_views(view_paths: dict[str, str], colour_hex: str, elements: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for view in _VIEWS:
        path = view_paths.get(view)
        if not path:
            continue
        base = tint_image(_load_image(path), colour_hex)
        for el in elements or []:
            if _element_view(el) == view:
                _draw_element(base, el, view)
        out[view] = _save_image(base)
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_composite.py -v`
Expected: PASS (4 tests). If Pillow isn't installed, add it: `pip install Pillow` (it is already a dependency via watermarking — verify with `python -c "import PIL"`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/composite.py backend/app/storage.py backend/tests/test_composite.py
git commit -m "feat(composite): Pillow 4-angle tint+overlay preview service"
```

---

## Task 11: `POST /composite/{session_id}` route

**Files:**
- Create: `backend/app/api/routes/composite.py`
- Modify: `backend/app/main.py` (register)
- Test: `backend/tests/test_composite_route.py`

**Interfaces:**
- Consumes: `composite.render_composite_views`, `media_url`, `get_supabase`.
- Produces: `POST /composite/{session_id}` → `{views: {view: url}}`. Loads session, reads `product_ref.view_images` (blank paths) + `collected.hat_colour.hex` + `collected.elements`, renders, saves `collected.composite_views` (paths), returns proxied URLs. On render failure returns `{views: {}, error: "..."}` with 200 so the chat can fall back gracefully.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_composite_route.py
import pytest
from fastapi.testclient import TestClient

from app.services import composite


class _Result:
    def __init__(self, data): self.data = data


class _Q:
    def __init__(self, rows): self._rows = rows; self._patch = None
    def select(self, *a, **k): return self
    def eq(self, f, v):
        self._rows = [r for r in self._rows if r.get(f) == v]; return self
    def limit(self, n): self._rows = self._rows[:n]; return self
    def update(self, patch): self._patch = patch; return self
    def execute(self): return _Result(self._rows)


class _SB:
    def __init__(self, rows): self._rows = rows
    def table(self, n): return _Q(list(self._rows))


@pytest.fixture()
def client(monkeypatch):
    session = {"id": "s1", "product_ref": {"view_images": {
        "front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"}},
        "collected": {"hat_colour": {"hex": "#1a2b5c"}, "elements": []}}
    monkeypatch.setattr("app.api.routes.composite.get_supabase", lambda: _SB([session]))
    monkeypatch.setattr(composite, "render_composite_views",
                        lambda vp, hexc, els: {"front": "composite/f.png"})
    from app.main import create_app
    return TestClient(create_app())


def test_composite_returns_proxied_urls(client):
    r = client.post("/composite/s1")
    assert r.status_code == 200
    assert "/media/" in r.json()["views"]["front"]


def test_composite_missing_session_404(client):
    assert client.post("/composite/nope").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_composite_route.py -v`
Expected: FAIL (route missing).

- [ ] **Step 3: Write the route + register**

```python
# backend/app/api/routes/composite.py
"""On-screen composite preview for the blank-hat flow (POST /composite/{id})."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Request

from app.db import get_supabase
from app.services import composite as composite_svc
from app.storage import media_url

router = APIRouter(tags=["composite"])
log = structlog.get_logger()


@router.post("/composite/{session_id}")
async def make_composite(session_id: str, request: Request) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]
    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}
    view_paths = product_ref.get("view_images") or {}
    colour_hex = (collected.get("hat_colour") or {}).get("hex") or "#808080"

    try:
        paths = composite_svc.render_composite_views(
            view_paths, colour_hex, collected.get("elements") or []
        )
    except Exception as exc:  # noqa: BLE001 — never dead-end the chat
        log.warning("composite_render_failed", session_id=session_id, error_type=type(exc).__name__)
        return {"views": {}, "error": "composite_failed"}

    collected["composite_views"] = paths
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()

    base = str(request.base_url)
    return {"views": {v: media_url(p, base) for v, p in paths.items()}}
```

Register `composite` in `main.py` (import + router tuple).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_composite_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/composite.py backend/app/main.py backend/tests/test_composite_route.py
git commit -m "feat(api): POST /composite renders the 4-angle preview"
```

---

## Task 12: Blank-mode recolour prompt

**Files:**
- Modify: `backend/app/prompts.py` (add `IMAGE_GEN_PROMPT_BLANK`)
- Modify: `backend/app/services/prompt_builder.py`
- Test: `backend/tests/test_prompt_builder.py` (add)

**Interfaces:**
- Consumes: `collected["flow_mode"]`, `product_ref["colour"]`.
- Produces: `build_prompt` selects `IMAGE_GEN_PROMPT_BLANK` (permits recolouring the cap body to the chosen colour, keeps geometry) when `collected["flow_mode"] == "blank"`; customise mode is unchanged (uses `IMAGE_GEN_PROMPT`).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_prompt_builder.py
from app.services import prompt_builder
from app.services.image.image_provider import GenerationParams


def _params():
    return GenerationParams(tier="preview", placement_zone="front_panel",
                            placement_position="centre", decoration_type="print",
                            remove_bg=False, pin_annotations=[], resolution="standard")


def test_blank_mode_prompt_mentions_recolour():
    collected = {"flow_mode": "blank", "elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "b/front.png", "colour": "Navy"}
    prompt = prompt_builder.build_prompt(collected, ref, _params())
    assert "Navy" in prompt
    assert "recolour" in prompt.lower() or "colour the cap" in prompt.lower()


def test_customise_mode_prompt_unchanged():
    from app.prompts import IMAGE_GEN_PROMPT
    collected = {"elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "p/front.png", "colour": "Black"}
    prompt = prompt_builder.build_prompt(collected, ref, _params())
    # customise mode still forbids recolour (fidelity-locked base prompt)
    assert "Do NOT recolour" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_prompt_builder.py -k "blank_mode or customise_mode" -v`
Expected: FAIL (blank test — no recolour wording).

- [ ] **Step 3a: Add `IMAGE_GEN_PROMPT_BLANK` to `prompts.py`**

```python
# A blank-hat variant: the reference is a WHITE blank of the correct shape. The
# cap BODY may (and should) be recoloured to the customer's chosen colour, but
# the geometry/shape/angle stay pixel-faithful. Everything else mirrors
# IMAGE_GEN_PROMPT's fidelity discipline. {hat_colour} is filled by build_prompt.
IMAGE_GEN_PROMPT_BLANK = """ROLE: You composite a custom design onto a REAL blank product photograph.

SOURCE OF TRUTH: The FIRST image is a blank (white/neutral) cap of the exact
shape, style and angle to reproduce. Treat its GEOMETRY as fixed.

PRIMARY DIRECTIVE — KEEP THE CAP SHAPE EXACTLY, RECOLOUR THE BODY.
Keep pixel-identical to the first image: cap type/style and silhouette, crown
shape, panel count, seams and stitching, brim/peak shape, closure/strap type,
eyelets, top button, sweatband, fabric texture and folds, camera angle, framing,
crop, lighting, shadows and background.
Recolour the cap BODY (and matching panels) to: {hat_colour}. Apply the colour
naturally so it follows the existing shadows, highlights and fabric texture — a
realistic dyed fabric, not a flat fill. Do NOT change the shape, angle or lighting.

THE PERMITTED CHANGES: recolour the body as above, and add the decoration(s)
below onto the specified panel(s), as though {decoration_kind} applied to this cap.
Do NOT add a person, model or new background. Add nothing not specified below.

DECORATION(S) TO ADD (each placed exactly as noted):
{design_block}

DECORATION STYLE:
Every added decoration must follow the panel's natural curvature, perspective and lighting so it looks physically applied, not like a flat sticker.
{decoration_style}
{pin_block}

OUTPUT — STRICT:
Return ONE photorealistic, SQUARE (1:1) image of the SAME single cap from the SAME
angle as the reference, identical in shape and framing, recoloured as specified and
carrying only the added decoration. The cap must be centred and fill roughly 70-75%
of the frame on a plain, uncluttered background. Render NOTHING ELSE — no title,
caption, label, watermark, second panel, collage, grid, duplicate cap or reference
swatch. One product photo of one cap and nothing more."""
```

- [ ] **Step 3b: Edit `prompt_builder.build_prompt`**

At the top of `build_prompt`, choose the template and compute the colour:

```python
    is_blank = collected.get("flow_mode") == "blank"
    template = prompts.IMAGE_GEN_PROMPT_BLANK if is_blank else prompts.IMAGE_GEN_PROMPT
```

Then replace the final `return prompts.IMAGE_GEN_PROMPT.format(...)` with:

```python
    fmt = dict(
        decoration_kind=decoration_kind,
        design_block=design_block,
        decoration_style=decoration_style,
        pin_block=pin_block,
    )
    if is_blank:
        fmt["hat_colour"] = product_ref.get("colour") or "the customer's chosen colour"
    return template.format(**fmt)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_prompt_builder.py -q`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/app/services/prompt_builder.py backend/tests/test_prompt_builder.py
git commit -m "feat(gen): blank-mode recolour prompt variant"
```

---

## Task 13: Frontend — API client additions

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/admin/adminApi.ts`
- Test: `frontend/src/__tests__/api.test.ts` (add cases)

**Interfaces:**
- Produces (customer `api.ts`): `listHatTypes(): Promise<HatType[]>`, `createBlankSession(hatTypeId, colour): Promise<SessionResponse>`, `postComposite(sessionId): Promise<{views: Record<string,string>; error?: string}>`.
- Produces (`adminApi.ts`): `HatType` interface, `listHatTypes`, `createHatType`, `updateHatType`, `deleteHatType`, `uploadHatAngle`.

- [ ] **Step 1: Write the failing test**

```ts
// add to frontend/src/__tests__/api.test.ts
import { listHatTypes, postComposite } from '../lib/api'

it('listHatTypes GETs /hat-types with store key', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, json: async () => [{ id: 'h1', name: '5-Panel', view_images: {}, colours: [] }],
  })
  vi.stubGlobal('fetch', fetchMock)
  const out = await listHatTypes()
  expect(out[0].name).toBe('5-Panel')
  expect(fetchMock.mock.calls[0][0]).toContain('/hat-types')
})

it('postComposite POSTs /composite/{id}', async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, json: async () => ({ views: { front: 'u' } }),
  })
  vi.stubGlobal('fetch', fetchMock)
  const out = await postComposite('s1')
  expect(out.views.front).toBe('u')
  expect(fetchMock.mock.calls[0][0]).toContain('/composite/s1')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/api.test.ts`
Expected: FAIL (imports undefined).

- [ ] **Step 3a: Add to `api.ts`**

Mirror the existing request helper in `api.ts` (which attaches `X-Store-Key`). Add:

```ts
export interface HatColour { name: string; hex: string }
export interface HatType {
  id: string
  slug: string
  name: string
  style: string
  view_images: Record<string, string>
  colours: HatColour[]
  placement_zones: string[]
  decoration_types: string[]
}

export function listHatTypes(): Promise<HatType[]> {
  return request<HatType[]>('/hat-types')
}

export function createBlankSession(hatTypeId: string, colour: HatColour) {
  return request<{ session_id: string; share_token: string; state: string }>(
    '/sessions/blank',
    { method: 'POST', body: JSON.stringify({ hat_type_id: hatTypeId, colour }) },
  )
}

export function postComposite(sessionId: string) {
  return request<{ views: Record<string, string>; error?: string }>(
    `/composite/${sessionId}`, { method: 'POST' },
  )
}
```

(Use whatever the file's existing `request`/base-URL helper is named; match `createSession`'s pattern.)

- [ ] **Step 3b: Add to `adminApi.ts`**

```ts
export interface HatType {
  id: string
  store_id: string | null
  slug: string
  name: string
  style: string
  description: string | null
  blank_view_images: Record<string, string>
  colours: { name: string; hex: string }[]
  placement_zones: string[]
  decoration_types: string[]
  pricing_slabs: Record<string, unknown>[]
  active: boolean
}

export function listHatTypes(): Promise<HatType[]> {
  return request<HatType[]>('/admin/hat-types')
}
export function createHatType(body: { name: string; slug: string; style?: string }): Promise<HatType> {
  return request<HatType>('/admin/hat-types', { method: 'POST', body: JSON.stringify(body) })
}
export function updateHatType(id: string, body: Partial<HatType>): Promise<HatType> {
  return request<HatType>(`/admin/hat-types/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
}
export function deleteHatType(id: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/hat-types/${id}`, { method: 'DELETE' })
}
export async function uploadHatAngle(id: string, view: string, file: File): Promise<{ blank_view_images: Record<string, string> }> {
  const secret = getSecret()
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE_URL}/admin/hat-types/${id}/angle/${view}`, {
    method: 'POST', headers: { 'X-Admin-Secret': secret ?? '' }, body: form,
  })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.json()
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/api.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/admin/adminApi.ts frontend/src/__tests__/api.test.ts
git commit -m "feat(fe): hat-type + blank-session + composite API clients"
```

---

## Task 14: Frontend — BlankHatPicker + blank bootstrap

**Files:**
- Create: `frontend/src/components/BlankHatPicker/index.tsx`
- Modify: `frontend/src/store/sessionStore.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/BlankHatPicker.test.tsx`

**Interfaces:**
- Consumes: `listHatTypes`, `createBlankSession`.
- Produces: `sessionStore` gains `view: 'blank'` and `startBlankSession(hatTypeId, colour)`; `bootstrapFromUrl` sets `view='blank'` when `?mode=blank`. `App.tsx` renders `<BlankHatPicker/>` when `sessionView === 'blank'`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/BlankHatPicker.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import { BlankHatPicker } from '../components/BlankHatPicker'
import * as api from '../lib/api'
import { vi } from 'vitest'

it('lists hat types from the API', async () => {
  vi.spyOn(api, 'listHatTypes').mockResolvedValue([
    { id: 'h1', slug: '5p', name: '5-Panel', style: '', view_images: { front: 'u' },
      colours: [{ name: 'Black', hex: '#000000' }], placement_zones: [], decoration_types: [] },
  ])
  render(<BlankHatPicker />)
  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/BlankHatPicker.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3a: Add `view: 'blank'` + `startBlankSession` to `sessionStore.ts`**

Extend `SessionView`:

```ts
export type SessionView = 'picker' | 'session' | 'blank'
```

Add to the store:

```ts
  startBlankSession: async (hatTypeId: string, colour: { name: string; hex: string }) => {
    const response = await createBlankSession(hatTypeId, colour)
    set({
      sessionId: response.session_id,
      shareToken: response.share_token,
      state: response.state,
      view: 'session',
    })
  },
```

In `bootstrapFromUrl`, after the resume-token block and before the `product_id` block:

```ts
    if (params.get('mode') === 'blank') {
      set({ view: 'blank' })
      return
    }
```

Import `createBlankSession` at the top from `../lib/api`. Add `startBlankSession` to the `SessionState` interface.

- [ ] **Step 3b: Create `BlankHatPicker`**

```tsx
// frontend/src/components/BlankHatPicker/index.tsx
import { useEffect, useState } from 'react'
import { listHatTypes, type HatType, type HatColour } from '../../lib/api'
import { useSessionStore } from '../../store/sessionStore'

export function BlankHatPicker() {
  const [hats, setHats] = useState<HatType[]>([])
  const [selected, setSelected] = useState<HatType | null>(null)
  const [colour, setColour] = useState<HatColour>({ name: 'Custom', hex: '#1a2b5c' })
  const startBlankSession = useSessionStore(s => s.startBlankSession)

  useEffect(() => { void listHatTypes().then(setHats).catch(() => setHats([])) }, [])

  if (hats.length === 0) {
    return <div className="p-8 text-center text-gray-500">No blank hats available yet.</div>
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h1 className="text-xl font-bold mb-4">Design your hat from scratch</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {hats.map(h => (
          <button key={h.id} onClick={() => setSelected(h)}
            className={`border rounded-lg p-3 ${selected?.id === h.id ? 'ring-2 ring-orange-500' : ''}`}>
            {h.view_images.front && <img src={h.view_images.front} alt={h.name} className="w-full h-32 object-contain" />}
            <div className="mt-2 text-sm font-medium">{h.name}</div>
          </button>
        ))}
      </div>

      {selected && (
        <div className="mt-6">
          <label className="block text-sm font-medium mb-2">Hat colour</label>
          <div className="flex items-center gap-3 mb-3">
            <input type="color" value={colour.hex}
              onChange={e => setColour({ name: e.target.value, hex: e.target.value })} />
            <div className="flex gap-2">
              {selected.colours.map(c => (
                <button key={c.hex} title={c.name} onClick={() => setColour(c)}
                  className="w-7 h-7 rounded-full border" style={{ background: c.hex }} />
              ))}
            </div>
          </div>
          <button onClick={() => startBlankSession(selected.id, colour)}
            className="bg-orange-500 text-white font-semibold px-5 py-2.5 rounded-lg">
            Start designing
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3c: Wire `App.tsx`**

Add near the session-view check:

```tsx
import { BlankHatPicker } from './components/BlankHatPicker'
// ...
  if (sessionView === 'blank') {
    return <BlankHatPicker />
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/BlankHatPicker.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BlankHatPicker frontend/src/store/sessionStore.ts frontend/src/App.tsx frontend/src/__tests__/BlankHatPicker.test.tsx
git commit -m "feat(fe): BlankHatPicker + mode=blank bootstrap"
```

---

## Task 15: Frontend — composite preview in ChatPanel + ProductViewer angles

**Files:**
- Modify: `frontend/src/components/ChatPanel/index.tsx`
- Modify: `frontend/src/components/ProductViewer/index.tsx`
- Test: `frontend/src/__tests__/ChatPanel.test.tsx` (add a case)

**Interfaces:**
- Consumes: `postComposite`, chat `data.composite_preview` flag from `_public_data`.
- Produces: when the chat state's `data.composite_preview` is true, ChatPanel calls `postComposite(sessionId)` once and renders the returned 4 angle images above the confirm/tweak option chips; ProductViewer prefers `composite_views` for non-front angles when present.

- [ ] **Step 1: Write the failing test**

```tsx
// add to frontend/src/__tests__/ChatPanel.test.tsx
// (follow the file's existing render/store-seeding pattern)
it('fetches and shows the composite preview when data.composite_preview is set', async () => {
  vi.spyOn(api, 'postComposite').mockResolvedValue({ views: { front: 'f', back: 'b', left: 'l', right: 'r' } })
  // seed chat store with a message whose data = { composite_preview: true, options: [...] }
  // render ChatPanel, then:
  await waitFor(() => expect(api.postComposite).toHaveBeenCalled())
  await waitFor(() => expect(screen.getAllByAltText(/preview/i).length).toBeGreaterThan(0))
})
```

Adapt the seeding to the existing `ChatPanel.test.tsx` harness (it already renders the panel with a mocked chat store; reuse that setup and set the latest assistant message's `data`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ChatPanel.test.tsx -t composite`
Expected: FAIL (no composite rendering yet).

- [ ] **Step 3a: ChatPanel — fetch + render composite**

In the component, add state and an effect keyed on the current chat `data`:

```tsx
const [composite, setComposite] = useState<Record<string, string> | null>(null)
// `data` is the latest assistant message's data payload already used for option chips
useEffect(() => {
  if (data?.composite_preview && sessionId && !composite) {
    void postComposite(sessionId).then(r => setComposite(r.views)).catch(() => setComposite({}))
  }
}, [data?.composite_preview, sessionId, composite])
```

Render above the option chips when `composite` is set:

```tsx
{composite && (
  <div className="grid grid-cols-2 gap-2 my-3">
    {(['front', 'back', 'left', 'right'] as const).map(v =>
      composite[v] ? <img key={v} src={composite[v]} alt={`${v} preview`} className="w-full rounded border" /> : null,
    )}
  </div>
)}
```

Reset `composite` to `null` when the state moves off `composite_preview` (so a later "Tweak → back" re-fetches): clear it in the same effect when `!data?.composite_preview`.

Import `postComposite` from `../../lib/api`.

- [ ] **Step 3b: ProductViewer — prefer composite_views for angles**

Where the viewer picks angle images, accept an optional `compositeViews?: Record<string,string>` prop (or read it from the session/generation store used to show angles) and, when present, use `compositeViews[angle]` for back/left/right while keeping the AI hero for front. Keep the existing behaviour when `compositeViews` is absent (customise flow untouched).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ChatPanel.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatPanel/index.tsx frontend/src/components/ProductViewer/index.tsx frontend/src/__tests__/ChatPanel.test.tsx
git commit -m "feat(fe): composite preview in chat + angle display"
```

---

## Task 16: Frontend — admin HatTypesView + nav

**Files:**
- Create: `frontend/src/admin/views/HatTypesView.tsx`
- Modify: `frontend/src/admin/AdminLayout.tsx` (nav link)
- Modify: `frontend/src/admin/AdminApp.tsx` (route)
- Test: `frontend/src/admin/views/HatTypesView.test.tsx`

**Interfaces:**
- Consumes: `adminApi` hat-type functions from Task 13.
- Produces: `HatTypesView` — list + create + a detail editor with 4 angle upload inputs, a colour-list editor, zone/decoration checkboxes, and an active toggle (disabled until all 4 angles present); reachable from admin nav at `/admin/hat-types`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/admin/views/HatTypesView.test.tsx
import { render, screen, waitFor } from '@testing-library/react'
import { HatTypesView } from './HatTypesView'
import * as adminApi from '../adminApi'
import { vi } from 'vitest'

it('lists hat types', async () => {
  vi.spyOn(adminApi, 'listHatTypes').mockResolvedValue([{
    id: 'h1', store_id: 's1', slug: '5p', name: '5-Panel', style: '', description: null,
    blank_view_images: {}, colours: [], placement_zones: [], decoration_types: [],
    pricing_slabs: [], active: false,
  }])
  render(<HatTypesView />)
  await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/HatTypesView.test.tsx`
Expected: FAIL (component missing).

- [ ] **Step 3a: Create `HatTypesView.tsx`**

Follow the structure of `StoresView.tsx` (list + create form). Minimum viable implementation:

```tsx
// frontend/src/admin/views/HatTypesView.tsx
import { useEffect, useState } from 'react'
import {
  listHatTypes, createHatType, updateHatType, uploadHatAngle, type HatType,
} from '../adminApi'

const VIEWS = ['front', 'back', 'left', 'right'] as const

export function HatTypesView() {
  const [hats, setHats] = useState<HatType[]>([])
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')

  const reload = () => listHatTypes().then(setHats).catch(() => setHats([]))
  useEffect(() => { void reload() }, [])

  const create = async () => {
    if (!name || !slug) return
    await createHatType({ name, slug })
    setName(''); setSlug(''); await reload()
  }

  const upload = async (id: string, view: string, file: File) => {
    await uploadHatAngle(id, view, file); await reload()
  }

  const allAngles = (h: HatType) => VIEWS.every(v => h.blank_view_images[v])

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Hat Types</h1>
      <div className="flex gap-2 mb-6">
        <input placeholder="Name" value={name} onChange={e => setName(e.target.value)} className="border p-2 rounded" />
        <input placeholder="slug" value={slug} onChange={e => setSlug(e.target.value)} className="border p-2 rounded" />
        <button onClick={create} className="bg-orange-500 text-white px-4 rounded">Add</button>
      </div>

      {hats.map(h => (
        <div key={h.id} className="border rounded-lg p-4 mb-4">
          <div className="flex items-center justify-between">
            <div className="font-semibold">{h.name} <span className="text-gray-400">({h.slug})</span></div>
            <label className="text-sm flex items-center gap-2">
              <input type="checkbox" checked={h.active}
                disabled={!allAngles(h)}
                onChange={e => updateHatType(h.id, { active: e.target.checked }).then(reload)} />
              Active {!allAngles(h) && <span className="text-xs text-gray-400">(needs all 4 angles)</span>}
            </label>
          </div>
          <div className="grid grid-cols-4 gap-3 mt-3">
            {VIEWS.map(v => (
              <div key={v} className="text-center">
                <div className="text-xs uppercase text-gray-500">{v}</div>
                {h.blank_view_images[v]
                  ? <div className="text-green-600 text-xs">uploaded</div>
                  : <div className="text-gray-300 text-xs">—</div>}
                <input type="file" accept="image/*"
                  onChange={e => e.target.files?.[0] && upload(h.id, v, e.target.files[0])}
                  className="text-xs mt-1" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
```

(The colour-list editor and zone/decoration checkboxes follow the same `updateHatType(h.id, { colours }|{ placement_zones })` pattern — add them as follow-up controls in this same view; the active toggle + angle uploads are the required baseline for the test.)

- [ ] **Step 3b: Add nav + route**

In `AdminLayout.tsx`, add a nav link to `/admin/hat-types` labelled "Hat Types" alongside the existing links. In `AdminApp.tsx`, add the route rendering `<HatTypesView />` (follow how `StoresView` is routed).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/HatTypesView.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/HatTypesView.tsx frontend/src/admin/AdminLayout.tsx frontend/src/admin/AdminApp.tsx frontend/src/admin/views/HatTypesView.test.tsx
git commit -m "feat(admin-fe): HatTypesView with angle uploads + active gating"
```

---

## Task 17: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: all pass (252 prior + new tests). Investigate any failure before proceeding.

- [ ] **Step 2: Frontend suite**

Run: `cd frontend && npx vitest run`
Expected: prior 118 (minus the 2 known-unrelated `adminQuotes` Router failures) + new tests pass.

- [ ] **Step 3: Manual smoke (blank flow)**

With the stack up (`docker compose up`, `npx supabase start`):
1. Admin: create a hat type at `/admin/hat-types`, upload 4 angle images, add a colour, set active.
2. Visit `/?mode=blank` → pick the hat + a colour → start designing.
3. Walk the chat to the composite preview → confirm 4 angles render → generate → verify email gate → design shows front hero + composite angles.

Expected: no dead-ends; customise flow (`?product_id=`) still works unchanged.

- [ ] **Step 4: Commit any fixes, then update CLAUDE.md**

Add a short "Blank-hat design flow" bullet to CLAUDE.md §13 current-implementation-state describing `flow_mode`, `hat_types`, the composite preview, and the recolour prompt.

```bash
git add CLAUDE.md
git commit -m "docs: note blank-hat design flow in project memory"
```

---

## Self-Review Notes

- **Spec coverage:** hat_types table + flow_mode (T1) ✓; admin CRUD + uploads (T4) ✓; customer GET /hat-types (T5) ✓; blank entry + session (T6, T14) ✓; ASK_HAT_COLOUR + COMPOSITE_PREVIEW states (T7) ✓; goal-planner blank branch + orchestrator (T8) ✓; composite service + route (T10, T11) ✓; recolour prompt (T12) ✓; front-hero-only generation (unchanged path, prompt in T12) ✓; admin frontend (T16) ✓; edge cases — composite failure fallback (T11), active-gating (T4/T16), no-hats empty state (T14) ✓; tests (all tasks) ✓; rollout order (T1→T16) ✓.
- **Placeholder scan:** all code steps contain complete code; the colour-list/zone editors in T16 and the ProductViewer wiring in T15 are described against a concrete existing pattern with the exact API call to use — no "TBD".
- **Type consistency:** `render_composite_views(view_paths, colour_hex, elements)` used identically in T10/T11; `HatType.view_images` (customer) vs `blank_view_images` (admin) named distinctly and consistently; `composite_preview`/`colour_picker` data flags match between `_public_data` (T8) and ChatPanel (T15); `flow_mode`/`hat_colour`/`composite_confirmed`/`composite_views` collected keys consistent across T6/T8/T10/T11/T12.
