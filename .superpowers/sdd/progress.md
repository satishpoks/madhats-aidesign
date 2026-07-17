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

Task 9: complete (commit 952cf62, review clean — Spec ✅, Quality Approved; reviewer re-ran focused suite 4/4 + tsc clean). All 4 node types (Text/Image/Shape/Drawing) guard draggable/onClick/onTap/Transformer on !!el.locked. Real behavioral test (Konva .fire('click') + .draggable() + Transformer presence) for Text+Image, locked+unlocked. bg-removal badge intact. jsdom needed getContext stub in test. Full vitest run stalls (documented Windows tinypool flake) — targeted runs used.

Task 10: complete (commit 66a6b48, review clean — Spec ✅, Quality Approved). ToolRail allowedTools Set gating + highlightTool (ring+animate-pulse); legacy `locked` fallback when allowedTools undefined; Draw/colourway/render unchanged. 7 tests (6 old + 1 new), tsc clean.
  MINOR (final review): hi() applies highlight regardless of allowedTools membership (Surface always passes the single allowed tool, so non-issue in practice).

Task 11: complete (commit 24b4a21, review clean — Spec ✅, Quality Approved). chatStore parseData: canvasDirective (snake→camel, defensive) + triggerFinalize; all 4 add-sites (interface/parseData/defaults/reset); no-stick proven by test. 3 new + 2 existing tests, tsc clean.

Task 12: complete (commit direct by controller — 6-line pure constant module toolInstructions.ts, tsc clean, no test needed). TOOL_INSTRUCTIONS record (upload/text/shape).

Task 13 BASE (HEAD before impl): d9bea1f (toolInstructions)

Task 13: complete (commit 7943e06 + fix 473cab3, review clean after fix — Spec ✅, Quality Approved). Surface reacts to canvasDirective+triggerFinalize: face switch, allowedTools/highlightTool→ToolRail, instruction callout, Done button (posts "done"), auto-open dialog, triggerFinalize→doRender() once (ref-guard). v1 legacy gating byte-identical (isV2 false). Impl also fixed render-button-bypass (rendered={isV2?true:rendered}).
  IMPORTANT FIX (reviewer-confirmed): SelectedToolbar was gated on `unlocked` (never true in v2) → font/size/colour controls unreachable despite instructions promising them. Fixed → `{(unlocked || isV2) && <SelectedToolbar/>}` + regression test. Controller-verified.
  MINOR (FINAL REVIEW — decide): ToolRail Draw toggle + cap-colour swatches gated on `locked` only, so always ENABLED in v2 regardless of the step's allowedTools (a v2 customer can freehand-draw / change cap colour during e.g. a logo-upload step). Pre-existing gating, off-spec for strict one-tool-at-a-time. Not fixed (scope). SelectedToolbar edit controls also always available once an element is selected in v2 (acceptable — needed for editing).

Task 14 BASE (HEAD before impl): 473cab3

Task 14: complete (commit a2b651a, review clean — Spec ✅, Quality Approved). Brand.canvas_intro?:string in types.ts; BrandingView textarea via setField('canvas_intro'), maxLength 600, aria-label. Mirrored co-located BrandingView.test.tsx harness. 1 new + 3 existing pass, tsc clean.
  MINOR (final): new test in __tests__/brandingCanvasIntro.test.tsx while component's other tests are co-located BrandingView.test.tsx (harmless split).

Task 15 BASE (HEAD before impl): a2b651a

Task 15: complete (commit 800f773, review clean — Spec ✅, Quality Approved). Genuine 12-turn e2e walk through real handle_message (asserts state EVERY turn, no weakening); _FakeSB + monkeypatched capture_lead_and_verify/_can_start_design. REGRESSION: backend full suite 550 pass (flag-off = v1 intact); frontend targeted 22 pass; tsc clean.

=== ALL 15 TASKS COMPLETE. Final whole-branch review DONE (opus). Verdict: merge safe (v1 byte-identical verified seam-by-seam), ENABLING not safe until fixes. ===

WIRE-UP (user reported v2 not live on the current flow):
  1. ROOT CAUSE: CANVAS_ORCHESTRATOR_V2 was in .env.example but NOT in the actual .env → default false
     → every canvas session still routed to v1. Added `CANVAS_ORCHESTRATOR_V2=true` to .env (gitignored,
     local config, not committed) + `docker compose up -d --force-recreate backend` (env is read only at
     container start). Verified in-container: settings.canvas_orchestrator_v2 = True.
  2. REAL CODE GAP FIXED: v2 states emitting NO directive (show_intro/ask_another_logo/ask_add_decor)
     made the frontend treat the turn as v1 (isV2 = canvasDirective !== null) → v1 whole-rail gating +
     status strip reading "Design locked in — finishing up in the chat" MID-DESIGN, and tool locking
     only worked by coincidence of the legacy gate. Now EVERY V2_OWNED state emits a directive (tool
     steps hand over one tool; all others lock all tools). V2_OWNED moved to state_machine_v2 as single
     source of truth (orchestrator_v2 imports it). Backend 555 passed (+1 new coverage test).
  LIVE-VERIFIED against the running API (not just tests):
     canvas: ''→ask_name[tools=[]] → 'Sam'→show_intro[tools=[]] → 'continue'→ask_logo_placement
     [tools=['upload'] face=front open=None] → 'Back'→logo_adjust[face=BACK open=upload done=True]
     → 'done'→ask_another_logo[tools=[]] → 'no'→ask_add_decor[tools=[]]  ✓ (Critical face fix proven live)
     v1 isolation with flag ON: non-canvas session → ask_name→ask_purpose, no canvas key ✓

FIX WAVE COMPLETE (commits 318821f backend / 62c01c5 frontend / b856a70 CLAUDE.md).
All 6 Critical+Important findings + cheap minors fixed. CONTROLLER-VERIFIED independently:
backend pytest 554 passed; frontend targeted 26/26 (7 files); tsc --noEmit clean.
Fixes: auto_open moved ASK_LOGO_PLACEMENT→LOGO_ADJUST (+ effect ordering, logo_face reset per loop);
_is_done negation-guarded + word-boundary regex (+ bg question removed from copy); lockPlaced() wired to
postDone (unlockAll deleted as dead); ToolRail railGated disables Draw+cap-colour in v2; finalize retry
(finalizeStarted reset + "Try again" button); CLAUDE.md documented.
NOT covered by a test: the "Try again" button path (needs a real canvas 2D backend/toDataURL that jsdom
lacks here) — verified by inspection + tsc.

FINAL REVIEW FINDINGS (all fixed above):
- CRITICAL 1: logo lands on WRONG FACE for any answer but Front. ASK_LOGO_PLACEMENT emits auto_open:"upload" so the file dialog opens BEFORE the face is answered; addImage appends to activeFace (=front default). Loop 2 pre-lands on previous logo's face. PLAN BUG (spec conflated ask-face + open-tool in one step). e2e only ever answered "Front" → missed.
- IMPORTANT 2: _is_done matches substrings + ignores is_negative → "no, not done yet"/"isn't good"/"not ready" all read as Done; also LOGO_ADJUST asks "background removed?" but only tests _is_done → "yes, remove the background" = Done, bg never removed.
- IMPORTANT 3: spec's "Done locks the layer" NEVER WIRED — lockAll only called at triggerFinalize; unlockAll zero prod callers. Tasks 8/9 primitives unused by Task 13.
- IMPORTANT 4: ToolRail Draw + cap-colour gated on `locked` only → always enabled in v2, violating allowed_tools:[] ("all locked") at ASK_ANYTHING_ELSE/ASK_QUANTITY.
- IMPORTANT 5: failed finalize = unrecoverable dead end (finalizeStarted ref never reset, triggerFinalize dep unchanged, render button disabled).
- IMPORTANT 6: CLAUDE.md not updated (parallel orchestrator behind env flag = load-bearing fact for next agent).
- MINORS: toolInstructions.ts dead (copy lives in prompts.V2_TOOL_TIPS — good deviation, delete orphan); Task-7 try/except import scaffolding now swallows real ImportErrors; unused `log`/`email_retry`; ASK_ADD_DECOR ambiguous free text silently skips decor loop + decor_choice not reset per loop; ASK_EMAIL shared v2/v1-tail invariant needs comment; v2_reply persona unused; DECOR_ADJUST reuses _logo_face; sessions.py hardcoded reply; _dispatch extra round-trip/no try-except; hi() membership; canvas_intro ""/ws test; test file split; branding.py docstring drift.
- Flag-flip migration note: flipping the flag strands in-flight v1 canvas sessions at canvas_design (they'd skip the deco/notes outro). Staged-rollout caveat.

MINOR findings roll-up for final review to triage:
- T3: v2_reply `persona` param unused; DECOR_ADJUST target_face reuses _logo_face (no decor_face field).
- T4: (fixed) delegation + honest reroute.
- T5: no test for flag-ON + non-canvas → v1; _dispatch DB lookup no try/except.
- T6: v2 finalize reply hardcoded (not from v2_reply).
- T7: no explicit ""/whitespace canvas_intro test.
- T10: hi() highlights regardless of allowedTools membership (Surface always passes single allowed tool).
- T13 (DECIDE): ToolRail Draw toggle + cap-colour swatches always ENABLED in v2 (gated on `locked`=false, not allowedTools) — a v2 customer can freehand-draw / recolour cap during any step. Off-spec for strict one-tool-at-a-time.
- T14: brandingCanvasIntro test in __tests__/ while other BrandingView tests co-located (harmless split).
Task 13 NOTE (big integration): Surface.tsx reacts to canvasDirective+triggerFinalize. Heavy component test — reuse the jsdom getContext stub pattern from lockedNode.test.tsx; mount via store setState. isV2 = canvasDirective!==null; null-directive v2 turns fall back to legacy locked (chatState!=='canvas_design' → true) which is fine (tools locked between questions). trigger_finalize → doRender() once (finalizeStarted ref guard).
Task 9 NOTE: plan's lockedNode test is VACUOUS (asserts onSelect not called after mere render, no click). Instruct implementer to write a BEHAVIORAL test (Konva .fire('click') + .draggable() inspection) for locked AND unlocked. Apply guard to all 4 node types. nodes.tsx already has the bg-removal badge (committed at base) — coexist.

================================================================================
=== NEW PLAN (2026-07-17): LLM-Assisted Canvas Orchestration (step registry) ===
================================================================================

Plan: docs/superpowers/plans/2026-07-17-llm-assisted-canvas-orchestration.md
Spec: docs/superpowers/specs/2026-07-17-llm-assisted-canvas-orchestration-design.md
Branch: feat/canvas-orchestrator-v2
BRANCH_BASE (merge-base w/ master): 8773c16  (unchanged from the previous plan)

WHY: live session e4c2f3de stalled at ask_email with quantity 0 — customer asked
3x for a second logo, was marched to email. Root cause: state_machine.is_negative
matches by SUBSTRING and "aNOther" contains "no", so v2's OWN chip label
"Yes, another logo" read as a decline. Logo loop + MAX_LOGOS=4 were dead code.
Generalisation: v1 is interpreter-first; v2 regressed to keywords for
understanding, and the chip label + its matcher were declared in 2 places with
nothing forcing agreement.

9 tasks. Registry -> router -> chip resolution -> apply hooks -> interpreter ->
UI surface -> reply assembly -> turn loop -> cleanup/e2e/docs.

PRE-FLIGHT (before Task 1):
  - Committed the previous session's uncommitted fix wave as 44e8eda (name
    capture/V2_ASK_NAME, goal_planner ASK_CHANGE_METHOD gate, Surface
    directive-anchored lockPlaced + read-only stage). Plan DEPENDS on
    prompts.V2_ASK_NAME/_RETRY which existed only in that working tree.
  - PLAN GAP FOUND+FIXED: plan dropped _plausible_name -> regressed "ok became
    a name". Now ported into canvas_steps as ASK_NAME's apply (Task 4) + tests.
  - TEST BASELINE: repo-root .env sets CANVAS_ORCHESTRATOR_V2=true -> 3
    PRE-EXISTING failures (test_flag_defaults_false, test_finalize_routes_to
    _decoration, test_chat_post_resolves_body_not_422). ALWAYS run
    `cd backend && CANVAS_ORCHESTRATOR_V2=false pytest -q`. Baseline 559 passed
    at 44e8eda. Do NOT "fix" those 3.
  - Hoisted satisfy/seed_for into tests/canvas_step_helpers.py (was mandated as
    verbatim dup in 2 files).
  Plan fixes committed as (see git log after 44e8eda).

SPEC DEVIATION (approved, in plan): §4.6 gate=True NOT implemented — first-unmet
routing makes it a no-op (never returns a step after ANY unmet step). Invariant
(no FINALIZE_CANVAS without email_captured) holds by construction: ask_email
precedes finalize, done_when reads email_captured, only _apply_email sets it, and
it is NOT in WRITABLE_SLOTS. Asserted by test in Task 2.

Task 1 BASE (HEAD before impl): see git log — the plan-fix commit.

Task 1: complete (commits b45225e + ca094cc, review clean — Spec ✅, Quality Approved).
  canvas_steps.py: Chip/Step frozen dataclasses, REGISTRY (12 steps in flow order),
  MAX_LOGOS=4, by_id, WRITABLE_SLOTS (union of step.slots), SLOT_ENUMS. 7 tests.
  Reviewer independently confirmed: v1 untouched (no v1 file in diff); WRITABLE_SLOTS
  really is the union with no bookkeeping key leaking in; logo-loop done_when correct
  for all 3 phases (none/mid/closed).
  CONTROLLER FIX: dropped unused `dataclasses.field` import (F401, my plan's bug) — ca094cc.
  BASELINE CORRECTION: real baseline is 562 passed w/ CANVAS_ORCHESTRATOR_V2=false
  (my "559" was the flag-ON passed count; 559+3failed=562). After Task 1: 569. Plan updated.
  MINOR (final review): test_ask_email_precedes_finalize is implied by the exact-order
  test (redundant, harmless). MAX_LOGOS declared in BOTH canvas_steps and state_machine_v2
  — Task 2 re-exports from canvas_steps, which resolves it; verify at Task 2 review.

Task 2 BASE (HEAD before impl): ca094cc

Task 2: complete (commit 5c639f5, review clean — Spec ✅, Quality Approved, ZERO findings).
  state_machine_v2 rewritten as a generic engine: next_step (first-unmet), V2_OWNED,
  progress_for/progress_v2, MAX_LOGOS+Step RE-EXPORTED from canvas_steps (no drift).
  New tests/canvas_step_helpers.py (satisfy/seed_for) — shared with Task 4, do NOT dup.
  14 tests. Suite: 9 failed / 556 passed.
  PLAN GAP FOUND BY IMPLEMENTER (correctly reported BLOCKED, did not commit a red route):
    app/api/routes/sessions.py:269 imports progress_v2 and calls it with GENERATING (a
    TAIL state, no registry step). Plan named only orchestrator_v2 + chat.py as consumers.
    FIX: progress moved Task 6 -> Task 2; progress_v2 keeps its exact signature;
    sessions.py UNTOUCHED. Plan updated (d5e41ae). Route test now green.
  THE 9 EXPECTED FAILURES (Tasks 6/8 restore): test_orchestrator_v2 x8 + test_v2_e2e::
    test_full_front_half_walk — AttributeError on v2_reply/canvas_directive/v2_public_data/
    advance_state_v2 from orchestrator_v2.py:198/:216. NO v1 or other route test fails.
  Reviewer independently verified: satisfy() does NOT shortcut via decor_done, so the
  12-step walk really asserts every step; finalize-without-email test proves the invariant
  genuinely (not incidentally); sessions.py byte-unmodified; v1 untouched.
  COVERAGE GAP TO WATCH (Task 8/9): old test_decor_ambiguous_reply_reasks_instead_of_skipping
    was deleted with the rewrite and has NO direct successor. New equivalent = "interpreter
    returns {} -> decor step re-asks". Add it in Task 8 or flag at final review.
  MAX_LOGOS cap has no test until Task 4 (test_logo_loop_stops_at_max_logos...) — verify there.
  CONTROLLER: deleted a stale plan note (L557) that described the OLD buggy _satisfy.

Task 3 BASE (HEAD before impl): 5c639f5
