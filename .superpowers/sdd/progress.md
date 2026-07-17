# SDD progress — Canvas-led refine + self-ticking background removal

Plan: docs/superpowers/plans/2026-07-17-canvas-led-refine.md
Spec: docs/superpowers/specs/2026-07-17-canvas-led-refine-design.md
Branch: feat/canvas-led-refine
BRANCH_BASE (merge-base with master, for final review): 9dfe5d0057c88f3dc4266b2d05a9a59cf4232e05
Task 1 BASE: 3abec9b4a7c22391245491004865926333ff2d22

NOTE: this branch is stacked on feat/v2-decoration-mix (decoration-mix +
merge_fields, commits cdf0296..3abec9b). Those are ancestors here — the final
whole-branch review should use BRANCH_BASE above only if reviewing everything;
to review THIS project alone, use 3abec9b4a7c22391245491004865926333ff2d22.

The previous project's ledger (v2 canvas flow gaps, complete) is archived at
progress-2026-07-17-v2-canvas-flow-gaps.md. Its Task N entries are NOT this
project's. Artifacts here are prefixed 'refine-' to avoid collision with the
stale task-N-brief.md / task-N-report.md files in this directory.

Test commands:
  backend:  cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q -p no:warnings
  frontend: cd frontend && npx vitest run <path>   (full run is flaky on Windows)
Baseline: backend 735 passing.

PRE-FLIGHT PLAN FIX (before Task 1): the plan omitted adding
CONFIRM_CANVAS_EDIT to goal_planner.GATE_STATES. _route only consults
advance_state for GATE_STATES; everything else goes to goal_planner.next_goal,
which for a finished canvas session answers GENERATING — a FRESH generation
burning the daily design cap. goal_planner.py:27-34 records the same trap
biting ASK_CHANGE_METHOD. Task 6 now covers it with two pinning tests.

STALE TICKET NOW MOOT: the archived ledger's ticket 2 (bg-removal WASM matting
never completing) died with 8773c16 — matting was removed in favour of the
mark-only design. Do not act on it.

---
