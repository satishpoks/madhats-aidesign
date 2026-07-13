# SDD progress — Canvas Design Studio Phase 1
Plan: docs/superpowers/plans/2026-07-13-canvas-design-studio-phase1.md
Branch: feat/canvas-design-studio
BRANCH_BASE: 364002f2de350d8349c9b54fe8eb3c91d5945137  (master 364002f — merge-base for final review)
Plan+spec commits: d222c8e (spec), cf4fec2 (plan)
Note: 9 pre-existing uncommitted master files ride in the working tree; task commits use targeted `git add` so they never enter feature commits.

Task 1 BASE (HEAD before impl): cf4fec2

(tasks not yet started)

Task 1: complete (commit 2581ec6, verified directly by controller — trivial verbatim-from-brief additive nullable migration; applied via supabase db reset, column confirmed jsonb/nullable). DEVIATION: file numbered 20260713000002 (000001 taken by existing generation_view_images migration) — functionally identical.
WIP CHECKPOINT: committed 9 pre-existing multiview files as 90550b6 (user-approved) so canvas commits stay clean. Working tree now clean.

Task 2 BASE (HEAD before impl): 90550b6

Task 2: complete (commit 09c4244, review clean — Spec ✅, Quality Approved, no Crit/Imp). canvas_to_elements() pure builder + 3 tests (RED→GREEN). Reviewer independently confirmed element-key contract against live prompt_builder (element_view round-trip, _first_with, build_params).
  Minor (final review): text elements omit remove_bg key + fontSize:0 drops size (functionally inert vs _first_with); tests cover only front/left legs (back/right/multi-element/empty-input untested).

Task 3 BASE (HEAD before impl): 09c4244

Task 3: complete (commit 3da46a1, review clean — Spec ✅, Quality Approved, no Crit/Imp/Minor). layout_guide_url added to abstract generate + StubAdapter + _GeminiAdapter (flash/pro subclass, no override). Reviewer confirmed _fetch_bytes reuse by direct file read; append order correct (after ref/prior/uploaded, before prompt). Full suite 392.
  Note: real adapters live in app/services/image/adapters/ (stub.py, gemini_base.py) — NOT gemini.py. Task 4/6 should target those paths.

Task 4 BASE (HEAD before impl): 3da46a1

Task 4: complete (commit 7f8a295, review clean — Spec ✅, Quality Approved, no Crit/Imp). Canvas branch in _run_generation: front-only AI render w/ signed layout_guide; non-front faces spliced from canvas_layouts (skip PRIMARY_VIEW, after failure gate). Non-canvas path verified byte-unchanged by direct file read. Full suite 393. Deviation: added generate_signed_url mock in test (matches test_multiview.py) — reviewer confirmed it can't mask the back-reuse assertion.
  Minor (final review): (a) test's fake_render_view discards kwargs so it doesn't assert layout_guide_url reaches the front render (wiring correct by inspection) — cheap harden: capture kwargs + assert layout_guide_url=="signed:uploads/front.png". (b) cache_key omits layout_guide_url → two canvas designs with identical elements/prompt but different pixel layout can cache-collide on front render (inherited pattern, mirrors prior_design_url gap).

Task 5 BASE (HEAD before impl): 7f8a295

Task 5: complete (commits e5b2a6d + fix ffc2c7e, review clean after fix — Spec ✅, Quality Approved). 3 canvas routes (create/layouts/finalize) + models/canvas.py + CANVAS_DESIGN enum. Reviewer independently confirmed capture_lead_and_verify(session,collected,email) call shape + email_captured→advance_state(GENERATING)→VERIFY_EMAIL wiring against live source. Full suite 401.
  3 Important findings FIXED (ffc2c7e): faces/files length-mismatch→400, invalid-face→400, +5 tests (hat_type create leg, 400-neither, 413 oversized, 415 bad mime, mismatch). Canvas routes file 8/8.
  ⚠️ CARRY TO FRONTEND (Task 11/12): finalize returns data:{} (verbatim per brief) — NO trigger_generation flag. ChatPanel's generation effect ALSO fires on chatState==='generating', so hydrating chatStore to state 'generating' still triggers startGeneration. Confirm this in Task 11/12 wiring.
  Minor (final review): partial-upload orphans earlier files in storage if a later file fails validation; finalize returns raw dict not response_model=ChatResponse.

Task 6 BASE (HEAD before impl): ffc2c7e

Task 6: complete (commit ac1bb69, controller-verified — canvasStore test 4/4, full file read, matches brief). NOTE: implementer did correct work but FAILED to commit + returned a garbled report (mentioned a phantom "Monitor notification"); controller finished the handoff by committing. Deviation (reasonable, accepted): addText omits default colour '#ffffff' so untouched text serialises uncoloured (team decides); Task 9 TextNode + Task 10 SelectedToolbar already fall back to #ffffff for display, so no break. konva ^10.3.0 + react-konva ^18.2.16.

Task 7 BASE (HEAD before impl): ac1bb69

Task 7: complete (commit 3d6ae69, controller-verified — trivial pure helper verbatim from brief, both dataUrlToFile + flattenStage present, test 1/1). haiku implementer committed correctly this time (explicit commit instruction worked).

Task 8 BASE (HEAD before impl): 3d6ae69

Task 8: complete (commit f3daecc, controller-verified — 3 fns present (createCanvasSession/uploadCanvasLayouts/finalizeCanvas) + CanvasLayoutsResponse type, tsc clean, scoped 2 files). No unit test (tsc-gated per brief).

Task 9 BASE (HEAD before impl): f3daecc

Task 9: complete (commit ba826e5, controller-verified — TextNode+ImageNode exported, crossOrigin='anonymous' present (taint-safety), tsc clean, single scoped file). No unit test (jsdom-canvas, justified in brief).

Task 10 BASE (HEAD before impl): ba826e5

Task 10: complete (commit 3c80317, controller-verified — CanvasStage+ToolRail+SelectedToolbar, crossOrigin present in CanvasStage, tsc clean, scoped 3 files). No unit test (per brief). Full-suite run timed out at 2min (known Windows tinypool slowness; new components untested + not yet imported so cannot affect existing tests — Task 13 verifies suite properly).

Task 11 BASE (HEAD before impl): 3c80317

Task 11: complete (commits a6cf062 + fix 3291260 + fix 95590a8, review clean after fixes — Spec ✅, Quality Approved). DesignStudio shell + face tabs + see-it-rendered (flatten→upload→finalize→hydrate handoff to ChatPanel). Handoff verified: hydrate([], 'generating', {}) sets chatState='generating' (ChatPanel fires generation on that) + kickoffDone=true (no greeting).
  CRITICAL FIXED (3291260): rAF-x2 didn't wait for async image loads → stale/blank/missing-logo exports for non-active faces. Fix: new imageCache.ts (shared HTMLImageElement cache) + CanvasStage/ImageNode read cache synchronously when complete + index.tsx preloads all decorated-face image URLs before the flatten loop. crossOrigin preserved.
  IMPORTANT FIXED (95590a8): loadImage clobbered concurrent same-url callers (handler reassignment on shared Image → first caller's promise hung, could blank the active face). Fix: inflight Promise dedup map; onload/onerror delete inflight (failures retryable). tsc clean.
  Minor (final review): imageCache Map unbounded (no eviction — session-scoped, low risk); CanvasStage lazy-init comment slightly overstates sync guarantee (effect, not initializer, carries face-switch sync — no code change).

Task 12 BASE (HEAD before impl): 95590a8

Task 12: complete (commit 3d58d0c, controller-verified — focused tests sessionStore 15/15 + BlankHatPicker 4/4, tsc clean, App branch order canvas→session→blank correct). NOTE: implementer did correct code + TDD but stalled waiting on a background full-suite run and didn't commit; controller ran focused tests + committed. Incidental: BlankHatPicker.test.tsx updated (mocked old startBlankSession→startCanvasBlankSession). startSession/startBlankSession retained for resume.
  PENDING: manual browser E2E (Task 12 Step 7 — needs Docker+browser): canvas taint check on toDataURL, finalize 200, ChatPanel handoff, design reveal. NOT yet run.

Task 13 (controller-run): full-suite regression + CLAUDE.md.

Task 13: complete (commit d4c9f25 CLAUDE.md). VERIFICATION: backend pytest 401 passed; frontend vitest 177 passed / 2 failed (pre-existing adminQuotes Router-context — confirmed NOT a canvas regression) + 1 tinypool Worker-exit flake (known Windows). CLAUDE.md canvas bullet + counts (401/177).

ALL 13 TASKS COMPLETE. Feature commits: 2581ec6(migration) 09c4244(describe) 3da46a1(provider) 7f8a295(gen) e5b2a6d+ffc2c7e(routes) ac1bb69(store) 3d6ae69(flatten) f3daecc(api) ba826e5(nodes) 3c80317(stage/rail) a6cf062+3291260+95590a8(studio+fixes) 3d58d0c(routing) d4c9f25(docs). Plus WIP checkpoint 90550b6.
PENDING: manual browser E2E (Task 12 Step 7) — not run (needs Docker+browser).
Ready for final whole-branch review.

FINAL REVIEW (opus, whole-branch cf4fec2..d4c9f25, WIP 90550b6 excluded): Ready to merge = YES, no Critical. Customise flow traced end-to-end and holds; hard constraint upheld (real photo first, layout guide additive); logo-asset-reaches-model seam CONFIRMED holds (uploadLogo sets uploaded_asset_path before finalize; view_has_logo gates crisp 2nd image; element.assetUrl is audit-only). _public_data degrades gracefully on canvas_design state (no crash).
  IMPORTANT #1 FIXED (8bf9c10): cache_key omitted layout guide → identical-elements/different-layout collision served wrong render + discarded layout guide. Fix folds canvas_layouts[view] path into the key input (model-facing view_prompt untouched; non-canvas keys proven byte-identical). Full suite 403; regression sweep 71.
  IMPORTANT #2 (OPEN — user decision): blank-flow cap colour unreachable in canvas path. BlankHatPicker calls startCanvasBlankSession w/o colour; DesignStudio hardcodes colourways=[]; canvas_to_elements ignores canvas_design["colourway"]; flow_mode='canvas' uses customise IMAGE_GEN_PROMPT (not _BLANK), so blank customers get uncoloured blank. Spec wanted a colour swatch row; plan never wired it. Fix-now vs Phase-1.1 ticket — ASKED USER.
  IMPORTANT #3 (OPEN — runtime verify): canvas taint/CORS on blank flow — /media proxy + Supabase signed URLs must send Access-Control-Allow-Origin or loadImage rejects → "See it rendered" fails for blank sessions. Needs manual E2E (Docker+browser). Customise flow lower risk (Shopify CDN/placehold.co permissively CORS'd). ASKED USER.
  NEW Minor (ticket): multi-logo front loses crisp art (each /uploads/logo overwrites uploaded_asset_path; only last logo's crisp asset passed as 2nd image; non-front unaffected — reuse flattened PNG).
  Minors → ticket (per opus triage): Task2 text remove_bg/fontSize:0/partial test legs; Task4 fake_render_view kwargs assert; Task5 partial-upload orphan + finalize response_model; Task11 imageCache eviction + comment.

LIVE E2E (customise flow, real docker stack, browser): PASS. Canvas loads (Shopify CDN bg via crossOrigin, no taint); add-text + SelectedToolbar + face tabs work; "See it rendered" → email modal → flatten (NO SecurityError) → POST /sessions/canvas 200 → /canvas-layouts 200 (OPTIONS preflight 200) → /canvas-finalize 200 → hydrate handoff to ChatPanel → generation "Creating your design…" → VERIFY_EMAIL (Ricardo verification message). Important #3 (CORS/taint) RESOLVED for customise (Shopify CDN sends CORS headers). Blank-flow /media CORS still to verify after Task 14.
E2E-CAUGHT BUG FIXED: POST /sessions/canvas 503 — entry_path defaulted None but design_sessions.entry_path is NOT NULL (Task 5 mocked supabase, missed it). Fixed model default → "canvas_first" + regression test. Canvas routes 9/9.

TASK 14 (blank colour, user-approved fix-now for final-review Important #2): COMPLETE.
  14a backend (commit 138d2c3): create_canvas_session hat_type leg sets collected["canvas_blank"]=True; finalize maps canvas_design["colourway"]→collected["hat_colour"]; prompt_builder._render_template treats canvas_blank as blank → IMAGE_GEN_PROMPT_BLANK recolour. Full suite 406. is_canvas gate + customise leg untouched.
  14b frontend (commit 1b8075f, controller-finished — subagent stalled on bg suite): sessionStore.blankColourways from hatType.colours; DesignStudio sources swatch row; CanvasStage multiply-tint Rect when colourway set. sessionStore test 16/16, tsc clean. Customise sets no colourway → no swatch/tint.
IMPORTANT #3 (CORS/taint) RESOLVED for BOTH flows: customise via live E2E (Shopify CDN); blank via /media CORS probe (ACAO=http://localhost:5173 present) + media.py streams bytes inline (Response(content=...), NOT a redirect) → Konva crossOrigin image gets ACAO → no taint. Blank UI flow not driven (no active hat type seeded locally) but the sole taint risk is confirmed safe by direct evidence.
Docs commit: 36b19bc (backend 406 / frontend 178).

FEATURE COMPLETE. All 13 plan tasks + Task 14 (blank colour) + 2 E2E-caught/review fixes done, reviewed, verified. Final review = ready to merge (all Important addressed). Remaining = deferred Minors (ticket list above) + optional: drive blank UI once a hat type is seeded.

============================================================
NEW PLAN: Split-Screen Customise Studio (canvas left + chat right)
Plan: docs/superpowers/plans/2026-07-13-customise-studio-split-screen.md
Branch: feat/canvas-design-studio | BASE before Task 1: c077bb4
Tasks: SS-1 ChatColumn · SS-2 DesignStudioSurface · SS-3 CustomiseStudio+App · SS-4 manual E2E
============================================================

SS-1: complete (commit de84c73, review clean — spec PASS, no findings). ChatColumn extracted, no auto-kickoff verified, ChatPanel untouched. 5/5 tests, build clean.
SS-2 BASE (HEAD before impl): de84c73

SS-2: complete (commit 4164690, review clean — spec PASS). DesignStudioSurface created, email modal removed, doRender hydrates in place (no nav), finalize no-email. index.tsx deleted. Build intentionally red (App.tsx-only). 
SS-3 BASE (HEAD before impl): 4164690

SS-3: complete (commit 03e5454, review clean — spec PASS). CustomiseStudio shell + App wiring; build GREEN. Full suite: 2 failed/190 passed — the 2 are pre-existing adminQuotes (Router context, unrelated) + known tinypool Windows worker-exit flake. New tests (ChatColumn 5 + CustomiseStudio 2) pass. No regressions.
ALL 3 SS CODE TASKS COMPLETE. Commits: de84c73(ChatColumn) 4164690(Surface) 03e5454(CustomiseStudio+App). Base c077bb4. Next: final whole-branch review over c077bb4..03e5454, then manual E2E (SS-4).

FINAL REVIEW (opus, whole-branch c077bb4..03e5454): Ready to merge = WITH FIXES. All binding constraints hold (ChatPanel untouched, hydrate-not-kickoff, no-email finalize, branch order). 
  IMPORTANT #1 FIXED (297bbc7): "See it rendered" button stuck on "Rendering..." forever after success — Surface no longer unmounts (hydrate-in-place), rendering only reset in catch. Fix: terminal `rendered` state set on success; ToolRail shows disabled "Rendered ✓". New ToolRail.test.tsx (3) + focused CustomiseStudio/ChatColumn all green (10), build clean. Trivial #3 (stale imageCache comment) fixed same commit.
  MINOR #2 (DEFERRED ticket): ChatColumn has dead locals (designReleased/awaitingVerification/RELEASED_STATES/genStatus/productRef) copied from ChatPanel that fed the omitted ProductViewer. designReleased/awaitingVerification were plan-MANDATED to keep; leaving all for the spec §4.2 orchestration-rewrite reconciliation. Not blocking.
CODE COMPLETE + reviewed. Remaining: SS-4 manual browser E2E (needs Docker+stack+seeded product).

SS-4 MANUAL E2E (live docker stack, browser, customise flow product 1111...): PASS.
  - Split screen renders: header "A Frame Flex Cap > Design"; LEFT face thumbnails + canvas + tool rail; RIGHT ChatColumn (Ricardo/Online + empty-state hint "Design your cap on the left...").
  - Add text -> element on front face + SelectedToolbar + thumbnail "1" badge.
  - See it rendered -> flatten (NO taint/SecurityError, generation ran) -> layouts -> finalize(no email) -> hydrate IN PLACE, NO navigation (URL/screen unchanged).
  - Render button reached terminal "Rendered ✓" (disabled) — final-review Important #1 fix CONFIRMED live (was the stuck-"Rendering…" bug).
  - Chat came alive in right panel: "Generating your design..." -> advanced to inline ASK_EMAIL ("Just need your email address...") confirming no-email finalize + ASK_EMAIL fallback (spec §4.1).
  - Console: no errors/exceptions.
FEATURE COMPLETE: SS-1..3 code + final-review fix (297bbc7) + SS-4 E2E all done, reviewed, verified. Commits: de84c73 4164690 03e5454 297bbc7. Ready to finish branch.
