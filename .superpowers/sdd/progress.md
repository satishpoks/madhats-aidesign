# SDD progress — canvas per-element images + admin 360 view

Plan: docs/superpowers/plans/2026-07-24-canvas-per-element-images-360-view.md
Spec: docs/superpowers/specs/2026-07-24-canvas-per-element-images-and-360-view-design.md
Branch: feat/canvas-per-element-images-360-view
Base (before Task 1): 61b4930

Tasks:
- T1: storage.path_from_signed_url helper
- T2: /uploads/logo returns asset_path
- T3: canvas_describe shared element_label + carry assetPath
- T4: providers accept uploaded_asset_urls list
- T5: generate.py per-view image conditioning (BUG FIX)
- T6: admin session endpoint canvas_faces
- T7: frontend canvasStore assetPath
- T8: frontend api + Surface thread asset_path
- T9: admin 360 view Customer's design section + download
- T10: full-suite verification

## Progress
Task 1: complete (commits 61b4930..6834ff7, review clean). No issues. Pure helper, 4/4 tests.

Task 2 base (before dispatch): 6834ff7
Task 2: complete (commits 6834ff7..b2e754e, review Approved). Reviewer's "Important"
  (reuse existing fixtures) adjudicated FALSE POSITIVE by controller: no uploads/logo
  route fixture exists (grep hits were string mentions); inline _FakeSB mirrors
  test_canvas_routes.py pattern. 1/1 test.

Task 3 base (before dispatch): b2e754e
Task 3: complete (commits b2e754e..541e3eb, review Approved). Hand-traced _describe
  output byte-identical (text/drawing/shape/logo). element_label shared; assetPath
  carried. 50/50 canvas_describe-touching tests. MINOR: required face-suffix dup in
  _describe shape branch (inherent to leading-"a" divergence).

Task 4 base (before dispatch): 541e3eb
Task 4: complete (commits 541e3eb..6074376, review Approved). Providers accept
  uploaded_asset_urls list; legacy single path traced byte-identical; each artwork
  own role="uploaded_asset" part. New 3 tests + adapter regressions; full suite 964.

Task 5 base (before dispatch): 6074376
Task 5: complete (commits 6074376..d530934, review Approved). CORE BUG FIX.
  _canvas_view_images per-view resolution (assetPath/recover/passthrough/skip);
  non-canvas byte-identical; provider gets full per-view list not first-only.
  4/4 new tests + full suite 968. MINOR (final triage): skip-branch (no
  assetUrl/assetPath) not directly tested.

Task 6 base (before dispatch): d530934
Task 6: complete (commits d530934..3249fcf, review Approved). Admin endpoint
  canvas_faces + canvas_design; _resolve_element_media proxies via /media (never
  raw signed URL); scoping/existing fields untouched; non-canvas → null/[]. 2 new
  tests + scoping regression; full suite 970. MINOR (final triage): http-passthrough
  + terminal-None branches untested; "other" el type falls to logo label (latent).

=== BACKEND COMPLETE (T1-T6), 970 tests passing ===

Task 7 base (before dispatch): 3249fcf
Task 7: complete (commits 3249fcf..f230114, review clean). canvasStore assetPath
  field + addImage 3rd param; round-trips via toCanvasDesign. 3 tests, tsc clean.

Task 8 base (before dispatch): f230114
Task 8: complete (commits f230114..1245679, review clean). uploadLogo return type
  + handleUpload thread asset_path; addGraphic untouched. Collateral (legit):
  updated 3 ChatPanel test mocks for the new return field. tsc clean, 10/10 tests.

Task 9 base (before dispatch): 1245679
Task 9: complete (commits 1245679..faea439, review Approved). Admin "Customer's design"
  section (per-face preview/layout/uploads thumbnails + Download + element text list);
  gated on canvas_faces.length (non-canvas unchanged); downloadImage blob util; adminApi
  types match backend field-for-field. Test uses vi.mock convention; findAllByText('Cap')
  fix legit (pre-existing dup). 2 tests, tsc clean. MINOR (final triage): downloadImage
  no res.ok check (brief-inherited); "Upload N" label vs download_name numbering can
  diverge if an image lacks resolvable url (cosmetic).

Task 10 base (before dispatch): faea439
Task 10: complete (verification only, no commit). Backend full suite 970; frontend
  targeted 25 (canvasStore 3, store/canvasStore 13, SessionDetailView 2, surfaceDirective 7);
  tsc exit 0; npm run build OK (pre-existing chunk-size warning only).

=== ALL 10 TASKS COMPLETE. Backend 970, frontend targeted 25, tsc+build clean. HEAD faea439 ===
Merge-base with master: a7f5100195a159f15f531ca25c218fbe93ce8627

FINAL WHOLE-BRANCH REVIEW (opus): READY TO MERGE — Yes. No Critical/Important.
  Verified: bug fixed + directly tested; data path coherent (asset_path↔assetPath
  consistent across every boundary); v1/non-canvas byte-identical; no raw signed URLs
  to browser; backward-compatible (additive, no migration).
FIX WAVE (commit faea439..18c75f8): downloadImage res.ok check; admin numbers only
  resolvable images (label==download_name); +test pinning no-leak (_resolve_element_media
  proxies expired signed URL via /media, never raw); +test _canvas_view_images skip branch;
  +frontend downloadImage.test. Covering suites green.
REMAINING (Minor/ticket, non-blocking):
  - http-passthrough latent gap if signed-URL format ever changes buckets (defensive guard).
  - (pre-existing) C6.2 back-decoration-on-no-angle skip is correct, noted.
NOT MINE (left uncommitted, user's in-progress edits): docker-compose.yml +
  docker-compose.prod.yml (env_file: .env on frontend). progress.md = scratch ledger.
=== FEATURE COMPLETE — READY TO MERGE (HEAD 18c75f8) ===
