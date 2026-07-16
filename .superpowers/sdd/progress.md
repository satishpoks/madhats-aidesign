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

Task 4: complete (commit a925d27 + fix 3f6306c, review + controller-verified fix). orchestrator_v2.handle_message (front half + tail handoff) + 6 tests, suite 542.
  IMPORTANT FIX (reviewer-caught PLAN GAP): v2 dispatches every canvas turn but only owns the front half — the shared interactive tail (OFFER_REFINE, refine loop, QUOTE_REQUESTED, upsell) had no v2 routing → dead-end even on happy-path refine. Fixed: `_V2_OWNED` set; `if current not in _V2_OWNED: return await _v1.handle_message(...)` delegates tail turns to v1 (reuses all v1 tail logic incl. canvas quote). Daily-cap reroute now speaks GENERATION_BLOCKED_ASIDE + CANVAS_QUOTE_ASK + quote chips; next turn delegates. Controller-verified guard placement + 2 new tests (delegation, reroute).
  Also removed unused `_apply_generation_gate` import + dropped always-False `email_retry` return (Minors).
  NOTE: this delegation is the mechanism that makes "reuse the existing tail" actually work for interactive tail states. Task 5 route-dispatch (by flow_mode) is unaffected — v2 delegates internally by state.

Task 5 BASE (HEAD before impl): 3f6306c

Task 5: complete (commit 4093721, review clean — Spec ✅, Quality Approved). chat.py _dispatch: canvas+flag→v2 else v1; poll routes untouched; flag-off skips DB. 2 dispatch tests + existing route test green.
  MINOR (for final review): no test for flag-ON + non-canvas → v1 (logic correct, untested); _dispatch DB lookup has no try/except (SessionNotFound caught at handler; acceptable).

Task 6 BASE (HEAD before impl): 4093721

Task 6: complete (commit 2224a85, review clean — Spec ✅, Quality Approved). finalize_canvas v2 branch (flag-gated) → state=generating + trigger_generation, skips deco outro, no lead capture. Reused test_canvas_routes.py harness; flag-off regression (test_finalize_routes_to_decoration) confirmed; suite 545.
  MINOR (final review): v2 branch reply "Perfect — generating…" hardcoded, not from v2_reply (v2_reply has no GENERATING entry) — matches brief.
  NOTE: once Task 7 lands the real branding.canvas_intro_text, orchestrator_v2's defensive try/except import picks it up automatically.

Task 7: complete (commit 723b760, review clean — Spec ✅, Quality Approved). branding.canvas_intro_text + validate_brand canvas_intro validation (≤600); NOT in public_brand. Admin PATCH read-merge already runs validate_brand (no route change). 4 tests + 23 brand tests.
  MINOR (final review): no explicit test for ""/whitespace canvas_intro (logic correct via .strip()).

=== BACKEND COMPLETE (Tasks 1-7). Frontend next (8-14). ===

Task 8 BASE (HEAD before impl): 723b760

Task 8: complete (commit cd9a69c, review clean — Spec ✅, Quality Approved). canvasStore locked?:boolean + lockAll (clears selection) / unlockAll; FACES-iterated immutable spreads; 2 tests.

Task 9 BASE (HEAD before impl): cd9a69c
Task 9 NOTE: plan's lockedNode test is VACUOUS (asserts onSelect not called after mere render, no click). Instruct implementer to write a BEHAVIORAL test (Konva .fire('click') + .draggable() inspection) for locked AND unlocked. Apply guard to all 4 node types. nodes.tsx already has the bg-removal badge (committed at base) — coexist.
