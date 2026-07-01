# SDD Progress — products pagination + frontend wiring

Branch: master (continuing session work)
Local Supabase: running (API :54321). Backend venv: backend/.venv. Store key: mh_pk_madhats_local

## Tasks
- Task 1: Backend /products pagination (envelope + limit/offset) — IN PROGRESS
- Task 2: Frontend picker wired to backend (X-Store-Key + pagination) — pending

## Log

## Figma findings (2026-07-01)
- Wireframe file = Shopify Widget integration only (button variants, PDP placement, tracking URL: /start?product_id=&variant_id=&colour=&source=shopify-pdp). No chatbot visual screens.
- FigJam user flow = full Ricardo chatbot conversation; maps 1:1 to backend state machine.
- Decisions: replace mock studio with chatbot flow; entry = URL params + dev picker; reuse existing design system.
- Frontend plan written: docs/superpowers/plans/2026-07-01-frontend-chatbot-plan.md (Tasks 2-5).

## Task 1 (pagination) — commit 33f94d1 — REVIEW: changes needed
Fix (dispatch after Task 2 commits, serialize git):
- Service returns the clamped values it used (e.g. return (items, total, used_limit, used_offset)); route reflects them instead of recomputing max(1,min(...)).
- Relax route Query constraints (drop ge=1/ge=0) so service clamping is the real behavior (spec says clamp, not reject limit=0).
- Add a DB-path test: list_products(limit=999) with real rows asserts .range called with (0,199) i.e. clamped to 200 (not stub fallback path).
- Minor (defer to final review): trivial route-clamp assertion; get_product stub ignores store_id.

## Task 2 (frontend foundation) — IN PROGRESS (agent a1b3c956)

## Task 2 (frontend foundation) — commit 57d107c — REVIEW: changes needed
Fix (dispatch after Task 1 fix commits, serialize git):
- ApiProductPicker.handleSelect: surface startSession failures (set an error state shown in UI), not silent catch.
- sessionStore.bootstrapFromUrl: console.warn on failure (diagnose broken embed URLs).
- Parse variant_id/colour/source from URL in bootstrapFromUrl and stash on productRef/session (spec said read them).
- Minor (defer to final review): add X-Store-Key assertions to createSession/sendChat/getSession tests; extract loadProducts() to dedupe retry.

Task 1: COMPLETE (commits 33f94d1..0850355, review clean, 23 tests pass)

Task 2: COMPLETE (commits 57d107c..6b468d5, review clean after fix, 25 tests pass)

## Task 3a (backend): no-key conversation fallback + greeting handshake — IN PROGRESS
Enables /chat to run locally with empty ANTHROPIC_API_KEY (canned replies + heuristics).
## Task 3 (frontend): chatbot conversation UI — pending (after 3a)

Task 3a: COMPLETE (commit 2ef96ed + off-by-one fix 819d34a; 49 tests; no-key flow reaches `generating` with correct collected data)
Note for Task 3: statement state youth_referral still waits for a user tap → frontend should render statement-only states with a "Continue" affordance.

## Task 3 (frontend): chatbot conversation UI — IN PROGRESS

Task 3: COMPLETE (commit 4e6ba16 + continuable cross-cutting fix aa70e19; frontend 43 tests pass, backend 49; live flow verified)
## Task 4 (frontend): logo upload + pin-annotate in chat — IN PROGRESS

Task 4: COMPLETE (commit 1d74b71; logo upload + pin-annotate; 62 frontend tests)
Task 5: COMPLETE (commit <this>; generation preview + lead capture; 63 frontend tests, build clean)
NOTE: backend app/ core + infra + docs still UNTRACKED — commit as foundation next.
