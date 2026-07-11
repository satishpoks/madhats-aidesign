# Smarter Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Studio chatbot feel natural and goal-directed, show the generated design on-screen once released, show a "Step X of N" progress counter, and add an admin-capped regenerate-with-changes loop — all without raising AI cost.

**Architecture:** The deterministic `ConversationState` machine stays the single source of truth for routing; a new per-turn LLM "interpreter" replaces keyword heuristics so the bot handles out-of-order info, side-questions, revisions and chit-chat while always steering back to the next needed fact. The generated (watermarked) design is surfaced on the left panel at the same gate as the emailed preview (email verified + generation complete), with product angles and each regeneration as clickable thumbnails. A DB-backed global `app_settings` row (edited from a new admin Settings view) holds two AI-usage caps enforced server-side.

**Tech Stack:** Python 3.12 / FastAPI, supabase-py, Anthropic Haiku, React 18 / Vite / Zustand / Tailwind, Vitest, pytest.

## Global Constraints

- Composite onto the real product reference photo — never generate a cap from scratch.
- No secrets in code; config via env vars / `app.config.settings`.
- No PII (name/email/phone) in logs or Sentry.
- ORM/`supabase-py` only — no raw string SQL in app code (SQL lives in migrations).
- `/admin/*` routes gated by `X-Admin-Secret` via `app.api.deps.require_admin`.
- Prompts/email/template strings live only in `app/prompts.py`.
- The conversation engine must keep working with **no `ANTHROPIC_API_KEY`** (deterministic heuristic fallback) so CI/local stays hermetic.
- Generated images shown to customers are always the **watermarked** URL, never the clean one.
- Backend tests: `cd backend && pytest -q`. Frontend tests: `cd frontend && npx vitest run`.

---

## File Structure

**Backend — create**
- `backend/supabase/migrations/20260711000001_app_settings.sql` — global settings table (single row).
- `backend/app/services/settings_service.py` — read/write global settings with a short cache.
- `backend/app/services/limits.py` — AI-usage cap helpers (per-session edits, per-customer/day designs).
- `backend/app/api/routes/admin_settings.py` — `GET/PATCH /admin/settings`.
- `backend/tests/test_settings_service.py`, `test_admin_settings.py`, `test_limits.py`, `test_conversation_smart.py`, `test_progress.py`, `test_regeneration_flow.py`.

**Backend — modify**
- `backend/app/config.py` — env defaults for the two caps.
- `backend/app/services/conversation/state_machine.py` — new states, `QUESTION_FIELD`, `advance_and_skip`, `progress`.
- `backend/app/services/conversation/intent_extractor.py` — `interpret_turn` + heuristic fallback.
- `backend/app/services/conversation/orchestrator.py` — interpreter-first turn, apply-fields, side-question/revise handling, progress in payload, refine-loop wiring.
- `backend/app/prompts.py` — `TURN_INTERPRETER_PROMPT`, new state prompts/canned replies, final-design email.
- `backend/app/api/routes/generate.py` — `/generate/regenerate/{session_id}`, cap enforcement, `tier="edit"`.
- `backend/app/services/delivery.py` — `send_final_design`.
- `backend/app/main.py` — register `admin_settings` router.
- `backend/.env.example` (repo-root `.env.example`) — document new env vars.

**Frontend — create**
- `frontend/src/admin/views/SettingsView.tsx` — global settings form.

**Frontend — modify**
- `frontend/src/admin/adminApi.ts`, `AdminApp.tsx`, `AdminLayout.tsx` — Settings view wiring.
- `frontend/src/components/ProductViewer/index.tsx` — main image + thumbnail strip.
- `frontend/src/components/ChatPanel/index.tsx` — gated design display, progress header, refine-loop UI.
- `frontend/src/store/chatStore.ts` — parse `progress`, handle `trigger_regeneration`.
- `frontend/src/store/generationStore.ts` — `designs[]`, `startRegeneration`.
- `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts` — `regenerate()` + `progress` on `ChatResponse`.

---

## Task 1: Global settings store (`app_settings` + settings_service)

**Files:**
- Create: `backend/supabase/migrations/20260711000001_app_settings.sql`
- Create: `backend/app/services/settings_service.py`
- Modify: `backend/app/config.py`
- Test: `backend/tests/test_settings_service.py`

**Interfaces:**
- Produces: `settings_service.StudioSettings` (dataclass: `regen_edits_per_session: int`, `designs_per_customer_per_day: int`, `faq_knowledge: str`); `settings_service.get_settings() -> StudioSettings`; `settings_service.update_settings(*, regen_edits_per_session: int | None = None, designs_per_customer_per_day: int | None = None, faq_knowledge: str | None = None) -> StudioSettings`; `settings_service.invalidate_cache() -> None`.

- [ ] **Step 1: Write the migration**

Create `backend/supabase/migrations/20260711000001_app_settings.sql`:

```sql
-- Global (single-row) studio settings, editable from the admin panel with no
-- developer involvement. id is pinned to 1 so there is always exactly one row.
create table if not exists app_settings (
  id                            int primary key default 1,
  regen_edits_per_session       int  not null default 3,
  designs_per_customer_per_day  int  not null default 2,
  faq_knowledge                 text not null default '',
  updated_at                    timestamptz not null default now(),
  constraint app_settings_singleton check (id = 1)
);

insert into app_settings (id) values (1) on conflict (id) do nothing;
```

- [ ] **Step 2: Add env defaults to config**

In `backend/app/config.py`, inside `class Settings`, after the `rate_limit_rpm` line (around line 49) add:

```python
    # --- AI usage caps (initial defaults; the app_settings DB row overrides) ---
    regen_edits_per_session: int = 3
    designs_per_customer_per_day: int = 2
```

- [ ] **Step 3: Write the failing test**

Create `backend/tests/test_settings_service.py`:

```python
from app.services import settings_service


def test_get_settings_falls_back_to_env_defaults(monkeypatch):
    # No DB row values -> env defaults from config.
    monkeypatch.setattr(settings_service, "_read_row", lambda: {})
    settings_service.invalidate_cache()
    s = settings_service.get_settings()
    assert s.regen_edits_per_session == 3
    assert s.designs_per_customer_per_day == 2
    assert s.faq_knowledge == ""


def test_db_row_overrides_env(monkeypatch):
    monkeypatch.setattr(
        settings_service,
        "_read_row",
        lambda: {"regen_edits_per_session": 5, "designs_per_customer_per_day": 1, "faq_knowledge": "hi"},
    )
    settings_service.invalidate_cache()
    s = settings_service.get_settings()
    assert s.regen_edits_per_session == 5
    assert s.designs_per_customer_per_day == 1
    assert s.faq_knowledge == "hi"


def test_cache_is_used_until_invalidated(monkeypatch):
    calls = {"n": 0}

    def _row():
        calls["n"] += 1
        return {"regen_edits_per_session": 7}

    monkeypatch.setattr(settings_service, "_read_row", _row)
    settings_service.invalidate_cache()
    settings_service.get_settings()
    settings_service.get_settings()
    assert calls["n"] == 1
    settings_service.invalidate_cache()
    settings_service.get_settings()
    assert calls["n"] == 2
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd backend && pytest tests/test_settings_service.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.settings_service`).

- [ ] **Step 5: Implement the settings service**

Create `backend/app/services/settings_service.py`:

```python
"""Global studio settings, editable from the admin panel.

Backed by the single-row `app_settings` table. Values fall back to the env
defaults in `app.config.settings` when the row is missing a column. A short
in-process cache avoids a DB hit on every conversation turn / limit check;
`update_settings` and `invalidate_cache` clear it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.config import settings
from app.db import get_supabase

_TTL_SECONDS = 30.0
_cache: dict = {"value": None, "ts": 0.0}


@dataclass
class StudioSettings:
    regen_edits_per_session: int
    designs_per_customer_per_day: int
    faq_knowledge: str


def _read_row() -> dict:
    """Return the single app_settings row as a dict (empty dict if absent)."""
    res = get_supabase().table("app_settings").select("*").eq("id", 1).limit(1).execute()
    return res.data[0] if res.data else {}


def _from_row(row: dict) -> StudioSettings:
    return StudioSettings(
        regen_edits_per_session=int(
            row.get("regen_edits_per_session", settings.regen_edits_per_session)
        ),
        designs_per_customer_per_day=int(
            row.get("designs_per_customer_per_day", settings.designs_per_customer_per_day)
        ),
        faq_knowledge=row.get("faq_knowledge") or "",
    )


def invalidate_cache() -> None:
    _cache["value"] = None
    _cache["ts"] = 0.0


def get_settings() -> StudioSettings:
    now = time.monotonic()
    if _cache["value"] is not None and (now - _cache["ts"]) < _TTL_SECONDS:
        return _cache["value"]
    value = _from_row(_read_row())
    _cache["value"] = value
    _cache["ts"] = now
    return value


def update_settings(
    *,
    regen_edits_per_session: int | None = None,
    designs_per_customer_per_day: int | None = None,
    faq_knowledge: str | None = None,
) -> StudioSettings:
    """Patch the single row with the provided fields, then invalidate the cache."""
    patch: dict = {"updated_at": "now()"}
    if regen_edits_per_session is not None:
        patch["regen_edits_per_session"] = int(regen_edits_per_session)
    if designs_per_customer_per_day is not None:
        patch["designs_per_customer_per_day"] = int(designs_per_customer_per_day)
    if faq_knowledge is not None:
        patch["faq_knowledge"] = faq_knowledge
    get_supabase().table("app_settings").update(patch).eq("id", 1).execute()
    invalidate_cache()
    return get_settings()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_settings_service.py -q`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add backend/supabase/migrations/20260711000001_app_settings.sql backend/app/services/settings_service.py backend/app/config.py backend/tests/test_settings_service.py
git commit -m "feat(settings): global app_settings store with cached read/write"
```

---

## Task 2: Admin settings API (`GET/PATCH /admin/settings`)

**Files:**
- Create: `backend/app/api/routes/admin_settings.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin_settings.py`

**Interfaces:**
- Consumes: `settings_service.get_settings`, `settings_service.update_settings`; `app.api.deps.require_admin`.
- Produces: `GET /admin/settings` → `{regen_edits_per_session, designs_per_customer_per_day, faq_knowledge}`; `PATCH /admin/settings` with any subset of those fields, returns the updated object.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_admin_settings.py`:

```python
from app.config import settings as app_settings
from app.services import settings_service


def test_get_settings_requires_admin(client):
    assert client.get("/admin/settings").status_code == 401


def test_get_and_patch_settings(client, monkeypatch):
    store: dict = {}
    monkeypatch.setattr(settings_service, "_read_row", lambda: store)
    monkeypatch.setattr(
        settings_service, "update_settings", _fake_update(store)
    )
    settings_service.invalidate_cache()
    hdr = {"X-Admin-Secret": app_settings.admin_secret}

    got = client.get("/admin/settings", headers=hdr)
    assert got.status_code == 200
    assert got.json()["designs_per_customer_per_day"] == 2

    patched = client.patch(
        "/admin/settings", headers=hdr, json={"regen_edits_per_session": 4}
    )
    assert patched.status_code == 200
    assert patched.json()["regen_edits_per_session"] == 4


def test_patch_rejects_negative(client):
    hdr = {"X-Admin-Secret": app_settings.admin_secret}
    resp = client.patch("/admin/settings", headers=hdr, json={"regen_edits_per_session": -1})
    assert resp.status_code == 422


def _fake_update(store):
    def _update(**fields):
        store.update({k: v for k, v in fields.items() if v is not None})
        return settings_service._from_row(store)
    return _update
```

> Note: the `client` fixture already exists in `backend/tests/conftest.py` (used by other route tests). Reuse it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_admin_settings.py -q`
Expected: FAIL (404 on `/admin/settings`).

- [ ] **Step 3: Implement the route**

Create `backend/app/api/routes/admin_settings.py`:

```python
"""Global studio settings, editable from the admin panel. Gated by X-Admin-Secret."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.services import settings_service

router = APIRouter(tags=["admin-settings"], dependencies=[Depends(require_admin)])


class SettingsOut(BaseModel):
    regen_edits_per_session: int
    designs_per_customer_per_day: int
    faq_knowledge: str


class SettingsPatch(BaseModel):
    regen_edits_per_session: int | None = Field(default=None, ge=0)
    designs_per_customer_per_day: int | None = Field(default=None, ge=0)
    faq_knowledge: str | None = None


def _out(s: settings_service.StudioSettings) -> SettingsOut:
    return SettingsOut(
        regen_edits_per_session=s.regen_edits_per_session,
        designs_per_customer_per_day=s.designs_per_customer_per_day,
        faq_knowledge=s.faq_knowledge,
    )


@router.get("/admin/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    return _out(settings_service.get_settings())


@router.patch("/admin/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsPatch) -> SettingsOut:
    updated = settings_service.update_settings(**body.model_dump(exclude_none=True))
    return _out(updated)
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, find where routers are included (search for `admin_diagnostics`) and add alongside them:

```python
from app.api.routes import admin_settings  # noqa: E402
...
app.include_router(admin_settings.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_admin_settings.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/admin_settings.py backend/app/main.py backend/tests/test_admin_settings.py
git commit -m "feat(admin): GET/PATCH /admin/settings for global studio config"
```

---

## Task 3: Admin Settings view (frontend)

**Files:**
- Modify: `frontend/src/admin/adminApi.ts`
- Create: `frontend/src/admin/views/SettingsView.tsx`
- Modify: `frontend/src/admin/AdminApp.tsx`, `frontend/src/admin/AdminLayout.tsx`
- Test: `frontend/src/admin/views/SettingsView.test.tsx`

**Interfaces:**
- Consumes: admin `request` helper.
- Produces: `adminApi.getSettings(): Promise<StudioSettings>`, `adminApi.updateSettings(body: Partial<StudioSettings>): Promise<StudioSettings>`, where `StudioSettings = { regen_edits_per_session: number; designs_per_customer_per_day: number; faq_knowledge: string }`.

- [ ] **Step 1: Add API functions**

In `frontend/src/admin/adminApi.ts`, add after the `getDiagnostics` function:

```typescript
export interface StudioSettings {
  regen_edits_per_session: number
  designs_per_customer_per_day: number
  faq_knowledge: string
}

export function getSettings(): Promise<StudioSettings> {
  return request<StudioSettings>('/admin/settings')
}

export function updateSettings(body: Partial<StudioSettings>): Promise<StudioSettings> {
  return request<StudioSettings>('/admin/settings', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/admin/views/SettingsView.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { SettingsView } from './SettingsView'
import * as api from '../adminApi'

vi.mock('../adminApi')

describe('SettingsView', () => {
  beforeEach(() => vi.resetAllMocks())

  it('loads and displays current settings', async () => {
    vi.mocked(api.getSettings).mockResolvedValue({
      regen_edits_per_session: 3,
      designs_per_customer_per_day: 2,
      faq_knowledge: 'Turnaround is 2 weeks.',
    })
    render(<SettingsView />)
    await waitFor(() =>
      expect(screen.getByLabelText(/edits per session/i)).toHaveValue(3),
    )
    expect(screen.getByLabelText(/designs per customer per day/i)).toHaveValue(2)
    expect(screen.getByLabelText(/faq/i)).toHaveValue('Turnaround is 2 weeks.')
  })
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/SettingsView.test.tsx`
Expected: FAIL (cannot resolve `./SettingsView`).

- [ ] **Step 4: Implement the view**

Create `frontend/src/admin/views/SettingsView.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { getSettings, updateSettings, type StudioSettings } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'

export function SettingsView() {
  const [form, setForm] = useState<StudioSettings | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getSettings().then(setForm).catch((e) => setError(String(e)))
  }, [])

  async function handleSave() {
    if (!form) return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const next = await updateSettings(form)
      setForm(next)
      setSaved(true)
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  if (!form) return <div className="p-6 text-sm text-[#6b6b80]">Loading…</div>

  return (
    <div className="max-w-xl">
      <h1 className="mb-4 text-lg font-semibold">Studio settings</h1>
      {error && <ErrorBanner message={error} />}
      <div className="space-y-5 rounded-xl border border-[#e0e1ea] bg-white p-6">
        <label className="block">
          <span className="text-[13px] font-medium">Regen edits per session</span>
          <input
            type="number"
            min={0}
            aria-label="Regen edits per session"
            value={form.regen_edits_per_session}
            onChange={(e) =>
              setForm({ ...form, regen_edits_per_session: Number(e.target.value) })
            }
            className="mt-1 w-full rounded-lg border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">Designs per customer per day</span>
          <input
            type="number"
            min={0}
            aria-label="Designs per customer per day"
            value={form.designs_per_customer_per_day}
            onChange={(e) =>
              setForm({ ...form, designs_per_customer_per_day: Number(e.target.value) })
            }
            className="mt-1 w-full rounded-lg border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <label className="block">
          <span className="text-[13px] font-medium">FAQ / knowledge (used to answer customer questions)</span>
          <textarea
            rows={6}
            aria-label="FAQ knowledge"
            value={form.faq_knowledge}
            onChange={(e) => setForm({ ...form, faq_knowledge: e.target.value })}
            className="mt-1 w-full rounded-lg border border-[#e0e1ea] px-3 py-2 text-sm"
          />
        </label>
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded-full bg-[#ff5c00] px-5 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          {saved && <span className="text-sm text-green-600">Saved</span>}
        </div>
      </div>
    </div>
  )
}
```

> If `ErrorBanner` has a different prop name, check `frontend/src/admin/components/ErrorBanner.tsx` and match it.

- [ ] **Step 5: Wire route + nav**

In `frontend/src/admin/AdminApp.tsx` add the import and route:

```tsx
import { SettingsView } from './views/SettingsView'
// ...inside <Route path="/admin" ...> children, after the "ops" route:
          <Route path="settings" element={<SettingsView />} />
```

In `frontend/src/admin/AdminLayout.tsx` add to the `NAV` array:

```tsx
  { to: '/admin/settings', label: 'Settings' },
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/admin/views/SettingsView.test.tsx`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/admin/adminApi.ts frontend/src/admin/views/SettingsView.tsx frontend/src/admin/views/SettingsView.test.tsx frontend/src/admin/AdminApp.tsx frontend/src/admin/AdminLayout.tsx
git commit -m "feat(admin): Settings view for global studio config"
```

---

## Task 4: State machine — new states, field map, skip-filled advance, progress

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py`
- Test: `backend/tests/test_progress.py`

**Interfaces:**
- Produces: new states `S.SHOW_DESIGN`, `S.OFFER_REFINE`, `S.DESCRIBE_CHANGES`, `S.REGENERATING`; `QUESTION_FIELD: dict[ConversationState, str]`; `advance_and_skip(current, collected, *, message="", upsell_count=0) -> ConversationState`; `progress(state: ConversationState, collected: dict) -> dict` returning `{"step": int, "total": int}`; module constant `AUTO_ADVANCE_STATES: frozenset[ConversationState]` (moved here from the orchestrator).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_progress.py`:

```python
from app.services.conversation.state_machine import (
    ConversationState as S,
    advance_and_skip,
    progress,
)


def test_progress_describe_branch_total():
    # has_logo False -> describe branch (no upload/remove-bg steps).
    collected = {"has_logo": False}
    p = progress(S.ASK_NAME, collected)
    assert p["step"] == 1
    assert p["total"] == 9  # name,purpose,qty,decoration,has_logo,describe,zone,position,email


def test_progress_upload_branch_is_longer():
    collected = {"has_logo": True}
    p = progress(S.ASK_PLACEMENT_ZONE, collected)
    assert p["total"] == 10  # upload branch adds remove-bg
    assert p["step"] == 8


def test_progress_post_design_is_complete():
    p = progress(S.SHOW_DESIGN, {"has_logo": False})
    assert p["step"] == p["total"]


def test_advance_and_skip_skips_already_answered_question():
    # Placement zone already known -> after position question we should not
    # re-ask a filled question; verify a filled zone is skipped when advancing
    # from a state whose next is ask_placement_zone.
    collected = {"has_logo": False, "placement_zone": "front_panel"}
    nxt = advance_and_skip(S.DESCRIBE_DESIGN, collected)
    assert nxt == S.ASK_PLACEMENT_POSITION  # zone skipped because already filled
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_progress.py -q`
Expected: FAIL (`ImportError: cannot import name 'advance_and_skip'`).

- [ ] **Step 3: Add the new states to the enum**

In `backend/app/services/conversation/state_machine.py`, in `class ConversationState`, add these four members after `SEND_PREVIEW_EMAIL = "send_preview_email"`:

```python
    SHOW_DESIGN = "show_design"
    OFFER_REFINE = "offer_refine"
    DESCRIBE_CHANGES = "describe_changes"
    REGENERATING = "regenerating"
```

- [ ] **Step 4: Rewire the post-verification transitions**

In the `TRANSITIONS` dict, replace the `S.SEND_PREVIEW_EMAIL` line and keep the rest:

```python
    S.SEND_PREVIEW_EMAIL: [S.SHOW_DESIGN],
    S.SHOW_DESIGN: [S.OFFER_REFINE],
    S.OFFER_REFINE: [S.DESCRIBE_CHANGES, S.QUOTE_REQUESTED],
    S.DESCRIBE_CHANGES: [S.REGENERATING],
    S.REGENERATING: [S.OFFER_REFINE],
    S.QUOTE_REQUESTED: [S.UPSELL_PROMPT],
```

- [ ] **Step 5: Add branch logic in `advance_state`**

In `advance_state`, before the `# --- Upsell branch ---` block, add:

```python
    # --- Refine loop branch ---
    if current is S.OFFER_REFINE:
        return S.DESCRIBE_CHANGES if collected.get("wants_changes") else S.QUOTE_REQUESTED
```

- [ ] **Step 6: Add the field map, moved AUTO_ADVANCE_STATES, advance_and_skip, and progress**

Append to `state_machine.py` (after `advance_state`):

```python
# States the orchestrator auto-advances through (they pose no question). Moved
# here from the orchestrator so advance_and_skip can consult it.
AUTO_ADVANCE_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.CHECK_YOUTH,
        ConversationState.DECORATION_ENGINE,
        ConversationState.CONFIRM_DECORATION,
    }
)

# Question states → the `collected` key they populate. Used to skip a question
# whose answer the customer already volunteered out of order, and to count
# progress. Only genuine customer-facing question states appear here.
QUESTION_FIELD: dict[ConversationState, str] = {
    ConversationState.ASK_NAME: "name",
    ConversationState.ASK_PURPOSE: "purpose",
    ConversationState.ASK_QUANTITY: "quantity",
    ConversationState.DESCRIBE_DESIGN: "design_description",
    ConversationState.ASK_REMOVE_BG: "remove_bg",
    ConversationState.ASK_PLACEMENT_ZONE: "placement_zone",
    ConversationState.ASK_PLACEMENT_POSITION: "placement_position",
}


def _filled(collected: dict, field: str) -> bool:
    val = collected.get(field)
    return val is not None and val != ""


def advance_and_skip(
    current: ConversationState,
    collected: dict,
    *,
    message: str = "",
    upsell_count: int = 0,
) -> ConversationState:
    """advance_state + skip routing-only states AND question states already answered.

    This is what makes out-of-order capture pay off: if the customer already
    gave (say) the placement zone, the machine walks past ASK_PLACEMENT_ZONE
    instead of re-asking it.
    """
    nxt = advance_state(current, collected, message=message, upsell_count=upsell_count)
    for _ in range(50):  # bounded walk; never loop forever
        if nxt in AUTO_ADVANCE_STATES:
            nxt = advance_state(nxt, collected, upsell_count=upsell_count)
            continue
        field = QUESTION_FIELD.get(nxt)
        if field and _filled(collected, field):
            nxt = advance_state(nxt, collected, upsell_count=upsell_count)
            continue
        break
    return nxt


# Ordered customer-facing question states used for the "Step X of N" counter.
# Branch-dependent segments are chosen from `collected`; a decoration token
# represents the single decoration-choice question (whichever variant is shown).
def _progress_path(collected: dict) -> list[ConversationState]:
    S = ConversationState
    path = [S.ASK_NAME, S.ASK_PURPOSE, S.ASK_QUANTITY, S.RECOMMEND_DECORATION, S.ASK_HAS_LOGO]
    if collected.get("has_logo"):
        path += [S.UPLOAD_LOGO, S.ASK_REMOVE_BG]
    else:
        path += [S.DESCRIBE_DESIGN]
    path += [S.ASK_PLACEMENT_ZONE, S.ASK_PLACEMENT_POSITION, S.ASK_EMAIL]
    return path


# States that mean "past the design questionnaire" -> progress is complete.
_POST_QUESTION_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.GENERATING,
        ConversationState.VERIFY_EMAIL,
        ConversationState.EMAIL_VERIFIED,
        ConversationState.SEND_PREVIEW_EMAIL,
        ConversationState.SHOW_DESIGN,
        ConversationState.OFFER_REFINE,
        ConversationState.DESCRIBE_CHANGES,
        ConversationState.REGENERATING,
        ConversationState.QUOTE_REQUESTED,
        ConversationState.UPSELL_PROMPT,
        ConversationState.SESSION_END,
    }
)

# Decoration-choice variants all map to the single decoration progress token.
_DECORATION_VARIANTS: frozenset[ConversationState] = frozenset(
    {
        ConversationState.WARN_PRINT_SETUP,
        ConversationState.RECOMMEND_DECORATION,
        ConversationState.RECOMMEND_EMBROIDERY,
        ConversationState.CONFIRM_DECORATION,
        ConversationState.DECORATION_ENGINE,
    }
)


def progress(state: ConversationState, collected: dict) -> dict:
    """Return {"step", "total"} for the 'Step X of N' UI, counting only
    customer-facing question states on the branch the customer is on."""
    path = _progress_path(collected)
    total = len(path)
    norm = ConversationState.RECOMMEND_DECORATION if state in _DECORATION_VARIANTS else state
    if norm in path:
        return {"step": path.index(norm) + 1, "total": total}
    if state in _POST_QUESTION_STATES:
        return {"step": total, "total": total}
    # GREETING / ASK_EMAIL fallback etc.
    return {"step": 1, "total": total}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_progress.py -q`
Expected: PASS (4 tests).

- [ ] **Step 8: Run the existing state-machine tests (guard against regressions)**

Run: `cd backend && pytest tests/ -q -k "state_machine or conversation or chat"`
Expected: PASS (no regressions). If a test imported `_AUTO_ADVANCE_STATES` from the orchestrator, it still exists there until Task 6; leave it.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_progress.py
git commit -m "feat(convo): refine states, field map, skip-filled advance, progress()"
```

---

## Task 5: Turn interpreter (`interpret_turn`) + prompt

**Files:**
- Modify: `backend/app/services/conversation/intent_extractor.py`
- Modify: `backend/app/prompts.py`
- Test: `backend/tests/test_conversation_smart.py` (interpreter unit tests only in this task)

**Interfaces:**
- Consumes: `prompts.TURN_INTERPRETER_PROMPT`, existing `_complete`, `_parse_json`, heuristics (`_parse_quantity_heuristic`, `_detect_youth_heuristic`).
- Produces: `intent_extractor.interpret_turn(state: str, message: str, collected: dict, allowed_targets: list[str], faq: str) -> dict` returning keys `intent` (one of `answer|provide_info|ask_question|revise|chitchat|backtrack`), `fields` (dict), `revise_target` (str|None), `backtrack_target` (str|None), `question_answer` (str), `on_topic` (bool). Deterministic fallback when no API key: `intent="answer"`, `fields` = heuristic extraction for the current state only.

- [ ] **Step 1: Add the interpreter prompt**

In `backend/app/prompts.py`, after `DESIGN_EXTRACTION_PROMPT`, add:

```python
TURN_INTERPRETER_PROMPT = """You interpret one customer message in a guided cap-design chat.
You do NOT decide what happens next — you only classify the message and extract data.

Current step: "{current_state}" (the question just asked).
Fields we may extract (only include ones the customer actually gave):
  name, purpose, quantity (integer), decoration_type (embroidery|print|patch),
  has_logo (bool), remove_bg (bool), design_description (short string),
  placement_zone (front_panel|side|back|under_brim), placement_position (string).

Known so far (JSON): {collected}
Allowed "go back" steps: {allowed_targets}
Store FAQ / knowledge (use ONLY this to answer questions; never invent prices,
turnaround or stock — if it isn't covered, leave question_answer empty):
{faq}

Customer message: "{message}"

Classify intent:
- "answer": a direct answer to the current step.
- "provide_info": gives info for this and/or later steps (extract all of it).
- "ask_question": asks us something (fill question_answer from the FAQ, or "").
- "revise": wants to change an earlier answer (set revise_target to an allowed step).
- "chitchat": off-topic / unclear.
- "backtrack": explicitly wants to go back (set backtrack_target to an allowed step).

Respond with ONLY a JSON object:
{{
  "intent": "...",
  "fields": {{ ... }},
  "revise_target": null,
  "backtrack_target": null,
  "question_answer": "",
  "on_topic": true
}}
"""
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_conversation_smart.py`:

```python
import pytest

from app.services.conversation import intent_extractor as ie


@pytest.mark.asyncio
async def test_interpret_turn_heuristic_extracts_current_field(monkeypatch):
    # No API key -> deterministic fallback: answer-only, current-field extraction.
    monkeypatch.setattr(ie, "_has_llm", False)
    out = await ie.interpret_turn(
        "ask_quantity", "about 50 hats", {}, [], ""
    )
    assert out["intent"] == "answer"
    assert out["fields"]["quantity"] == 50
    assert out["question_answer"] == ""


@pytest.mark.asyncio
async def test_interpret_turn_uses_llm_json_when_available(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return (
            '{"intent":"provide_info","fields":{"quantity":50,'
            '"placement_zone":"front_panel"},"revise_target":null,'
            '"backtrack_target":null,"question_answer":"","on_topic":true}'
        )

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.interpret_turn("ask_quantity", "50 on the front", {}, [], "")
    assert out["intent"] == "provide_info"
    assert out["fields"]["placement_zone"] == "front_panel"


@pytest.mark.asyncio
async def test_interpret_turn_normalizes_missing_keys(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def fake_complete(prompt, **kw):
        return '{"intent":"chitchat"}'

    monkeypatch.setattr(ie, "_complete", fake_complete)
    out = await ie.interpret_turn("ask_name", "how's your day?", {}, [], "")
    assert out["intent"] == "chitchat"
    assert out["fields"] == {}
    assert out["backtrack_target"] is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_conversation_smart.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'interpret_turn'`).

- [ ] **Step 4: Implement `interpret_turn` + heuristic extraction**

In `backend/app/services/conversation/intent_extractor.py`, add near the bottom (after `generate_reply`). First add the heuristic per-state extractor and the normalizer, then the public function:

```python
_VALID_INTENTS = {"answer", "provide_info", "ask_question", "revise", "chitchat", "backtrack"}
_VALID_ZONES = {"front_panel", "side", "back", "under_brim"}


def _zone_from_text(message: str) -> str | None:
    low = message.lower()
    if "under" in low or "brim" in low:
        return "under_brim"
    if "side" in low:
        return "side"
    if "back" in low:
        return "back"
    if "front" in low or "panel" in low:
        return "front_panel"
    return None


def _extract_fields_for_state(state: str, message: str, collected: dict) -> dict:
    """No-LLM per-state extraction — mirrors the pre-existing keyword ingest so
    behaviour without an API key is unchanged (answer-to-current-step only)."""
    fields: dict = {}
    low = message.lower()
    if state == "ask_name":
        name = message.strip().split("\n")[0][:60]
        if name:
            fields["name"] = name
    elif state == "ask_purpose":
        fields["purpose"] = message.strip()
        fields["youth_flag"] = _detect_youth_heuristic(message)
    elif state == "ask_quantity":
        fields["quantity"] = _parse_quantity_heuristic(message)
    elif state in ("warn_print_setup", "recommend_decoration", "recommend_embroidery"):
        if "embroid" in low:
            fields["decoration_type"] = "embroidery"
        elif "patch" in low:
            fields["decoration_type"] = "patch"
        elif "print" in low:
            fields["decoration_type"] = "print"
    elif state == "ask_has_logo":
        fields["has_logo"] = ("upload" in low or "logo" in low or "yes" in low or "artwork" in low) and not (
            "describe" in low or "instead" in low or "don't" in low
        )
    elif state == "ask_remove_bg":
        fields["remove_bg"] = ("yes" in low or "remove" in low) and "no" not in low
    elif state == "describe_design":
        fields["design_description"] = {"summary": message.strip()}
    elif state == "ask_placement_zone":
        fields["placement_zone"] = _zone_from_text(message) or "front_panel"
    elif state == "ask_placement_position":
        fields["placement_position"] = message.strip()[:60]
    return fields


def _normalize_interpretation(data: dict, allowed_targets: list[str]) -> dict:
    intent = data.get("intent")
    if intent not in _VALID_INTENTS:
        intent = "answer"
    fields = data.get("fields")
    fields = fields if isinstance(fields, dict) else {}
    # Guard the enumerated zone value.
    if fields.get("placement_zone") not in _VALID_ZONES:
        fields.pop("placement_zone", None)
    revise = data.get("revise_target")
    backtrack = data.get("backtrack_target")
    if revise not in allowed_targets:
        revise = None
    if backtrack not in allowed_targets:
        backtrack = None
    return {
        "intent": intent,
        "fields": fields,
        "revise_target": revise,
        "backtrack_target": backtrack,
        "question_answer": (data.get("question_answer") or "").strip(),
        "on_topic": bool(data.get("on_topic", True)),
    }


async def interpret_turn(
    state: str,
    message: str,
    collected: dict,
    allowed_targets: list[str],
    faq: str,
) -> dict:
    """Single per-turn interpretation. Structured intent + extracted fields.

    Without an API key: deterministic answer-only fallback (current step only).
    """
    if not _has_llm:
        return {
            "intent": "answer",
            "fields": _extract_fields_for_state(state, message, collected),
            "revise_target": None,
            "backtrack_target": None,
            "question_answer": "",
            "on_topic": True,
        }
    prompt = prompts.TURN_INTERPRETER_PROMPT.format(
        current_state=state,
        collected=json.dumps(_safe_collected(collected)),
        allowed_targets=", ".join(allowed_targets) or "(none)",
        faq=faq or "(no FAQ provided)",
        message=message,
    )
    data = _parse_json(await _complete(prompt, max_tokens=400))
    return _normalize_interpretation(data, allowed_targets)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_conversation_smart.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/intent_extractor.py backend/app/prompts.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): single-call turn interpreter with heuristic fallback"
```

---

## Task 6: Orchestrator rewire (interpreter-first, revise/side-question, progress)

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: append to `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `ie.interpret_turn`, `state_machine.advance_and_skip`, `state_machine.AUTO_ADVANCE_STATES`, `state_machine.QUESTION_FIELD`, `state_machine.progress`, `settings_service.get_settings`, `limits.can_edit` (Task 11 — guarded so this task does not hard-depend on it; see Step 4 note).
- Produces: `handle_message` return `data` now always includes `progress: {"step", "total"}`.

- [ ] **Step 1: Write the failing integration tests**

Append to `backend/tests/test_conversation_smart.py`:

```python
from app.services.conversation import orchestrator as orch
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def limit(self, *_):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        return self


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store, name)


@pytest.mark.asyncio
async def test_progress_is_returned_each_turn(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {"quantity": 20}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    res = await orch.handle_message("s1", "20")
    assert "progress" in res["data"]
    assert res["data"]["progress"]["total"] >= 1


@pytest.mark.asyncio
async def test_side_question_does_not_advance(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value, "collected": {"name": "Al"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "Embroidery lasts longer."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("re-ask"))
    res = await orch.handle_message("s1", "which lasts longer?")
    assert res["state"] == S.ASK_QUANTITY.value  # stayed put


def _fixed_interpret(payload):
    base = {"intent": "answer", "fields": {}, "revise_target": None,
            "backtrack_target": None, "question_answer": "", "on_topic": True}
    base.update(payload)

    async def _f(*a, **k):
        return dict(base)

    return _f


def _fixed_reply(text):
    async def _f(*a, **k):
        return text
    return _f
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_conversation_smart.py -q`
Expected: FAIL (`progress` missing / side-question advances).

- [ ] **Step 3: Rewire the imports and constant**

In `orchestrator.py`, replace the `_AUTO_ADVANCE_STATES` definition (lines ~40-46) with an import-and-alias, and add the new imports at the top of the file:

```python
from app.services import settings_service
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import (
    AUTO_ADVANCE_STATES,
    ConversationState,
    QUESTION_FIELD,
    advance_and_skip,
    advance_state,
    allowed_backtracks,
    progress,
)
```

Delete the local `_AUTO_ADVANCE_STATES = frozenset({...})` block and every reference to `_AUTO_ADVANCE_STATES` (there is one in `handle_message` and one in `check_verification`) — replace those `while new_state in _AUTO_ADVANCE_STATES:` loops as described below.

- [ ] **Step 4: Replace the interpret/ingest/advance core of `handle_message`**

Replace the body from `# --- 3. back-track detection ---` down to `# --- 6. word the reply ---` (the `else:` branch after the GREETING kickoff) with:

```python
        # --- 3+4. interpret the turn (one call: intent + fields) ---
        faq = settings_service.get_settings().faq_knowledge
        targets = [s.value for s in allowed_backtracks(current)]
        interp = await ie.interpret_turn(current.value, message, collected, targets, faq)

        _apply_fields(current, interp.get("fields") or {}, collected)

        # inline email capture (unchanged behaviour)
        if current in (ConversationState.GENERATING, ConversationState.ASK_EMAIL) and not collected.get(
            "email_captured"
        ):
            email = leads_service.extract_email(message)
            if email:
                lead_id = leads_service.capture_lead_and_verify(session, collected, email)
                collected["email_captured"] = True
                if lead_id:
                    collected["lead_id"] = lead_id

        intent = interp["intent"]
        if intent in ("ask_question", "chitchat"):
            # Answer/redirect, then RE-ASK the current question. Do not advance.
            new_state = current
            reply = await ie.generate_reply(
                current.value, collected, persona, aside=interp.get("question_answer") or None
            )
        else:
            if intent in ("revise", "backtrack"):
                target = interp.get("revise_target") or interp.get("backtrack_target")
                new_state = ConversationState(target) if target else current
            elif current is ConversationState.OFFER_REFINE and collected.get("wants_changes"):
                # Enforce the per-session edit cap here (guarded import so this
                # file works before Task 11 lands).
                if _can_edit(session_id):
                    new_state = ConversationState.DESCRIBE_CHANGES
                else:
                    collected["edit_cap_reached"] = True
                    new_state = ConversationState.QUOTE_REQUESTED
            else:
                new_state = advance_and_skip(
                    current, collected, message=message, upsell_count=upsell_count
                )
            if new_state is ConversationState.UPSELL_PROMPT and collected.get("wants_upsell"):
                upsell_count += 1
            # auto-advance through routing-only states
            while new_state in AUTO_ADVANCE_STATES:
                new_state = advance_state(new_state, collected, upsell_count=upsell_count)
            reply = await ie.generate_reply(new_state.value, collected, persona)
```

- [ ] **Step 5: Add `_apply_fields`, `_can_edit`, and the `wants_*` flags; update the return payload**

Add these helpers to `orchestrator.py` (replacing the old `_ingest`/`_match_zone` which are no longer used — delete them). `_apply_fields` maps interpreter fields onto `collected` and also derives the boolean intents the state machine branches on:

```python
def _apply_fields(state: ConversationState, fields: dict, collected: dict) -> None:
    """Merge validated interpreter fields into collected, and derive the
    branch booleans the state machine reads (has_logo, wants_pins, etc.)."""
    S = ConversationState
    for key in (
        "name", "purpose", "quantity", "decoration_type", "design_description",
        "placement_zone", "placement_position", "remove_bg", "has_logo", "youth_flag",
    ):
        if key in fields and fields[key] is not None:
            collected[key] = fields[key]

    # State-specific yes/no captures the interpreter encodes as intent+message.
    low = "".join(str(fields.get(k, "")) for k in fields)  # unused; kept for clarity
    if state is S.ASK_HAS_LOGO and "has_logo" not in fields:
        # Fall back: if the model didn't set has_logo explicitly, infer from a
        # provided design_description (=> describe path).
        if fields.get("design_description"):
            collected["has_logo"] = False
    if state is S.ASK_PIN_ANNOTATION:
        collected["wants_pins"] = bool(fields.get("wants_pins"))
    if state is S.PIN_ANNOTATE_MODE:
        collected["add_another_pin"] = bool(fields.get("add_another_pin"))
    if state is S.UPSELL_PROMPT:
        collected["wants_upsell"] = bool(fields.get("wants_upsell"))
    if state is S.OFFER_REFINE:
        collected["wants_changes"] = bool(fields.get("wants_changes"))
    if state is S.DESCRIBE_CHANGES and fields.get("design_description"):
        collected["last_change"] = fields["design_description"]


def _can_edit(session_id: str) -> bool:
    """Per-session edit cap check. Guarded so this file imports cleanly before
    the limits module (Task 11) exists."""
    try:
        from app.services import limits  # noqa: PLC0415
    except ImportError:
        return True
    return limits.can_edit(session_id)
```

Then update the `return { ... }` at the end of `handle_message` and `check_verification` to add progress. Change both return dicts' `"data"` builder to merge progress:

```python
    data = _public_data(new_state, collected)
    data["progress"] = progress(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}
```

Apply the same two-line change in `check_verification` (build `data`, add `progress`, return).

- [ ] **Step 6: Extend `generate_reply` to accept an optional aside**

In `intent_extractor.py`, change `generate_reply`'s signature and prompt so a side-question answer can precede the re-asked question:

```python
async def generate_reply(state: str, collected: dict, persona_name: str, aside: str | None = None) -> str:
    if not _has_llm:
        base = _generate_reply_canned(state, collected, persona_name)
        return f"{aside} {base}" if aside else base
    # ...existing instruction build...
    system = prompts.RICARDO_SYSTEM_PROMPT.replace("Ricardo", persona_name)
    prompt = prompts.REPLY_GENERATION_PROMPT.format(
        state_instruction=(f"First briefly answer: '{aside}'. Then: {instruction}" if aside else instruction),
        collected=json.dumps(_safe_collected(collected)),
    )
    return await _complete(prompt, system=system, max_tokens=200)
```

- [ ] **Step 7: Add canned replies / state prompts for the new states**

In `backend/app/prompts.py`, add entries to BOTH `STATE_PROMPTS` and `CANNED_REPLIES`:

```python
    # STATE_PROMPTS additions
    "show_design": "Tell them their design is ready and shown on screen (watermarked preview).",
    "offer_refine": "Ask if they'd like to tweak anything about the design, or if they're happy with it.",
    "describe_changes": "Invite them to describe the change they'd like to the design.",
    "regenerating": "Let them know you're updating the design with their changes now.",
```

```python
    # CANNED_REPLIES additions
    "show_design": "Here's your design — take a look on the left! It's a watermarked preview.",
    "offer_refine": "Want to tweak anything about it, or are you happy with this design?",
    "describe_changes": "Sure — tell me what you'd like to change and I'll update it.",
    "regenerating": "Updating your design with those changes now…",
```

Also add a canned/edit-cap line the reply can use when `collected["edit_cap_reached"]` — the QUOTE_REQUESTED reply already covers next steps, so no new state is needed; the cap message is delivered by the `offer_refine`→`quote_requested` transition reply.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_conversation_smart.py tests/test_progress.py -q`
Expected: PASS.

Run the full conversation/chat suite to catch regressions:
Run: `cd backend && pytest tests/ -q -k "chat or conversation or orchestrator or state"`
Expected: PASS. Fix any test that imported the now-deleted `_ingest`/`_match_zone`/`_AUTO_ADVANCE_STATES` from the orchestrator by pointing it at the new interpreter/`state_machine` symbols.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/app/services/conversation/intent_extractor.py backend/app/prompts.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): interpreter-first orchestrator with side-questions, revise, progress"
```

---

## Task 7: Frontend — "Step X of N" progress display

**Files:**
- Modify: `frontend/src/store/chatStore.ts`
- Modify: `frontend/src/components/ChatPanel/index.tsx`
- Test: `frontend/src/store/chatStore.test.ts` (add a case; create if absent)

**Interfaces:**
- Consumes: `data.progress = {step, total}` from `ChatResponse`.
- Produces: `chatStore.progress: { step: number; total: number } | null`.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/store/chatStore.test.ts` (create the file with this content if it does not exist):

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useChatStore } from './chatStore'
import * as api from '../lib/api'

vi.mock('../lib/api')

describe('chatStore progress', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    vi.resetAllMocks()
  })

  it('captures progress from the chat response', async () => {
    vi.mocked(api.sendChat).mockResolvedValue({
      reply: 'ok',
      state: 'ask_quantity',
      data: { progress: { step: 3, total: 9 } },
    } as never)
    await useChatStore.getState().sendMessage('s1', 'hi')
    expect(useChatStore.getState().progress).toEqual({ step: 3, total: 9 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: FAIL (`progress` is undefined).

- [ ] **Step 3: Add `progress` to the store**

In `frontend/src/store/chatStore.ts`:
- Add to the interface: `progress: { step: number; total: number } | null`.
- In `parseData`, add: `const progress = (data.progress && typeof data.progress === 'object') ? (data.progress as { step: number; total: number }) : null` and include `progress` in the returned object.
- Initialise `progress: null` in the store, in `reset()`, and set it in every `set(...)` that consumes `parseData` (`kickoff`, `sendMessage`, `hydrate`, `pollVerification`).

- [ ] **Step 4: Render it in the header**

In `frontend/src/components/ChatPanel/index.tsx`, read the value:

```tsx
  const progress = useChatStore(s => s.progress)
```

And in the chat header block (the "Ricardo — MadHats AI" area, around line 451-460) add, after the identity `<div>`:

```tsx
        {progress && progress.step < progress.total && (
          <span className="ml-auto text-xs font-medium text-textMuted">
            Step {progress.step} of {progress.total}
          </span>
        )}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/components/ChatPanel/index.tsx frontend/src/store/chatStore.test.ts
git commit -m "feat(studio): show Step X of N progress in chat header"
```

---

## Task 8: ProductViewer — main image + thumbnail strip

**Files:**
- Modify: `frontend/src/components/ProductViewer/index.tsx`
- Test: `frontend/src/components/ProductViewer/ProductViewer.test.tsx`

**Interfaces:**
- Produces: `ProductViewer` accepts a new prop `designUrls?: string[]` (watermarked design images, newest last). When present and non-empty, the newest design is the default main image; product angles + all designs render as clickable thumbnails.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/ProductViewer/ProductViewer.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import { ProductViewer } from './index'

const productRef = {
  name: 'Trucker',
  reference_image_url: 'front.png',
  view_images: { front: 'front.png', back: 'back.png' },
}

describe('ProductViewer', () => {
  it('shows product angles when no design yet', () => {
    render(<ProductViewer productRef={productRef} />)
    expect(screen.getByRole('img', { name: /main view/i })).toBeInTheDocument()
  })

  it('promotes the newest design to the main image and swaps on thumbnail click', () => {
    render(<ProductViewer productRef={productRef} designUrls={['design1.png', 'design2.png']} />)
    const main = screen.getByRole('img', { name: /main view/i }) as HTMLImageElement
    expect(main.src).toContain('design2.png') // newest design is main
    fireEvent.click(screen.getByRole('button', { name: /show front/i }))
    expect((screen.getByRole('img', { name: /main view/i }) as HTMLImageElement).src).toContain('front.png')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/ProductViewer/ProductViewer.test.tsx`
Expected: FAIL (no main-view img / prop unsupported).

- [ ] **Step 3: Rewrite ProductViewer**

Replace `frontend/src/components/ProductViewer/index.tsx` with a main-image + thumbnail-strip layout:

```tsx
import { useEffect, useMemo, useState } from 'react'

interface ProductRefLike {
  name: string
  colour?: string
  reference_image_url: string
  view_images?: Record<string, string>
}

interface ProductViewerProps {
  productRef: ProductRefLike | null
  /** Watermarked design images (newest last). Shown once released. */
  designUrls?: string[]
}

const VIEW_ORDER = ['front', 'back', 'left', 'right'] as const

interface Thumb {
  key: string
  label: string
  src: string
}

export function ProductViewer({ productRef, designUrls = [] }: ProductViewerProps) {
  const angleThumbs = useMemo<Thumb[]>(() => {
    const imgs = productRef?.view_images ?? {}
    const ordered = VIEW_ORDER.filter(v => imgs[v]).map(v => ({ key: v, label: v, src: imgs[v] }))
    if (ordered.length === 0 && productRef?.reference_image_url) {
      return [{ key: 'front', label: 'front', src: productRef.reference_image_url }]
    }
    return ordered
  }, [productRef])

  const designThumbs = useMemo<Thumb[]>(
    () => designUrls.map((src, i) => ({ key: `design-${i}`, label: designUrls.length > 1 ? `design ${i + 1}` : 'design', src })),
    [designUrls],
  )

  // Design thumbs first (newest design is the initial main image).
  const thumbs = useMemo<Thumb[]>(() => [...designThumbs, ...angleThumbs], [designThumbs, angleThumbs])
  const defaultKey = designThumbs.length ? designThumbs[designThumbs.length - 1].key : angleThumbs[0]?.key ?? ''
  const [activeKey, setActiveKey] = useState(defaultKey)

  // When a new design arrives, promote it to the main view.
  useEffect(() => {
    if (designThumbs.length) setActiveKey(designThumbs[designThumbs.length - 1].key)
  }, [designThumbs.length])

  if (!productRef) {
    return (
      <div className="h-full flex items-center justify-center text-textMuted text-sm bg-base">
        Loading product…
      </div>
    )
  }

  const active = thumbs.find(t => t.key === activeKey) ?? thumbs[0]

  return (
    <div className="h-full flex flex-col p-4 md:p-6 gap-4 bg-base overflow-y-auto">
      <div className="flex-shrink-0">
        <h2 className="text-textPrimary font-semibold leading-tight">
          {productRef.name}
          {productRef.colour && <span className="text-textSub"> — {productRef.colour}</span>}
        </h2>
        <p className="text-textMuted text-xs mt-0.5">
          {designThumbs.length ? 'Your design — tap a thumbnail to compare angles' : 'Choose a view to explore your cap'}
        </p>
      </div>

      {/* Main image */}
      <div className="flex-1 min-h-0 flex items-center justify-center rounded-2xl bg-surface border-2 border-border p-4">
        {active && (
          <img src={active.src} alt="main view" className="max-h-full max-w-full object-contain" draggable={false} />
        )}
      </div>

      {/* Thumbnail strip */}
      <div className="flex-shrink-0 flex gap-3 overflow-x-auto pb-1">
        {thumbs.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveKey(t.key)}
            aria-label={`Show ${t.label}`}
            aria-pressed={activeKey === t.key}
            title={t.label}
            className={`group relative flex-shrink-0 w-20 h-20 rounded-xl bg-surface p-1.5 transition-colors ${
              activeKey === t.key ? 'border-2 border-accent' : 'border-2 border-border hover:border-textMuted'
            }`}
          >
            <img src={t.src} alt={t.label} className="w-full h-full object-contain" draggable={false} />
          </button>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/ProductViewer/ProductViewer.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ProductViewer/index.tsx frontend/src/components/ProductViewer/ProductViewer.test.tsx
git commit -m "feat(studio): ProductViewer main image + clickable thumbnail strip"
```

---

## Task 9: Gate the on-screen design behind verification

**Files:**
- Modify: `frontend/src/store/generationStore.ts`
- Modify: `frontend/src/components/ChatPanel/index.tsx`
- Test: `frontend/src/store/generationStore.test.ts` (add/extend)

**Interfaces:**
- Produces: `generationStore.designs: string[]` (watermarked URLs in completion order); the first completed generation pushes into it.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/store/generationStore.test.ts` (create if absent):

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useGenerationStore } from './generationStore'
import * as api from '../lib/api'

vi.mock('../lib/api')

describe('generationStore designs', () => {
  beforeEach(() => {
    useGenerationStore.getState().reset()
    vi.resetAllMocks()
  })

  it('appends the completed design to designs[]', async () => {
    vi.mocked(api.generatePreview).mockResolvedValue({ job_id: 'j1' })
    vi.mocked(api.generationStatus).mockResolvedValue({
      status: 'complete',
      image_url: 'clean.png',
      watermarked_url: 'wm.png',
    } as never)
    await useGenerationStore.getState().startGeneration('s1')
    expect(useGenerationStore.getState().designs).toEqual(['wm.png'])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/store/generationStore.test.ts`
Expected: FAIL (`designs` undefined).

- [ ] **Step 3: Add `designs[]` to the generation store**

In `frontend/src/store/generationStore.ts`:
- Add `designs: string[]` to the interface and initial state (`designs: []`), and to `reset()`.
- In `startGeneration`, when a poll returns `complete`, push the URL:

```typescript
        if (res.status === 'complete') {
          const url = res.watermarked_url ?? res.image_url ?? null
          set(state => ({
            status: 'done',
            previewUrl: url,
            designs: url ? [...state.designs, url] : state.designs,
          }))
          return
        }
```

- [ ] **Step 4: Feed gated designs into ProductViewer**

In `frontend/src/components/ChatPanel/index.tsx`:
- Read the designs and a "released" flag:

```tsx
  const designs = useGenerationStore(s => s.designs)
  const RELEASED_STATES = ['email_verified', 'send_preview_email', 'show_design', 'offer_refine', 'describe_changes', 'regenerating', 'quote_requested', 'upsell_prompt', 'session_end']
  const designReleased = RELEASED_STATES.includes(chatState)
```

- Pass them to the viewer (replace the existing `<ProductViewer productRef={productRef} />`):

```tsx
          <ProductViewer productRef={productRef} designUrls={designReleased ? designs : []} />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/store/generationStore.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/generationStore.ts frontend/src/components/ChatPanel/index.tsx frontend/src/store/generationStore.test.ts
git commit -m "feat(studio): show generated design on-screen once email is verified"
```

---

## Task 10: Backend regeneration endpoint + `tier="edit"`

**Files:**
- Modify: `backend/app/api/routes/generate.py`
- Test: `backend/tests/test_regeneration_flow.py`

**Interfaces:**
- Produces: `POST /generate/regenerate/{session_id}` → `JobResponse` (same shape as preview); it builds the prompt with the accumulated design intent **plus** `collected["last_change"]`, records the generation with `tier="edit"`, and reuses `_run_generation`. Enforcement of caps is added in Task 11; this task wires the endpoint and the edit tier.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_regeneration_flow.py`:

```python
def test_regenerate_creates_edit_generation(client, monkeypatch):
    # Minimal happy-path: session exists with a product ref; regenerate returns a job.
    from app.api.routes import generate as gen

    session = {
        "id": "s1",
        "product_ref": {"reference_image_url": "ref.png", "product_id": "p1", "colour": "black"},
        "collected": {"design_description": {"summary": "logo"}, "last_change": "make it bigger"},
        "store_id": None,
    }

    captured = {}

    class _T:
        def __init__(self, name): self.name = name
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def order(self, *a, **k): return self
        def execute(self):
            if self.name == "design_sessions":
                return type("R", (), {"data": [session]})()
            return type("R", (), {"data": [{"job_id": "j1", "id": "g1"}]})()
        def insert(self, rows):
            captured["tier"] = rows.get("tier")
            return self

    monkeypatch.setattr(gen, "get_supabase", lambda: type("SB", (), {"table": lambda self, n: _T(n)})())
    monkeypatch.setattr(gen, "check_text", _noop_async)
    monkeypatch.setattr(gen.BackgroundTasks, "add_task", lambda self, *a, **k: None)

    resp = client.post("/generate/regenerate/s1", json={"tier": "edit"})
    assert resp.status_code == 200
    assert captured["tier"] == "edit"


async def _noop_async(*a, **k):
    return None
```

> If the existing generate tests use a different scaffolding, mirror that instead — the key assertion is `tier == "edit"` and a 200.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regeneration_flow.py -q`
Expected: FAIL (404 — route missing).

- [ ] **Step 3: Add the regenerate route**

In `backend/app/api/routes/generate.py`, add after `generate_final`:

```python
@router.post("/generate/regenerate/{session_id}", response_model=JobResponse)
@limiter.limit(settings.rate_limit_str)
async def generate_regenerate(
    session_id: str, body: GenerateRequest, request: Request, background: BackgroundTasks
) -> JobResponse:
    """Regenerate the design with the customer's latest requested change.

    Same pipeline as preview, but tagged tier='edit' and the prompt includes
    collected['last_change']. Caps are enforced in _start_generation (Task 11).
    """
    return await _start_generation(session_id, "edit", background)
```

- [ ] **Step 4: Make `_start_generation` handle the edit tier**

In `_start_generation`, the prompt builder must fold in `last_change` for edits. After `collected = session.get("collected") or {}` add:

```python
    if tier == "edit" and collected.get("last_change"):
        # Layer the requested change onto the existing design intent so the edit
        # modifies rather than replaces the design. build_params/build_prompt
        # already consume collected; surface the change as an extra instruction.
        collected = {**collected, "change_request": collected["last_change"]}
```

Then in `backend/app/services/prompt_builder.py`, in `build_prompt`, if `collected.get("change_request")` is set, append a line to the assembled design block. Locate where the design block string is built and add:

```python
    change = collected.get("change_request")
    if change:
        design_block = f"{design_block}\nRequested change from the customer: {change}."
```

> Match the actual variable name in `build_prompt` (it may be `design_block` or similar); if the prompt is assembled differently, append the change instruction to the design-intent portion before `IMAGE_GEN_PROMPT.format(...)`.

- [ ] **Step 5: Map the `edit` tier to a provider tier**

`get_provider(tier)` only knows `preview`/`final`. In `_start_generation`, translate the provider lookup so `edit` uses the preview provider. Change the `provider = get_provider(tier)` call inside `_run_generation` — pass a provider tier. Simplest: in `_start_generation`, compute `provider_tier = "preview" if tier == "edit" else tier` and pass it through to `_run_generation` as a new kwarg `provider_tier`, defaulting to `tier`; in `_run_generation` use `get_provider(provider_tier)`. Update the `background.add_task(_run_generation, ... tier=tier, provider_tier=provider_tier, ...)` call and the `_run_generation` signature accordingly.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_regeneration_flow.py -q`
Expected: PASS.
Run the generation suite: `cd backend && pytest tests/ -q -k generation`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/generate.py backend/app/services/prompt_builder.py backend/tests/test_regeneration_flow.py
git commit -m "feat(generate): /generate/regenerate with edit tier + change instruction"
```

---

## Task 11: AI-usage caps (`limits.py`) + enforcement

**Files:**
- Create: `backend/app/services/limits.py`
- Modify: `backend/app/api/routes/generate.py`
- Test: `backend/tests/test_limits.py`

**Interfaces:**
- Produces: `limits.edit_count(session_id: str) -> int`; `limits.can_edit(session_id: str) -> bool` (edit_count < settings.regen_edits_per_session); `limits.designs_today(email: str) -> int`; `limits.can_start_design(email: str | None) -> bool` (True when email is None or under the daily cap).
- Consumes: `settings_service.get_settings`, `get_supabase`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_limits.py`:

```python
from app.services import limits, settings_service


def _settings(monkeypatch, *, edits=3, per_day=2):
    monkeypatch.setattr(
        settings_service, "get_settings",
        lambda: settings_service.StudioSettings(edits, per_day, ""),
    )


def test_can_edit_respects_cap(monkeypatch):
    _settings(monkeypatch, edits=2)
    monkeypatch.setattr(limits, "edit_count", lambda sid: 1)
    assert limits.can_edit("s1") is True
    monkeypatch.setattr(limits, "edit_count", lambda sid: 2)
    assert limits.can_edit("s1") is False


def test_can_start_design_allows_when_no_email(monkeypatch):
    _settings(monkeypatch, per_day=2)
    assert limits.can_start_design(None) is True


def test_can_start_design_respects_daily_cap(monkeypatch):
    _settings(monkeypatch, per_day=2)
    monkeypatch.setattr(limits, "designs_today", lambda email: 2)
    assert limits.can_start_design("a@b.com") is False
    monkeypatch.setattr(limits, "designs_today", lambda email: 1)
    assert limits.can_start_design("a@b.com") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_limits.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.limits`).

- [ ] **Step 3: Implement `limits.py`**

Create `backend/app/services/limits.py`:

```python
"""AI-usage caps. Two dimensions:

- Per-session regeneration edits (`can_edit`): first design is free; then
  `regen_edits_per_session` modify-and-regenerate attempts.
- Per-customer/day designs (`can_start_design`): at most
  `designs_per_customer_per_day` NEW (non-edit) designs per verified email in a
  rolling 24h window. Edits do not count toward the daily cap.

PII safety: emails are used for lookups only, never logged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import get_supabase
from app.services import settings_service


def edit_count(session_id: str) -> int:
    """Number of regeneration ('edit') generations recorded for this session."""
    res = (
        get_supabase()
        .table("generations")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("tier", "edit")
        .limit(1)
        .execute()
    )
    return res.count or 0


def can_edit(session_id: str) -> bool:
    return edit_count(session_id) < settings_service.get_settings().regen_edits_per_session


def _session_ids_for_email(email: str) -> list[str]:
    res = get_supabase().table("leads").select("session_id").eq("email", email).execute()
    return [r["session_id"] for r in (res.data or []) if r.get("session_id")]


def designs_today(email: str) -> int:
    """Count NEW (non-edit) generations across this email's sessions in 24h."""
    session_ids = _session_ids_for_email(email)
    if not session_ids:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    res = (
        get_supabase()
        .table("generations")
        .select("id", count="exact")
        .in_("session_id", session_ids)
        .neq("tier", "edit")
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return res.count or 0


def can_start_design(email: str | None) -> bool:
    """True if a NEW design may be generated for this customer right now.

    No email yet (can't attribute) -> allowed; the next attributable attempt is
    counted then.
    """
    if not email:
        return True
    return designs_today(email) < settings_service.get_settings().designs_per_customer_per_day
```

- [ ] **Step 4: Enforce caps in `_start_generation`**

In `backend/app/api/routes/generate.py`, import limits and leads lookup, and enforce before inserting the job. After the `product_ref`/`collected` load and the reference-image check, add:

```python
    from app.services import limits  # noqa: PLC0415

    # Per-customer/day cap for NEW designs (not edits). Uses the session's lead
    # email if one exists yet.
    lead_email = _session_lead_email(session_id)
    if tier != "edit" and not limits.can_start_design(lead_email):
        raise HTTPException(status_code=429, detail="daily_design_limit")
    if tier == "edit" and not limits.can_edit(session_id):
        raise HTTPException(status_code=429, detail="edit_limit")
```

Add the helper at module scope:

```python
def _session_lead_email(session_id: str) -> str | None:
    res = (
        get_supabase()
        .table("leads")
        .select("email")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["email"] if res.data else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_limits.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/limits.py backend/app/api/routes/generate.py backend/tests/test_limits.py
git commit -m "feat(limits): per-session edit cap + per-customer daily design cap"
```

---

## Task 12: Frontend refine loop (regenerate UI + thumbnails)

**Files:**
- Modify: `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`
- Modify: `frontend/src/store/generationStore.ts`
- Modify: `frontend/src/store/chatStore.ts`
- Modify: `frontend/src/components/ChatPanel/index.tsx`
- Test: `frontend/src/store/generationStore.test.ts` (extend)

**Interfaces:**
- Consumes: `data.trigger_regeneration` (added to the `regenerating` state payload in Task 6 — see Step 1 below), `chatState in {offer_refine, describe_changes, regenerating}`.
- Produces: `api.regenerate(sessionId): Promise<{ job_id: string }>`; `generationStore.startRegeneration(sessionId: string): Promise<void>` (appends the new design to `designs[]`).

- [ ] **Step 1: Emit `trigger_regeneration` from the backend**

In `backend/app/services/conversation/orchestrator.py`, in `_public_data`, add a branch so the `regenerating` state tells the client to fire a regeneration (mirrors `generating`'s `trigger_generation`). In the `_public_data` function add:

```python
    if state is S.REGENERATING:
        return {"trigger_regeneration": True}
```

And add to the statement-only tuple so `show_design`/`offer_refine` render sensibly: give `OFFER_REFINE` options and `SHOW_DESIGN` a continue. In `_public_data`:

```python
    if state is S.OFFER_REFINE:
        return {"options": ["Request changes", "Looks good"]}
    if state is S.SHOW_DESIGN:
        return {"continuable": True}
```

Commit this small backend change as part of this task's final commit (it is frontend-driven behaviour).

- [ ] **Step 2: Write the failing test**

Add to `frontend/src/store/generationStore.test.ts`:

```ts
it('startRegeneration appends a second design', async () => {
  const api = await import('../lib/api')
  ;(api.regenerate as unknown as ReturnType<typeof vi.fn>) = vi.fn().mockResolvedValue({ job_id: 'j2' })
  vi.mocked(api.generationStatus).mockResolvedValue({
    status: 'complete', image_url: 'c2.png', watermarked_url: 'wm2.png',
  } as never)
  useGenerationStore.setState({ designs: ['wm1.png'] })
  await useGenerationStore.getState().startRegeneration('s1')
  expect(useGenerationStore.getState().designs).toEqual(['wm1.png', 'wm2.png'])
})
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/store/generationStore.test.ts`
Expected: FAIL (`regenerate` / `startRegeneration` undefined).

- [ ] **Step 4: Add the API function + type**

In `frontend/src/lib/api.ts`, add:

```typescript
/** Regenerate the design with the latest requested change. */
export function regenerate(sessionId: string): Promise<{ job_id: string }> {
  return request<{ job_id: string }>(`/generate/regenerate/${sessionId}`, {
    method: 'POST',
    body: JSON.stringify({ tier: 'edit' }),
  })
}
```

In `frontend/src/lib/types.ts`, add `progress?: { step: number; total: number }` to the `ChatResponse` `data` type if it is strongly typed there (otherwise no change — `data` is already a loose record).

- [ ] **Step 5: Add `startRegeneration` to the generation store**

In `frontend/src/store/generationStore.ts`, import `regenerate`, and add a method that mirrors `startGeneration` but calls `regenerate` and does NOT use the once-guard (each edit is a fresh run):

```typescript
  startRegeneration: async (sessionId: string) => {
    set({ status: 'generating', error: null })
    try {
      const { job_id } = await regenerate(sessionId)
      set({ jobId: job_id })
      for (let i = 0; i < MAX_POLLS; i++) {
        const res = await generationStatus(job_id)
        if (res.status === 'complete') {
          const url = res.watermarked_url ?? res.image_url ?? null
          set(state => ({
            status: 'done',
            previewUrl: url,
            designs: url ? [...state.designs, url] : state.designs,
          }))
          return
        }
        if (res.status === 'failed') { set({ status: 'error' }); return }
        await delay(POLL_INTERVAL_MS)
      }
      set({ status: 'error' })
    } catch (err) {
      set({ status: 'error', error: err instanceof Error ? err.message : 'Regeneration failed' })
    }
  },
```

Add `startRegeneration` to the interface.

- [ ] **Step 6: Handle `trigger_regeneration` + refine input in ChatPanel**

In `frontend/src/store/chatStore.ts`, extend `parseData` to also surface `triggerRegeneration` (`data.trigger_regeneration === true`) and store it (add `triggerRegeneration: boolean` to the interface, initial `false`, set it everywhere `parseData` is consumed, reset in `reset()`).

In `frontend/src/components/ChatPanel/index.tsx`:
- Read `const startRegeneration = useGenerationStore(s => s.startRegeneration)` and `const triggerRegeneration = useChatStore(s => s.triggerRegeneration)`.
- Add an effect to fire regeneration when the state asks for it:

```tsx
  useEffect(() => {
    if (sessionId && triggerRegeneration) {
      void startRegeneration(sessionId)
    }
  }, [sessionId, triggerRegeneration, startRegeneration])
```

- The `offer_refine` chips render through the existing `options` mechanism; the `describe_changes` state is free-text so the existing text input handles it. No extra UI needed beyond what `options`/input already provide.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/store/generationStore.test.ts src/store/chatStore.test.ts`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/types.ts frontend/src/store/generationStore.ts frontend/src/store/chatStore.ts frontend/src/components/ChatPanel/index.tsx backend/app/services/conversation/orchestrator.py frontend/src/store/generationStore.test.ts
git commit -m "feat(studio): refine loop — regenerate on request, append design thumbnail"
```

---

## Task 13: Final-design email on completion (deduped)

**Files:**
- Modify: `backend/app/services/delivery.py`
- Modify: `backend/app/services/conversation/orchestrator.py`
- Modify: `backend/app/prompts.py`
- Modify: `backend/supabase/migrations/20260711000001_app_settings.sql` is NOT reused — add a new migration for the lead flag.
- Create: `backend/supabase/migrations/20260711000002_final_email_flag.sql`
- Test: `backend/tests/test_final_design_email.py`

**Interfaces:**
- Produces: `delivery.send_final_design(session_id: str) -> bool` — sends the final (currently-selected/latest) watermarked design once, only if it differs from the first delivered design; sets `leads.final_email_sent`.

- [ ] **Step 1: Add the lead flag migration**

Create `backend/supabase/migrations/20260711000002_final_email_flag.sql`:

```sql
-- Tracks whether the "final design" email (sent when the customer settles on a
-- regenerated design) has gone out, so it is sent at most once.
alter table leads add column if not exists final_email_sent boolean not null default false;
alter table leads add column if not exists final_email_sent_at timestamptz;
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_final_design_email.py`:

```python
from app.services import delivery


def test_send_final_design_skips_when_no_regeneration(monkeypatch):
    # Only one generation exists (== the first) -> nothing to resend.
    monkeypatch.setattr(delivery, "_completed_generations", lambda sid: [{"id": "g1", "watermarked_url": "wm1"}])
    assert delivery.send_final_design("s1") is False


def test_send_final_design_sends_when_regenerated(monkeypatch):
    gens = [
        {"id": "g1", "watermarked_url": "wm1", "image_url": "c1"},
        {"id": "g2", "watermarked_url": "wm2", "image_url": "c2"},
    ]
    monkeypatch.setattr(delivery, "_completed_generations", lambda sid: gens)
    monkeypatch.setattr(delivery, "_lead_for_session", lambda sid: {"id": "l1", "email": "a@b.com", "name": "Al", "final_email_sent": False})
    sent = {}
    monkeypatch.setattr(delivery, "_deliver_final", lambda lead, url: sent.setdefault("url", url) or True)
    monkeypatch.setattr(delivery, "_mark_final_sent", lambda lead_id: None)
    assert delivery.send_final_design("s1") is True
    assert sent["url"] == "wm2"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_final_design_email.py -q`
Expected: FAIL (`AttributeError: send_final_design`).

- [ ] **Step 4: Add the final-design email body**

In `backend/app/prompts.py`, after `PREVIEW_EMAIL_SUBJECT`, add:

```python
FINAL_DESIGN_EMAIL_SUBJECT = "Your updated MadHats design 🎉"
```

The final email reuses `PREVIEW_EMAIL_HTML` (same template) with this subject — no new HTML needed.

- [ ] **Step 5: Implement `send_final_design`**

In `backend/app/services/delivery.py`, add the helper functions and the public function:

```python
def _completed_generations(session_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at")
        .execute()
    )
    return res.data or []


def _lead_for_session(session_id: str) -> dict | None:
    res = (
        get_supabase()
        .table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _mark_final_sent(lead_id: str) -> None:
    get_supabase().table("leads").update(
        {"final_email_sent": True, "final_email_sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", lead_id).execute()


def _deliver_final(lead: dict, image_path: str) -> bool:
    url = _to_signed(image_path)
    image_bytes = _fetch_image_bytes(url)
    return email_service.send_preview_email(
        lead["email"],
        lead["name"],
        url,
        brief="Here's your updated design based on your latest changes.",
        quote_url="",
        edit_url="",
        talk_url=f"mailto:{settings.resend_from_address}",
        image_bytes=image_bytes,
        subject=prompts.FINAL_DESIGN_EMAIL_SUBJECT,
    )


def send_final_design(session_id: str) -> bool:
    """Email the final (latest) design once, iff it differs from the first
    delivered design. Idempotent via leads.final_email_sent. Best-effort."""
    gens = _completed_generations(session_id)
    if len(gens) < 2:
        return False  # no regeneration -> the first preview email already covered it
    lead = _lead_for_session(session_id)
    if not lead or lead.get("final_email_sent") or not lead.get("email"):
        return False
    latest = gens[-1]
    image_path = latest.get("watermarked_url") or latest.get("image_url")
    if not image_path:
        return False
    if not _deliver_final(lead, image_path):
        return False
    _mark_final_sent(lead["id"])
    log.info("final_design_delivered", session_id=session_id)
    return True
```

- [ ] **Step 6: Add an optional `subject` to `send_preview_email`**

In `backend/app/services/email.py`, give `send_preview_email` a `subject: str | None = None` parameter defaulting to `prompts.PREVIEW_EMAIL_SUBJECT`, and use it where the subject is set. (Find the `def send_preview_email(...)` signature and the `subject=` it passes to the Resend send; thread the parameter through.)

- [ ] **Step 7: Call it at completion**

In `backend/app/services/conversation/orchestrator.py`, when the machine transitions into `QUOTE_REQUESTED`, fire the final-design email best-effort. In `handle_message`, right after `new_state` is finalised (before persisting), add:

```python
        if new_state is ConversationState.QUOTE_REQUESTED:
            try:
                from app.services import delivery  # noqa: PLC0415
                delivery.send_final_design(session_id)
            except Exception:  # noqa: BLE001 — delivery is best-effort
                log.warning("final_design_send_failed", session_id=session_id)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_final_design_email.py -q`
Expected: PASS (2 tests).

- [ ] **Step 9: Commit**

```bash
git add backend/supabase/migrations/20260711000002_final_email_flag.sql backend/app/services/delivery.py backend/app/services/email.py backend/app/services/conversation/orchestrator.py backend/app/prompts.py backend/tests/test_final_design_email.py
git commit -m "feat(delivery): email final design on completion, deduped"
```

---

## Task 14: Env docs + full-suite verification

**Files:**
- Modify: `.env.example` (repo root)
- Modify: `CLAUDE.md` (§ Current implementation state — one bullet)

- [ ] **Step 1: Document new env vars**

In the repo-root `.env.example`, add under a sensible section:

```bash
# --- AI usage caps (initial defaults; overridable in the admin Settings view) ---
REGEN_EDITS_PER_SESSION=3
DESIGNS_PER_CUSTOMER_PER_DAY=2
```

- [ ] **Step 2: Update CLAUDE.md implementation-state note**

Add one bullet under "Current implementation state" summarising: conversational interpreter-first engine, on-screen design display gated at verification with thumbnails, Step X of N progress, admin-capped regeneration loop + global `app_settings`.

- [ ] **Step 3: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS (all prior + new tests). Investigate and fix any regression before continuing.

- [ ] **Step 4: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS.

- [ ] **Step 5: Apply migrations locally and smoke-test**

Run: `cd backend && npx supabase db reset`
Expected: migrations apply cleanly (including the two new ones) and seed loads.

- [ ] **Step 6: Commit**

```bash
git add .env.example CLAUDE.md
git commit -m "docs: env vars + implementation-state note for smarter studio"
```

---

## Self-Review

**Spec coverage:**
- §4.1 Conversation engine → Tasks 4 (skip-filled/field map), 5 (interpret_turn), 6 (orchestrator rewire, side-question/revise/chitchat, goal-leading via no-advance).
- §4.2 On-screen display → Tasks 8 (ProductViewer main+thumbnails), 9 (gate at verification + designs[]).
- §4.3 Progress → Tasks 4 (`progress()`), 6 (payload), 7 (render).
- §4.4 Regeneration loop + limits → Tasks 10 (endpoint/edit tier), 11 (caps), 12 (frontend loop), 13 (final email); new states in Task 4; cap message via orchestrator in Task 6.
- §4.5 Settings store + admin view → Tasks 1, 2, 3.
- §5 Data/schema → migrations in Tasks 1 and 13; `tier="edit"` reuse in Task 10; per-day counting in Task 11.
- §6 Testing → each task is TDD; Task 14 runs full suites + migration reset.

**Placeholder scan:** No "TBD/implement later". Two guarded-import notes (Task 6 `_can_edit`, Task 13 completion hook) are deliberate ordering seams, not placeholders — each ships working code. The two "match the actual variable name" notes (Task 10 Step 4, Task 6 Step 4) are because those internal names live in files the implementer will have open; the surrounding code is fully specified.

**Type consistency:** `StudioSettings(regen_edits_per_session, designs_per_customer_per_day, faq_knowledge)` used identically in Tasks 1/2/3/11. `interpret_turn(state, message, collected, allowed_targets, faq)` defined in Task 5, called in Task 6. `advance_and_skip`/`progress`/`QUESTION_FIELD`/`AUTO_ADVANCE_STATES` defined in Task 4, consumed in Task 6. `designs: string[]` defined in Task 9, appended in Task 12. `tier="edit"` written in Task 10, counted in Task 11, deduped in Task 13. `send_preview_email(..., subject=...)` added in Task 13 Step 6 and used by `_deliver_final`.
