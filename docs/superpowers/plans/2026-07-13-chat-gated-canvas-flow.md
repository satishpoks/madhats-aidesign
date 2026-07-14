# Chat-Gated Canvas Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chat lead the canvas Design Studio — greet → name → email(+verify) → purpose → quantity → *unlock* the canvas → "Done designing" → decoration (admin list, multi-select) → notes → generate.

**Architecture:** Reuse the existing state machine + split-screen `CustomiseStudio`. A canvas session now starts at `GREETING` (not `canvas_design`); a dedicated canvas branch in the goal planner drives a linear intro/outro; `canvas-finalize` routes to a new `ASK_DECORATION` step instead of `generating`. Decoration types are a new store-scoped table with admin CRUD. Every new branch is gated by `flow_mode == 'canvas'` so the non-canvas Q&A paths are untouched.

**Tech Stack:** Python 3.12 / FastAPI, supabase-py (no ORM), Supabase Postgres migrations; React 18 / Vite / Zustand / Tailwind; Konva canvas.

## Global Constraints

- **supabase-py only** — no raw SQL strings in app code; schema changes go in `backend/supabase/migrations/` (no Alembic/SQLAlchemy). — CLAUDE.md §3
- **Store-scoped admin routes require BOTH `X-Admin-Secret` AND `X-Store-Key`.** — CLAUDE.md §13
- **No PII in logs** (name/email never logged). — CLAUDE.md §8.10
- **No secrets in code**; env vars only. — CLAUDE.md §8.1
- **Non-canvas Q&A conversation must not change** — every new branch is `flow_mode == 'canvas'`-gated.
- **Decoration list is admin-managed per store** and served from the backend (`GET /decoration-types`).
- **Decoration is always asked**, multi-select, with a **cost caveat when 2+** selected (message only — no live pricing).
- Backend tests: `pytest -q`. Frontend tests: `npx vitest run` (never `npm test` — watch mode hangs). Both suites must stay green.
- Spec: `docs/superpowers/specs/2026-07-13-chat-gated-canvas-flow-design.md`.

---

## Task 1: `decoration_types` table + seed

**Files:**
- Create: `backend/supabase/migrations/20260713000004_decoration_types.sql`
- Modify: `backend/supabase/seed.sql` (append default rows for the local store)

**Interfaces:**
- Produces: table `decoration_types(id, store_id, name, sort_order, active, created_at)`.

- [ ] **Step 1: Write the migration**

Create `backend/supabase/migrations/20260713000004_decoration_types.sql`:

```sql
-- Decoration types: admin-managed, per-store list of decoration methods
-- (embroidery, print, patch, …) offered to the customer AFTER they design on
-- the canvas. Store-scoped (multi-tenant). Mirrors the graphics table pattern.

create table if not exists decoration_types (
  id         uuid primary key default gen_random_uuid(),
  store_id   uuid references stores(id) on delete cascade,
  name       text not null,
  sort_order int  not null default 0,
  active     bool not null default true,
  created_at timestamptz not null default now()
);
create unique index if not exists idx_decoration_types_store_name
  on decoration_types(store_id, lower(name));
create index if not exists idx_decoration_types_store on decoration_types(store_id);

-- RLS: service_role full; anon may read only ACTIVE rows (customer chip list).
alter table decoration_types enable row level security;
drop policy if exists decoration_types_read_anon on decoration_types;
create policy decoration_types_read_anon on decoration_types
  for select to anon, authenticated using (active = true);

grant select on decoration_types to anon, authenticated;
grant all privileges on decoration_types to service_role;
```

- [ ] **Step 2: Seed default rows**

In `backend/supabase/seed.sql`, find where the local store row is inserted (search for the store insert / `mh_pk_madhats_local`). After the store exists, append (adjust the store lookup to match the file's existing style — the file already references the local store id/public_key elsewhere; reuse that pattern):

```sql
-- Default decoration types for the local dev store.
insert into decoration_types (store_id, name, sort_order)
select s.id, v.name, v.ord
from stores s
cross join (values ('Embroidery', 0), ('Print', 1), ('Patch', 2), ('Vinyl', 3)) as v(name, ord)
where s.public_key = 'mh_pk_madhats_local'
on conflict do nothing;
```

- [ ] **Step 3: Apply and verify locally**

Run: `cd backend && npx supabase db reset`
Expected: migrations + seed apply with no error; `decoration_types` exists with 4 rows for the local store.

Verify: `npx supabase db reset` prints success; optionally in Studio (`http://localhost:54323`) the `decoration_types` table shows Embroidery/Print/Patch/Vinyl.

- [ ] **Step 4: Commit**

```bash
git add backend/supabase/migrations/20260713000004_decoration_types.sql backend/supabase/seed.sql
git commit -m "feat(db): decoration_types table + seed defaults"
```

---

## Task 2: Decoration-types service + models

**Files:**
- Create: `backend/app/services/decoration_types.py`
- Create: `backend/app/models/decoration_type.py`
- Test: `backend/tests/test_decoration_types_service.py`

**Interfaces:**
- Produces:
  - `services.decoration_types.list_types(store_id: str, active_only: bool = False) -> list[dict]`
  - `services.decoration_types.create_type(store_id: str, name: str) -> dict`
  - `services.decoration_types.delete_type(type_id: str) -> None`
  - `models.decoration_type.DecorationTypePublic(id: str, name: str)`
  - `models.decoration_type.DecorationTypeAdmin(id: str, name: str, active: bool, sort_order: int)`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decoration_types_service.py`:

```python
"""Unit tests for the decoration_types service (supabase-py mocked)."""
from __future__ import annotations

from app.services import decoration_types as svc


class _FakeQuery:
    def __init__(self, store):
        self._store = store
        self._filters = {}
    def select(self, *_a):
        return self
    def eq(self, col, val):
        self._filters[col] = val
        return self
    def order(self, *_a, **_k):
        return self
    def execute(self):
        rows = [r for r in self._store if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": rows})()
    def insert(self, row):
        row = {"id": "d1", "sort_order": 0, "active": True, **row}
        self._store.append(row)
        self._pending = [row]
        return self
    def delete(self):
        self._delete = True
        return self


class _FakeSB:
    def __init__(self, store):
        self._store = store
    def table(self, _name):
        return _FakeQuery(self._store)


def test_list_active_only(monkeypatch):
    store = [
        {"id": "a", "store_id": "s1", "name": "Embroidery", "active": True},
        {"id": "b", "store_id": "s1", "name": "Old", "active": False},
    ]
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSB(store))
    rows = svc.list_types("s1", active_only=True)
    assert [r["name"] for r in rows] == ["Embroidery"]


def test_list_all(monkeypatch):
    store = [
        {"id": "a", "store_id": "s1", "name": "Embroidery", "active": True},
        {"id": "b", "store_id": "s1", "name": "Old", "active": False},
    ]
    monkeypatch.setattr(svc, "get_supabase", lambda: _FakeSB(store))
    assert len(svc.list_types("s1")) == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_decoration_types_service.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.decoration_types`.

- [ ] **Step 3: Write the model**

Create `backend/app/models/decoration_type.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class DecorationTypePublic(BaseModel):
    id: str
    name: str


class DecorationTypeAdmin(BaseModel):
    id: str
    name: str
    active: bool
    sort_order: int
```

- [ ] **Step 4: Write the service**

Create `backend/app/services/decoration_types.py`:

```python
"""Decoration-types access (admin-managed, per store). supabase-py only."""
from __future__ import annotations

from app.db import get_supabase


def list_types(store_id: str, active_only: bool = False) -> list[dict]:
    q = get_supabase().table("decoration_types").select("*").eq("store_id", store_id)
    if active_only:
        q = q.eq("active", True)
    return q.order("sort_order").order("created_at").execute().data or []


def create_type(store_id: str, name: str) -> dict:
    row = {"store_id": store_id, "name": name}
    return get_supabase().table("decoration_types").insert(row).execute().data[0]


def delete_type(type_id: str) -> None:
    get_supabase().table("decoration_types").delete().eq("id", type_id).execute()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_decoration_types_service.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/decoration_types.py backend/app/models/decoration_type.py backend/tests/test_decoration_types_service.py
git commit -m "feat(backend): decoration_types service + models"
```

---

## Task 3: Decoration-types routes (customer + admin) + registration

**Files:**
- Create: `backend/app/api/routes/decoration_types.py` (customer `GET /decoration-types`)
- Create: `backend/app/api/routes/admin_decoration_types.py` (admin CRUD)
- Modify: `backend/app/main.py` (import + include both routers)
- Test: `backend/tests/test_decoration_types_route.py`

**Interfaces:**
- Consumes: `services.decoration_types.*` (Task 2), `app.api.deps.require_store`, `app.api.deps.require_admin`.
- Produces HTTP:
  - `GET /decoration-types` → `[{id, name}]` (active only, `X-Store-Key`)
  - `GET /admin/decoration-types` → `[{id, name, active, sort_order}]` (`X-Admin-Secret` + `X-Store-Key`)
  - `POST /admin/decoration-types` body `{"name": str}` → `{id, name, active, sort_order}`
  - `DELETE /admin/decoration-types/{id}` → `{"deleted": true}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_decoration_types_route.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.services import decoration_types as svc


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("app.api.deps.resolve_store", lambda k: {"id": "s1"} if k else None)
    monkeypatch.setattr(svc, "list_types", lambda s, active_only=False: [
        {"id": "d1", "name": "Embroidery", "active": True, "sort_order": 0},
        {"id": "d2", "name": "Print", "active": True, "sort_order": 1},
    ])
    monkeypatch.setattr(svc, "create_type", lambda s, name: {
        "id": "d9", "name": name, "active": True, "sort_order": 0})
    monkeypatch.setattr(svc, "delete_type", lambda i: None)
    from app.main import create_app
    return TestClient(create_app())


def test_customer_requires_store_key(client):
    assert client.get("/decoration-types").status_code == 401


def test_customer_lists_active(client):
    r = client.get("/decoration-types", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    assert [x["name"] for x in r.json()] == ["Embroidery", "Print"]
    # public shape has no active/sort_order
    assert set(r.json()[0].keys()) == {"id", "name"}


def test_admin_requires_secret(client):
    # store key present but no admin secret → gated
    r = client.get("/admin/decoration-types", headers={"X-Store-Key": "k"})
    assert r.status_code in (401, 403)


def test_admin_crud(client, monkeypatch):
    monkeypatch.setattr("app.api.deps.verify_admin_secret", lambda s: s == "sekret")
    h = {"X-Admin-Secret": "sekret", "X-Store-Key": "k"}
    assert client.get("/admin/decoration-types", headers=h).status_code == 200
    r = client.post("/admin/decoration-types", json={"name": "Vinyl"}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Vinyl"
    assert client.delete("/admin/decoration-types/d1", headers=h).json() == {"deleted": True}
```

> NOTE: `verify_admin_secret` is the function `require_admin` uses. Confirm its
> name by opening `backend/app/api/deps.py`; if the admin gate helper is named
> differently (e.g. it reads `settings.admin_secret` directly), monkeypatch
> `app.config.settings.admin_secret` to `"sekret"` instead. Adjust this one line
> to match the repo.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_decoration_types_route.py -q`
Expected: FAIL — routes not found (404) / import error.

- [ ] **Step 3: Write the customer route**

Create `backend/app/api/routes/decoration_types.py`:

```python
"""Customer-facing decoration-type list (tenant-scoped via X-Store-Key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_store
from app.models.decoration_type import DecorationTypePublic
from app.services import decoration_types as svc

router = APIRouter(tags=["decoration-types"])


@router.get("/decoration-types", response_model=list[DecorationTypePublic])
async def list_decoration_types(store: dict = Depends(require_store)) -> list[dict]:
    return [
        {"id": r["id"], "name": r.get("name") or ""}
        for r in svc.list_types(store["id"], active_only=True)
    ]
```

- [ ] **Step 4: Write the admin route**

Create `backend/app/api/routes/admin_decoration_types.py`:

```python
"""Admin decoration-type management. Gated by X-Admin-Secret + X-Store-Key."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin, require_store
from app.models.decoration_type import DecorationTypeAdmin
from app.services import decoration_types as svc

router = APIRouter(tags=["admin-decoration-types"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


class CreateDecorationTypeBody(BaseModel):
    name: str


def _to_admin(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "active": bool(row.get("active", True)),
        "sort_order": row.get("sort_order", 0),
    }


@router.get("/admin/decoration-types", response_model=list[DecorationTypeAdmin])
async def list_decoration_types(store: dict = Depends(require_store)) -> list[dict]:
    return [_to_admin(r) for r in svc.list_types(store["id"])]


@router.post("/admin/decoration-types", response_model=DecorationTypeAdmin)
async def create_decoration_type(
    body: CreateDecorationTypeBody, store: dict = Depends(require_store)
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    row = svc.create_type(store["id"], name)
    log.info("decoration_type_created", store_id=store["id"])  # no PII
    return _to_admin(row)


@router.delete("/admin/decoration-types/{type_id}")
async def delete_decoration_type(
    type_id: str, store: dict = Depends(require_store)
) -> dict:
    svc.delete_type(type_id)
    return {"deleted": True}
```

- [ ] **Step 5: Register both routers**

In `backend/app/main.py`, add to the `from app.api.routes import (...)` block (Task-relevant lines ~18-40): add `admin_decoration_types,` and `decoration_types,` (keep alphabetical grouping). Then in the `include_router` tuple (lines ~100-119) add:

```python
        decoration_types.router,
        admin_decoration_types.router,
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_decoration_types_route.py -q`
Expected: PASS (4 passed).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/decoration_types.py backend/app/api/routes/admin_decoration_types.py backend/app/main.py backend/tests/test_decoration_types_route.py
git commit -m "feat(backend): decoration-types customer + admin routes"
```

---

## Task 4: State machine — ASK_DECORATION, ASK_NOTES, CANVAS_DESIGN branch, canvas progress

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py`
- Test: `backend/tests/test_state_machine.py` (add cases)

**Interfaces:**
- Produces: `ConversationState.ASK_DECORATION` (`"ask_decoration"`), `ConversationState.ASK_NOTES` (`"ask_notes"`); `advance_state` branches for `CANVAS_DESIGN`, `ASK_DECORATION`, `ASK_NOTES`; `progress()` canvas path.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_state_machine.py`:

```python
def test_canvas_design_waits_until_finalized():
    assert advance_state(S.CANVAS_DESIGN, {}) is S.CANVAS_DESIGN
    assert advance_state(S.CANVAS_DESIGN, {"canvas_finalized": True}) is S.ASK_DECORATION


def test_decoration_then_notes_then_generating():
    assert advance_state(S.ASK_DECORATION, {}) is S.ASK_NOTES
    assert advance_state(S.ASK_NOTES, {}) is S.GENERATING


def test_canvas_progress_path():
    collected = {"flow_mode": "canvas"}
    p = progress(S.ASK_DECORATION, collected)
    assert p["total"] == 7          # name,email,purpose,quantity,design,decoration,notes
    assert 1 <= p["step"] <= p["total"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_state_machine.py -q -k "canvas or decoration_then"`
Expected: FAIL — `AttributeError: ASK_DECORATION` / wrong routing.

- [ ] **Step 3: Add the enum members**

In `state_machine.py`, in `class ConversationState`, add after `CANVAS_DESIGN`:

```python
    ASK_DECORATION = "ask_decoration"
    ASK_NOTES = "ask_notes"
```

- [ ] **Step 4: Add transitions**

In the `TRANSITIONS` dict, add these entries (place near `S.CANVAS_DESIGN`):

```python
    S.CANVAS_DESIGN: [S.ASK_DECORATION],
    S.ASK_DECORATION: [S.ASK_NOTES],
    S.ASK_NOTES: [S.GENERATING],
```

- [ ] **Step 5: Add the CANVAS_DESIGN branch to advance_state**

In `advance_state`, add (before the `# --- Default:` fallthrough):

```python
    # --- Canvas: rest at CANVAS_DESIGN until the canvas is finalized ---
    if current is S.CANVAS_DESIGN:
        return S.ASK_DECORATION if collected.get("canvas_finalized") else S.CANVAS_DESIGN
```

(`ASK_DECORATION → ASK_NOTES` and `ASK_NOTES → GENERATING` fall through to the
default "first declared successor" using the TRANSITIONS added in Step 4.)

- [ ] **Step 6: Add QUESTION_FIELD entries**

In `QUESTION_FIELD`, add:

```python
    ConversationState.ASK_DECORATION: "decoration_done",
    ConversationState.ASK_NOTES: "notes_done",
```

- [ ] **Step 7: Add the canvas progress path**

In `_progress_path`, at the very top of the function body add:

```python
    if collected.get("flow_mode") == "canvas":
        return [
            S.ASK_NAME, S.SAVE_PROGRESS_EMAIL, S.ASK_PURPOSE, S.ASK_QUANTITY,
            S.CANVAS_DESIGN, S.ASK_DECORATION, S.ASK_NOTES,
        ]
```

Then in `progress()`, ensure `CANVAS_DESIGN`, `ASK_DECORATION`, `ASK_NOTES` are
handled: they are in the canvas path so `norm in path` matches directly. Also add
`ASK_NOTES` to `_POST_QUESTION_STATES`? No — it is in the canvas path, so leave it.
Add `S.CANVAS_DESIGN` to the non-canvas `_POST_QUESTION_STATES` set is NOT needed
(canvas path owns it). No other change.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_state_machine.py -q`
Expected: PASS (all, including the 3 new).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(conversation): ASK_DECORATION/ASK_NOTES states + canvas branch"
```

---

## Task 5: Goal planner — canvas branch

**Files:**
- Modify: `backend/app/services/conversation/goal_planner.py`
- Test: `backend/tests/test_goal_planner.py` (add cases)

**Interfaces:**
- Consumes: state-machine members from Task 4.
- Produces: `goal_planner._canvas_next_goal(collected: dict) -> ConversationState`; `next_goal` dispatches to it when `flow_mode == 'canvas'`. Adds `CANVAS_DESIGN`, `ASK_DECORATION`, `ASK_NOTES` to `GATE_STATES`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_goal_planner.py` (match the file's existing import of `next_goal`):

```python
from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation.goal_planner import next_goal


def test_canvas_intro_sequence():
    assert next_goal({"flow_mode": "canvas"}) is S.ASK_NAME
    assert next_goal({"flow_mode": "canvas", "name": "Sam"}) is S.SAVE_PROGRESS_EMAIL
    c = {"flow_mode": "canvas", "name": "Sam", "email_prompt_shown": True}
    assert next_goal(c) is S.ASK_PURPOSE
    c = {**c, "purpose_asked": True}
    assert next_goal(c) is S.ASK_QUANTITY
    c = {**c, "quantity": 12}
    assert next_goal(c) is S.CANVAS_DESIGN


def test_canvas_outro_sequence():
    base = {"flow_mode": "canvas", "name": "Sam", "email_prompt_shown": True,
            "purpose_asked": True, "quantity": 12, "canvas_finalized": True}
    assert next_goal(base) is S.ASK_DECORATION
    assert next_goal({**base, "decoration_done": True}) is S.ASK_NOTES
    assert next_goal({**base, "decoration_done": True, "notes_done": True}) is S.GENERATING
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && pytest tests/test_goal_planner.py -q -k canvas`
Expected: FAIL — non-canvas planner returns wrong states.

- [ ] **Step 3: Add `_canvas_next_goal` and dispatch**

In `goal_planner.py`, add before `def next_goal`:

```python
def _canvas_next_goal(collected: dict) -> S:
    """Linear intro/outro for canvas sessions: name → email → purpose →
    quantity → design (rest) → decoration → notes → generate."""
    if not collected.get("name"):
        return S.ASK_NAME
    if not collected.get("email_prompt_shown"):
        return S.SAVE_PROGRESS_EMAIL
    if not collected.get("purpose") and not collected.get("purpose_asked"):
        return S.ASK_PURPOSE
    if "quantity" not in collected:
        return S.ASK_QUANTITY
    if not collected.get("canvas_finalized"):
        return S.CANVAS_DESIGN
    if not collected.get("decoration_done"):
        return S.ASK_DECORATION
    if not collected.get("notes_done"):
        return S.ASK_NOTES
    return S.GENERATING
```

Then at the top of `next_goal`'s body (first lines, before the `# 1. name` block):

```python
    if collected.get("flow_mode") == "canvas":
        return _canvas_next_goal(collected)
```

- [ ] **Step 4: Add the new gate states**

In the `GATE_STATES` frozenset add:

```python
        S.CANVAS_DESIGN,
        S.ASK_DECORATION,
        S.ASK_NOTES,
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_goal_planner.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/goal_planner.py backend/tests/test_goal_planner.py
git commit -m "feat(conversation): canvas goal-planner branch"
```

---

## Task 6: Prompts — canned replies + instructions for the new states

**Files:**
- Modify: `backend/app/prompts.py`

**Interfaces:**
- Produces: `CANNED_REPLIES` + `STATE_PROMPTS` entries for `canvas_design`, `ask_decoration`, `ask_notes` (used by `ie.generate_reply`).

- [ ] **Step 1: Add CANNED_REPLIES entries**

In `CANNED_REPLIES` (dict starting ~line 266), add:

```python
    "canvas_design": (
        "You're all set — design your hat on the left. Add text, upload images, "
        "pick colours and place them on any side. Tap 'Done designing' when you're "
        "happy, or tell me here if you'd rather describe what you want."
    ),
    "ask_decoration": (
        "Love it! How would you like this decorated? Pick any that apply — "
        "just remember each extra decoration adds to the cost."
    ),
    "ask_notes": (
        "Almost there! Any final notes for our team before I generate your design — "
        "special requests, colours to match, deadlines? If not, tap 'No, generate'."
    ),
```

- [ ] **Step 2: Add STATE_PROMPTS entries**

In `STATE_PROMPTS` (dict starting ~line 37), add:

```python
    "canvas_design": (
        "Tell the customer their design tools are unlocked on the left — they can add "
        "text, upload images, pick colours, and design on any side — and to tap "
        "'Done designing' when ready, or describe it here instead. One or two sentences."
    ),
    "ask_decoration": (
        "Ask how they'd like the design decorated, noting they can pick more than one "
        "and that each extra decoration adds to the cost. One or two warm sentences."
    ),
    "ask_notes": (
        "Ask if they have any final notes for the team before you generate the design "
        "(special requests, colour matching, deadlines), making clear they can skip. "
        "One or two sentences."
    ),
```

- [ ] **Step 3: Verify import still loads**

Run: `cd backend && python -c "from app import prompts; assert 'ask_decoration' in prompts.CANNED_REPLIES and 'ask_notes' in prompts.STATE_PROMPTS; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add backend/app/prompts.py
git commit -m "feat(prompts): canvas_design/ask_decoration/ask_notes copy"
```

---

## Task 7: Orchestrator — capture decoration + notes, skip CONFIRM_BRIEF for canvas, public data

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: `backend/tests/test_conversation_smart.py` (add cases) OR a new `backend/tests/test_canvas_conversation.py`

**Interfaces:**
- Consumes: state-machine + goal-planner canvas branch (Tasks 4-5); `collected["decoration_options"]` (list of names, set by Task 8 finalize).
- Produces: capture logic writing `collected["decoration_types"]` (list), `decoration_done`, `notes`, `notes_done`; `_state_public_data` returns for `ASK_DECORATION`/`ASK_NOTES`/`CANVAS_DESIGN`; folds decoration + notes into `brief_notes` and sets `decoration_type` for the style modifier.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_canvas_conversation.py`:

```python
"""Canvas decoration/notes capture in the orchestrator (pure helpers)."""
from __future__ import annotations

from app.services.conversation import orchestrator as orch
from app.services.conversation.state_machine import ConversationState as S


def test_public_data_ask_decoration_multiselect():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery", "Print"],
                 "decoration_types": ["Embroidery"]}
    data = orch._state_public_data(S.ASK_DECORATION, collected)
    assert data["options"] == ["Embroidery", "Print"]
    assert data["multiselect"] is True
    assert data["selected"] == ["Embroidery"]


def test_public_data_ask_notes_has_skip_chip():
    data = orch._state_public_data(S.ASK_NOTES, {"flow_mode": "canvas"})
    assert "No, generate" in data["options"]


def test_capture_decoration_matches_options_and_marks_done():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery", "Print", "Patch"]}
    orch._apply_canvas_outro(S.ASK_DECORATION, collected, "Embroidery, Print")
    assert collected["decoration_types"] == ["Embroidery", "Print"]
    assert collected["decoration_done"] is True
    # folded into the brief + style modifier chosen
    assert any("Embroidery" in n for n in collected["brief_notes"])
    assert collected["decoration_type"] == "embroidery"


def test_capture_decoration_none_still_advances():
    collected = {"flow_mode": "canvas", "decoration_options": ["Embroidery"]}
    orch._apply_canvas_outro(S.ASK_DECORATION, collected, "none")
    assert collected["decoration_types"] == []
    assert collected["decoration_done"] is True


def test_capture_notes_records_and_skips():
    c1 = {"flow_mode": "canvas"}
    orch._apply_canvas_outro(S.ASK_NOTES, c1, "Match pantone 185C please")
    assert c1["notes_done"] is True
    assert "Match pantone" in " ".join(c1["brief_notes"])

    c2 = {"flow_mode": "canvas"}
    orch._apply_canvas_outro(S.ASK_NOTES, c2, "No, generate")
    assert c2["notes_done"] is True
    assert not c2.get("brief_notes")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_conversation.py -q`
Expected: FAIL — `_apply_canvas_outro` not defined; `_state_public_data` missing the new-state branches.

- [ ] **Step 3: Add `_apply_canvas_outro`**

In `orchestrator.py`, add near the other `_apply_*` helpers (after `_apply_brief_confirm`):

```python
# Map a decoration name to the prompt style modifier bucket. Anything not
# recognised falls back to print (the safe default the prompt builder uses).
_DECORATION_STYLE_MAP = (
    ("embroider", "embroidery"),
    ("stitch", "embroidery"),
    ("patch", "embroidery"),   # patches render like stitched appliqué
    ("print", "print"),
    ("vinyl", "print"),
    ("transfer", "print"),
    ("screen", "print"),
)


def _decoration_style_bucket(name: str) -> str:
    low = (name or "").lower()
    for kw, bucket in _DECORATION_STYLE_MAP:
        if kw in low:
            return bucket
    return "print"


def _apply_canvas_outro(state: ConversationState, collected: dict, message: str) -> None:
    """Capture the canvas outro answers (decoration multi-select, then notes)."""
    S = ConversationState
    text = (message or "").strip()
    low = text.lower()

    if state is S.ASK_DECORATION:
        options = collected.get("decoration_options") or []
        # Match any offered option named in the (comma-joined) message.
        chosen = [opt for opt in options if opt.lower() in low]
        collected["decoration_types"] = chosen
        collected["decoration_done"] = True
        if chosen:
            collected.setdefault("brief_notes", []).append(
                f"Decoration method: {', '.join(chosen)}"
            )
            # First choice drives the render style modifier (embroidery vs print).
            collected["decoration_type"] = _decoration_style_bucket(chosen[0])
        return

    if state is S.ASK_NOTES:
        collected["notes_done"] = True
        _skip = (
            is_negative(text)
            or "generate" in low
            or bool(_DONE_ELEMENTS_RE.search(low))
        )
        if text and not _skip:
            collected["notes"] = text[:600]
            collected.setdefault("brief_notes", []).append(text[:600])
        return
```

- [ ] **Step 4: Wire the capture into `handle_message`**

In `handle_message`, in the interpret block (after the existing
`elif current is ConversationState.CONFIRM_BRIEF:` capture branch, ~line 319),
add:

```python
        elif current in (ConversationState.ASK_DECORATION, ConversationState.ASK_NOTES):
            _apply_canvas_outro(current, collected, message)
```

- [ ] **Step 5: Skip CONFIRM_BRIEF for canvas**

In `handle_message`, find the pre-generation confirm interception (~line 394):

```python
        if new_state is ConversationState.GENERATING and not collected.get("brief_confirmed"):
            new_state = ConversationState.CONFIRM_BRIEF
            collected["brief_prompt_shown"] = True
```

Change the condition to exclude canvas:

```python
        if (
            new_state is ConversationState.GENERATING
            and not collected.get("brief_confirmed")
            and collected.get("flow_mode") != "canvas"
        ):
            new_state = ConversationState.CONFIRM_BRIEF
            collected["brief_prompt_shown"] = True
```

- [ ] **Step 6: Add public data for the new states**

In `_state_public_data`, add (before the final `return {}`):

```python
    if state is S.ASK_DECORATION:
        return {
            "options": collected.get("decoration_options") or [],
            "multiselect": True,
            "selected": collected.get("decoration_types") or [],
        }
    if state is S.ASK_NOTES:
        return {"options": ["No, generate"]}
    if state is S.CANVAS_DESIGN:
        return {}
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_conversation.py -q`
Expected: PASS (5 passed).

- [ ] **Step 8: Run the full conversation suite for regressions**

Run: `cd backend && pytest tests/test_conversation_smart.py tests/test_state_machine.py tests/test_goal_planner.py -q`
Expected: PASS (no regressions in the non-canvas flow).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_canvas_conversation.py
git commit -m "feat(conversation): capture canvas decoration + notes; skip brief-confirm for canvas"
```

---

## Task 8: canvas-finalize routes to ASK_DECORATION; canvas session starts at GREETING

**Files:**
- Modify: `backend/app/api/routes/sessions.py`
- Test: `backend/tests/test_canvas_routes.py` (adjust existing finalize assertion + add)

**Interfaces:**
- Consumes: `services.decoration_types.list_types` (Task 2), `ie.generate_reply`, `state_machine.progress`.
- Produces: canvas session initial `state == "greeting"`; `canvas-finalize` returns `{reply, state: "ask_decoration", data: {options, multiselect, selected, progress}}` and sets `collected.canvas_finalized`, `collected.decoration_options`.

- [ ] **Step 1: Inspect the existing finalize test**

Run: `cd backend && grep -n "canvas-finalize\|generating\|state\|create_canvas\|canvas_design" tests/test_canvas_routes.py`
Read the finalize test — it currently asserts `state == "generating"`. You will update that assertion in Step 5.

- [ ] **Step 2: Change the canvas session initial state**

In `sessions.py` `create_canvas_session`, change the insert's `"state": "canvas_design"` to `"state": "greeting"`:

```python
    res = sb.table("design_sessions").insert({
        "store_id": store["id"], "share_token": share_token, "state": "greeting",
        "channel": body.channel, "entry_path": body.entry_path, "flow_mode": "canvas",
        "product_ref": product_ref, "collected": collected, "status": "draft",
    }).execute()
```

- [ ] **Step 3: Rewrite the finalize body to route to ASK_DECORATION**

Replace the tail of `finalize_canvas` (from the lead-capture comment block through the `return`) with:

```python
    elements, description = canvas_describe.canvas_to_elements(body.canvas_design)
    collected["elements"] = elements
    collected["design_description"] = {"summary": description} if description else None
    collected["flow_mode"] = "canvas"
    if body.name:
        collected["name"] = body.name

    colourway = (body.canvas_design or {}).get("colourway")
    if isinstance(colourway, dict) and (colourway.get("name") or colourway.get("hex")):
        collected["hat_colour"] = colourway

    # The design is done — advance the chat from CANVAS_DESIGN into the outro
    # (decoration → notes → generate). Name + email were captured in chat during
    # the intro, so no lead capture here.
    collected["canvas_finalized"] = True

    from app.services import decoration_types as deco_svc
    from app.services.conversation import intent_extractor as ie
    from app.services.conversation.state_machine import ConversationState as S
    from app.services.conversation.state_machine import progress as sm_progress

    active = deco_svc.list_types(store["id"], active_only=True)
    collected["decoration_options"] = [t["name"] for t in active]

    new_state = S.ASK_DECORATION
    persona = store.get("persona_name") or settings.chatbot_persona_name
    reply = await ie.generate_reply(new_state.value, collected, persona)

    sb.table("design_sessions").update(
        {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
    ).eq("id", session_id).execute()

    return {
        "reply": reply,
        "state": new_state.value,
        "data": {
            "options": collected["decoration_options"],
            "multiselect": True,
            "selected": [],
            "progress": sm_progress(new_state, collected),
        },
    }
```

> Ensure `from app.config import settings` is imported at the top of
> `sessions.py` (check; add if missing). The `canvas_describe` import already
> exists in this file.

- [ ] **Step 4: Update the finalize test**

In `backend/tests/test_canvas_routes.py`, the finalize test must (a) monkeypatch
`decoration_types.list_types` and `intent_extractor.generate_reply`, and (b)
assert the new state. Replace the finalize assertions with this pattern (adapt to
the file's existing fixture/monkeypatch style):

```python
def test_finalize_routes_to_decoration(monkeypatch, canvas_session_client):
    from app.services import decoration_types as deco_svc
    from app.services.conversation import intent_extractor as ie
    monkeypatch.setattr(deco_svc, "list_types",
                        lambda s, active_only=False: [{"name": "Embroidery"}, {"name": "Print"}])
    async def _reply(*a, **k):
        return "How would you like this decorated?"
    monkeypatch.setattr(ie, "generate_reply", _reply)

    client, session_id = canvas_session_client
    r = client.post(f"/sessions/{session_id}/canvas-finalize",
                    json={"canvas_design": {"faces": {}}},
                    headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "ask_decoration"
    assert body["data"]["multiselect"] is True
    assert body["data"]["options"] == ["Embroidery", "Print"]
```

> If the existing test file has a single finalize test asserting
> `state == "generating"`, replace it with the above. Keep the file's existing
> fixtures (session insert mock, `canvas_describe.canvas_to_elements` monkeypatch).
> If there is no reusable fixture, model the client on
> `tests/test_hat_types_route.py` (monkeypatch `app.api.deps.resolve_store` and
> the DB access the route uses).

- [ ] **Step 5: Run the canvas-route tests**

Run: `cd backend && pytest tests/test_canvas_routes.py -q`
Expected: PASS (finalize routes to `ask_decoration`; session creation state is `greeting`).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/sessions.py backend/tests/test_canvas_routes.py
git commit -m "feat(canvas): finalize routes to decoration step; canvas session starts at greeting"
```

---

## Task 9: Frontend API — getDecorationTypes; chatStore parse multiselect

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/store/chatStore.ts`
- Test: `frontend/src/store/chatStore.test.ts` (add) and/or `frontend/src/__tests__/api.test.ts`

**Interfaces:**
- Produces:
  - `api.getDecorationTypes(): Promise<{id: string; name: string}[]>`
  - chatStore parses `multiselect: boolean` and `selected: string[]` from `data`.

- [ ] **Step 1: Write the failing chatStore test**

Add to `frontend/src/store/chatStore.test.ts`:

```ts
import { useChatStore } from './chatStore'

test('parses multiselect + selected from data', () => {
  useChatStore.getState().reset()
  useChatStore.getState().hydrate([], 'ask_decoration', {
    options: ['Embroidery', 'Print'], multiselect: true, selected: ['Print'],
  })
  const s = useChatStore.getState()
  expect(s.multiselect).toBe(true)
  expect(s.selected).toEqual(['Print'])
  expect(s.options).toEqual(['Embroidery', 'Print'])
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: FAIL — `s.multiselect` is `undefined`.

- [ ] **Step 3: Add getDecorationTypes to api.ts**

In `frontend/src/lib/api.ts`, near `listGraphics` (~line 207) add:

```ts
/** List the active decoration types (embroidery/print/…) for the current store. */
export function getDecorationTypes(): Promise<{ id: string; name: string }[]> {
  return request<{ id: string; name: string }[]>('/decoration-types')
}
```

- [ ] **Step 4: Add multiselect/selected to chatStore**

In `frontend/src/store/chatStore.ts`:

In `parseData`, add:

```ts
  const multiselect = data.multiselect === true
  const selected = Array.isArray(data.selected) ? (data.selected as string[]) : []
```

and include `multiselect, selected` in its returned object.

In `interface ChatStoreState`, add:

```ts
  /** ask_decoration: the option chips are a multi-select set. */
  multiselect: boolean
  /** ask_decoration: currently-selected decoration names. */
  selected: string[]
```

In the `create(...)` initial state, add `multiselect: false,` and `selected: [],`.
In `reset()`, add `multiselect: false,` and `selected: [],`.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/store/chatStore.ts frontend/src/store/chatStore.test.ts
git commit -m "feat(frontend): getDecorationTypes + chatStore multiselect parse"
```

---

## Task 10: ChatColumn — canvas intro kickoff + decoration multi-select + notes

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx`
- Test: `frontend/src/__tests__/ChatColumn.test.tsx` (add cases)

**Interfaces:**
- Consumes: `chatStore` (`multiselect`, `selected`, `sendMessage`, `kickoff`, `chatState`); `sessionStore.sessionId`.
- Produces: on-mount canvas kickoff; a multi-select decoration chip group with a Continue button + cost caveat; a "No, generate" chip at `ask_notes`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/__tests__/ChatColumn.test.tsx` (follow the file's existing render/store-seeding helpers):

```tsx
test('ask_decoration shows a multi-select with cost caveat once 2+ chosen', async () => {
  // seed chat store at ask_decoration
  useChatStore.getState().hydrate([], 'ask_decoration', {
    options: ['Embroidery', 'Print'], multiselect: true, selected: [],
  })
  useSessionStore.setState({ sessionId: 's1' } as never)
  render(<ChatColumn />)

  fireEvent.click(screen.getByRole('button', { name: 'Embroidery' }))
  fireEvent.click(screen.getByRole('button', { name: 'Print' }))
  expect(screen.getByText(/adds to the cost/i)).toBeInTheDocument()
})
```

> Import `useChatStore`, `useSessionStore`, `render`, `screen`, `fireEvent` the
> same way the existing tests in this file do.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: FAIL — no toggling chips / caveat rendered.

- [ ] **Step 3: Add the canvas kickoff effect**

In `ChatColumn.tsx`, read the extra store bits at the top (near the other
`useChatStore` selectors):

```tsx
  const kickoff = useChatStore(s => s.kickoff)
  const multiselect = useChatStore(s => s.multiselect)
  const selected = useChatStore(s => s.selected)
  const messagesLen = useChatStore(s => s.messages.length)
  const kickoffDone = useChatStore(s => s.kickoffDone)
```

Add a kickoff effect (the OLD comment says "no kickoff here" — replace that
comment block with this effect). Canvas sessions must greet on load; resumed
sessions set `kickoffDone` via `hydrate`, so they are skipped:

```tsx
  // Canvas sessions run the intro Q&A in this column, so kick off the greeting
  // on mount. Resumed sessions hydrate with kickoffDone=true and are skipped.
  useEffect(() => {
    if (sessionId && messagesLen === 0 && !kickoffDone) {
      void kickoff(sessionId)
    }
  }, [sessionId, messagesLen, kickoffDone, kickoff])
```

- [ ] **Step 4: Add local multi-select state + handler**

Inside the component, add:

```tsx
  const [decoSel, setDecoSel] = useState<string[]>([])

  // Re-seed the local selection whenever the backend selection changes
  // (e.g. resuming a session already at ask_decoration).
  useEffect(() => { setDecoSel(selected) }, [selected])

  function toggleDeco(name: string) {
    setDecoSel(prev => prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name])
  }

  function submitDeco() {
    if (!sessionId || sending) return
    void sendMessage(sessionId, decoSel.length ? decoSel.join(', ') : 'none')
  }
```

- [ ] **Step 5: Render the multi-select block**

In the bottom panel, BEFORE the existing single-select `options` chip row
(`{options.length > 0 && colourSwatches.length === 0 && ( ... )}`), add a
multi-select branch, and guard the existing single-select row so it does not
also render when `multiselect` is true:

```tsx
        {/* Decoration multi-select (ask_decoration) */}
        {multiselect && options.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap gap-2">
              {options.map(opt => {
                const on = decoSel.includes(opt)
                return (
                  <button
                    key={opt}
                    onClick={() => toggleDeco(opt)}
                    disabled={sending}
                    aria-pressed={on}
                    className={`px-4 py-2 rounded-full text-sm transition-colors disabled:opacity-50 ${
                      on
                        ? 'bg-accent text-white border border-accent'
                        : 'bg-surface border border-border text-textPrimary hover:border-accent'
                    }`}
                  >
                    {on ? '✓ ' : ''}{opt}
                  </button>
                )
              })}
            </div>
            {decoSel.length > 1 && (
              <p className="text-xs text-amber-600">
                Heads up — each extra decoration adds to the cost, so pick only what you need.
              </p>
            )}
            <button
              onClick={submitDeco}
              disabled={sending}
              className="self-start px-5 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors"
            >
              Continue
            </button>
          </div>
        )}
```

Then change the existing single-select condition from:

```tsx
        {options.length > 0 && colourSwatches.length === 0 && (
```

to:

```tsx
        {options.length > 0 && colourSwatches.length === 0 && !multiselect && (
```

- [ ] **Step 6: Add `useState` import if missing**

`ChatColumn.tsx` already imports `useState` (used elsewhere) — confirm; no change
needed if present.

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__/ChatColumn.test.tsx
git commit -m "feat(frontend): canvas kickoff + decoration multi-select + notes chip in ChatColumn"
```

---

## Task 11: DesignStudioSurface lock/unlock + "Done designing" button

**Files:**
- Modify: `frontend/src/components/DesignStudio/Surface.tsx`
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx`
- Test: `frontend/src/__tests__/ToolRail.test.tsx` (button label + disabled)

**Interfaces:**
- Consumes: `chatStore.chatState`.
- Produces: `ToolRail` renders "Done designing" and accepts a `disabled` prop; `Surface` shows a lock overlay while the chat is not at `canvas_design`.

- [ ] **Step 1: Write the failing ToolRail test**

In `frontend/src/__tests__/ToolRail.test.tsx`, add:

```tsx
test('render button reads "Done designing" and disables when disabled', () => {
  render(
    <ToolRail
      onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false} disabled
    />,
  )
  const btn = screen.getByRole('button', { name: /done designing/i })
  expect(btn).toBeDisabled()
})
```

> Match the existing import style in this test file for `ToolRail`, `render`,
> `screen`.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ToolRail.test.tsx`
Expected: FAIL — button text is "See it rendered"; no `disabled` prop.

- [ ] **Step 3: Update ToolRail**

In `ToolRail.tsx`, add `disabled` to the props interface and function signature:

```tsx
interface ToolRailProps {
  onAddText: () => void
  onUploadClick: () => void
  onGraphicsClick: () => void
  colourways: Colourway[]
  onRender: () => void
  rendering: boolean
  rendered: boolean
  disabled?: boolean
}

export function ToolRail({ onAddText, onUploadClick, onGraphicsClick, colourways, onRender, rendering, rendered, disabled }: ToolRailProps) {
```

Update the render button:

```tsx
      <button onClick={onRender} disabled={disabled || rendering || rendered}
        className="mt-auto px-4 py-3 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
        {rendered ? 'Design saved ✓' : rendering ? 'Saving…' : 'Done designing'}
      </button>
```

- [ ] **Step 4: Add lock/unlock to Surface**

In `Surface.tsx`, add the chat-state selector at the top of the component:

```tsx
  const chatState = useChatStore(s => s.chatState)
  const unlocked = chatState === 'canvas_design'
  // Intro states (pre-design) vs outro/other (post-design). Empty string is the
  // pre-kickoff instant → treat as intro.
  const introStates = ['', 'greeting', 'ask_name', 'save_progress_email', 'ask_purpose', 'ask_quantity']
  const isIntro = introStates.includes(chatState)
```

`useChatStore` is already imported in `Surface.tsx`.

Wrap the canvas working area with a relatively-positioned container and overlay.
Change the outer working `div` (the one containing FaceThumbnails/CanvasStage/
ToolRail, currently `<div className="flex-1 flex flex-col md:flex-row min-h-0">`)
to add `relative`, and insert an overlay as its first child:

```tsx
      <div className="relative flex-1 flex flex-col md:flex-row min-h-0">
        {!unlocked && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-base/70 backdrop-blur-[1px]">
            <p className="max-w-xs text-center text-sm text-textMuted px-6">
              {isIntro
                ? 'Answer a couple of quick questions on the right, then your design tools unlock here →'
                : 'Design locked in — finishing up in the chat. ✓'}
            </p>
          </div>
        )}
```

(Keep the existing three inner columns unchanged. Close the wrapper div as
before.)

- [ ] **Step 5: Pass `disabled` to ToolRail and guard doRender**

In `Surface.tsx`, update the `<ToolRail ... />` usage to pass `disabled={!unlocked}`:

```tsx
          <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
            onGraphicsClick={() => setGraphicsOpen(true)}
            colourways={colourways} onRender={() => void doRender()} rendering={rendering} rendered={rendered}
            disabled={!unlocked} />
```

And at the top of `doRender`, bail if locked:

```tsx
  async function doRender() {
    if (!sessionId || rendering) return
    // ... existing body
```

- [ ] **Step 6: Run the ToolRail test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ToolRail.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DesignStudio/Surface.tsx frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/__tests__/ToolRail.test.tsx
git commit -m "feat(canvas): lock canvas until chat unlocks it; rename render → Done designing"
```

---

## Task 12: Admin — decoration-types API client, view, route, nav

**Files:**
- Modify: `frontend/src/admin/adminApi.ts`
- Create: `frontend/src/admin/views/DecorationTypesView.tsx`
- Modify: `frontend/src/admin/AdminApp.tsx`
- Modify: `frontend/src/admin/AdminLayout.tsx`
- Test: `frontend/src/admin/views/DecorationTypesView.test.tsx`

**Interfaces:**
- Consumes: admin `request` helper + `useStores` (`./views/hatTypes/shared`).
- Produces: `adminApi.listDecorationTypes/createDecorationType/deleteDecorationType`; `/admin/decoration-types` route + "Decorations" nav entry.

- [ ] **Step 1: Add adminApi client functions**

In `frontend/src/admin/adminApi.ts`, near the graphics admin functions (~line 441), add:

```ts
export interface AdminDecorationType {
  id: string
  name: string
  active: boolean
  sort_order: number
}

export function listDecorationTypes(storeKey: string): Promise<AdminDecorationType[]> {
  return request<AdminDecorationType[]>('/admin/decoration-types', {}, storeKey)
}

export function createDecorationType(name: string, storeKey: string): Promise<AdminDecorationType> {
  return request<AdminDecorationType>('/admin/decoration-types', {
    method: 'POST', body: JSON.stringify({ name }),
  }, storeKey)
}

export function deleteDecorationType(id: string, storeKey: string): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(`/admin/decoration-types/${id}`, { method: 'DELETE' }, storeKey)
}
```

- [ ] **Step 2: Write the failing view test**

Create `frontend/src/admin/views/DecorationTypesView.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, test, expect, beforeEach } from 'vitest'
import { DecorationTypesView } from './DecorationTypesView'
import * as adminApi from '../adminApi'
import * as shared from './hatTypes/shared'

beforeEach(() => {
  vi.spyOn(shared, 'useStores').mockReturnValue({
    stores: [{ id: 's1', name: 'MadHats', public_key: 'mh_pk' } as never], error: null,
  } as never)
  vi.spyOn(adminApi, 'listDecorationTypes').mockResolvedValue([
    { id: 'd1', name: 'Embroidery', active: true, sort_order: 0 },
  ])
})

test('lists decoration types for the selected store', async () => {
  render(
    <MemoryRouter initialEntries={['/admin/decoration-types?store=s1']}>
      <DecorationTypesView />
    </MemoryRouter>,
  )
  await waitFor(() => expect(screen.getByText('Embroidery')).toBeInTheDocument())
})
```

> Confirm `useStores`'s return shape by opening
> `frontend/src/admin/views/hatTypes/shared.ts`; adjust the mock to match its
> real fields (it exposes `stores` and `error` — used by `GraphicsView`).

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/DecorationTypesView.test.tsx`
Expected: FAIL — module `./DecorationTypesView` not found.

- [ ] **Step 4: Write the view**

Create `frontend/src/admin/views/DecorationTypesView.tsx` (modelled on `GraphicsView`):

```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  listDecorationTypes, createDecorationType, deleteDecorationType,
  type AdminDecorationType,
} from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores } from './hatTypes/shared'

export function DecorationTypesView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [items, setItems] = useState<AdminDecorationType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmId, setConfirmId] = useState<string | null>(null)

  useEffect(() => {
    if (stores.length > 0 && !stores.some(s => s.id === storeId)) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  const storeKey = stores.find(s => s.id === storeId)?.public_key ?? null

  function reload(key: string) {
    setLoading(true)
    listDecorationTypes(key)
      .then(data => { setItems(data); setError(null) })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (storeKey) reload(storeKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeKey])

  async function onAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!storeKey || !name.trim()) return
    setBusy(true); setError(null)
    try {
      await createDecorationType(name.trim(), storeKey)
      setName('')
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Add failed')
    } finally {
      setBusy(false)
    }
  }

  async function onDelete(id: string) {
    if (!storeKey) return
    setError(null)
    try {
      await deleteDecorationType(id, storeKey)
      setConfirmId(null)
      reload(storeKey)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Delete failed')
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold">Decoration types</h1>
        <select
          value={storeId}
          onChange={e => setParams({ store: e.target.value }, { replace: true })}
          className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-1.5 text-[13px]"
          aria-label="Store"
        >
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <span className="text-[12px] text-[#9a9ab0]">Methods offered to customers after they design (embroidery, print, …).</span>
      </div>

      {(storesError || error) && <ErrorBanner message={storesError || error || ''} />}

      <form onSubmit={onAdd} className="flex flex-wrap items-center gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="e.g. Embroidery"
          className="rounded-lg border border-[#e0e1ea] px-3 py-1.5 text-[13px]"
          aria-label="Decoration name"
        />
        <button
          type="submit"
          disabled={busy || !storeKey || !name.trim()}
          className={`rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : 'hover:bg-[#e65300]'} disabled:opacity-50`}
        >
          {busy ? 'Adding…' : 'Add'}
        </button>
      </form>

      {loading ? (
        <p className="text-[13px] text-[#6b6b80]">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-[#6b6b80]">No decoration types yet — add one above.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {items.map(d => (
            <li key={d.id} className="flex items-center justify-between rounded-xl border border-[#e0e1ea] bg-white px-4 py-2">
              <span className="text-[14px] text-[#1a1a2e]">{d.name}</span>
              {confirmId === d.id ? (
                <span className="flex gap-1">
                  <button onClick={() => onDelete(d.id)} className="rounded bg-red-600 px-2 py-1 text-[11px] text-white">Delete</button>
                  <button onClick={() => setConfirmId(null)} className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px]">Cancel</button>
                </span>
              ) : (
                <button onClick={() => setConfirmId(d.id)} className="rounded border border-[#e0e1ea] px-2 py-1 text-[11px] text-red-600 hover:bg-red-50">Delete</button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
```

- [ ] **Step 5: Register the route**

In `frontend/src/admin/AdminApp.tsx`, import and add the route:

```tsx
import { DecorationTypesView } from './views/DecorationTypesView'
```

and inside `<Route path="/admin" ...>`:

```tsx
          <Route path="decoration-types" element={<DecorationTypesView />} />
```

- [ ] **Step 6: Add the nav entry**

In `frontend/src/admin/AdminLayout.tsx`, in the nav items array (near the
`{ to: '/admin/graphics', label: 'Graphics' }` entry) add:

```tsx
  { to: '/admin/decoration-types', label: 'Decorations' },
```

- [ ] **Step 7: Run the view test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/DecorationTypesView.test.tsx`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/admin/adminApi.ts frontend/src/admin/views/DecorationTypesView.tsx frontend/src/admin/views/DecorationTypesView.test.tsx frontend/src/admin/AdminApp.tsx frontend/src/admin/AdminLayout.tsx
git commit -m "feat(admin): decoration-types management view + API + nav"
```

---

## Task 13: Full-suite verification + in-browser smoke

**Files:** none (verification only)

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: all pass (was 416; now higher with the new tests). If any pre-existing
flake appears (Windows tinypool note in CLAUDE.md is frontend-only), re-run
focused.

- [ ] **Step 2: Frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all pass except the 2 known pre-existing `adminQuotes` failures noted in
CLAUDE.md. No NEW failures.

- [ ] **Step 3: In-browser smoke (customise canvas)**

Use the `run` skill (or `docker compose up` + the browser tools). Load
`http://localhost:5173/?product_id=<a synced product id>`. Verify:
1. Chat greets and asks name; the **canvas is covered by the lock overlay**.
2. Provide name → it asks for email; provide email → verification is sent
   (Mailpit `http://localhost:54324` shows it), chat continues to purpose.
3. Answer purpose + quantity → **canvas unlocks**; button reads **"Done designing"**.
4. Add text/an image; tap **Done designing** → chat asks **decoration** (chips
   from the admin list); select 2 → **cost caveat** appears; Continue.
5. Chat asks **notes**; type a note (or tap "No, generate") → generation starts.
6. Verify email via the Mailpit link → design delivered/on-screen; refine works.

- [ ] **Step 4: In-browser smoke (blank canvas)**

Load `http://localhost:5173/?mode=blank` → pick a hat type → same intro/outro;
confirm the **colour swatch row** appears when the canvas unlocks and the tint
shows on the flattened faces.

- [ ] **Step 5: Admin smoke**

Load `http://localhost:5173/admin/decoration-types`, select the store, add a
decoration type, confirm it appears in the customer `ask_decoration` chips.

- [ ] **Step 6: Update CLAUDE.md state note + commit**

Add a bullet under "Current implementation state" summarising the chat-gated
canvas flow (intro Q&A → unlock → decoration → notes → generate; admin decoration
types). Update the test counts to the new totals.

```bash
git add CLAUDE.md
git commit -m "docs(claude): note chat-gated canvas flow + decoration types"
```

---

## Self-Review notes (author)

- **Spec coverage:** intro order (Tasks 4-8), email-after-name via SAVE_PROGRESS_EMAIL (Task 5 planner + existing capture), unlock (Task 11), "Done designing" (Task 11), decoration admin list (Tasks 1-3, 12), multi-select + cost caveat (Tasks 7, 10), always-ask (planner always routes ASK_DECORATION), notes (Tasks 7, 10), both flows (canvas planner is flow-mode gated; blank reuses it), blank tooling unchanged (no task touches blank canvas internals), CONFIRM_BRIEF skip (Task 7). ✅
- **Non-canvas untouched:** every branch checks `flow_mode == 'canvas'`; regression guard is Task 7 Step 8 + Task 13 Step 1. ✅
- **Type consistency:** `decoration_types` (list) vs `decoration_type` (singular style bucket) are deliberately distinct and used consistently. `_apply_canvas_outro`, `_canvas_next_goal`, `getDecorationTypes`, `AdminDecorationType`, `listDecorationTypes/createDecorationType/deleteDecorationType` names match across tasks. ✅
- **Deferred:** per-section blank colour (spec §7).
