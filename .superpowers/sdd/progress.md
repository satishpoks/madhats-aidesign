# SDD progress — v2 Canvas Flow Gaps

Plan: docs/superpowers/plans/2026-07-17-v2-canvas-flow-gaps.md
Spec: docs/superpowers/specs/2026-07-17-v2-canvas-flow-gaps-design.md
Branch: feat/canvas-v2-flow-gaps
BRANCH_BASE: 0a9c321c1ff691a542b81d2472a7342c135c0757  (merge-base with master, for final review)

8 tasks. Task 1 (registry capabilities) MUST land first — it changes
`resolve_chip`'s signature, which every later task's tests call.

Test command: `CANVAS_ORCHESTRATOR_V2=false pytest -q` from `backend/`.
Baseline: 660 passing.

NOTE: `.superpowers/sdd/` holds stale `task-N-brief.md` / `task-N-report.md`
files from the PREVIOUS project. This project's artifacts are prefixed
`gaps-` to avoid collision. The previous project's ledger is archived at
`progress-2026-07-15-orchestrator-v2.md` — its Task N entries are NOT this
project's.

FINAL WHOLE-BRANCH REVIEW (opus, 0a9c321..4c912c5): conditionally ready.
  IMPORTANT (a flaw in the PLAN, not the implementation) — FIXED in d33570c:
  `ASK_HAS_LOGO.done_when` was `"has_logo" in c` (as the plan mandated), but the
  load-bearing effect (`logos_done=True`) lives in `_apply_has_logo`, and the
  orchestrator runs ONLY the current step's apply. The interpreter may volunteer
  any WRITABLE_SLOT on an earlier turn — so "Hi I'm Sam, no logo, just text"
  filled has_logo=False, satisfied done_when, the step never became current, its
  apply never ran, and the text-only customer was marched into the logo loop:
  the exact gap the step exists to close. Reviewer REPRODUCED it against the
  real registry. Fix: `done_when=lambda c: c.get("has_logo") is True or not
  _logos_open(c)` — True needs no side effect so it may skip on the raw slot;
  False stays unmet until apply has run.
  GENERALISATION worth remembering: **a step whose `done_when` reads its own raw
  slot while its `apply` carries bookkeeping is unsafe under reordering.**
  `another_logo` has the same shape (pre-existing, harmless today). No test
  covers this class — `test_a_volunteered_answer_is_banked_and_its_step_skipped`
  uses `quantity`, which has no apply.
  Reviewer CONFIRMED intact: the lead gate (FINALIZE unreachable without
  email_captured; `prepare` cannot jump it), interpreter containment (traced
  that an invented decoration name is read by NOTHING downstream), the no-LLM
  front half, v1 untouched, `decoration_options` frozen per session, the
  frontend multiselect + cost caveat plumbing reaching v2, and that the suite
  was NOT weakened across the branch. The ASK_LOGO_BG/`tool="upload"` coupling
  was judged "the best-documented thing in the branch" — pinned in 4 places.

TICKETS TO FILE (not merge blockers):
  1. `ask_decor_placement` leaves `instructions=None`, so the canvas callout
     falls back to the text tip ("Tap Add text… drag to position it") WHILE the
     chat asks which face — a customer who follows the callout drops text on the
     default front face, then DECOR_ADJUST's auto_open adds a SECOND element on
     the named face. Stray front text flows into the render. `Step.instructions`
     (added by this branch) is the exact fix. ASK_LOGO_PLACEMENT has the same
     pre-existing wart. Fixing it also lets the tool<->tip invariant test go
     back to being uniform (see Minor below).
  2. **Escalated:** bg-removal WASM matting didn't finish in ~90s (external CDN
     model download, no timeout). Pre-existing, BUT this branch ships
     `ask_logo_bg`, whose copy is "tick Remove background… I'll wait" and which
     pauses the funnel on it — converting a dormant defect into one on the
     critical path for every logo customer. File LINKED to this work.
  3. v2 resume mid-design doesn't rehydrate the canvas directive (pre-existing;
     recorded in CLAUDE.md).
  4. Invariant note on `Step.apply` re: the generalisation above.
  5. `uploads.py:48` is a THIRD writer of `collected["has_logo"]` (v1 route).
     Benign today only because ASK_HAS_LOGO precedes any tool being unlocked.

Minor findings roll-up (hand to the final whole-branch review):
- T1: `tests/test_orchestrator_v2.py` nudge test comment says `ASK_QUANTITY` is
  "an unused state" — it is a real registry state; the test works because
  `cs.by_id` is monkeypatched. Comment misleads.
- T1: `orchestrator_v2._stall` docstring says "we re-render the chips" without
  noting they may now be dynamic (`chips_from`). Cosmetic.
- T2: v1 and v2 now share `collected["has_logo"]` by convention, not enforced
  isolation. Inert today (flow_mode partitions the engines) but implicit.
- T4: no directive-level test pins `ASK_DECOR_PLACEMENT`'s `auto_open is None` /
  `allowed_tools`, the way the logo branch has one — the exact bug class Task 4
  exists to prevent. **Task 7's e2e asserts it through the real pipeline**, so
  check it landed there before treating this as open.
- T6: the `# noqa: PLC0415 cycle` comment on the local import of
  `_decoration_style_bucket` overstates the risk — reviewer traced the import
  graph and a top-level import would not cycle today. Harmless + consistent with
  the file's defensive pattern; comment is just imprecise.
- T4: `test_tool_steps_carry_a_tip_and_tipless_steps_carry_no_tool` bundles
  ASK_LOGO_BG + ASK_DECOR_PLACEMENT under one weaker assertion, dropping the
  `step.instructions` truthy check for ASK_LOGO_BG. Compensated by
  `test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable`.

---

Task 1 BASE (HEAD before impl): 0a9c321

Task 1: complete (commits 12b2f1c..7a9231d, review clean — Spec ✅, Quality
Approved). Added `Step.chips_from`/`Step.multiselect`, `chips_of()` as the single
chip read path, `resolve_chip(step, message, collected)` (signature change, all
callers updated), `_resolve_multi` (comma-joined labels + the UI's `'none'`
sentinel + None for free text), `public_data_for` multiselect shape. +9 tests.
  FIX (7a9231d): reviewer caught `_stall` reading `step.chips` directly — a
  dynamic-chip step would never fire the outage nudge (the exact path the nudge
  exists to rescue). Now `cs.chips_of(step, collected)`. Reviewer verified the
  regression test by reverting the fix and watching it fail, then confirmed the
  only remaining `.chips` read in `app/` is inside `chips_of` itself.
  NOTE: real baseline is 668 passing, not the 660 the plan quotes from CLAUDE.md.
  After T1: 676.

Task 2 BASE (HEAD before impl): 7a9231d

Task 2: complete (commit a1afa0f, review clean — Spec ✅, Quality Approved).
ASK_HAS_LOGO step ("No — text only" sets logos_done -> first-unmet skips the
whole logo branch), ASK_LOGO_PLACEMENT ask copy de-duplicated, _SLOT_DOCS +
progress anchor + test helper. 683 passing, 1 EXPECTED failure (test_v2_e2e —
Task 7 closes it).
  PLAN WAS WRONG: `ASK_HAS_LOGO = "ask_has_logo"` ALREADY EXISTED at
  state_machine.py:24 (v1's Q&A flow). A second member with the same value
  would be an enum ALIAS, so the implementer reused it. Correct call.
  Reviewer traced the collision and proved it inert: `flow_mode` is an
  immutable-per-session partition — v1's canvas router (`_canvas_next_goal`)
  never returns ASK_HAS_LOGO, and `chat.py::_dispatch` keys on flow_mode, not
  on the state name. So a session resting on ask_has_logo via v1 routing always
  has flow_mode != "canvas" and never reaches v2. NOTE for Task 6: the same
  question applies to ASK_DECORATION, which v1 DOES use in the canvas flow —
  spec §5 already accepts that caveat, but it is a live one, not theoretical.
  MINOR: v1 and v2 now share `collected["has_logo"]` by convention, not by
  enforced isolation (inherited from the plan's design).
  VERIFIED: ASK_LOGO_BG / ASK_DECOR_PLACEMENT do NOT pre-exist (v1's analogue is
  ASK_REMOVE_BG, a different value) — Tasks 3/4 add genuinely new members.

Task 3 BASE (HEAD before impl): a1afa0f

Task 3: complete (commit ac67314, review clean — Spec ✅, Quality Approved, no
findings). ASK_LOGO_BG step + `Step.instructions` field + V2_BG_INSTRUCTIONS +
SLOT_ENUMS/_SLOT_DOCS/progress anchor. 692 passing, 1 EXPECTED failure (e2e).
  The load-bearing `tool="upload"` was independently re-traced by the reviewer
  through the real frontend chain (Surface.tsx:41 v2Editing -> :111-113
  lockPlaced -> nodes.tsx `onClick = locked ? undefined : onSelect` ->
  SelectedToolbar mounts only when v2Editing) — dropping the tool WOULD make the
  Remove-background toggle unreachable, and the test pins it.
  Reviewer audited all 3 modified pre-existing tests: each was tightened, none
  weakened (registry-order list is now longer/stricter; the tool<->tip invariant
  test gained a positive assertion for the tool-without-tip case rather than
  skipping it; the router-path test reflects a real first-unmet shift).
  Reviewer also checked out a1afa0f and proved the e2e failure pre-dates Task 3
  (it is Task 2's insertion; Task 7 owns the walk).

Task 4 BASE (HEAD before impl): ac67314

Task 4: complete (commit 565b6b1, review clean — Spec ✅, Quality Approved, 2
Minors rolled up). ASK_DECOR_PLACEMENT step + `_face(step, collected)` made
step-aware + `_DECOR_STEPS` tool override + `_apply_anything_else` clears
decor_face. 706 passing, 1 EXPECTED failure (e2e).
  LIVE BUG FIXED + reproduced first (`assert 'front' == 'left'`): DECOR_ADJUST
  set face_target=True while _face read `pending_logo` (None after the logo loop
  closes) -> text had ALWAYS silently landed on the front of the cap.
  Reviewer enumerated all 5 face_target=True steps and confirmed each resolves
  from the right source; confirmed Task 3's `step.instructions or ...` line was
  NOT regressed when directive_for was rewritten; audited all 4 modified
  pre-existing tests (all legitimate — the orchestrator one was traced to a real
  new first-unmet precondition, not a weakened assertion).

Task 5 BASE (HEAD before impl): 565b6b1

Task 5: complete (commit e6f23c7, review clean — Spec ✅, Quality Approved, no
findings). ASK_LOGO_PLACEMENT.ask_retry ("Where should this one go…", reads
correctly both as a re-ask AND as the next logo) + V2_TOOL_TIPS["text"] reflowed
onto two lines. Copy-only; no pre-existing test touched. 708 passing, 1 EXPECTED
failure (e2e).

Task 6 BASE (HEAD before impl): e6f23c7

Task 6: complete (commit a1f5f30, review clean — Spec ✅, Quality Approved, 1
Minor rolled up). ASK_DECORATION step (DB-backed dynamic chips, multiselect) +
`Step.prepare` + `_prepare_decoration`/`_apply_decoration`/`_decoration_chips` +
orchestrator prepare-then-re-resolve + _SLOT_DOCS + _PROGRESS_PATH (7->8).
717 passing, 1 EXPECTED failure (e2e).
  Reviewer verified in source (not from the report): the prepare/re-resolve
  ordering; that a store with no methods / a missing store / a DB error all
  auto-skip the step rather than dead-ending the funnel before email capture;
  that the exact-token filter is the real interpreter guard and an invented
  method cannot set `decoration_type`; that decoration_done/_options/_type all
  stayed OUT of WRITABLE_SLOTS; that no duplicate enum member was added and v1's
  orchestrator.py is imported-from, not modified. Frontend needed no change —
  ChatColumn's multiselect UI (built for v1) is already format-compatible.
  Reviewer judged all 5 modified pre-existing tests individually: all
  legitimate. Notably seeding `decoration_done=True` in
  `test_finalize_unreachable_without_email_captured` STRENGTHENS it — without it
  the test would pass for the wrong reason (stopping at ASK_DECORATION rather
  than proving the email gate).

Task 7 BASE (HEAD before impl): a1f5f30

Task 7: complete (commit 1185042, review clean — Spec ✅, Quality Approved, no
findings). e2e walk updated for all 4 new steps. **SUITE FULLY GREEN: 718
passed, 0 failed** (independently re-run by the reviewer). Test-only change; no
production code touched.
  Reviewer cross-checked EVERY chip string in the walk against the registry's
  actual `Chip(...)` literals (the near-miss failure mode this test exists to
  catch), confirmed the LLMUnavailable monkeypatch still covers the whole walk
  (proving the front half needs no model at all), and confirmed the walk order
  is derived from REGISTRY rather than hand-picked.
  CLOSES the T4 Minor: ASK_DECOR_PLACEMENT now asserts `auto_open is None`
  through the real pipeline.

Task 8 BASE (HEAD before impl): 1185042

Task 8: complete (commit 4c912c5 — CLAUDE.md). VERIFIED IN A REAL BROWSER +
against the real backend/DB (customise flow; user said to skip blank — a
separate orchestrator is planned for it).
  PROVEN (the spec's central claim): at `ask_logo_bg` the just-placed logo is
  STILL SELECTED (transform handles visible, not locked) and the "Remove
  background" checkbox IS present and tickable, with the new
  V2_BG_INSTRUCTIONS banner above it. The directive really is
  tools=['upload'] auto_open=None. No frontend change was needed — claim held.
  Also proven live: ask_has_logo asked; 2nd logo says "Where should this one
  go" (not the verbatim repeat); "Yes, another logo" reads as ANOTHER;
  ask_decor_placement asked BEFORE the text tool opens; decor_adjust
  target_face=back (the named face — the always-front bug, fixed); the size/
  colour tip on its own line; ask_decoration multi-select populated from the
  store's 4 real DB rows; progress 8 steps, steady through both loops.
  Final collected: logos=[{face:back,bg:removed},{face:left,bg:none}],
  decor_face=back, decoration_types=[Embroidery,Patch],
  decoration_type=embroidery (first choice drove the render bucket).
  TESTING NOTE: LOGO_ADJUST's auto_open fires a NATIVE file dialog that blocks
  browser automation. Route around it: drive that one step server-side via
  `curl POST /chat/{id}`, then let the browser send the next message — it lands
  on ask_logo_bg (auto_open=None) with no dialog. Place a logo without the
  picker by dispatching a File onto the hidden input via javascript_tool.
  NEW PRE-EXISTING FINDINGS (not caused by this work — for the final review /
  user):
  1. Resuming a v2 canvas session mid-design via `?session=<token>` does NOT
     rehydrate the `canvas` directive -> isV2 false -> v1's whole-rail lock +
     "Design locked in — finishing up" over a live design. Recorded in CLAUDE.md.
  2. The bg-removal WASM matting did not complete in ~90s on this host (✂ busy
     badge persists; @imgly IS installed in the container, so it is the runtime
     CDN model download, which has no timeout). This change now actively directs
     customers to that toggle, so the latency matters more than before.
