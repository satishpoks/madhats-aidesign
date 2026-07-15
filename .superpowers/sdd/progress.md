# SDD progress — Step-by-Step Canvas Orchestrator (v2)

Plan: docs/superpowers/plans/2026-07-15-step-by-step-canvas-orchestrator-v2.md
Spec: docs/superpowers/specs/2026-07-15-step-by-step-canvas-orchestrator-v2-design.md
Branch: feat/canvas-orchestrator-v2
BRANCH_BASE: 8773c16dd17bbe2532908bc79b61073842cf18a8  (master 8773c16 — merge-base for final review)

Note: pre-existing bg-removal WIP committed on master as 8773c16 (user-approved)
so v2 task commits stay clean. Working tree clean at branch start.

15 tasks total (7 backend, 7 frontend, 1 e2e/regression).

Task 1 BASE (HEAD before impl): 36cc1ba (ledger-reset commit; the recorded 8773c16 was pre-ledger)

Task 1: complete (commit 5932bbc, review clean — Spec ✅, Quality Approved, no findings). CANVAS_ORCHESTRATOR_V2 bool flag in config.py + .env.example + 2 tests.

Task 2 BASE (HEAD before impl): 5932bbc

Task 2: complete (commit 775c22f, review clean — Spec ✅, Quality Approved, no findings). 8 additive enum members + state_machine_v2 (advance_state_v2/progress_v2/MAX_LOGOS/V2_STATES) + 7 tests. Reviewer independently confirmed enum edit additive-only + v1 advance_state untouched + no ordinal-dependent enum use in repo.

Task 3 BASE (HEAD before impl): 775c22f

Task 3: complete (commit 04d4497 + fix 165e86a, review clean after fix — Spec ✅, Quality Approved). canvas_directive/v2_public_data/v2_reply + V2_TOOL_TIPS/V2_DEFAULT_INTRO + 14 tests.
  FIX: reviewer caught brief self-contradiction — canvas_directive must lock tools at BOTH ASK_ANYTHING_ELSE AND ASK_QUANTITY (impl had dropped ASK_QUANTITY, test wrongly asserted None). Fixed + test corrected. Controller-verified fix diff directly.
  MINOR (for final review): v2_reply `persona` param unused (signature parity); DECOR_ADJUST target_face reuses _logo_face (no decor_face field — matches plan).
  TEST-INFRA NOTE (for Task 4/6/15): backend has NO conftest.py; orchestrator tests use an inline _FakeSB/_FakeTable (see tests/test_conversation_smart.py ~L40-90) + monkeypatch <module>.get_supabase. The plan's "add conftest fixtures" is WRONG — use the _FakeSB pattern. For v2: also monkeypatch orchestrator_v2._can_start_design and orchestrator_v2.leads_service.capture_lead_and_verify; leave store_id off the fake session so get_store is skipped; v2_reply is deterministic (no generate_reply monkeypatch needed).

Task 4 BASE (HEAD before impl): 165e86a
