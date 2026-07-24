# Canvas v2 Milestone Progress Bar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cramped "Step X of N" corner text with a full-width, labeled 5-milestone progress bar (Intro → Logo & Image → Text & Graphics → Review → Quote request) for the v2 canvas flow.

**Architecture:** The backend (`state_machine_v2`) computes which of five sections the current step belongs to and ships it in the existing `progress` blob as `sections` + `section`. The frontend adds a `MilestoneBar` component that self-hides unless `progress.sections` is present (which only the v2 orchestrator emits), mounted full-width in `CustomiseStudio` under the header. The old corner text is suppressed for v2.

**Tech Stack:** Python 3.12 / FastAPI (backend), React 18 / TypeScript / Zustand / Tailwind / Vitest (frontend).

## Global Constraints

- **v2 canvas only.** Only `state_machine_v2` emits `sections`. v1 (`orchestrator.py`, `state_machine.py`, `goal_planner.py`) and non-canvas flows must remain byte-identical — they keep emitting `{step, total}` with no `sections` key.
- **Backward compat.** `progress_for`/`progress_v2` must keep returning the existing `step`/`total` values unchanged; only ADD keys.
- **Section labels (verbatim, in order):** `"Intro"`, `"Logo & Image"`, `"Text & Graphics"`, `"Review"`, `"Quote request"`.
- **Brand theming.** Frontend colours use the existing Tailwind `accent` class (`bg-accent`/`text-accent` → `var(--brand-primary, #FF5C00)`) so per-store branding still applies. Existing palette classes: `text-textPrimary`, `text-textMuted`, `border-border`, `bg-base`.
- **Run backend tests with the v2 flag off** to match the repo convention: `CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` (from `backend/`).

---

### Task 1: Backend — section mapping + extended progress

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (add constants + funcs near `_PROGRESS_PATH` ~line 184; edit `progress_for` ~190-195 and `progress_v2` ~198-206)
- Test: `backend/tests/test_state_machine_v2.py` (add new tests; update the two existing exact-match progress tests at lines 175-191)

**Interfaces:**
- Produces:
  - `v2._SECTIONS: list[str]` — the five labels in order.
  - `v2.section_for(step: Step) -> int` — 0-based section index; `finalize_canvas`/unmapped → `5` (== `len(_SECTIONS)`, meaning "all complete").
  - `v2.progress_for(step)` now returns `{"step": int, "total": int, "sections": list[str], "section": int}`.
  - `v2.progress_v2(state, collected=None)` returns the same shape; shared-tail states (`by_id` → None) return `section = 5`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_state_machine_v2.py`:

```python
def test_section_for_maps_every_step_to_its_section():
    expected = {
        S.ASK_NAME: 0, S.SHOW_INTRO: 0,
        S.ASK_HAS_LOGO: 1, S.ASK_LOGO_PLACEMENT: 1, S.LOGO_ADJUST: 1,
        S.ASK_LOGO_BG: 1, S.ASK_EMAIL: 1, S.ASK_ANOTHER_LOGO: 1,
        S.ASK_ADD_DECOR: 2, S.ASK_DECOR_PLACEMENT: 2, S.DECOR_ADJUST: 2,
        S.ASK_ANYTHING_ELSE: 2,
        S.ASK_QUANTITY: 3, S.ASK_DECORATION: 3, S.ASK_DECORATION_MIX: 3,
        S.NEEDED_BY: 3, S.ASK_PURPOSE: 3, S.REVIEW_DESIGN: 3, S.REWORK_CANVAS: 3,
        S.REQUEST_QUOTE: 4,
    }
    for sid, section in expected.items():
        assert v2.section_for(cs.by_id(sid)) == section, sid
    # Every non-finalize registry step is mapped explicitly (guards a step added
    # later without a section landing silently in "complete").
    for step in cs.REGISTRY:
        if step.id is S.FINALIZE_CANVAS:
            continue
        assert step.id in expected, f"{step.id} has no section"


def test_finalize_and_tail_report_complete_section():
    assert v2.section_for(cs.by_id(S.FINALIZE_CANVAS)) == len(v2._SECTIONS)
    assert v2.progress_v2(S.GENERATING, {})["section"] == len(v2._SECTIONS)


def test_progress_for_carries_sections_and_active_index():
    p = v2.progress_for(cs.by_id(S.ASK_QUANTITY))
    assert p["sections"] == ["Intro", "Logo & Image", "Text & Graphics",
                             "Review", "Quote request"]
    assert p["section"] == 3
    assert v2.progress_for(cs.by_id(S.REQUEST_QUOTE))["section"] == 4
```

Also UPDATE the two existing exact-`==` tests so they include the new keys. Replace lines 175-191 with:

```python
def test_progress_collapses_loop_steps_onto_their_anchor():
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    secs = v2._SECTIONS
    # ASK_HAS_LOGO and ASK_LOGO_PLACEMENT both have progress step 3
    assert v2.progress_for(cs.by_id(S.ASK_HAS_LOGO)) == {
        "step": 3, "total": total, "sections": secs, "section": 1}
    for sid in (S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        assert v2.progress_for(cs.by_id(sid)) == {
            "step": 3, "total": total, "sections": secs, "section": 1}
    for sid in (S.ASK_ADD_DECOR, S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        assert v2.progress_for(cs.by_id(sid)) == {
            "step": 4, "total": total, "sections": secs, "section": 2}
    assert v2.progress_for(cs.by_id(S.FINALIZE_CANVAS)) == {
        "step": total, "total": total, "sections": secs, "section": len(secs)}


def test_progress_v2_is_state_keyed_and_survives_a_tail_state():
    # sessions.py's canvas-finalize route calls this with GENERATING, which has
    # NO registry step. It must report "complete", not explode.
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    secs = v2._SECTIONS
    assert v2.progress_v2(S.GENERATING, {}) == {
        "step": total, "total": total, "sections": secs, "section": len(secs)}
    assert v2.progress_v2(S.ASK_QUANTITY, {}) == {
        "step": 5, "total": total, "sections": secs, "section": 3}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py -q -k "section or progress"`
Expected: FAIL — `AttributeError: module ... has no attribute 'section_for'` / `'_SECTIONS'`.

- [ ] **Step 3: Implement the mapping + funcs**

In `state_machine_v2.py`, immediately AFTER the `_PROGRESS_PATH` definition (ends ~line 187), add:

```python
_SECTIONS: list[str] = [
    "Intro", "Logo & Image", "Text & Graphics", "Review", "Quote request",
]
# Every registry step -> its milestone section (0-based). FINALIZE_CANVAS is
# deliberately absent: it (and any shared-tail state with no registry step)
# resolves to len(_SECTIONS) == "all milestones complete".
_STEP_SECTION: dict[S, int] = {
    S.ASK_NAME: 0, S.SHOW_INTRO: 0,
    S.ASK_HAS_LOGO: 1, S.ASK_LOGO_PLACEMENT: 1, S.LOGO_ADJUST: 1,
    S.ASK_LOGO_BG: 1, S.ASK_EMAIL: 1, S.ASK_ANOTHER_LOGO: 1,
    S.ASK_ADD_DECOR: 2, S.ASK_DECOR_PLACEMENT: 2, S.DECOR_ADJUST: 2,
    S.ASK_ANYTHING_ELSE: 2,
    S.ASK_QUANTITY: 3, S.ASK_DECORATION: 3, S.ASK_DECORATION_MIX: 3,
    S.NEEDED_BY: 3, S.ASK_PURPOSE: 3, S.REVIEW_DESIGN: 3, S.REWORK_CANVAS: 3,
    S.REQUEST_QUOTE: 4,
}


def section_for(step: Step) -> int:
    """The 0-based milestone section for a step. finalize + any unmapped step
    resolve to len(_SECTIONS) == all milestones complete."""
    return _STEP_SECTION.get(step.id, len(_SECTIONS))
```

Then edit `progress_for` (currently lines ~190-195) to add the two keys to BOTH return paths:

```python
def progress_for(step: Step) -> dict:
    total = len(_PROGRESS_PATH)
    section = {"sections": _SECTIONS, "section": section_for(step)}
    anchor = _PROGRESS_ANCHORS.get(step.id, step.id)
    if anchor in _PROGRESS_PATH:
        return {"step": _PROGRESS_PATH.index(anchor) + 1, "total": total, **section}
    return {"step": total, "total": total, **section}   # finalize + tail -> complete
```

Then edit `progress_v2` (currently lines ~198-206) so the `step is None` path also carries the section as complete:

```python
def progress_v2(state: S, collected: dict | None = None) -> dict:
    """State-keyed wrapper, kept at its original signature for
    `sessions.py`'s canvas-finalize route — which calls it with GENERATING, a
    shared-tail state that has no registry step (-> "complete")."""
    step = cs.by_id(state)
    if step is None:
        total = len(_PROGRESS_PATH)
        return {"step": total, "total": total,
                "sections": _SECTIONS, "section": len(_SECTIONS)}
    return progress_for(step)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py -q`
Expected: PASS (all, including the two updated tests).

- [ ] **Step 5: Run the broader v2 suite to catch any other exact-match progress assertions**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_canvas_steps.py -q`
Expected: PASS. If any test asserts an exact `progress` dict, update it to include `"sections"`/`"section"` the same way (do NOT change production behaviour to satisfy it).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): add milestone section to progress blob"
```

---

### Task 2: Frontend — carry `sections`/`section` through the chat store

**Files:**
- Modify: `frontend/src/store/chatStore.ts` (the `progress` type at line 30; the parse at lines 94-96)
- Test: `frontend/src/store/chatStore.test.ts`

**Interfaces:**
- Consumes: the backend `data.progress` object now containing optional `sections`/`section` (Task 1).
- Produces: `useChatStore(s => s.progress)` typed as `{ step: number; total: number; sections?: string[]; section?: number } | null`, with those fields populated when present.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/store/chatStore.test.ts` (inside the existing `describe('chatStore progress', …)` block so it gets the `reset()`/`resetAllMocks()` `beforeEach`):

```typescript
  it('carries milestone sections + active index when present', async () => {
    vi.mocked(api.sendChat).mockResolvedValue({
      reply: 'ok',
      state: 'ask_quantity',
      data: { progress: {
        step: 5, total: 8,
        sections: ['Intro', 'Logo & Image', 'Text & Graphics', 'Review', 'Quote request'],
        section: 3,
      } },
    } as never)
    await useChatStore.getState().sendMessage('s1', 'hi')
    const p = useChatStore.getState().progress
    expect(p?.section).toBe(3)
    expect(p?.sections).toEqual(
      ['Intro', 'Logo & Image', 'Text & Graphics', 'Review', 'Quote request'])
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: FAIL — `p.section` is `undefined` (the cast drops the extra fields; TS type also lacks them).

- [ ] **Step 3: Widen the type + parse**

In `frontend/src/store/chatStore.ts`, change the `progress` field type (line 30) from:

```typescript
  progress: { step: number; total: number } | null
```
to:
```typescript
  progress: { step: number; total: number; sections?: string[]; section?: number } | null
```

And change the parse (lines 94-96) from:

```typescript
  const progress = (data.progress && typeof data.progress === 'object')
    ? (data.progress as { step: number; total: number })
    : null
```
to:
```typescript
  const progress = (data.progress && typeof data.progress === 'object')
    ? (data.progress as { step: number; total: number; sections?: string[]; section?: number })
    : null
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/store/chatStore.test.ts`
Expected: PASS (both the existing `{ step: 3, total: 9 }` test and the new one).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/store/chatStore.test.ts
git commit -m "feat(chat): carry milestone sections through progress"
```

---

### Task 3: Frontend — `MilestoneBar` component

**Files:**
- Create: `frontend/src/components/CustomiseStudio/MilestoneBar.tsx`
- Test: `frontend/src/components/CustomiseStudio/MilestoneBar.test.tsx`

**Interfaces:**
- Consumes: `useChatStore(s => s.progress)` typed `{ step; total; sections?; section? } | null` (Task 2).
- Produces: `export function MilestoneBar(): JSX.Element | null` — the default export used by Task 4.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/CustomiseStudio/MilestoneBar.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach } from 'vitest'
import { MilestoneBar } from './MilestoneBar'
import { useChatStore } from '../../store/chatStore'

const SECTIONS = ['Intro', 'Logo & Image', 'Text & Graphics', 'Review', 'Quote request']

beforeEach(() => {
  useChatStore.getState().reset()
})

test('renders nothing when progress has no sections (v1 / non-canvas)', () => {
  useChatStore.setState({ progress: { step: 3, total: 9 } })
  const { container } = render(<MilestoneBar />)
  expect(container.firstChild).toBeNull()
})

test('renders nothing when progress is null', () => {
  useChatStore.setState({ progress: null })
  const { container } = render(<MilestoneBar />)
  expect(container.firstChild).toBeNull()
})

test('renders all five labels for a v2 canvas session', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  for (const label of SECTIONS) expect(screen.getByText(label)).toBeInTheDocument()
})

test('marks earlier sections complete, the current one active, later ones upcoming', () => {
  useChatStore.setState({ progress: { step: 5, total: 8, sections: SECTIONS, section: 2 } })
  render(<MilestoneBar />)
  // data-state is one of: complete | current | upcoming, keyed by label.
  expect(screen.getByTestId('milestone-Intro')).toHaveAttribute('data-state', 'complete')
  expect(screen.getByTestId('milestone-Logo & Image')).toHaveAttribute('data-state', 'complete')
  expect(screen.getByTestId('milestone-Text & Graphics')).toHaveAttribute('data-state', 'current')
  expect(screen.getByTestId('milestone-Review')).toHaveAttribute('data-state', 'upcoming')
  expect(screen.getByTestId('milestone-Quote request')).toHaveAttribute('data-state', 'upcoming')
})

test('marks every section complete once section index is past the last (section == length)', () => {
  useChatStore.setState({ progress: { step: 8, total: 8, sections: SECTIONS, section: 5 } })
  render(<MilestoneBar />)
  for (const label of SECTIONS)
    expect(screen.getByTestId(`milestone-${label}`)).toHaveAttribute('data-state', 'complete')
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/CustomiseStudio/MilestoneBar.test.tsx`
Expected: FAIL — cannot resolve `./MilestoneBar`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/CustomiseStudio/MilestoneBar.tsx`:

```tsx
import { useChatStore } from '../../store/chatStore'

/**
 * MilestoneBar — a full-width labeled 5-dot stepper for the v2 canvas flow.
 *
 * It reads progress from the chat store and self-hides unless
 * `progress.sections` is present. Only the v2 orchestrator
 * (state_machine_v2.progress_for) emits `sections`, so this renders for v2
 * canvas sessions only — v1 and non-canvas flows fall through to null.
 */
export function MilestoneBar() {
  const progress = useChatStore(s => s.progress)
  if (!progress?.sections || progress.sections.length === 0) return null

  const sections = progress.sections
  const active = progress.section ?? 0

  return (
    <nav
      aria-label="Design progress"
      className="w-full border-b border-border bg-base px-4 py-3"
    >
      <ol className="flex items-start justify-between gap-1 max-w-3xl mx-auto">
        {sections.map((label, i) => {
          const state = i < active ? 'complete' : i === active ? 'current' : 'upcoming'
          const isLast = i === sections.length - 1
          return (
            <li
              key={label}
              data-testid={`milestone-${label}`}
              data-state={state}
              className="relative flex flex-1 flex-col items-center min-w-0"
            >
              {/* Connector track to the NEXT dot; filled if this dot is done. */}
              {!isLast && (
                <span
                  aria-hidden
                  className={`absolute top-2.5 left-1/2 h-0.5 w-full ${
                    i < active ? 'bg-accent' : 'bg-border'
                  }`}
                />
              )}
              {/* Dot */}
              <span
                aria-hidden
                className={`relative z-10 flex h-5 w-5 items-center justify-center rounded-full border-2 text-[10px] font-bold ${
                  state === 'complete'
                    ? 'border-accent bg-accent text-white'
                    : state === 'current'
                    ? 'border-accent bg-base text-accent ring-4 ring-accent/20'
                    : 'border-border bg-base text-textMuted'
                }`}
              >
                {state === 'complete' ? '✓' : i + 1}
              </span>
              {/* Label */}
              <span
                className={`mt-1.5 text-center text-[10px] sm:text-xs leading-tight ${
                  state === 'upcoming'
                    ? 'text-textMuted'
                    : 'text-textPrimary font-medium'
                }`}
              >
                {label}
              </span>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/CustomiseStudio/MilestoneBar.test.tsx`
Expected: PASS (all five tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomiseStudio/MilestoneBar.tsx frontend/src/components/CustomiseStudio/MilestoneBar.test.tsx
git commit -m "feat(canvas): milestone progress bar component"
```

---

### Task 4: Frontend — mount the bar + hide the old corner text

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/index.tsx` (mount between `StoreHeader` and the split)
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:397` (gate the corner text on `!progress.sections`)

**Interfaces:**
- Consumes: `MilestoneBar` (Task 3); `useChatStore(s => s.progress)` with optional `sections` (Task 2).

- [ ] **Step 1: Mount `MilestoneBar` in `CustomiseStudio/index.tsx`**

Add the import at the top (with the other component imports):

```tsx
import { MilestoneBar } from './MilestoneBar'
```

Then insert `<MilestoneBar />` between the `StoreHeader` and the split `<div>` (currently lines 18-19):

```tsx
      <StoreHeader subtitle={productRef ? `${productRef.name} › Design` : undefined} />
      <MilestoneBar />

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
```

`MilestoneBar` self-hides for non-v2 sessions, so no extra guard is needed here.

- [ ] **Step 2: Suppress the old "Step X of N" corner text for v2**

In `frontend/src/components/CustomiseStudio/ChatColumn.tsx`, change the condition at line 397 from:

```tsx
        {progress && progress.step < progress.total && (
```
to:
```tsx
        {progress && !progress.sections && progress.step < progress.total && (
```

This keeps the corner text exactly as-is for v1 / non-canvas sessions (which have no `sections`) and removes it for v2, where the full-width `MilestoneBar` replaces it.

- [ ] **Step 3: Typecheck + build to verify no regressions**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: PASS — no type errors, build succeeds.

- [ ] **Step 4: Run the Windows-stall-safe focused frontend subset + the new tests**

Run: `cd frontend && npx vitest run src/components/CustomiseStudio/MilestoneBar.test.tsx src/store/chatStore.test.ts src/__tests__/surfaceDirective.test.tsx`
Expected: PASS. (Full `vitest run` is a known Windows tinypool flake — see CLAUDE.md; run focused files.)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomiseStudio/index.tsx frontend/src/components/CustomiseStudio/ChatColumn.tsx
git commit -m "feat(canvas): mount milestone bar, retire corner step text for v2"
```

---

### Task 5: Manual in-browser verification

**Files:** none (verification only).

- [ ] **Step 1: Start the stack**

Run: `docker compose up -d` (backend `:8000`, frontend `:5173`; Supabase already running via `npx supabase start`). Ensure `CANVAS_ORCHESTRATOR_V2=true` in the repo-root `.env` (the live v2 flow) and `--force-recreate backend` if you changed `.env`.

- [ ] **Step 2: Walk the v2 canvas flow**

Open a canvas session (`http://localhost:5173/?product_id=<id>` or `?mode=blank`). Confirm:
- The full-width bar sits directly under the store header, above canvas + chat.
- At the greeting/name step, **Intro** is the current (highlighted) dot; the rest are hollow.
- Placing a logo advances the highlight to **Logo & Image**; adding text advances to **Text & Graphics**; quantity/decoration/deadline/purpose sit under **Review**; the quote CTA lights **Quote request**.
- Completed sections show a ✓ and the accent fill; the connector track fills up to the current dot.
- The old top-right "Step X of N" text is gone for this v2 session.

- [ ] **Step 3: Confirm non-v2 is unaffected (if a v1/non-canvas entry exists)**

If a v1 canvas or describe/blank session is reachable in this environment, confirm the milestone bar does NOT appear and the "Step X of N" corner text still shows. (If not reachable, note it as untested — the `!progress.sections` gate guarantees it structurally.)

- [ ] **Step 4: Note results**

Record what was verified (and anything not reachable) in the PR / handoff.

---

## Self-Review Notes

- **Spec coverage:** §3 section map → Task 1 `_STEP_SECTION`. §4 backend → Task 1. §5.1 store type → Task 2. §5.2 component → Task 3. §5.3 mount → Task 4 Step 1. §5.4 hide corner → Task 4 Step 2. §7 tests → Tasks 1-3. §6 complete/loop/resume behaviour → covered by `section == len` handling (Task 1) + loop steps sharing a section index (map) + progress-from-`collected` (no new state).
- **Back-compat trap handled:** the two existing exact-`==` progress tests are rewritten in Task 1 Step 1; Task 1 Step 5 sweeps the wider v2 suite for any other exact-match assertions.
- **Type consistency:** `progress` shape `{ step; total; sections?: string[]; section?: number }` is identical across Tasks 2, 3, 4. `section_for` / `_SECTIONS` / `_STEP_SECTION` names match between plan text and code blocks. `MilestoneBar` (named export) is consistent across Tasks 3 and 4.
