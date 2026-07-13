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

============================================================
NEW PLAN: Canvas Photorealistic Multi-Angle Rendering
Plan: docs/superpowers/plans/2026-07-13-canvas-photoreal-multiangle.md
Spec: docs/superpowers/specs/2026-07-13-canvas-photoreal-multiangle-design.md
Branch: feat/canvas-design-studio | BRANCH_BASE (final review): 20bc2b8 (first commit of this plan's work; spec/plan commits 20bc2b8..eb03d36)
Tasks: PM-1 canvas_describe enrichment · PM-2 render every decorated face · PM-3 full-suite verify
Task PM-1 BASE (HEAD before impl): eb03d36
============================================================

Task PM-1: complete (commit 6d75a36, review clean — Spec ✅, Quality ✅, no findings). canvas_describe text branch: curve→style:"curved", dropped fontSize px emission. 7/7 test_canvas_describe pass. Reviewer confirmed prompt_builder._element_line degrades gracefully on missing size key + renders "curved style".

Task PM-2 BASE (HEAD before impl): 6d75a36

Task PM-2: complete (commit f52afba, review clean — Spec ✅, Quality ✅, no findings; reviewer independently re-ran suites 55 passed inc. both cache-key regressions). Canvas branch → render_views(collected); flat-PNG reuse splice deleted; canvas_layouts kept (still read by _one for layout guide); docstring/comment refreshed. is_edit/else branches byte-unchanged. Rewritten test asserts both faces reach provider, no view_images entry is a raw uploads/*.png path, each render got its signed layout guide + correct ref angle. Full suite 415.
  Non-blocking obs (reviewer): elif is_canvas / else now have identical body (kept separate for the canvas comment) — intentional per plan, no change.

Task PM-3 (controller-run): full-suite regression.

Task PM-3: complete (controller-run). Full backend suite: 415 passed, 0 failed (40.4s). Optional Step 2 (live prompt-preview) skipped — needs a live session/Docker.

ALL 3 TASKS COMPLETE. Feature commits: 6d75a36(canvas_describe) f52afba(multi-angle render). Plan/spec: 20bc2b8(spec) eb03d36(plan). Ready for final whole-branch review over 20bc2b8..f52afba.

FINAL REVIEW (opus, whole-branch 20bc2b8..f52afba): READY to merge — no Critical/Important. Traced canvas path end-to-end; real product photo is conditioning FIRST image for EVERY per-view render (reference_image_url_for_view never empty — falls back to front); two-face design both reach model with own layout guide + ref angle + scoped elements (back decoration cannot leak to front); undecorated non-front faces never render (render_views = front+decorated only; frontend flattens only non-empty faces); no PII logging change; non-canvas + edit paths byte-unchanged; canvas_describe curve/size edit only touches canvas text branch. Focused suites 24 passed; full suite 415.
  Minor TICKET #1 (informational, correct): canvas EDIT turns now carry forward REAL prev renders via prev_views instead of overwriting non-front faces with flat PNGs (old splice was is_canvas-gated, ran on canvas edits too). Correct feature consequence; NON-canvas edit path untouched.
  Minor TICKET #2 (data-quality follow-up): for a SYNCED product with few images, catalogue_sync._map_views sets left/right/back = front image → decorating the back AI-renders back decoration onto a front-angle cap. Still a real product photo (constraint holds) + within accepted model-variability trade-off, but worse than the old flat mock for that case. Follow-up: ensure real per-angle photos for canvas-enabled synced products (blank sessions already carry all 4 real angles; unaffected).

============================================================
NEW PLAN: Canvas Background Removal + Freehand Draw Tool
Plan: docs/superpowers/plans/2026-07-13-canvas-bgremove-drawtool.md
Spec: docs/superpowers/specs/2026-07-13-canvas-bgremove-drawtool-design.md
Branch: feat/canvas-design-studio | BRANCH_BASE (final review): first commit of this plan work
Tasks: BD-1 store foundations · BD-2 bg removal · BD-3 draw tool · BD-4 backend describe · BD-5 verify+docs
============================================================
Task BD-1 BASE (HEAD before impl): eb0a858

Task BD-1: complete (commit f4ae7b8, review clean — Spec ✅, Quality ✅, no findings). canvasStore: drawing type + points + originalAssetUrl, drawMode/drawColour/drawWidth + setters, addDrawing (active face, current colour/width, selects), reset clears draw-mode. 11/11 canvasStore tests. Reviewer confirmed all el.type consumers are if-chains (no exhaustive switch) so union add is non-breaking.

Task BD-2 BASE (HEAD before impl): f4ae7b8

Task BD-2: complete (commit 9b36fa5, review clean — Spec ✅, Quality ✅). NOTE: implementer stalled on a bg run + wrote a WRONG report (stale multi-view content); controller verified the ACTUAL code by direct file read + ran build/tests (tsc clean, imgly code-split into separate ort async chunk; 13/13 focused tests) then committed the handoff. bgRemove.ts (removeBackgroundToFile dynamic-import + toggleBackground re-uploads on BOTH ON/OFF, records originalAssetUrl on ON, restores on OFF) + SelectedToolbar BgRemoveToggle (busy/disabled/failed, no half-apply on error) + drawing stroke-colour branch. Reviewer confirmed both toggle dirs re-upload (uploaded_asset_path tracks toggle), dynamic import, error never calls update().
  Minor TICKET: OFF-toggle does fetch(originalAssetUrl) directly — if uploadLogo asset_url is a TTL-signed URL that expired mid-session, restore fails with generic "Failed — try again" (pre-existing: the canvas element already uses asset_url for display). Low risk; consider /media proxy or longer TTL.

Task BD-3 BASE (HEAD before impl): 9b36fa5

Task BD-3: complete (impl 70a7a02 + fix bd657cb, review clean after fix — Spec ✅, Quality ✅). DrawingNode (Konva Line in draggable Group, move+delete, no Transformer) + CanvasStage draw-mode pointer handling (down/move/up, listening={!drawMode}, live stroke, commit ≥2 pts) + ToolRail Draw toggle + colour/thickness bar + FaceThumbnails drawing render. Build tsc-clean; store 11/11.
  Fix bd657cb (1 Important + 2 Minor from review): (a) e.evt.preventDefault() in onDown/onMove gated to drawMode (mobile touchmove no longer scrolls) — controller-verified guards sit after !drawMode early-returns; (b) useEffect clears in-progress stroke on activeFace change (no stale-coords wrong-face commit); (c) dropped dead useRef import.
  Minor TICKET (deferred, not fixed): no window-level mouseup fallback — releasing the pointer outside the stage silently discards the in-progress stroke (data loss, not corruption).

Task BD-4 BASE (HEAD before impl): bd657cb

Task BD-4: complete (commit e601c61, review clean — Spec ✅, Quality ✅, no findings). canvas_describe drawing branch in _element (elif before else/logo → type:graphic + content "a hand-drawn line[ in <colour>]" + colour=stroke) + _describe. placement_zone inherited from FACE_ZONE at top (→ correct face routing via element_view). 8/8 describe tests. Reviewer confirmed no coords in description text (raw geometry only in out["canvas"] structured sub-dict, same as text/shape).

Task BD-5 (controller-run): full-suite verify + CLAUDE.md.

Task BD-5: complete (commit for CLAUDE.md). VERIFICATION: backend pytest 416 passed (+1 describe test). Frontend build tsc-clean; focused suites 13/13 (canvasStore 11 + bgRemove 2). Frontend delta +4 tests (canvasStore 9→11, new bgRemove +2) → 185 passing; full vitest run produced no output (known Windows tinypool flake per ledger) so count derived from deterministic focused-run delta. CLAUDE.md canvas bullet (bg removal + draw tool) + counts (416/185) + deferred tickets noted.

ALL 5 BD TASKS COMPLETE. Feature commits: f4ae7b8(store) 9b36fa5(bg removal) 70a7a02+bd657cb(draw tool+fix) e601c61(backend describe) + CLAUDE.md. Ready for final whole-branch review over 9b36fa5^..HEAD (this plan work).

FINAL REVIEW (opus, whole-branch eb0a858..27f315d, 6 commits): READY to merge — no Critical/Important. Traced BG-removal seam end-to-end: bgRemove.ts uploadLogo → uploads.py sets collected["uploaded_asset_path"]+has_logo → generate.py reads it as signed 2nd conditioning image → transparent asset genuinely reaches Gemini (NOT cosmetic). imgly is the ONLY dynamic import (code-split, no eager load). Drawing→graphic w/ placement_zone from FACE_ZONE, no coords in text; test asserts it. Backend change is ONLY the additive canvas_describe drawing branch — generate/prompt_builder/render_views untouched (no multi-angle regression). Draw-tool pointer handling traced: ≥2-pt commit, stroke cleared on face switch (no leak), onMove guarded, listening gate, renders on stage+thumbnails+drag round-trip. Backend 416; frontend build tsc-clean + focused 13/13.
  Minor TICKETS (non-blocking, deferred): (1) DrawingNode ignores isSelected → selected stroke has no on-canvas selection affordance (only toolbar signals it) — UX inconsistency vs text/image/shape. (2) bgRemove OFF leaves originalAssetUrl populated (harmless stale field; re-toggle still resolves correctly). (3) single tap in draw mode (<4 pts) silently discarded — cannot place a dot (acceptable for a pen).

FEATURE COMPLETE (bg removal + draw tool). All 5 BD tasks + final review done. Commits: f4ae7b8 9b36fa5 70a7a02 bd657cb e601c61 27f315d. Ready to finish branch. PENDING: manual browser E2E (needs Docker + imgly installed in container) — not run.

CORRECTION: full frontend vitest run completed — 196 passed / 2 failed (pre-existing adminQuotes) / 202 total. Earlier derived 185 was off a stale 181 baseline; CLAUDE.md corrected to 196.
