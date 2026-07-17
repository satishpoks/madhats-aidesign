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

Task 1: complete (commit 09dddf0, review clean — Spec ✅, Quality Approved, no
findings). Face-aware `patchElement(face,id,patch)` / `removeElementOn(face,id)`
/ `patchPendingLogo(face,patch)` on canvasStore. 22 frontend tests passing
(6 new + lock + store suites), zero regressions.
  Reviewer independently confirmed the two load-bearing semantics: patchElement
  does NOT read `.locked` (canvasStore.ts:172-174) and patchPendingLogo walks
  BACKWARD for the last unlocked type==='image' (`:180-190`), no-op when none.
  Reviewer named + checked one risk not in the brief: a dangling `selectedId`
  after removeElementOn (the existing `removeElement` clears it, `:169`; the new
  one doesn't). Traced to SelectedToolbar.tsx:13-14 — a stale id degrades to
  "nothing shown", not a crash. Correctly left to callers. NOT a finding, but
  worth remembering if a later task removes a SELECTED element.

Task 2 BASE (HEAD before impl): 09dddf0

Task 2: complete (commit 2e716b9, review clean — Spec ✅, Quality Approved, 2
Minors rolled up). lib/canvasOps.ts (parseCanvasOps/applyCanvasOps + CanvasOp
types) + a 2-line chatStore change. 11 frontend tests passing, tsc clean.
  Reviewer verified the task's CENTRAL guarantee against the source file, not
  the report's grep claim: applyCanvasOps is called exactly once, at
  chatStore.ts:172, inside sendMessage, BEFORE the set() — and NOT in kickoff
  (:131), hydrate (:190), applyResponse (:207) or any poll. The
  hydrate-never-applies test was judged a real regression guard, not a tautology.
  Implementer deviated from the brief's literal test code to match the file's
  existing `vi.mocked(sendChat)` mocking pattern — reviewer judged this correct.

Minor findings roll-up (hand to the final whole-branch review):
- T2: `canvasOps.ts:130-134` — a `pending_logo` op silently ignores `remove:true`
  (only `patch` is applied for that kind), though the shared `CanvasOp.remove`
  field implies it is general. Inherited verbatim from the brief's reference
  code, so not an implementer deviation. Residual gap IF a later task ever emits
  a pending_logo remove. Nothing does today.
- T2: `canvasOps.ts:131,133` — `op.patch as Partial<CanvasElement>` is an
  unchecked cast; a malformed backend payload has no frontend backstop. This is
  the documented design (backend resolves everything), not a defect.

Task 3 BASE (HEAD before impl): 2e716b9

Task 3: complete (commit 1e3299a, review clean — Spec ✅, Quality Approved, 2
Minors rolled up). THE LIVE BUG IS FIXED: `Step.ops` field + `_ops_logo_bg` +
ASK_LOGO_BG chips ("Yes, remove background") + new V2_BG_INSTRUCTIONS +
orchestrator_v2 emits data["canvas_ops"]. 741 passing (was 735).
  Reviewer verified BOTH mandated invariants intact from the diff context:
  `pending_logo["bg"]` + its done_when untouched (the op is additive, not a
  replacement), and `tool="upload"` retained with an updated comment. The
  load-bearing pin test is unaffected.
  Reviewer audited the 2 modified pre-existing tests individually
  (test_canvas_steps.py:411, test_v2_e2e.py:310): BOTH are label-only renames —
  assertions byte-identical, expected next-state unchanged. Not weakened.
  Confirmed canvas_ops is read from the step just ANSWERED, before next_step
  re-resolves (hunk ordering, orchestrator_v2.py:172-187).

Minor findings roll-up (continued):
- T3: `orchestrator_v2.py:106-113` — the quota-blocked FINALIZE_CANVAS early
  return builds its own `data` and never merges `canvas_ops`. Harmless today
  (ASK_LOGO_BG is far from FINALIZE_CANVAS) but a latent trap if any ops-bearing
  step is ever positioned right before a quota-blocked finalize.
- T3: `_ops_logo_bg`'s `_pending(c).get("face") or "front"` fallback has no test
  for the missing-face case. Brief-specified code, low value.

Task 4 BASE (HEAD before impl): 1e3299a

Task 4: complete (commit e9490ed, review clean — Spec ✅, Quality Approved, 3
Minors + 1 ticket). New pure module `canvas_edit.py` (inventory/resolve_ops +
AMOUNTS/SCALES/ROTATIONS/NAMED_COLOURS). 13 new tests; 754 passing.
  Reviewer VERIFIED THE ARITHMETIC BY HAND rather than pattern-matching: move
  clamp (0.8+0.2=1.0 -> 0.9 via 1-h), resize-around-centre (0.2*1.15=0.23,
  centre 0.5 held -> x=0.385), rotation accumulation (% 360 safe for negatives).
  Confirmed purity by reading every import (only `__future__`), confirmed
  non-mutation, confirmed drop-not-guess on all 5 paths, confirmed NOT wired in.
  Noted the careful `is None` vs falsy handling for curve==0.
  PLAN ERROR (harmless): the brief's step 4 says "15 tests"; the test code it
  specifies defines 13. Miscount in the plan text, not a coverage gap.

  ⚠️ RESOLVED BY CONTROLLER (reviewer raised it as cross-task, correctly):
  a `rotate` op on a `drawing` emits only {"rotation"}, while the frontend's own
  rotate handle persists x/y/rotation together (Konva rotates a stroke around its
  bbox centre — CLAUDE.md's canvas section documents this). Judged NOT a spec
  gap: the spec's op vocabulary never promises pivot-parity with the UI handle,
  and the failure mode is "rotates about a different pivot" — visible on the
  canvas and re-describable by the customer — not a crash. FILED AS A TICKET for
  the final review to triage; not a blocker.

Minor findings roll-up (continued):
- T4: no tests for resize "smaller" (the 1/scale reciprocal), rotate
  "anticlockwise" (the negation), move left/right, curve down/none, or an
  unresolvable STRING colour ("mauve") — all simple table-lookup mirrors of
  tested paths, but the brief calls out drop-for-bad-colour as first-class.
- T4: `resolve_ops`'s `isinstance(op, dict)` guard has no test.
- T4: `_index` (canvas_edit.py:76-82) lets a duplicate element id across faces
  silently overwrite the earlier one — relies on an UNSTATED invariant that ids
  are globally unique across canvas_design (plausible given frontend uid(), but
  unstated in this module).

Task 5 BASE (HEAD before impl): e9490ed

Task 5: complete (commits b9acf87..7fecce9, review clean after fix — Spec ✅,
Quality Approved, 1 Minor rolled up). `ie.interpret_canvas_edit(message,
inventory)` + `prompts.CANVAS_EDIT_PROMPT`. 758 passing.
  FIX (7fecce9) — reviewer caught an IMPORTANT plan-mandated defect: the PII test
  the PLAN specified was VACUOUS. It mocked the SDK failure as
  RuntimeError("upstream 500") — a fixed string never carrying the customer's
  words — so it passed identically whether the code logged type(exc).__name__ or
  str(exc), i.e. never exercised the "SDK error stringifies request content" risk
  it is named for. Controller judged the fix as FULFILLING the plan's stated
  intent (the test's own name IS the property), not contradicting it.
  The fixer then found a SECOND, DEEPER vacuity the reviewer had not: `caplog`
  never captures structlog output in this repo at all (structlog only wires into
  stdlib logging via app/main.py, never triggered in a unit test) — so the
  assertion was blind regardless of the exception. Now uses
  structlog.testing.capture_logs(), the pattern already proven in
  tests/test_intent_extractor_v2.py:114-137 for this same logger.
  PROVEN non-vacuous by deliberate regression (err=str(exc) -> FAIL on the leaked
  token; restore -> green). Re-reviewer independently HAND-TRACED the same and
  confirmed production `intent_extractor.py:720` unchanged — no behaviour was
  smuggled in to make the test pass.
  GENERALISATION WORTH REMEMBERING: **`caplog` cannot see structlog in this
  repo.** Any test asserting on log contents must use
  `structlog.testing.capture_logs()`. Other such tests may be silently vacuous.
  PLAN ERROR (harmless): brief said "19 tests"; real count 17.

Minor findings roll-up (continued):
- T5: `intent_extractor.py:721` `raise LLMUnavailable(str(exc)) from exc` still
  carries str(exc) into the EXCEPTION message, though the log line deliberately
  avoids it. PII risk is closed only at the log line, not end-to-end: a future
  caller logging str(e) on catching LLMUnavailable reopens it. Mirrors the
  pre-existing interpret_turn_v2 convention (line 662) exactly — inherited, not
  introduced. Task 6 is the first consumer; check it doesn't log str(e).

Task 6 BASE (HEAD before impl): 7fecce9

Task 6: complete (commits 8b9ca55..3e26036, review clean after 2 fix rounds —
Spec ✅, Quality Approved). Canvas describe branch -> canvas_edit -> ops ->
CONFIRM_CANVAS_EDIT; refuse -> brief_notes -> OFFER_REFINE; stall. 785 passing.
  IMPLEMENTER FIXED A PLAN BUG: the brief put `canvas_ops = []` inside the else
  branch, but the GREETING kickoff path also reaches `data = _public_data(...)`
  -> UnboundLocalError on every session's FIRST turn. Hoisted above the split.
  Reviewer independently confirmed the GREETING fall-through.

  ROUND 1 (opus) — 2 Important:
  1. **`last_change` was ungated** (orchestrator.py:1002 wrote it on EVERY
     DESCRIBE_CHANGES turn). generate.py:188-191 falls back to last_change when
     refine_details is empty — which is EXACTLY the canvas case, since the canvas
     leg never writes refine_details. So a canvas edit STILL became a
     change_request: "the logo's a bit big" -> ops shrink it on canvas AND the
     image model is separately told to shrink it -> DOUBLE-SHRUNK render. This
     contradicted the code's own comments. Plan miss, not implementer error.
     FIXED + re-verified: re-reviewer grepped both writers and proved
     `_apply_refine`'s write is unreachable for canvas (dispatch routes away;
     advance_state returns before REFINE_FOLLOWUP/REFINE_CONFIRM). Gate holds.
  2. **PLAN-MANDATED:** the brief's `edit_confirmed = "looks right" in low or
     is_affirmative(message)`. is_affirmative is SUBSTRING-based and "lo-OK-s"
     contains "ok" — so "that looks wrong" confirmed and spent a render, the
     exact harm the gate exists to prevent. ESCALATED TO USER (per skill: a
     plan-mandated finding is the human's call). USER CHOSE: the interpreter
     reads free text at the gate. Implemented as `ie.interpret_edit_confirm` +
     `prompts.CANVAS_EDIT_CONFIRM_PROMPT` + async `_apply_edit_confirm`; chip =
     0 model calls; outage -> `edit_confirm_stalled` -> stay put.
     Re-reviewer confirmed EVERY unhappy path defaults to not-rendering
     (refused/stalled/False/UNSET all avoid REGENERATING) and that the stall
     check precedes the confirmed check, so a stale True loses to a stall.

  ROUND 2 (opus) — 1 Important + 1 Minor, both fixed (3e26036):
  3. **PLAN MISS: CONFIRM_CANVAS_EDIT had NO reply copy** in either STATE_PROMPTS
     or CANNED_REPLIES, so the gate rendered generic filler ("Let's keep going…")
     beside its own chips — never telling the customer the change was applied,
     never asking if it looks right. The informed confirmation the gate exists
     for. Its sibling ASK_CHANGE_METHOD (same feature) had both entries. Fixed;
     re-reviewer confirmed the entries are REACHABLE in production (not dead
     dict keys) and the copy promises no render/email.
  4. Chip resolution was substring, so "Not quite — the front one looks right"
     confirmed ("looks right" tested first). Now exact strip+casefold match
     against the shipped labels, per the v2 registry precedent.

TICKETS (not blockers):
  - Ops are EPHEMERAL: only `canvas_edit_ops=True` is persisted; the ops live
    solely in the HTTP response. A page reload at CONFIRM_CANVAS_EDIT leaves the
    customer on the chips with the ops gone — "Looks right" would then regenerate
    an UNEDITED canvas. Matches the designed interface, but real.
  - A refused change gets NO acknowledgement: it routes to OFFER_REFINE, whose
    generic "want to tweak anything?" re-asks the same question. The customer's
    "make the embroidery thicker" is silently noted to brief_notes and they are
    invited to retype it. Spec-compliant but a customer-facing hole.
  - No-key deployments dead-end at canvas DESCRIBE_CHANGES: _has_llm=False makes
    interpret_canvas_edit raise forever -> canvas_edit_stalled -> re-ask forever,
    and that state ships NO chips to escape with. CLAUDE.md advertises the engine
    working with no Anthropic key; v2 solved this with Step.direct_answer + the
    chip nudge. The stall IS what the user mandated for an outage, but a
    permanent no-key state is not an outage.
  - `TRANSITIONS` IS runtime-read (state_machine.py:332 `nexts[0]` default), not
    merely documentation as its comment implies. Inert here (both new states
    return explicitly on every path) but the comment misleads.

Task 7 BASE (HEAD before impl): 3e26036

Task 7: complete (commit d241713, review clean [opus] — Spec ✅, Quality
Approved, 1 cosmetic Minor). `_mark_canvas_rework` (covers BOTH rework routes) +
_public_data REGENERATING branch returns trigger_finalize when reworking else
trigger_regeneration + Surface.tsx re-arms finalizeStarted when triggerFinalize
goes false. Backend 788 passing; frontend surfaceDirective + canvasOps 10 passing.
  Reviewer VERIFIED ALL 3 NAMED RISKS by reasoning through the code:
  1. re-arm vs catch-block retry: NO conflict. The effect deps only on
     [triggerFinalize]; the catch sets the ref false while triggerFinalize is
     still true, so the effect does NOT re-run (no auto-retry loop/deadlock);
     recovery is the pre-existing "Try again" button. doRender's own
     `if (!sessionId || rendering) return` guards a mid-flight toggle.
  2. rework without re-flatten: IMPOSSIBLE. The REGENERATING branch is exclusive
     (reworking -> trigger_finalize and returns); trigger_finalize always
     re-flattens before finalizeCanvas.
  3. reworking leak: NO. Set only for CANVAS_DESIGN/REGENERATING, popped by
     sessions.py which the trigger_finalize path always reaches. v1 plain-regen
     (flow_mode session) never sets it.
  Minor (cosmetic): _mark_canvas_rework signature continuation indent 1 space off.

Task 8 BASE (HEAD before impl): d241713

Task 8: complete (commit bd4635e — CLAUDE.md). VERIFICATION APPROACH DIFFERED
FROM THE PLAN (which said drive a full browser walk): instead the new backend
path was driven END-TO-END against the LIVE running stack + REAL HAIKU via the
chat API, with throwaway sessions seeded at the exact states and deleted after.
Stronger for the backend; does NOT cover the Konva visual render.
  PROVEN LIVE (real Haiku, real DB):
  - adjust: "make the logo smaller" -> confirm_canvas_edit + resize op
    (0.25->0.217, centre held — the "smaller" reciprocal path T4's units skipped)
    + new confirm copy (no render/email promise) + [Looks right, Not quite].
  - refuse: "make the embroidery thicker" -> offer_refine, no ops, brief_notes
    got the request (Haiku returned []).
  - confirm: "Looks right" -> regenerating, trigger_finalize=True (not
    trigger_regeneration), reworking=True, canvas_finalized=False.
  - reject-text (THE substring regression): "hmm that looks wrong to me" ->
    describe_changes, NOT regenerating. The interpreter reads it right.
  - v2 bg removal: "Yes, remove background" at ask_logo_bg (pending logo on BACK)
    -> canvas_ops {pending_logo, face:back, removeBg:true} -> ask_another_logo.
  NOT DONE: browser-visual confirmation of the Konva re-render (badge appears /
  logo moves). The frontend apply seam is unit-tested but no browser was driven.
  Recommended to the user as a visual pass. Suites: backend 788, frontend
  subset 28.

ALL 8 TASKS COMPLETE. Next: final whole-branch review (opus), then
finishing-a-development-branch.

=== FINAL WHOLE-BRANCH REVIEW (opus, 3abec9b..bd4635e) — "Ready to merge? With fixes" ===
CONFIRMED SOUND: the canvas_ops round trip, apply-at-response-site (not effect),
the LLM/geometry split, the confirm gate's exact-match + interpreter (substring
hole closed), CONFIRM_CANVAS_EDIT gating, PII discipline across all new code, and
change_request retirement airtight (both last_change writers traced — _apply_refine
unreachable for canvas).

IMPORTANT #1 (the one real cross-task defect, NOT previously listed as a gap):
  Iterative relative edits compound against a STALE base. `_apply_canvas_edit`
  (orchestrator.py:218) resolves ops against the PERSISTED canvas_design, but
  that's only written at canvas-finalize ("Looks right"). In the intended
  DESCRIBE_CHANGES -> "Not quite" -> DESCRIBE_CHANGES iteration loop nothing
  re-persists, so every describe turn recomputes from the ORIGINAL geometry while
  the frontend canvas already holds the accumulated edits. "move up" then "up
  more" both emit {y:0.35} from persisted y=0.4 -> the 2nd is a frontend no-op.
  Accumulating ops (move/resize/rotate) affected; absolute ops
  (recolour/set_text/delete) fine. No crash, no wasted render (render only on
  confirm), recoverable by absolute phrasing. Reachable on the primary path,
  undercuts the "iterate for free" promise, and is UNDOCUMENTED.
  SHARES ROOT CAUSE with the ops-ephemeral ticket (backend never sees edited
  state between turns). Reviewer's fix: frontend sends live canvas_design on the
  describe turn; backend resolves + persists against it (fixes both). Backend
  already trusts frontend canvas state at finalize, so it's consistent.

  Also: the ops-ephemeral ticket UNDERSELLS its blast radius — a mid-confirm
  reload rehydrates the UNEDITED persisted design, so "Looks right" then
  re-flattens and RENDERS AN UNEDITED CANVAS (a silently-wrong PAID render, not
  just lost ops). Rare (reload exactly at the gate) so not a blocker, but the
  ticket text must own this.

MINOR (reviewer): #2 canvasOps.ts parses `remove` for pending_logo but apply
drops it (dead branch, latent trap) — fold into the same touch. #3
_maybe_gather_element still runs on a canvas DESCRIBE_CHANGES turn -> a wasted
keyed LLM call per describe turn if the interpreter volunteered a
design_description (benign: canvas-finalize overwrites collected["elements"]).

TRIAGE of prior rolled-up findings: refused-ack -> ticket; no-key stall ->
ticket (prod always has a key); TRANSITIONS -> non-issue (new states ARE in the
table + pinned); _index dup-id -> non-issue (random uid, globally unique);
quota-blocked finalize drops canvas_ops -> ticket, latent (no ops step near
finalize today).

DECISION PENDING (user): fix #1 now (a Task 9: frontend sends live
canvas_design each describe turn + backend persists) vs ship with #1 documented
as a known gap + soften the "Not quite" re-ask copy.

Task 9 BASE (HEAD before impl): 0c0bb3e

Task 9: complete (commit e0b9628, review clean — Spec ✅, Quality Approved, 1
Minor). Frontend sends live canvas_design on a describe turn; chat.py
`_persist_live_canvas_design` adopts it (scoped to describe_changes + canvas +
well-formed) before dispatch; existing `_apply_canvas_edit` reads the fresh
design. No change to _apply_canvas_edit / handle_message / routing. Backend 792,
frontend targeted 107 passing.
  Reviewer verified the scoping guard is AIRTIGHT (malformed payload
  short-circuits before get_supabase; persist fires only at describe_changes +
  flow_mode==canvas), non-canvas wire is BYTE-IDENTICAL (sendChat without 3rd arg
  still emits {message}), and ALL 11 modified pre-existing frontend tests (report
  miscounted as 9) are legit cosmetic-arity updates — each fires from a
  non-describe state so expecting `undefined` 3rd arg is correct, none weakened.
  Minor: report's own count (9) is wrong (11). Harmless.
  VERIFIED LIVE (real stack, real Haiku): 0.4 -> 0.35 -> 0.25. Turn 1 "move up"
  (base 0.4) -> y=0.35; "Not quite" -> describe_changes; Turn 2 "up more" with
  the frontend's edited design (y=0.35) -> y=0.25. It compounded from the EDITED
  base instead of repeating 0.35 (the bug). Ops-ephemeral reload bug also closed
  (the edited design is now persisted each describe turn).

=== ALL 9 TASKS COMPLETE. Branch feat/canvas-led-refine ready to finish. ===
Final review's one Important (compounding) is FIXED + live-verified. Remaining
open items are all tickets (refused-ack copy; no-key stall at DESCRIBE_CHANGES;
quota-blocked-finalize drops canvas_ops; TRANSITIONS comment) — none blockers.
