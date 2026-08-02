# Canvas Studio Flow Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Five polish changes to the v2 canvas Design Studio — hide unusable tools, keep the watermark on to the end, redirect to the store's shop after the quote, split the header/lane colours between brand primary and customer bubble, and give phones one panel at a time.

**Architecture:** Four changes are frontend-only and touch one component each. The watermark fix moves an existing per-step lookup into a single pure predicate (`watermark_for_state`) called by *both* payload producers, which is what makes it survive v1-delegated tail turns and resumes. The redirect adds two validated fields to the existing `stores.brand` jsonb — no migration — surfaced through `GET /storefront` and consumed by one new dialog component.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React 18 / TypeScript / Zustand / Tailwind / Vitest + Testing Library (frontend). Konva/react-konva for the canvas.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-08-02-canvas-studio-flow-polish-design.md`. Read it before Task 1.
- **Branch:** `feat/canvas-studio-flow-polish` (already created; the spec is committed on it).
- **Never break v1.** Every backend change is gated on `collected["flow_mode"] == "canvas"` or on a v2-owned registry step. Non-canvas (`session`/`blank`) flows must be byte-identical.
- **No new dependencies.** Backend and frontend both.
- **No PII in logs or Sentry breadcrumbs** (security rule 10) — customer name, email and the reference code never reach a log line.
- **Secrets stay in env vars.** Nothing added here is a secret; the redirect URL is public store config.
- **Backend tests run in Docker**, because the repo-root `.env` points at hosted Supabase and `backend/tests` has no `conftest.py`:
  `MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q <paths>"`
  For the five v2 suites use `-e CANVAS_ORCHESTRATOR_V2=true`.
  If Docker is down, the venv fallback works: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q <paths>`
- **Frontend tests run inside the container** (host `npx vitest` is broken on this Windows machine — missing `@vitest/utils`, the documented per-platform `node_modules` gotcha):
  `docker compose exec -T frontend npx vitest run <paths>`
  Typecheck: `docker compose exec -T frontend npx tsc --noEmit`
- **Measured baselines at branch start** (re-measure by stashing if a number looks off; every previously-recorded figure in CLAUDE.md has been stale at least once):
  - backend flag-off: **1305 passed, 0 failed**
  - five v2 suites flag-on: **355 passed, 0 failed**
  - frontend `src/__tests__ src/components/StoreHeader.test.tsx`: **366 passed, 0 failing**
  - frontend `src/admin`: **63 passed**
- **jsdom performs no layout.** Any test about sizing or breakpoints pins class strings and mount presence only. Say so in comments; never claim a layout assertion.
- **jsdom ships no `matchMedia` and no `ResizeObserver`.** Feature-detect before constructing either (`useIsDesktop` already does).
- **Copy register:** the v2 canvas conversation is formal. `backend/tests/test_v2_copy_guards.py` fails on casual words ("pop your", "grab your", "love where", "no worries", "are you after", "tap") in v2 strings and on any v2 string containing "under the cap". New *frontend* copy in this plan is not covered by that guard, but match the register anyway.

---

## File Structure

**Backend — modify**
- `app/services/conversation/state_machine_v2.py` — add `watermark_for_state`; `public_data_for` calls it; fix the stale comment.
- `app/services/conversation/orchestrator.py` — `_public_data` emits `watermark`.
- `app/services/branding.py` — validate + publish `redirect_url` / `redirect_seconds`; export `DEFAULT_REDIRECT_SECONDS`.

**Backend — test**
- `tests/test_state_machine_v2.py` — watermark predicate table.
- `tests/test_orchestrator_watermark.py` — **new**; the v1/resume producer emits the key.
- `tests/test_branding.py` — redirect field validation.
- `tests/test_storefront.py` — redirect fields reach the customer payload.

**Frontend — create**
- `src/components/CustomiseStudio/RedirectCountdown.tsx` — the end-of-session dialog. One responsibility: count down and navigate.

**Frontend — modify**
- `src/components/DesignStudio/ToolRail.tsx` — `toolsVisible` prop.
- `src/components/DesignStudio/Surface.tsx` — compute and pass `toolsVisible`.
- `src/components/CustomiseStudio/ColumnHeader.tsx` — `tone` prop.
- `src/components/CustomiseStudio/ChatColumn.tsx` — assistant lane colour; `sessionEnded` lock.
- `src/components/CustomiseStudio/index.tsx` — tones, mobile tabs, mount the dialog.
- `src/lib/types.ts` — `Brand.redirect_url`, `Brand.redirect_seconds`.
- `src/admin/views/BrandingView.tsx` — the two new fields.

**Frontend — test (all new files under `src/__tests__/`)**
- `toolRailVisibility.test.tsx`, `columnHeaderTone.test.tsx`, `redirectCountdown.test.tsx`, `mobilePanelTabs.test.tsx`
- extend `ChatColumn.test.tsx` and `chatAttribution.test.tsx`

**Docs**
- `CLAUDE.md` — resolve the watermark ticket, record the new brand fields and the mobile-verification limitation.

---

## Task 1: Watermark predicate (`watermark_for_state`)

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py:344-379`
- Test: `backend/tests/test_state_machine_v2.py` (append)

**Interfaces:**
- Consumes: `canvas_steps.by_id_value(value: str) -> Step | None`; `_WATERMARKED_STEPS: frozenset[S]`
- Produces: `state_machine_v2.watermark_for_state(state: str, collected: dict) -> bool` — Task 2 imports this by that exact name. `state` is the **persisted string value** (e.g. `"review_design"`), never the enum.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_state_machine_v2.py`:

```python
# --- watermark_for_state -----------------------------------------------------
# One pure predicate answers for a live v2 turn, a v1-delegated tail turn and a
# resume, so the three can never disagree. `state` is the persisted string.

def test_watermark_on_at_the_review_with_neither_flag_set():
    # Covers a RESUME landing on review_design: design_confirmed is not set yet,
    # so only the step fallback can answer True here.
    assert v2.watermark_for_state("review_design", _seed()) is True


def test_watermark_off_while_reworking():
    # Reworking IS editing — a diagonal overlay over a design the customer is
    # dragging reads as a broken app.
    assert v2.watermark_for_state("rework_canvas", _seed(design_rework=True)) is False


def test_watermark_off_at_review_when_rework_was_just_tapped():
    # design_rework is checked BEFORE design_confirmed on purpose: a rework pass
    # that re-reaches review_design must not re-stamp a canvas about to be edited.
    c = _seed(design_confirmed=True, design_rework=True)
    assert v2.watermark_for_state("review_design", c) is False


@pytest.mark.parametrize("state", [
    "ask_final_notes", "request_quote", "finalize_canvas",
])
def test_watermark_on_for_the_remaining_owned_steps(state):
    assert v2.watermark_for_state(state, _seed(design_confirmed=True)) is True


@pytest.mark.parametrize("state", [
    "generating", "verify_email", "offer_refine", "quote_requested",
])
def test_watermark_on_through_the_shared_tail(state):
    # These states have NO registry step (v1 owns them), which is exactly why
    # the step lookup cannot be the only source — design_confirmed carries it.
    assert v2.watermark_for_state(state, _seed(design_confirmed=True)) is True


@pytest.mark.parametrize("state", [
    "ask_name", "show_intro", "ask_has_logo", "logo_adjust", "ask_quantity",
])
def test_watermark_off_while_still_designing(state):
    assert v2.watermark_for_state(state, _seed(name="Sam")) is False


@pytest.mark.parametrize("state", [
    "review_design", "ask_final_notes", "request_quote", "finalize_canvas",
    "generating", "quote_requested",
])
def test_watermark_never_fires_for_a_non_canvas_flow(state):
    # v1 session/blank flows must be byte-identical. flow_mode is the guard.
    c = {"flow_mode": "session", "design_confirmed": True}
    assert v2.watermark_for_state(state, c) is False


def test_watermark_ignores_an_unknown_state():
    assert v2.watermark_for_state("no_such_state", _seed()) is False


def test_public_data_for_uses_the_shared_predicate():
    step = cs.by_id(S.REVIEW_DESIGN)
    data = v2.public_data_for(step, _seed())
    assert data["watermark"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=true backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_state_machine_v2.py -k watermark"
```
Expected: FAIL — `AttributeError: module ... has no attribute 'watermark_for_state'`.

- [ ] **Step 3: Implement the predicate**

In `state_machine_v2.py`, replace the `_WATERMARKED_STEPS` comment block and `watermark_for` (currently lines 344-360) with:

```python
# Once the design is finished it is only ever DISPLAYED, never edited — so from
# the review onward every pixel on screen carries a watermark. REWORK_CANVAS is
# the deliberate hole: reworking IS editing, and dragging a logo around under a
# diagonal watermark reads as a broken app.
#
# This set alone is NOT enough, and that was a shipped bug. A shared-tail state
# (generating / verify / refine / quote) has no registry step, and neither does
# a resume — both are served by `orchestrator._public_data`. Use
# `watermark_for_state` below, which covers all three producers.
_WATERMARKED_STEPS: frozenset[S] = frozenset({
    S.REVIEW_DESIGN, S.ASK_FINAL_NOTES, S.REQUEST_QUOTE, S.FINALIZE_CANVAS,
})


def watermark_for_state(state: str, collected: dict) -> bool:
    """True when the on-screen canvas must carry its watermark overlay.

    Pure — a function of the persisted state string plus `collected` — so it
    answers identically for a live v2 turn, a v1-delegated tail turn and a
    resume. Both payload producers call it, which is what stops them drifting.

    Order is load-bearing:

    * `flow_mode` first: v1 session/blank flows never watermark, and this guard
      is what keeps them byte-identical.
    * `design_rework` BEFORE `design_confirmed`: `_apply_review` pops the other
      flag on each tap, but a rework pass that re-reaches REVIEW_DESIGN must not
      re-stamp a canvas the customer is about to edit again.
    * `design_confirmed` carries the whole shared tail and every resume after
      the review — neither has a registry step to look up.
    * The step fallback is what covers REVIEW_DESIGN itself, where neither flag
      is set yet, including a resume landing there.
    """
    if collected.get("flow_mode") != "canvas":
        return False
    if collected.get("design_rework"):
        return False
    if collected.get("design_confirmed"):
        return True
    step = cs.by_id_value(state)
    return bool(step and step.id in _WATERMARKED_STEPS)
```

Then in `public_data_for`, replace `data["watermark"] = watermark_for(step)` with:

```python
    data["watermark"] = watermark_for_state(step.id.value, collected)
```

Delete the now-unused `watermark_for` function.

- [ ] **Step 4: Check for other callers of `watermark_for`**

```
grep -rn "watermark_for\b" backend/
```
Expected: only the definition and `public_data_for` existed. If a test references the old name, update it to `watermark_for_state`.

- [ ] **Step 5: Run the tests to verify they pass**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=true backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_state_machine_v2.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_canvas_steps.py tests/test_v2_copy_guards.py"
```
Expected: PASS, and the total is **355 + 10 new = 365**.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "fix(canvas): one watermark predicate for every payload producer"
```

---

## Task 2: The v1/resume producer emits `watermark`

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py:1193-1207`
- Test: `backend/tests/test_orchestrator_watermark.py` (create)

**Interfaces:**
- Consumes: `state_machine_v2.watermark_for_state(state: str, collected: dict) -> bool` (Task 1)
- Produces: `orchestrator._public_data(...)` now always includes the key `"watermark"` (a bool). `sessions.get_session` reuses this function, so this is also the resume payload.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_orchestrator_watermark.py`:

```python
"""`orchestrator._public_data` serves BOTH v1-delegated turns and every resume
(`sessions.get_session` imports this same function), so it is the producer that
has to carry the watermark flag through the shared tail. Before this it emitted
nothing, and `chatStore.parseData` fell back to `false` — the design lost its
watermark the moment the flow left finalize_canvas, and on any reload."""
from __future__ import annotations

import pytest

from app.services.conversation.orchestrator import _public_data
from app.services.conversation.state_machine import ConversationState as S


@pytest.mark.parametrize("state", [
    S.QUOTE_REQUESTED, S.GENERATING, S.VERIFY_EMAIL, S.OFFER_REFINE,
])
def test_tail_states_carry_the_watermark_for_a_confirmed_canvas_design(state):
    data = _public_data(state, {"flow_mode": "canvas", "design_confirmed": True})
    assert data["watermark"] is True


def test_a_canvas_session_still_designing_is_not_watermarked():
    data = _public_data(S.CANVAS_DESIGN, {"flow_mode": "canvas"})
    assert data["watermark"] is False


def test_a_non_canvas_session_is_never_watermarked():
    data = _public_data(S.QUOTE_REQUESTED, {"flow_mode": "session",
                                            "design_confirmed": True})
    assert data["watermark"] is False


def test_the_key_is_always_present_so_the_frontend_never_guesses():
    # chatStore.parseData reads `'watermark' in data` before falling back. The
    # key being unconditionally present is what retires that fallback.
    assert "watermark" in _public_data(S.GREETING, {})
```

- [ ] **Step 2: Run it to verify it fails**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_orchestrator_watermark.py"
```
Expected: FAIL with `KeyError: 'watermark'`.

- [ ] **Step 3: Implement**

In `orchestrator.py`, inside `_public_data`, immediately before `return data`:

```python
    # The canvas watermark. This function serves v1 turns AND, via
    # sessions.get_session, every resume — neither carries a v2 canvas
    # directive, so without this key the frontend defaults to unwatermarked and
    # a finished design loses its overlay on the next turn and on reload.
    # Function-local import: state_machine_v2 pulls in canvas_steps, which
    # reaches back into leads/intent_extractor, and a module-level import here
    # would close that cycle.
    from app.services.conversation.state_machine_v2 import watermark_for_state

    data["watermark"] = watermark_for_state(state.value, collected)
    return data
```

- [ ] **Step 4: Run it to verify it passes**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_orchestrator_watermark.py"
```
Expected: PASS (7 tests).

- [ ] **Step 5: Run the whole backend suite — this touches a function on every turn's hot path**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q"
```
Expected: **1305 + 10 (Task 1) + 7 (this task) = 1322 passed, 0 failed.** If any pre-existing test asserts an exact `data` dict for a v1 state, it will now fail on the extra key — update it to assert the keys it cares about rather than equality, and note it in the commit message.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_orchestrator_watermark.py
git commit -m "fix(canvas): keep the watermark on through the tail and on resume"
```

---

## Task 3: Redirect fields in branding + storefront

**Files:**
- Modify: `backend/app/services/branding.py:23-34, 94-124, 152-168`
- Test: `backend/tests/test_branding.py` (append), `backend/tests/test_storefront.py` (append)

**Interfaces:**
- Produces:
  - `branding.DEFAULT_REDIRECT_SECONDS: int = 30`
  - `validate_brand` accepts `redirect_url: str` (http(s) with a netloc; `""`/`None` clears the key) and `redirect_seconds: int` (5..300 inclusive; `bool` rejected; non-int rejected)
  - `public_brand` includes both keys when set
  - `GET /storefront` → `{"brand": {..., "redirect_url": str, "redirect_seconds": int}}`
- Task 6 (frontend) consumes `Brand.redirect_url` / `Brand.redirect_seconds` with these exact snake_case names.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_branding.py`:

```python
# --- end-of-session redirect --------------------------------------------------

def test_validate_brand_accepts_a_redirect():
    cleaned = branding.validate_brand({
        "redirect_url": "  https://madhats.com.au/collections/caps  ",
        "redirect_seconds": 45,
    })
    assert cleaned["redirect_url"] == "https://madhats.com.au/collections/caps"
    assert cleaned["redirect_seconds"] == 45


def test_validate_brand_clears_an_empty_redirect_url():
    # An empty string is how the admin form turns the redirect OFF. Dropping the
    # key (rather than storing "") is what makes `public_brand` omit it and the
    # dialog never mount.
    assert "redirect_url" not in branding.validate_brand({"redirect_url": "   "})


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "ftp://madhats.com.au", "madhats.com.au", "https://",
])
def test_validate_brand_rejects_a_non_http_redirect(url):
    with pytest.raises(ValueError):
        branding.validate_brand({"redirect_url": url})


@pytest.mark.parametrize("secs", [4, 301, 0, -1, "30", 30.5, True, None])
def test_validate_brand_rejects_out_of_range_seconds(secs):
    # `True` is rejected explicitly: bool is a subclass of int in Python, so a
    # bare isinstance(x, int) check would accept it and store `true` as a delay.
    with pytest.raises(ValueError):
        branding.validate_brand({"redirect_seconds": secs})


@pytest.mark.parametrize("secs", [5, 30, 300])
def test_validate_brand_accepts_the_range_bounds(secs):
    assert branding.validate_brand({"redirect_seconds": secs})["redirect_seconds"] == secs


def test_public_brand_publishes_the_redirect():
    out = branding.public_brand(
        {"redirect_url": "https://madhats.com.au", "redirect_seconds": 20}, "http://api/")
    assert out["redirect_url"] == "https://madhats.com.au"
    assert out["redirect_seconds"] == 20


def test_public_brand_omits_an_unconfigured_redirect():
    # No URL => the frontend mounts no dialog and starts no timer. Absence is
    # the off switch; there is no separate enabled flag.
    assert branding.public_brand({"primary_colour": "#FF5C00"}, "http://api/") == {
        "primary_colour": "#FF5C00"}
```

Append to `backend/tests/test_storefront.py`:

```python
def test_storefront_publishes_the_redirect_config(client, store_headers, monkeypatch):
    monkeypatch.setattr(
        "app.services.branding.media_url", lambda p, base: f"http://api/media/{p}")
    monkeypatch.setitem(_STORE["brand"], "redirect_url", "https://acme.example")
    monkeypatch.setitem(_STORE["brand"], "redirect_seconds", 15)
    body = client.get("/storefront", headers=store_headers).json()
    assert body["brand"]["redirect_url"] == "https://acme.example"
    assert body["brand"]["redirect_seconds"] == 15
    # Still no leaks alongside the new fields.
    assert "watermark_asset_url" not in body["brand"]
    assert "sales_notification_email" not in body
```

- [ ] **Step 2: Run to verify they fail**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_branding.py tests/test_storefront.py"
```
Expected: FAIL — the new cases raise nothing / the keys are absent.

- [ ] **Step 3: Implement**

In `branding.py`, extend the module docstring's brand shape with `redirect_url, redirect_seconds`, then add below `MAX_LABEL_LEN`:

```python
# End-of-session redirect: after the quote reference is shown, the customer is
# offered a countdown back to the store's own shop. Absence of `redirect_url` is
# the off switch — there is no separate enabled flag.
DEFAULT_REDIRECT_SECONDS = 30
MIN_REDIRECT_SECONDS = 5
MAX_REDIRECT_SECONDS = 300
```

Add `"redirect_url", "redirect_seconds"` to `_PUBLIC_KEYS`.

Add a helper above `validate_brand`:

```python
def _validate_redirect(cleaned: dict) -> None:
    """In-place validation of the two redirect fields. Mutates `cleaned`:
    a blank URL is REMOVED rather than stored as "", because `public_brand`
    skips falsy values and the frontend keys "no redirect" off the key's
    absence."""
    url = cleaned.get("redirect_url")
    if url is not None:
        url = str(url).strip()
        if not url:
            cleaned.pop("redirect_url", None)
        else:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("redirect_url must be an http(s) URL")
            cleaned["redirect_url"] = url

    secs = cleaned.get("redirect_seconds")
    if secs is None:
        cleaned.pop("redirect_seconds", None)
        return
    # bool is a subclass of int, so `isinstance(secs, int)` alone would accept
    # True and store it as a one-second delay.
    if isinstance(secs, bool) or not isinstance(secs, int):
        raise ValueError("redirect_seconds must be a whole number of seconds")
    if not MIN_REDIRECT_SECONDS <= secs <= MAX_REDIRECT_SECONDS:
        raise ValueError(
            f"redirect_seconds must be between {MIN_REDIRECT_SECONDS} "
            f"and {MAX_REDIRECT_SECONDS}")
```

Call it inside `validate_brand`, immediately before `return cleaned`:

```python
    _validate_redirect(cleaned)
    return cleaned
```

- [ ] **Step 4: Run to verify they pass**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_branding.py tests/test_storefront.py tests/test_admin_store_branding.py"
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/branding.py backend/tests/test_branding.py backend/tests/test_storefront.py
git commit -m "feat(branding): per-store end-of-session redirect url and countdown"
```

---

## Task 4: Hide the tool rail when the canvas is not editable

**Files:**
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx:6-64`
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:59-63, 386-398`
- Test: `frontend/src/__tests__/toolRailVisibility.test.tsx` (create)

**Interfaces:**
- Produces: `ToolRailProps.toolsVisible?: boolean` — **defaults to `true`**. Every existing call site and test omits it and must keep its current behaviour.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/toolRailVisibility.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

function renderRail(toolsVisible?: boolean) {
  return render(
    <ToolRail
      onAddText={vi.fn()} onUploadClick={vi.fn()} onGraphicsClick={vi.fn()}
      colourways={[{ name: 'Red', hex: '#c00' }]}
      onRender={vi.fn()} rendering={false} rendered={false}
      toolsVisible={toolsVisible}
    />,
  )
}

const CONTROLS = [/add text/i, /upload image/i, /graphics/i, /draw/i, /done designing/i]

describe('ToolRail visibility', () => {
  it('renders every control when the canvas is editable', () => {
    renderRail(true)
    for (const name of CONTROLS) {
      expect(screen.getByRole('button', { name })).toBeInTheDocument()
    }
    expect(screen.getByRole('button', { name: 'Red' })).toBeInTheDocument()
  })

  it('renders NO control when the canvas is not editable', () => {
    // Disabled buttons at 50% opacity read as a broken app, not as "not yet" —
    // so they are removed from the DOM, not merely dimmed.
    renderRail(false)
    for (const name of CONTROLS) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: 'Red' })).not.toBeInTheDocument()
  })

  it('defaults to visible when the prop is omitted (v1 call shape)', () => {
    renderRail(undefined)
    expect(screen.getByRole('button', { name: /add text/i })).toBeInTheDocument()
  })

  it('keeps its width classes while empty so the cap does not resize', () => {
    // CanvasStage sizes itself from a live measurement of the centre column
    // (ResizeObserver + MutationObserver). A rail that collapsed to zero width
    // would resize the cap on every turn transition. jsdom does no layout, so
    // this pins the class tokens, not pixels.
    const { container } = renderRail(false)
    const root = container.firstElementChild as HTMLElement
    expect(root.className).toContain('md:w-44')
    expect(root.className).toContain('lg:w-52')
    expect(root.className).toContain('xl:w-64')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```
docker compose exec -T frontend npx vitest run src/__tests__/toolRailVisibility.test.tsx
```
Expected: FAIL — the "NO control" case finds the buttons.

- [ ] **Step 3: Implement in `ToolRail.tsx`**

Add to `ToolRailProps`:

```ts
  /** False while the canvas is not editable on this turn: render an empty rail
   *  rather than a column of disabled buttons. Defaults to true so v1 call
   *  sites (which never pass it) are unaffected. */
  toolsVisible?: boolean
```

Add `toolsVisible` to the destructured parameter list, and immediately before the existing `return (`:

```tsx
  // Width classes are duplicated deliberately between the two returns rather
  // than hoisted: they are the load-bearing part of the empty branch (the
  // responsive stage measures this column), and a shared constant is easy to
  // "clean up" out of the branch that needs it most.
  if (toolsVisible === false) {
    return <div data-testid="tool-rail-empty" className="flex flex-col gap-2.5 p-3 xl:p-4 w-full md:w-44 lg:w-52 xl:w-64" />
  }
```

- [ ] **Step 4: Wire it in `Surface.tsx`**

After the existing `const showAdjust = ...` line (~line 63) add:

```tsx
  // The tool rail's controls render only when the canvas is actually editable
  // this turn. Every other v2 step is a chat question, so a column of disabled
  // buttons there reads as broken rather than as "not yet". Same predicate as
  // showAdjust — the Adjust panel and the tools appear and disappear together.
  const toolsVisible = isV2 ? v2Editing : unlocked
```

and pass `toolsVisible={toolsVisible}` to `<ToolRail ... />` (~line 398).

- [ ] **Step 5: Run the test plus the neighbouring suites**

```
docker compose exec -T frontend npx vitest run src/__tests__/toolRailVisibility.test.tsx src/__tests__/ToolRail.test.tsx src/__tests__/toolRailUploadHighlight.test.tsx src/__tests__/surfaceDirective.test.tsx src/__tests__/surfaceRework.test.tsx
```
Expected: PASS. If `surfaceDirective.test.tsx` now fails looking for a tool button at a no-tool directive, that is the *intended* behaviour change — update that assertion to expect absence and say so in the commit message.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/toolRailVisibility.test.tsx
git commit -m "feat(canvas): hide the tool rail's controls when the canvas is not editable"
```

---

## Task 5: Column header and chat lane colours

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/ColumnHeader.tsx`
- Modify: `frontend/src/components/CustomiseStudio/index.tsx:64, 92-96`
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:471-472`
- Test: `frontend/src/__tests__/columnHeaderTone.test.tsx` (create); extend `frontend/src/__tests__/chatAttribution.test.tsx`

**Interfaces:**
- Produces: `ColumnHeader` gains a **required** `tone: 'primary' | 'customer'` prop. Two allowed values, so a caller cannot invent a third.
  - `'primary'` → `bg-accent` (`--brand-primary`), used by the chat/Ricardo column
  - `'customer'` → `bg-chatUserBubble` (`--chat-user-bubble`), used by the canvas column

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/columnHeaderTone.test.tsx`:

```tsx
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ColumnHeader } from '../components/CustomiseStudio/ColumnHeader'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

describe('ColumnHeader tone', () => {
  it('fills with the store primary colour for the assistant half', () => {
    render(<ColumnHeader name="Ricardo" instruction="Your turn — answer here"
                         active tone="primary" />)
    expect(screen.getByRole('status').className).toContain('bg-accent')
  })

  it('fills with the customer bubble colour for the customer half', () => {
    render(<ColumnHeader name="Your design" instruction="Your turn — design here"
                         active tone="customer" />)
    expect(screen.getByRole('status').className).toContain('bg-chatUserBubble')
  })

  it('uses neither tone while resting', () => {
    const { container } = render(
      <ColumnHeader name="Ricardo" instruction="x" active={false} tone="primary" />)
    const el = container.firstElementChild as HTMLElement
    expect(el.className).not.toContain('bg-accent')
    expect(el.className).toContain('bg-surfaceAlt')
  })
})

describe('CustomiseStudio assigns each half its own tone', () => {
  beforeEach(() => {
    useChatStore.getState().reset()
    useSessionStore.setState({
      sessionId: 'sess-1', shareToken: 't', state: 'greeting',
      productRef: {
        id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
        reference_image_url: 'https://example.com/cap.jpg', view_images: {},
      },
      entryContext: null, view: 'canvas',
    } as never)
  })

  it('gives the chat header the primary colour when it is active', () => {
    useChatStore.setState({
      canvasDirective: {
        allowedTools: [], targetFace: null, autoOpen: null,
        instructions: null, showDone: false, unlockAll: false,
      },
    } as never)
    render(<CustomiseStudio />)
    // The chat is the active half at a no-tool step, so its header is filled.
    expect(screen.getByRole('status').className).toContain('bg-accent')
  })

  it('gives the canvas header the customer bubble colour when it is active', () => {
    useChatStore.setState({
      canvasDirective: {
        allowedTools: ['upload'], targetFace: null, autoOpen: null,
        instructions: null, showDone: true, unlockAll: false,
      },
    } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').className).toContain('bg-chatUserBubble')
  })
})
```

Append to `frontend/src/__tests__/chatAttribution.test.tsx` (inside its existing top-level `describe`, matching that file's existing render helper — read it first and reuse its setup rather than duplicating one):

```tsx
  it('lanes the assistant in the brand primary and the customer in their own colour', () => {
    // The two speakers must be told apart by more than position. Ricardo carries
    // the store's primary colour; the customer carries the bubble colour the
    // admin set for them. Canvas accent belongs to the design tools only.
    renderWithMessages([
      { id: 'a', role: 'assistant', text: 'Hello' },
      { id: 'b', role: 'user', text: 'Hi' },
    ])
    const lanes = screen.getAllByTestId('msg-lane')
    expect(lanes[0].className).toContain('border-accent')
    expect(lanes[0].className).not.toContain('border-canvasAccent')
    expect(lanes[1].className).toContain('border-chatUserBubble')
  })
```

- [ ] **Step 2: Run to verify they fail**

```
docker compose exec -T frontend npx vitest run src/__tests__/columnHeaderTone.test.tsx src/__tests__/chatAttribution.test.tsx
```
Expected: FAIL — `tone` is not a prop (TS error at runtime it is simply ignored, so the class assertions fail).

- [ ] **Step 3: Implement `ColumnHeader.tsx`**

```tsx
/** Which colour the ACTIVE fill uses. Two values, not a free class string, so
 *  the palette split is enumerable and a caller cannot invent a third half.
 *  'primary'  = the store's brand primary (--brand-primary) — the assistant.
 *  'customer' = the customer's own chat bubble colour (--chat-user-bubble).
 *  Canvas accent is deliberately absent: it belongs to the design tools. */
export type HeaderTone = 'primary' | 'customer'

const TONE_FILL: Record<HeaderTone, string> = {
  primary: 'bg-accent text-white',
  customer: 'bg-chatUserBubble text-white',
}

export function ColumnHeader({ name, instruction, active, tone }: {
  name: string
  instruction: string
  active: boolean
  tone: HeaderTone
}) {
  return (
    <div
      {...(active ? { role: 'status' } : {})}
      className={`flex h-8 flex-none items-center gap-2 px-4 text-xs font-semibold transition-colors duration-300 ${
        active ? TONE_FILL[tone] : 'border-b border-border bg-surfaceAlt text-textMuted'
      }`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 flex-none rounded-full ${
          active ? 'animate-pulse bg-white' : 'bg-border'
        }`}
      />
      {active ? instruction : name}
    </div>
  )
}
```

Keep the existing top-of-file doc comment and add a line noting the tone split.

- [ ] **Step 4: Update the two call sites in `index.tsx`**

Canvas column (~line 64): add `tone="customer"`.
Chat column (~line 92): add `tone="primary"`.

- [ ] **Step 5: Update the assistant lane in `ChatColumn.tsx`**

Line ~472: `'items-start border-l-2 border-canvasAccent pl-2'` → `'items-start border-l-2 border-accent pl-2'`.

- [ ] **Step 6: Run to verify they pass**

```
docker compose exec -T frontend npx vitest run src/__tests__/columnHeaderTone.test.tsx src/__tests__/chatAttribution.test.tsx src/__tests__/customiseStudioFocus.test.tsx src/__tests__/CustomiseStudio.test.tsx src/__tests__/ChatColumn.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```
Expected: PASS and a clean typecheck — `tone` is required, so `tsc` proves both call sites were updated.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CustomiseStudio/ColumnHeader.tsx frontend/src/components/CustomiseStudio/index.tsx frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__/columnHeaderTone.test.tsx frontend/src/__tests__/chatAttribution.test.tsx
git commit -m "feat(studio): brand primary for the assistant half, bubble colour for the customer half"
```

---

## Task 6: End-of-session countdown dialog

**Files:**
- Create: `frontend/src/components/CustomiseStudio/RedirectCountdown.tsx`
- Modify: `frontend/src/lib/types.ts:120-136`
- Modify: `frontend/src/components/CustomiseStudio/index.tsx`
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:229-230, 705, 770, 786, 739`
- Test: `frontend/src/__tests__/redirectCountdown.test.tsx` (create); extend `frontend/src/__tests__/ChatColumn.test.tsx`

**Interfaces:**
- Consumes: `Brand.redirect_url?: string`, `Brand.redirect_seconds?: number` (Task 3's snake_case payload keys); `useBrandStore(s => s.brand)`; `useChatStore(s => s.chatState)`
- Produces: `RedirectCountdown` — a self-contained default-exported-by-name component taking **no props**. It reads the store itself and renders `null` unless it should be open.
- Produces: `DEFAULT_REDIRECT_SECONDS = 30` exported from `RedirectCountdown.tsx` (mirrors `branding.DEFAULT_REDIRECT_SECONDS`).

- [ ] **Step 1: Add the Brand fields to `types.ts`**

Inside `interface Brand`:

```ts
  /** Where to send the customer once the quote reference has been shown.
   *  Absence is the off switch — no URL means no dialog and no timer. */
  redirect_url?: string
  /** Countdown before that redirect fires, in seconds. Server-validated to
   *  5..300; falls back to DEFAULT_REDIRECT_SECONDS when unset. */
  redirect_seconds?: number
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/__tests__/redirectCountdown.test.tsx`:

```tsx
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useChatStore } from '../store/chatStore'
import { useBrandStore } from '../store/brandStore'
import { RedirectCountdown } from '../components/CustomiseStudio/RedirectCountdown'

const assign = vi.fn()

beforeEach(() => {
  vi.useFakeTimers()
  assign.mockClear()
  // jsdom's window.location is not assignable; replace just the method we call.
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...window.location, assign },
  })
  useChatStore.getState().reset()
  useBrandStore.setState({ brand: {}, loaded: true } as never)
})

afterEach(() => {
  vi.useRealTimers()
})

function open(seconds?: number) {
  useBrandStore.setState({
    brand: { redirect_url: 'https://madhats.com.au', redirect_seconds: seconds },
  } as never)
  useChatStore.setState({ chatState: 'quote_requested' } as never)
  return render(<RedirectCountdown />)
}

function tick(seconds: number) {
  act(() => { vi.advanceTimersByTime(seconds * 1000) })
}

describe('RedirectCountdown', () => {
  it('renders nothing before the session ends', () => {
    useBrandStore.setState({ brand: { redirect_url: 'https://madhats.com.au' } } as never)
    useChatStore.setState({ chatState: 'ask_quantity' } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when the store configured no redirect', () => {
    // Absence of the URL is the off switch — an unconfigured store must behave
    // exactly as it did before this feature existed.
    useChatStore.setState({ chatState: 'quote_requested' } as never)
    const { container } = render(<RedirectCountdown />)
    expect(container).toBeEmptyDOMElement()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })

  it('counts down from the configured seconds and then redirects', () => {
    open(10)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('10')
    tick(4)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('6')
    expect(assign).not.toHaveBeenCalled()
    tick(6)
    expect(assign).toHaveBeenCalledWith('https://madhats.com.au')
  })

  it('falls back to 30 seconds when the store set no duration', () => {
    open(undefined)
    expect(screen.getByTestId('redirect-countdown')).toHaveTextContent('30')
  })

  it('redirects immediately on "Go to the shop now"', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    open(30)
    await user.click(screen.getByRole('button', { name: /go to the shop now/i }))
    expect(assign).toHaveBeenCalledWith('https://madhats.com.au')
  })

  it('cancels for good on "Stay here" — no later tick may fire it', async () => {
    // The interval must be cleared, not merely hidden. A dialog that closes but
    // keeps ticking would yank the customer away from the design they chose to
    // stay and look at.
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    open(10)
    await user.click(screen.getByRole('button', { name: /stay here/i }))
    expect(screen.queryByTestId('redirect-countdown')).not.toBeInTheDocument()
    tick(120)
    expect(assign).not.toHaveBeenCalled()
  })

  it('never fires after unmount', () => {
    const { unmount } = open(10)
    unmount()
    tick(60)
    expect(assign).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 3: Run it to verify it fails**

```
docker compose exec -T frontend npx vitest run src/__tests__/redirectCountdown.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 4: Implement `RedirectCountdown.tsx`**

```tsx
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useBrandStore } from '../../store/brandStore'
import { useChatStore } from '../../store/chatStore'

/** Mirrors `branding.DEFAULT_REDIRECT_SECONDS`. Used when a store set a URL but
 *  left the duration blank. */
export const DEFAULT_REDIRECT_SECONDS = 30

/** The one chat state that ends a v2 canvas session: `sessions.finalize_canvas`
 *  returns it with the MH-XXXXXX reference in the reply. */
const END_STATE = 'quote_requested'

/**
 * The end-of-session hand-off: the quote is in, so offer the customer their way
 * back to the shop.
 *
 * Self-contained by design — it takes no props and reads both stores itself, so
 * mounting it is a one-liner and no parent has to know the trigger state.
 *
 * A store that configured no `redirect_url` gets NOTHING: no dialog, no timer,
 * no navigation. Absence of the URL is the off switch; there is no separate
 * enabled flag to fall out of step with it.
 */
export function RedirectCountdown() {
  const chatState = useChatStore(s => s.chatState)
  const brand = useBrandStore(s => s.brand)
  const url = brand.redirect_url
  const total = brand.redirect_seconds ?? DEFAULT_REDIRECT_SECONDS

  const shouldOpen = chatState === END_STATE && !!url
  const [cancelled, setCancelled] = useState(false)
  const [left, setLeft] = useState(total)
  const panelRef = useRef<HTMLDivElement>(null)
  const stayRef = useRef<HTMLButtonElement>(null)

  const open = shouldOpen && !cancelled

  // Re-seed whenever the dialog becomes eligible, so a session that somehow
  // re-enters the end state does not resume a half-spent counter.
  useEffect(() => {
    if (shouldOpen) setLeft(total)
  }, [shouldOpen, total])

  // The tick. Cleared on close AND on unmount — a cancelled countdown that kept
  // running would yank the customer away from the design they chose to stay for.
  useEffect(() => {
    if (!open) return
    const id = setInterval(() => {
      setLeft(prev => {
        if (prev <= 1) {
          clearInterval(id)
          if (url) window.location.assign(url)
          return 0
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(id)
  }, [open, url])

  // Focus the low-cost control, not the one that navigates away — same rule the
  // ReviewDialog follows for its close button.
  useEffect(() => {
    if (open) stayRef.current?.focus()
  }, [open])

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setCancelled(true)
      if (e.key !== 'Tab' || !panelRef.current) return
      const f = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (f.length === 0) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open])

  if (!open || !url) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      // Backdrop dismiss, guarded so a click INSIDE the panel that bubbles here
      // does not close it. Escape alone is not a dismiss on a phone.
      onClick={e => { if (e.target === e.currentTarget) setCancelled(true) }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="redirect-title"
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-6 shadow-xl"
      >
        <h2 id="redirect-title" className="text-base font-semibold text-textPrimary">
          Your request is with our team
        </h2>
        <p className="mt-2 text-sm text-textSub">
          We will take you back to the shop in{' '}
          <strong data-testid="redirect-countdown" className="text-textPrimary">{left}</strong>{' '}
          seconds. You are welcome to stay and look at your design instead.
        </p>
        <div className="mt-5 flex flex-col gap-2 sm:flex-row-reverse">
          <button
            type="button"
            onClick={() => window.location.assign(url)}
            className="rounded-full bg-accent px-5 py-2.5 text-sm font-semibold text-white hover:bg-accentHover"
          >
            Go to the shop now
          </button>
          <button
            ref={stayRef}
            type="button"
            onClick={() => setCancelled(true)}
            className="rounded-full border border-border px-5 py-2.5 text-sm text-textPrimary hover:border-accent"
          >
            Stay here
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
```

- [ ] **Step 5: Run it to verify it passes**

```
docker compose exec -T frontend npx vitest run src/__tests__/redirectCountdown.test.tsx
```
Expected: PASS (7 tests).

- [ ] **Step 6: Mount it and lock the ended session**

In `CustomiseStudio/index.tsx`: import `RedirectCountdown` and render `<RedirectCountdown />` as the last child of the outer `<div className="h-screen bg-base flex flex-col">`. It portals to `document.body`, so its position in the tree only affects unmount timing.

In `ChatColumn.tsx`, replace the `inputLocked` definition (~line 230):

```tsx
  // The session is over: the quote reference has been issued and there is
  // nothing left the customer can say that moves anything. An enabled composer
  // here invites an answer to a question that no longer exists, which reads as
  // a broken bot — the same reason awaitingEmailVerify locks it.
  const sessionEnded = chatState === 'quote_requested'
  const inputLocked = sending || awaitingEmailVerify || sessionEnded
```

Then suppress the remaining affordances by adding `&& !sessionEnded` to each of these render guards:
- the Back menu block (`{sessionId && backTargets.length > 0 && !sending && !awaitingEmailVerify && (`)
- the option chip row (`{options.length > 0 && colourSwatches.length === 0 && !multiselect && (`)
- the `options2` row (`{options2.length > 0 && (`)
- the voice block (`{speech.supported && (`)

and change `isStatementOnly` to `const isStatementOnly = continuable && !sending && !awaitingEmailVerify && !sessionEnded`.

- [ ] **Step 7: Add the lock test**

Append to `frontend/src/__tests__/ChatColumn.test.tsx` (reuse that file's existing render helper and store setup):

```tsx
  it('locks every affordance once the quote reference has been issued', () => {
    // Nothing the customer types can move a finished session. Leaving the
    // composer live would invite an answer to a question that no longer exists.
    renderColumnAtState('quote_requested', { options: ['Something'], continuable: true })
    expect(screen.getByPlaceholderText(/type your message/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: /send/i })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Something' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /continue/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /back/i })).not.toBeInTheDocument()
  })
```

If `ChatColumn.test.tsx` has no `renderColumnAtState` helper, write one in that file following its existing setup (it already mounts `ChatColumn` with store state) — do not duplicate an ad-hoc mount.

- [ ] **Step 8: Run the affected suites and typecheck**

```
docker compose exec -T frontend npx vitest run src/__tests__/redirectCountdown.test.tsx src/__tests__/ChatColumn.test.tsx src/__tests__/CustomiseStudio.test.tsx src/__tests__/backMenu.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```
Expected: PASS, clean typecheck.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/CustomiseStudio/RedirectCountdown.tsx frontend/src/components/CustomiseStudio/index.tsx frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/lib/types.ts frontend/src/__tests__/redirectCountdown.test.tsx frontend/src/__tests__/ChatColumn.test.tsx
git commit -m "feat(studio): countdown back to the shop once the quote reference is issued"
```

---

## Task 7: Mobile — one panel at a time

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/index.tsx`
- Test: `frontend/src/__tests__/mobilePanelTabs.test.tsx` (create)

**Interfaces:**
- Consumes: `useIsDesktop()` from `../../lib/useIsDesktop`; `useActiveSurface(): 'canvas' | 'chat'`; `useChatStore(s => s.triggerFinalize)`
- Produces: `data-testid="panel-tabs"` (the tab bar, mobile only) and `data-testid="tab-chat"` / `data-testid="tab-canvas"` buttons, each carrying `aria-selected`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/mobilePanelTabs.test.tsx`:

```tsx
import { describe, expect, it, beforeEach, vi } from 'vitest'
import { render, screen, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

// jsdom ships no matchMedia, so useIsDesktop falls back to `true`. Stub it to
// drive the phone branch. Feature detection is what makes this stub-able at all.
function setViewport(desktop: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value: (query: string) => ({
      matches: desktop, media: query, onchange: null,
      addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  })
}

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

const directive = (allowedTools: string[], showDone = false) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone, unlockAll: false,
})

beforeEach(() => {
  useChatStore.getState().reset()
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  } as never)
})

describe('phone: one panel at a time', () => {
  beforeEach(() => setViewport(false))

  it('opens on the chat', () => {
    render(<CustomiseStudio />)
    expect(screen.getByTestId('tab-chat')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).toContain('hidden')
    expect(screen.getByTestId('chat-column-wrap').className).not.toContain('hidden')
  })

  it('keeps the hidden panel MOUNTED', () => {
    // Surface.doRender() flattens through stageRef in a loop over the decorated
    // faces. Unmounting the Konva stage would null that ref and break finalize
    // outright, and remounting would lose the in-progress design. Hiding is the
    // only safe way to show one panel at a time.
    render(<CustomiseStudio />)
    expect(screen.getByTestId('surface')).toBeInTheDocument()
    expect(screen.getByTestId('chat-column')).toBeInTheDocument()
  })

  it('auto-switches to the canvas when the flow needs the canvas', () => {
    render(<CustomiseStudio />)
    act(() => {
      useChatStore.setState({ canvasDirective: directive(['upload'], true) } as never)
    })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
  })

  it('lets the customer peek at the other panel, and the peek sticks', async () => {
    const user = userEvent.setup()
    render(<CustomiseStudio />)
    await user.click(screen.getByTestId('tab-canvas'))
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    // A re-render with the SAME active surface must not snap the peek back —
    // the sync effect is keyed on `active` changing, not on every render.
    act(() => { useChatStore.setState({ sending: true } as never) })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
  })

  it('forces the canvas visible while the design is being captured', () => {
    // At finalize_canvas the directive hands over no tool, so the chat is the
    // "active surface" and the canvas would be display:none during the
    // multi-face flatten loop. Rather than rely on Konva painting a hidden
    // element, force the tab.
    render(<CustomiseStudio />)
    act(() => { useChatStore.setState({ triggerFinalize: true } as never) })
    expect(screen.getByTestId('tab-canvas')).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
  })
})

describe('desktop: both panels, no tabs', () => {
  beforeEach(() => setViewport(true))

  it('renders no tab bar and hides neither panel', () => {
    render(<CustomiseStudio />)
    expect(screen.queryByTestId('panel-tabs')).not.toBeInTheDocument()
    expect(screen.getByTestId('canvas-column').className).not.toContain('hidden')
    expect(screen.getByTestId('chat-column-wrap').className).not.toContain('hidden')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```
docker compose exec -T frontend npx vitest run src/__tests__/mobilePanelTabs.test.tsx
```
Expected: FAIL — no `tab-chat` element.

- [ ] **Step 3: Implement in `index.tsx`**

Add imports:

```tsx
import { useEffect, useState } from 'react'
import { useIsDesktop } from '../../lib/useIsDesktop'
import { RedirectCountdown } from './RedirectCountdown'
```

Add a small tab-bar component above `CustomiseStudio`:

```tsx
/** Phone-only panel switcher. Desktop shows both halves side by side and never
 *  renders this. The dot marks the half the FLOW wants, which is only ever
 *  visible after a manual peek — auto-switch keeps them in agreement otherwise. */
function PanelTabs({ tab, wanted, onPick }: {
  tab: ActiveSurface
  wanted: ActiveSurface
  onPick: (t: ActiveSurface) => void
}) {
  const TABS: { id: ActiveSurface; label: string }[] = [
    { id: 'chat', label: 'Chat' },
    { id: 'canvas', label: 'Design' },
  ]
  return (
    <div data-testid="panel-tabs" role="tablist" aria-label="Studio panels"
         className="flex gap-1 border-b border-border bg-base px-2 py-1.5 md:hidden">
      {TABS.map(t => (
        <button
          key={t.id}
          data-testid={`tab-${t.id}`}
          role="tab"
          aria-selected={tab === t.id}
          onClick={() => onPick(t.id)}
          className={`flex flex-1 items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-sm font-semibold transition-colors ${
            tab === t.id
              ? 'bg-surface text-textPrimary shadow-sm'
              : 'text-textMuted hover:text-textPrimary'
          }`}
        >
          {t.label}
          {tab !== t.id && wanted === t.id && (
            <span aria-label="needs your attention"
                  className="h-1.5 w-1.5 rounded-full bg-accent" />
          )}
        </button>
      ))}
    </div>
  )
}
```

Import the type: `import { useActiveSurface, type ActiveSurface } from '../../lib/useActiveSurface'`.

Inside `CustomiseStudio`, after the existing `const active = useActiveSurface()`:

```tsx
  const isDesktop = useIsDesktop()
  const triggerFinalize = useChatStore(s => s.triggerFinalize)

  // Phone: exactly one panel is shown. `tab` follows the backend-derived active
  // surface, but ONLY when that surface changes — which is what lets a manual
  // peek stick until the flow actually moves on. There is no second source of
  // truth: `active` remains the only thing that drives it automatically.
  const [tab, setTab] = useState<ActiveSurface>('chat')
  useEffect(() => { setTab(active) }, [active])

  // At FINALIZE_CANVAS the directive hands over no tool, so `active` is 'chat'
  // and the canvas would be display:none for the whole multi-face flatten loop
  // in Surface.doRender(). Konva would probably still paint a hidden element,
  // but a silently blank layout guide is catastrophic and hard to attribute —
  // so remove the dependency. It also shows the customer their design while it
  // is being captured. Deliberately NOT folded into useActiveSurface: that hook
  // answers "where should the customer act", a different question from "what
  // must be painted".
  useEffect(() => { if (triggerFinalize) setTab('canvas') }, [triggerFinalize])

  const showCanvas = isDesktop || tab === 'canvas'
  const showChat = isDesktop || tab === 'chat'
```

Render `{!isDesktop && <PanelTabs tab={tab} wanted={active} onPick={setTab} />}` immediately after `<MilestoneBar />`.

Append `${showCanvas ? '' : 'hidden'}` to the canvas column's className and `${showChat ? '' : 'hidden'}` to the chat column's className. **Do not** wrap either column in a conditional — they must stay mounted.

Add `<RedirectCountdown />` as the last child of the outer div (if Task 6 has not already done so).

- [ ] **Step 4: Run to verify it passes**

```
docker compose exec -T frontend npx vitest run src/__tests__/mobilePanelTabs.test.tsx src/__tests__/mobileLayout.test.tsx src/__tests__/customiseStudioFocus.test.tsx src/__tests__/CustomiseStudio.test.tsx src/__tests__/columnHeaderTone.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```
Expected: PASS. Note that the pre-existing suites run without a `matchMedia` stub, so `useIsDesktop` returns `true` there and the desktop branch is exercised — their assertions are unaffected.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomiseStudio/index.tsx frontend/src/__tests__/mobilePanelTabs.test.tsx
git commit -m "feat(studio): one auto-switching panel with manual tabs on a phone"
```

---

## Task 8: Admin Branding fields for the redirect

**Files:**
- Modify: `frontend/src/admin/views/BrandingView.tsx`
- Test: `frontend/src/admin/` — extend the existing BrandingView test file (find it with `ls frontend/src/admin/**/*.test.tsx`; if none covers BrandingView, create `frontend/src/admin/views/BrandingView.redirect.test.tsx`)

**Interfaces:**
- Consumes: `Brand.redirect_url`, `Brand.redirect_seconds` (Task 6, Step 1); server rules from Task 3.

- [ ] **Step 1: Read the file first**

```
sed -n '1,120p' frontend/src/admin/views/BrandingView.tsx
```
Note how `validate()` returns `string | null`, how fields bind to `brand`, and how a `set(key, value)` style updater is spelt. Match it exactly rather than inventing a second pattern.

- [ ] **Step 2: Write the failing test**

Following the conventions of the file you just read (same mocks, same store/API stubs):

```tsx
it('rejects a non-http redirect url before saving', async () => {
  const user = userEvent.setup()
  renderBranding({ redirect_url: '' })
  await user.type(screen.getByLabelText(/redirect url/i), 'madhats.com.au')
  await user.click(screen.getByRole('button', { name: /save/i }))
  expect(await screen.findByText(/http\(s\)/i)).toBeInTheDocument()
})

it('rejects a countdown outside 5–300 seconds', async () => {
  const user = userEvent.setup()
  renderBranding({ redirect_url: 'https://madhats.com.au', redirect_seconds: 30 })
  const secs = screen.getByLabelText(/countdown/i)
  await user.clear(secs)
  await user.type(secs, '2')
  await user.click(screen.getByRole('button', { name: /save/i }))
  expect(await screen.findByText(/between 5 and 300/i)).toBeInTheDocument()
})
```

- [ ] **Step 3: Run to verify they fail**

```
docker compose exec -T frontend npx vitest run src/admin
```
Expected: FAIL — no such labels.

- [ ] **Step 4: Implement**

Add a "Return to shop" block near the colour grid:

```tsx
      {/* Return to shop — shown to the customer once their quote reference has
          been issued. Leaving the URL blank turns the whole thing off; there is
          no separate enabled flag, on either side of the wire. */}
      <div className="grid grid-cols-3 gap-4 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <label className="col-span-2 flex flex-col gap-1 text-[12px] text-[#6b6b80]">
          Redirect URL (after the quote)
          <input
            type="url"
            placeholder="https://yourstore.com  — leave blank for no redirect"
            value={brand.redirect_url ?? ''}
            onChange={e => set('redirect_url', e.target.value)}
            className="rounded-lg border border-[#e0e1ea] px-3 py-2 text-[13px] text-[#1f2033]"
          />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-[#6b6b80]">
          Countdown (seconds)
          <input
            type="number"
            min={5}
            max={300}
            value={brand.redirect_seconds ?? 30}
            onChange={e => set('redirect_seconds', Number(e.target.value))}
            className="rounded-lg border border-[#e0e1ea] px-3 py-2 text-[13px] text-[#1f2033]"
          />
        </label>
      </div>
```

Mirror the server rules in `validate()` (this file already mirrors the menu rules deliberately):

```tsx
  // Mirrors branding._validate_redirect. Duplicated on purpose so the admin sees
  // the error before a round trip; the SERVER remains the source of truth.
  const rurl = (brand.redirect_url ?? '').trim()
  if (rurl && !/^https?:\/\/[^/\s]+/i.test(rurl)) {
    return 'Redirect URL must be an http(s) URL'
  }
  if (rurl) {
    const secs = brand.redirect_seconds ?? 30
    if (!Number.isInteger(secs) || secs < 5 || secs > 300) {
      return 'Countdown must be a whole number between 5 and 300 seconds'
    }
  }
```

- [ ] **Step 5: Run to verify they pass**

```
docker compose exec -T frontend npx vitest run src/admin
docker compose exec -T frontend npx tsc --noEmit
```
Expected: PASS (63 + 2 new = 65), clean typecheck.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/BrandingView.tsx frontend/src/admin
git commit -m "feat(admin): redirect url and countdown in the Branding view"
```

---

## Task 9: Full verification, browser walk, and docs

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run every suite and record the real numbers**

```
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q"
MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=true backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py"
docker compose exec -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx
docker compose exec -T frontend npx vitest run src/admin
docker compose exec -T frontend npx tsc --noEmit
```

Write the ACTUAL counts down. Do not copy the expected figures from this plan — every previously-recorded baseline in CLAUDE.md has been stale at least once. If a count is lower than the baseline plus the new tests, find out why before proceeding.

- [ ] **Step 2: Browser walk**

Bring the stack up (`docker compose up -d`, plain HTTP per §13) with `CANVAS_ORCHESTRATOR_V2=true`, open `http://localhost:5173/?product_id=<id>` and check:

1. At `ask_name` the tool rail shows **no** buttons, and the column keeps its width (the cap does not jump).
2. The chat column's header bar is the brand primary; the canvas column's header bar is the customer bubble colour; Ricardo's message lane is primary, yours is the bubble colour.
3. Answer through to a logo step: the rail's controls appear, and only the allowed tool is enabled.
4. Drive to `review_design` (see the note below on flipping verification flags) — the watermark shows. Confirm "Looks great, send it" and walk to `request_quote`: **the watermark is still there**, and it survives a page reload at that state.
5. Complete `request_quote`: the reference message lands, chat input/Send/chips/Back are all gone, and the countdown dialog opens. Check "Stay here" stops the counter permanently, then reload and use "Go to the shop now".
6. Confirm the layout guide is still clean: the watermark is a DOM sibling of the Konva stage, so it must not appear in the uploaded `canvas-layouts` PNG. Fetch the stored `design_sessions.collected.canvas_layouts.front` signed URL and confirm no watermark pixels.

**Environment notes that will otherwise cost you an hour:**
- This dev environment's Resend key is real but sandboxed and 422s any recipient except the account owner, so a synthetic customer can never complete double opt-in. Drive past `await_email_verify` with a backend-container Python snippet that sets `collected.email_captured` / `collected.email_verified` exactly as `leads.py::_apply_email` / `_mark_session_verified` write them.
- `LOGO_ADJUST` auto-opens a native file dialog, which blocks the automation channel. Patch `HTMLInputElement.prototype.click` to a no-op for `type=file`, then inject a `File` via `DataTransfer` into `input[aria-label="Upload image"]` and dispatch `change`.
- Set a `redirect_url` on the local store first: `PATCH /admin/stores/{id}` with `X-Admin-Secret`, body `{"brand": {"redirect_url": "https://example.com", "redirect_seconds": 10}}`. PATCH read-merges brand, so this will not wipe the colours.

- [ ] **Step 3: Mobile — state the limitation honestly**

A sub-768px viewport has not been drivable in this environment in any previous batch (`resize_window` is a no-op here; the devtools MCP could not attach). Attempt it once. If it fails again, record in the final report and in CLAUDE.md that the mobile layout is pinned by jsdom class-string and mount-presence tests only, which perform no real layout. **Do not report a mobile walk that did not happen.**

- [ ] **Step 4: Update CLAUDE.md**

- Delete the open ticket beginning "every chat payload with NO `canvas` directive now renders the canvas UNwatermarked" — it is fixed. Replace it with a one-line record of `watermark_for_state` as the single predicate and why `design_rework` is checked first.
- Add the two new `stores.brand` fields (`redirect_url`, `redirect_seconds`) to the per-store branding entry, noting that absence of the URL is the off switch.
- Add a Canvas Studio entry covering: the tool rail hiding on non-editing steps and why the width stays reserved; the header/lane colour split; the phone single-panel switcher, the mounted-not-unmounted constraint and the `triggerFinalize` override.
- Replace the test baselines with the numbers measured in Step 1.
- Record the mobile-verification limitation from Step 3.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the canvas studio flow polish batch"
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| 1. Tool rail hidden until editable | 4 |
| 2. Watermark persists (predicate + both producers + doc debt) | 1, 2, 9 |
| 3. Redirect: backend fields | 3 |
| 3. Redirect: admin fields | 8 |
| 3. Redirect: dialog + session lock | 6 |
| 4. Header + lane colours | 5 |
| 5. Mobile single panel | 7 |
| Verification / docs | 9 |

**Type consistency**
- `watermark_for_state(state: str, collected: dict) -> bool` — same signature in Tasks 1, 2 and both test files. Task 1 deletes `watermark_for`; Task 2 never references it.
- `toolsVisible?: boolean` — same name in Task 4's prop, Surface wiring and test.
- `tone: 'primary' | 'customer'` — required in Task 5's component and both call sites; `tsc --noEmit` in Task 5 Step 6 proves the call sites moved.
- `redirect_url` / `redirect_seconds` — same snake_case in Task 3 (Python), Task 6 (`Brand`) and Task 8 (admin form). `DEFAULT_REDIRECT_SECONDS = 30` exists on both sides and both are named identically.
- `ActiveSurface` — imported as a type in Task 7 from the module that already exports it.
- `data-testid` names used across tasks: `tool-rail-empty` (4), `redirect-countdown` (6), `panel-tabs` / `tab-chat` / `tab-canvas` (7). Existing ones reused unchanged: `canvas-column`, `chat-column-wrap`, `msg-lane`, `surface`, `chat-column`.

**Placeholder scan:** none. Every code step carries the actual code; every test step carries the actual assertions; every run step carries the exact command and the expected result.
