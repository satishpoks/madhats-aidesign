# SDD Progress — v2 canvas Back: element-aware restart + single-step lock

Branch: feat/tls-all-servers
Plan: docs/superpowers/plans/2026-07-25-v2-canvas-back-element-restart.md
Started base: 21f1b7f

Global constraints:
- v2 canvas flow only (settings.canvas_orchestrator_v2 on AND flow_mode=="canvas"); never touch v1/non-canvas.
- Backend tests: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q <path>`.
- No browser confirm(); confirm is inline chat UI.
- Internal `_`-prefixed keys never in WRITABLE_SLOTS, never in LLM context.
- Element-adjust set exactly {LOGO_ADJUST, ASK_LOGO_BG, DECOR_ADJUST}.
- Decor restart -> ASK_ADD_DECOR; logo restart -> ASK_LOGO_PLACEMENT.

Tasks:
1. Backend — element-adjust set, gated can_go_back, back_removes_element, lock-clear
2. Backend — handle_back element-restart branch + restart copy
3. Frontend — removePending action + canvas_ops remove verb
4. Frontend — backRemovesElement + ChatColumn confirm dialog

--- ledger ---
Task 1 base (before dispatch): 21f1b7f
Task 1: complete (commits 21f1b7f..741a49f, review clean). _ELEMENT_ADJUST_STEPS
  {LOGO_ADJUST,ASK_LOGO_BG,DECOR_ADJUST}; _public gates can_go_back on `not _back_used` + adds
  back_removes_element; handle_message pops _back_used after empty-turn guard, before interpreter.
  handle_back untouched (Task 2). 3/3 new + full backend 1009 pass. _back_used not in WRITABLE_SLOTS
  (by construction) and not LLM-leaked (verified by reviewer).
  MINOR: brief's -k filter misses one of the 3 new test names (harmless; verified separately).

Task 2 base (before dispatch): 741a49f
Task 2: complete (commits 741a49f..6b7ecf1, review clean). handle_back: _restart_element helper
  (logo -> pending_logo={} -> ASK_LOGO_PLACEMENT; decor -> pop decor_choice/face/placed ->
  ASK_ADD_DECOR) + emits canvas_ops pending_logo remove w/ face fallback; _back_used=True on BOTH
  element + non-element paths; V2_BACK_RESTART_ACK copy. GREETING/target-None/quote_requested guards
  unchanged. 3/3 new + wider 140 + full backend 1012 pass. No scope creep.

Task 3 base (before dispatch): 6b7ecf1
Task 3: complete (commits 6b7ecf1..244d020, review clean). canvasStore.removePending(face) removes
  last-unlocked element of ANY type (no image filter), no-op when none, clears selectedId if removed
  was selected; applyCanvasOps pending_logo branch calls removePending on remove:true (patch path
  kept); parseCanvasOps unchanged. 10/10 focused + 20/20 neighbours + tsc clean. Brief test typo
  fixed: .url -> .assetUrl (real field on CanvasElement; reviewer confirmed not masking).

Task 4 base (before dispatch): 244d020
Task 4: complete (commits 244d020..531eb87, review clean). chatStore.backRemovesElement in all 4
  canGoBack sites; ChatColumn inline confirm ("Remove this element and start it over?") gated on
  confirmingBack && backRemovesElement; Remove&start over -> goBack, Keep going -> dismiss; flag-false
  Back unchanged. No window.confirm. 24/24 (chatStoreBack 5 + ChatColumn 9 + canvasStoreOps 10) + tsc
  clean. kickoffDone:true in tests prevents mount-kickoff clobber (reviewer verified).

=== ALL 4 TASKS COMPLETE. HEAD 531eb87. ===

FINAL WHOLE-BRANCH REVIEW (opus): READY TO MERGE — no Critical/Important.
  Verified end-to-end: lock sets on both Back paths -> can_go_back=false that turn -> FE hides button
  -> next forward turn pops _back_used; no chained backs. Logo restart -> ASK_LOGO_PLACEMENT, decor ->
  ASK_ADD_DECOR (email gate not tripped). Canvas-op {kind:pending_logo,remove:true} agrees FE<->BE,
  applied imperatively (not effect). _back_used never in LLM ctx / WRITABLE_SLOTS. Terminal flags +
  GREETING/post-submit guards intact. v1/non-canvas provably unaffected.
  MINOR (fixed): confirmingBack could go stale and re-open the destructive confirm unbidden after a
  chip tap on a later element-adjust step.

Fix wave: complete (commit 531eb87..b3e6e19). ChatColumn useEffect resets confirmingBack on chatState
  change + regression test. 15/15 (ChatColumn 10 + chatStoreBack 5) pass, tsc clean.

FOLLOW-UP TICKETS (non-blocking, from final review recommendations):
  - removePending / element-restart assume "at most one unlocked element per face" (the lockPlaced
    anchor). Holds today; add a one-line invariant comment on removePending.
  - handle_back lock is UI-enforced only (no server early-return when _back_used set). Optional
    defensive early-return would make "one step per Back" hold regardless of client.

=== FEATURE COMPLETE — READY TO MERGE. HEAD b3e6e19. Branch feat/tls-all-servers. ===
