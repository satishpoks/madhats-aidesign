# Canvas v2 — 5-Milestone Progress Bar

**Date:** 2026-07-25
**Status:** Design approved, pending spec review
**Scope:** Frontend + a small backend addition. v2 canvas flow only.

---

## 1. Problem

The v2 canvas conversation shows progress as a cramped **"Step X of N"** text
label tucked in the top-right corner of the 380px chat header
(`ChatColumn.tsx:397-401`). Customers can't easily tell *which stage* of the
design they're in.

We want a **labeled 5-milestone progress bar** in a more prominent location, so
the customer always knows what stage they're at. The five milestones:

1. **Intro**
2. **Logo & Image**
3. **Text & Graphics**
4. **Review**
5. **Quote request**

---

## 2. Scope

- **v2 canvas flow only** (`state_machine_v2` / `orchestrator_v2`, i.e.
  `flow_mode == "canvas"` with `CANVAS_ORCHESTRATOR_V2` on). This is the live
  flow and its step sequence is exactly what the five milestones describe
  (especially "Quote request").
- v1 canvas and the non-canvas describe/blank flows are **out of scope** and
  keep their existing "Step X of N" corner text unchanged.

---

## 3. Section → step map

The v2 registry (`canvas_steps.REGISTRY`, declaration order == first-unmet
routing order) maps onto the five sections as follows. This is the single
source of truth and lives next to the registry (matching the codebase's
registry-driven philosophy).

| # | Section          | Step ids |
|---|------------------|----------|
| 0 | Intro            | `ask_name`, `show_intro` |
| 1 | Logo & Image     | `ask_has_logo`, `ask_logo_placement`, `logo_adjust`, `ask_logo_bg`, `ask_email`, `ask_another_logo` |
| 2 | Text & Graphics  | `ask_add_decor`, `ask_decor_placement`, `decor_adjust`, `ask_anything_else` |
| 3 | Review           | `ask_quantity`, `ask_decoration`, `ask_decoration_mix`, `needed_by`, `ask_purpose`, `review_design`, `rework_canvas` |
| 4 | Quote request    | `request_quote` |
| — | (complete)       | `finalize_canvas` + shared-tail states (`generating`, verify, deliver, refine) → all five sections complete |

Notes:
- `ask_email` sits in the Logo & Image phase by declaration order; its
  `done_when` may skip it early, but when it *is* current it belongs to Logo &
  Image — no backward jump.
- The existing `{step, total}` 8-counter folds `request_quote` onto
  `ask_purpose` (Review), so it has **no distinct Quote milestone**. That's why
  the section index must be computed on the backend — the frontend cannot derive
  a 5th "Quote request" milestone from `{step, total}` alone.

---

## 4. Backend change — `services/conversation/state_machine_v2.py`

Add next to `_PROGRESS_PATH`:

```python
_SECTIONS: list[str] = [
    "Intro", "Logo & Image", "Text & Graphics", "Review", "Quote request",
]
_STEP_SECTION: dict[S, int] = {
    S.ASK_NAME: 0, S.SHOW_INTRO: 0,
    S.ASK_HAS_LOGO: 1, S.ASK_LOGO_PLACEMENT: 1, S.LOGO_ADJUST: 1,
    S.ASK_LOGO_BG: 1, S.ASK_EMAIL: 1, S.ASK_ANOTHER_LOGO: 1,
    S.ASK_ADD_DECOR: 2, S.ASK_DECOR_PLACEMENT: 2, S.DECOR_ADJUST: 2,
    S.ASK_ANYTHING_ELSE: 2,
    S.ASK_QUANTITY: 3, S.ASK_DECORATION: 3, S.ASK_DECORATION_MIX: 3,
    S.NEEDED_BY: 3, S.ASK_PURPOSE: 3, S.REVIEW_DESIGN: 3, S.REWORK_CANVAS: 3,
    S.REQUEST_QUOTE: 4,
    # FINALIZE_CANVAS deliberately absent -> "complete" (section == len).
}
_COMPLETE = len(_SECTIONS)  # 5 -> all dots complete
```

`section_for(step) -> int`: returns `_STEP_SECTION.get(step.id, _COMPLETE)`.
So `finalize_canvas` and any step id not in the map resolve to complete.

Extend `progress_for(step)` to add two keys (keep `step`/`total` for v1 + test
back-compat):

```python
def progress_for(step: Step) -> dict:
    ...
    out["sections"] = _SECTIONS
    out["section"] = section_for(step)
    return out
```

`progress_v2(state, collected)` (the state-keyed wrapper `sessions.py` calls
with `GENERATING`, a shared-tail state with no registry step): when `by_id`
returns `None`, also return `sections=_SECTIONS, section=_COMPLETE` so a
post-finalize session renders all five milestones complete.

Only `state_machine_v2` sets `sections`. v1 (`orchestrator.py`,
`state_machine.py`, `goal_planner.py`) and the non-canvas flows keep emitting
`{step, total}` without `sections`, so they are byte-identical.

---

## 5. Frontend

### 5.1 `chatStore` progress type
Extend to:
```ts
progress: { step: number; total: number; sections?: string[]; section?: number } | null
```
The parse in `parseChatData` passes the extra fields through unchanged.

### 5.2 New component `components/CustomiseStudio/MilestoneBar.tsx`
- Reads `const progress = useChatStore(s => s.progress)`.
- **Renders nothing** unless `progress?.sections` is present. This is what
  scopes it to v2 canvas (only v2 sends `sections`).
- Renders the 5 labeled dots joined by a horizontal track:
  - `i < progress.section` → **complete**: filled dot + check, brand accent.
  - `i === progress.section` → **current**: highlighted dot (accent ring /
    subtle pulse), label emphasised.
  - `i > progress.section` → **upcoming**: hollow/muted dot, muted label.
  - The connecting track fills up to the current section.
- Colours use the brand accent CSS var (`text-accent` / `bg-accent` →
  `var(--brand-primary, …)`) so per-store branding still applies.
- Labels always visible beneath each dot. Small responsive text so all five fit
  on mobile ("Text & Graphics" is the longest).

### 5.3 Mount point — `components/CustomiseStudio/index.tsx`
Insert `<MilestoneBar />` full-width between `<StoreHeader />` and the
canvas/chat split `<div>`. It self-hides for non-v2 sessions, so no extra
gating needed at the mount site.

### 5.4 `ChatColumn.tsx`
Suppress the old corner indicator for v2 by tightening the condition at
`:397` to also require `!progress.sections`:
```tsx
{progress && !progress.sections && progress.step < progress.total && (
  <span …>Step {progress.step} of {progress.total}</span>
)}
```
v1 / non-canvas sessions (no `sections`) keep the corner text exactly as today.

---

## 6. Behaviour / edge cases

- **Complete state:** once `request_quote` is submitted (finalize + shared
  tail), `section == 5` → all five dots render complete. The bar stays visible
  through the generating/verify/deliver/refine tail as a fully-complete bar.
- **Loops** (logo loop, decor loop, rework): all their steps map to the same
  section, so the active milestone stays put during a deep-dive — no flicker.
- **Resume:** progress is derived from `collected` each turn, so a resumed
  session lands on the correct milestone with no extra state.

---

## 7. Testing

**Backend** (extend the `state_machine_v2` progress tests):
- Every registry step id maps to its expected section index.
- `request_quote` → section 4; `finalize_canvas` → complete (5).
- `progress_v2(GENERATING, …)` → complete (5) with `sections` present.
- `progress_for` still returns the original `step`/`total` values.

**Frontend** (`MilestoneBar.test.tsx`):
- Renders all 5 section labels when `progress.sections` is present.
- Marks the correct dot active and the earlier dots complete for a given
  `progress.section`.
- Renders nothing when `progress` is null or has no `sections`.

---

## 8. Out of scope / non-goals

- No change to v1 canvas or non-canvas flows.
- No new per-store configuration of section labels (fixed five).
- No animation beyond a subtle current-dot highlight (YAGNI).
