# MadHats AI Design Studio — Project Memory

> This file is the single source of truth for all AI agents working on this project.
> Read it fully before starting any task. Update it when decisions change.

---

## 1. What This Is

An AI Design Studio MVP for **MadHats** (madhats.com.au) — an Australian custom headwear and printing company on Shopify. The product lets customers:

- **Describe it, see it (Flow A):** type or speak a design idea → AI generates an on-cap mockup
- **Photo-to-product (Flow B):** upload a logo/artwork → AI composites it onto the chosen cap
- **Worn / in-context (Flow C):** show the designed cap on a generic model or in a lifestyle scene

The Studio sits alongside (not replacing) InkyBay, MadHats' current product personaliser.

---

## 2. Hard Constraints — Never Violate

- **Composite onto real product reference photos.** Every generation call passes the real product reference image as conditioning input. Never generate a cap shape from scratch.
- **No customer face uploads.** "Worn" mode uses a generic model only. No end-user photo/face upload flow.
- **InkyBay stays live.** Do not touch, break, or replace InkyBay in any way.
- **Models are swappable via config (env vars).** Zero code change required to swap image generation models. All model IDs live in environment variables.
- **Human-in-the-loop.** Generated concepts are previews. The MadHats design team approves before anything becomes production artwork.
- **No secrets in code.** All API keys, secrets, and credentials go in environment variables. Never hardcode.
- **No PII in logs.** Customer name/email must never appear in application logs or error reports.
- **Coordinate Shopify storefront work** with the MadHats in-house Shopify developer. Do not modify the live storefront unilaterally.

---

## 3. Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 / FastAPI |
| Frontend | React 18 / Vite / Tailwind CSS 3 |
| Image gen — preview tier | Gemini Flash (model ID from env: GEMINI_PREVIEW_MODEL) |
| Image gen — final tier | Gemini Pro (model ID from env: GEMINI_FINAL_MODEL) |
| Image gen — photoreal / A-B | fal.ai / FLUX (model ID from env: FAL_PHOTOREAL_MODEL) |
| Database | **Supabase (Postgres 17)** — local stack via Supabase CLI for dev |
| Object storage | **Supabase Storage** (private bucket `madhats-assets`, signed URLs) |
| Hosting | Railway (backend + frontend as separate services) |
| State management | Zustand |
| DB access | **supabase-py** (service-role client); SQL migrations in `backend/supabase/migrations/` (no SQLAlchemy/Alembic) |
| Conversation LLM | Claude Haiku (model ID from env: `CLAUDE_HAIKU_MODEL`) |
| Observability | Sentry + structlog |
| Local dev | `supabase start` (Postgres + Storage + Studio) + uvicorn; Docker Compose for full stack |
| Package manager (backend) | pip / pyproject.toml |
| Package manager (frontend) | npm |

---

## 3b. Multi-Tenancy (built — pooled / shared-schema)

The system serves **multiple Shopify stores** (10+) from one backend + one Supabase DB.

- **Model:** pooled multi-tenancy. A `stores` table holds one row per storefront; tenant-scoped tables (`product_references`, `design_sessions`, and everything downstream via the session) carry `store_id`.
- **Tenant routing:** each store's widget sends its **publishable** key as the `X-Store-Key` header. `app/api/deps.py:require_store` resolves it to a store. `/products` and `/sessions` are tenant-scoped; downstream routes inherit `store_id` from the session.
- **Per-store config (in `stores` row):** persona name/avatar/greeting, brand (logo/colours/watermark), `allowed_origins`, `sales_notification_email`, `shopify_domain`.
- **Shared (env vars):** all provider API keys (Gemini/Anthropic/Resend) — never per-store, never in the DB.
- **Onboarding a store:** `POST /admin/stores` (auto-generates `public_key`) → `POST /admin/stores/{id}/sync` pulls that store's `products.json` into `product_references` (`app/services/catalogue_sync.py`).
- **Known gaps:** CORS is global and currently **open to all origins** — `ALLOWED_ORIGINS` defaults to `*`, which `main.py:build_cors_kwargs` serves via `allow_origin_regex=".*"` (reflects the request Origin, since a literal `*` is illegal with `allow_credentials=True`); set a comma-separated list to lock it down (per-store CORS still not implemented). `/products` returns PostgREST's default 1000-row cap (large catalogues need pagination).

---

## 4. Repository Structure

```
madhats-aidesign/
  CLAUDE.md                    ← you are here
  .claude/
    settings.json              ← project Claude Code permissions + hooks
    agents/                    ← subagent role definitions
  .env.example                 ← committed; documents all env vars
  .gitignore
  docker-compose.yml           ← local dev: backend + frontend (Supabase via `supabase start`)
  railway.toml                 ← Railway deployment config
  backend/                     ← FastAPI service
    supabase/                  ← config.toml, migrations/, seed.sql (local Supabase stack)
  frontend/                    ← React/Vite service
  docs/
    superpowers/
      specs/                   ← design specs
      plans/                   ← implementation plans
```

---

## 5. Key Abstractions

### ImageProvider (backend/app/services/image_provider.py)

The single interface for all image generation. Never call a model API directly from a route — always go through this.

```python
class ImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,           # real product photo — always required
        uploaded_asset_url: str | None,      # customer logo/artwork, if any
        params: GenerationParams,
    ) -> GenerationResult:
        ...
```

Active adapter per tier is selected by env vars:
- `IMAGE_PROVIDER_PREVIEW` → `gemini_flash` | `fal_flux` | `stub`
- `IMAGE_PROVIDER_FINAL` → `gemini_pro` | `fal_flux` | `stub`
- `IMAGE_PROVIDER_PHOTOREAL` → `fal_flux` | `gemini_pro` | `stub`

### PromptBuilder (backend/app/services/prompt_builder.py)

Assembles the cap-specific prompt from raw user input. Handles:
- Placement zone (front panel, side, back, under-brim)
- Decoration style (embroidery look vs print look)
- Cap shape/style description
- User's design description or uploaded asset context

### Data Models

```
DesignSession       — one per user design session (has share token)
Generation          — one per image generated (cost + latency logged here)
GenerationLog       — append-only audit row per provider call (prompt, image refs, params, raw response); one per attempt
ApprovalSubmission  — created when user clicks "Request This Concept"
ProductReference    — cap catalogue entry (stub data for prototype; Shopify sync for MVP)
Lead                — captured customer contact + email-verification + preview/quote delivery flags
```

---

## 6. Three Flows

**Flow A — Describe it, see it**
User picks product → types (or speaks) design description → preview generation → iterate → request concept

**Flow B — Photo-to-product**
User picks product → uploads logo/artwork → preview generation (compositing) → iterate → request concept

**Flow C — Worn / in context**
After Flow A or B, user triggers "worn" rendering → generic model wearing the designed cap → shown as secondary preview

---

## 7. Feature Tiers

**Core (prototype):** F1–F10
- Product picker (stub catalogue), text prompt, preview generation, logo upload, live preview surface, ImageProvider abstraction, concept submission, approval queue, session persistence, cost logging

**Standard (full MVP):** F11–F20
- Voice input, worn/in-context (Flow C), final-tier 2K generation, caching, rate limiting, input moderation, describe-first path, Shopify catalogue sync, mobile-responsive, observability

---

## 8. Security Rules

All agents must follow these before writing any endpoint, adapter, or file handler:

1. Secrets via env vars only — `settings.py` reads them via pydantic-settings
2. Uploaded files: validate MIME type + magic bytes + size limit before any processing
3. All stored images accessed via signed URLs (TTL = `SIGNED_URL_TTL` env var) — bucket never public
4. Rate limit all generation endpoints: `RATE_LIMIT_RPM` requests/minute per session/IP
5. Input moderation check before every model call
6. CORS locked to `ALLOWED_ORIGINS` env var
7. `/admin/*` routes gated by `X-Admin-Secret: <ADMIN_SECRET>` header
8. Alembic migrations run on deploy — never in application startup
9. ORM only for DB queries — no raw string SQL
10. No PII (customer name/email/notes) in logs or Sentry breadcrumbs

---

## 9. Environment Variables

See `.env.example` for the full list. Key groups:
- `GEMINI_API_KEY`, `FAL_API_KEY` — model API keys
- `IMAGE_PROVIDER_PREVIEW/FINAL/PHOTOREAL` — adapter routing
- `GEMINI_PREVIEW_MODEL`, `GEMINI_FINAL_MODEL`, `FAL_PHOTOREAL_MODEL` — model IDs (never hardcode)
- `R2_*` — Cloudflare R2 storage
- `DATABASE_URL` — Postgres connection string
- `ADMIN_SECRET` — gates `/admin/*` routes
- `RATE_LIMIT_RPM` — generation rate limit
- `SIGNED_URL_TTL` — image URL TTL in seconds
- `ALLOWED_ORIGINS` — comma-separated CORS origins
- `SENTRY_DSN` — optional error tracking

---

## 10. Agent / Subagent Map

When working as an orchestrator, dispatch subagents per this map:

| Agent | Scope | Owns |
|---|---|---|
| **Orchestrator** | Full repo | CLAUDE.md, docs/, top-level config, plan tracking |
| **Backend** | `backend/` | FastAPI routes, services, models, tests |
| **Frontend** | `frontend/` | React components, hooks, store, Tailwind, tests |
| **Infra** | Docker, Railway, env | docker-compose.yml, Dockerfiles, railway.toml, .env.example |
| **QA** | `tests/`, acceptance | Runs full test suite, checks acceptance criteria, flags regressions |

Each subagent should:
1. Read CLAUDE.md before starting any task
2. Check the implementation plan for their assigned task
3. Follow the hard constraints in Section 2
4. Follow security rules in Section 8
5. Write failing tests before implementing (TDD)
6. Commit after each completed task

---

## 11. Acceptance Criteria (Milestone 1 — Prototype)

- [ ] `docker compose up` starts backend + frontend + postgres + localstack cleanly
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] `GET /products` returns at least 5 stub products with correct shape
- [ ] Product picker renders blank cap silhouettes per style; colourway swatches selectable
- [ ] Studio canvas: describe tab + upload tab switch correctly; placement zone + decoration style selectable
- [ ] `POST /generate/preview` returns an image URL (Gemini Flash wired to real API; other adapters may stub)
- [ ] Preview panel shows shimmer during generation; displays image on success
- [ ] `POST /submissions` creates an approval record; `GET /submissions` requires X-Admin-Secret
- [ ] Session saved to Postgres; shareable token in response; `GET /sessions/{token}` retrieves session
- [ ] All generated image URLs are signed (not public bucket URLs)
- [ ] Rate limiting active on generation routes
- [ ] CORS, admin auth gate, and signed URLs confirmed working
- [ ] Sentry receiving events from both backend and frontend

---

## 12. Open Decisions (Confirm During Discovery)

- Gemini model IDs for preview and final tiers — verify against live Google API docs at implementation time; set in env vars
- Curated initial product subset — which 5–10 top-selling styles/colours launch first (confirm with MadHats)
- Shopify field-schema mapping — with the in-house Shopify developer (Standard tier)
- Approval queue format — internal dashboard (this build) vs. email notification (confirm with MadHats team)
- Asset/image retention policy — confirm with client before production launch
- Storefront embedding method — with the in-house Shopify developer (post-prototype)
- Voice input (STT) — Whisper vs. Deepgram vs. Gemini audio (Standard tier decision)

---

## 13. Quick Reference — Common Commands

> **How this dev runs the stack:** **both** `backend` and `frontend` run in Docker
> via `docker compose up` (see `docker-compose.yml`) — NOT bare `uvicorn`/`npm run
> dev` on the host. Backend → `http://localhost:8000`, frontend (Vite dev + HMR) →
> `http://localhost:5173`. Supabase runs on the **host** via `npx supabase start`;
> the backend container reaches it at `host.docker.internal:54321`.
>
> - **`.env` changes** (backend): read only at container start. A running `--reload`
>   worker does NOT pick up new env vars — recreate: `docker compose up -d
>   --force-recreate backend` (or down/up).
> - **New dependencies** (the gotcha): the frontend mounts an **anonymous volume at
>   `/app/node_modules`** (compose line ~30) so the container keeps its own Linux
>   deps. Installing a package on the **host** (`npm install x`) updates
>   `package.json` but NOT the container's `node_modules` → Vite fails with
>   `Failed to resolve import "x"`. Fix: install **inside** the container, then
>   restart it so Vite re-optimizes:
>   `docker compose exec frontend npm install` → `docker compose restart frontend`.
>   Same idea for backend Python deps: rebuild the image (`docker compose build
>   backend`) or `pip install` inside the running container.

```bash
# Local Supabase stack (Postgres + Storage + Studio) — Docker must be running
cd backend
npx supabase start         # boots stack, applies migrations + seed.sql (real catalogue)
npx supabase status        # show local URLs/keys
npx supabase stop          # shut down
npx supabase db reset      # wipe + re-apply migrations + seed
# Studio: http://localhost:54323   Mailpit (emails): http://localhost:54324

# Backend (FastAPI) — reads repo-root .env
cd backend
python -m venv .venv && .venv/Scripts/activate   # source .venv/bin/activate on *nix
pip install -e ".[dev]"
uvicorn app.main:app --reload                    # http://localhost:8000/docs
pytest -q                                        # tests (no Alembic — SQL migrations only)

# Frontend (React/Vite — Ricardo chatbot) — runs in the `frontend` container via
# `docker compose up`. Host `npm run dev` also works, but new deps must be installed
# INSIDE the container (see the node_modules-volume gotcha in the callout above):
docker compose exec frontend npm install <pkg>   # add a dep to the running container
docker compose restart frontend                  # Vite re-optimizes on restart
# Host-side (build/tests only — node_modules is per-platform):
cd frontend
npm run build
npx vitest run                                   # tests (npm test = watch mode, hangs)
```

**Local default store key (X-Store-Key):** `mh_pk_madhats_local`.
Onboard another store: `POST /admin/stores` → `POST /admin/stores/{id}/sync`.

### Current implementation state
- Frontend is the **Ricardo chatbot** (`frontend/src/components/ChatPanel`), backend-driven via `data.options`/`continuable`; the old mock studio screens are retired. Entry via `?product_id=…` (Shopify widget) or a dev product picker.
- Conversation engine works **with no Anthropic key** (canned replies + heuristics) and uses real Haiku when `ANTHROPIC_API_KEY` is set.
- Image gen uses **Gemini image models** (`gemini-2.5-flash-image` preview / `gemini-3-pro-image` final) when `IMAGE_PROVIDER_PREVIEW=gemini_flash`; `stub` returns a placeholder. Requires Gemini quota/billing. The prompt is **fidelity-locked** (`prompt_builder.py` emits enumerated imperative instructions from the full extracted design intent — colours/text/imagery/style — not a soft paragraph) so the generated cap stays identical to the reference photo; the generation cache never serves a stub placeholder.
- **Decoupled generation + gated delivery** (`services/delivery.py`, `api/routes/generate.py`, `services/leads.py`): image generation runs async in the background; the emailed preview is sent only when the lead's email is **verified** AND a generation is **complete with a real image**. Transient model failures (e.g. Gemini 429/quota) are retried; on final failure ops is alerted and the customer never sees an error. `POST /admin/deliveries/backfill` is a self-heal sweep for designs that finished after verification or whose send failed. The preview image is inlined as a CID attachment so it renders in the inbox. **Stalled-render watchdog** (`generate.reap_stuck_generations`, `POST /admin/generations/reap-stuck`): the provider call has no timeout, so a hung Gemini connection could pin a job at `pending` forever (never produced → never delivered). The watchdog marks jobs stuck past `?stuck_minutes=` (default 8) as `failed` and **re-enqueues a fresh render** (bounded to `MAX_STALL_RETRIES`=2 per session via a `stalled:`-prefixed error tag, then ops-alerts) so the design still gets produced + delivered. Both self-heal endpoints (`reap-stuck` + `deliveries/backfill`) are driven by a **`watchdog` compose sidecar** (`docker-compose*.yml`: a `curlimages/curl` loop hitting them every 180s over the compose network with `X-Admin-Secret`).
- **Request-a-Quote flow** (`api/routes/quote.py`, `services/leads.py` quote-token helpers, `api/routes/admin_leads.py`): the preview email's "request a quote" CTA links to a signed, server-rendered page (`GET /quote/{token}`) where the customer confirms their design (editable quantity + optional note) and optionally leaves a phone number + phone-notify consent. Submitting (`POST /quote/{token}`) updates `collected.quantity`, tags the lead (`quote_confirmed`, `quote_confirmed_at`, `notify_by_phone`, `quote_note`), and sends a one-time "customer confirmed" sales email. Confirmed leads surface via `GET /admin/quote-requests` (X-Admin-Secret). The auto-notify-at-delivery behaviour (`quote_request_sent`) is unchanged — this is a second, richer signal.
- **Per-call audit log** (`services/generation_logger.py`, append-only `generation_logs` table): every provider call logs inputs (full prompt, reference/logo image refs, params) before and outputs (response meta + full raw response) after — one row per attempt, including retries.
- **Admin/ops routes** (`X-Admin-Secret`): `GET /admin/prompt-preview/{session_id}` (exact prompt Gemini would receive), `POST /admin/deliveries/backfill` (delivery self-heal), plus store onboarding/sync.
- **Frontend:** email is captured **inline in the chat** (the redundant contact form is gone).
- **Smarter Studio conversation:** the engine is now **interpreter-first** — out-of-order answers, side-questions, "revise X", and chit-chat are handled via an LLM interpreter, while the deterministic state machine still owns routing and goal-leads the conversation back on track (no-advance on unmet fields), routed via a goal planner (`services/conversation/goal_planner.py`). Before generation, the customer is gathered through a **per-element deep-dive loop**: `ASK_MORE_ELEMENTS` offers to add a typed element — text, a graphic, a logo, or a note for the team — or finish; each accepted element then goes through `ELEMENT_DEEPDIVE`, which walks its own attribute sequence (`services/conversation/element_planner.py: ATTRIBUTE_ORDER`) — e.g. text asks content/font/size/colour/style then its own placement (zone + position); a logo asks remove-background/size/placement; every non-content attribute is deferrable ("you choose" etc. via `DEFER_WORDS`) so the designer's team decides. **Deep-dive extraction is context-aware** (regression fix): the attribute-extraction loop only writes the attribute currently being asked or one still unset — a later answer can never clobber an already-captured attribute (previously a placement reply like "Back" overwrote a text element's content). `extract_element_attributes(el_type, message, ask_for=…)` passes the asked attribute to the model so a short answer is read as THAT attribute (not greedily inferred as `content`), and `generate_reply(..., element=…)` gives the model the element's type + content so a text element's questions say "your text 'satish'" (not "your logo") and ask the *text* colour, not the cap's. Placement is now **per-element** (the old single global `ASK_PLACEMENT_ZONE`/`ASK_PLACEMENT_POSITION` pair is retired from the gather loop) giving InkyBay-parity capture of multiple decorations in one session. `prompt_builder.py` enumerates every completed element in full to the image model — not just the first description. The frontend shows the on-screen design (main image + product-angle + regeneration thumbnails) gated at email verification, plus a "Step X of N" progress indicator that stays steady across the deep-dive. Once the customer verifies their email, the state machine auto-advances straight through the delivery states to `OFFER_REFINE` in one turn — a single collapsed message ("Your email's verified — your design's in your inbox and on-screen now.") confirms verification + delivery and asks the tweak question, instead of three redundant "your design is on its way" Continue taps. Customers can regenerate-with-changes up to admin-configurable per-session/per-day caps (`REGEN_EDITS_PER_SESSION`, `DESIGNS_PER_CUSTOMER_PER_DAY`), backed by a global `app_settings` table and an admin Settings view; the final design is emailed once on completion (deduped). The **email is now captured early** — right after the design source (logo upload / description), framed as "saves your progress", via a non-blocking `SAVE_PROGRESS_EMAIL` state (verification link sent as before; the chat continues into the deep-dive rather than waiting). **Pin-point placement is hidden** for now — the `ASK_PIN_ANNOTATION`/`PIN_ANNOTATE_MODE` states, `PinAnnotator` component, and `/pins` route are retained but unreached (reversible). Because `GENERATING` no longer asks for the email, `advance_after_generation` (`GET /chat/{id}/generation-advance`, mirrors the regeneration poll) moves `GENERATING` forward once generation settles — to `VERIFY_EMAIL`, or collapsed to `OFFER_REFINE` if already verified, or to the `ASK_EMAIL` fallback if no email was captured.
- **Blank-hat design flow (custom hat from a blank canvas):** a second flow alongside "customise", selected by entry point — customise = Shopify "customise this hat" → `?product_id=`; blank = `?mode=blank` → a `BlankHatPicker` that lists an admin-managed **`hat_types`** catalogue and lets the customer pick a hat type + colour. Sessions carry `flow_mode` (`customise`|`blank`, column on `design_sessions`); blank sessions reuse the `product_ref` jsonb to carry the blank reference (front angle = `reference_image_url`, all 4 blanks = `view_images`, chosen colour). The conversation spine is shared; blank mode adds two `flow_mode`-gated states — `ASK_HAT_COLOUR` (fallback only) and `COMPOSITE_PREVIEW` (a backend-composited flat 4-angle preview, `services/composite.py` via Pillow: luminance-multiply tint + per-zone overlay, `POST /composite/{session_id}`, shown before the AI render for confirm/tweak). Generation AI-renders only the **front hero** (blank-mode `IMAGE_GEN_PROMPT_BLANK` keeps geometry locked but permits recolouring the body to the chosen colour); the other 3 angles come from the composite. Admin manage hat types via `/admin/hat-types` (CRUD + per-angle uploads, store-scoped: require `X-Admin-Secret` **and** `X-Store-Key`) and the admin **Hat Types** view (store selector → `public_key` as `X-Store-Key`); a hat type can only go `active` once all 4 blank angles are uploaded. Customer catalogue: `GET /hat-types` (active only, proxied angle URLs). The customise flow is untouched (every blank branch is `flow_mode`-gated).
- **Hat Types admin — CMS-style UX** (`frontend/src/admin/views/HatTypesView.tsx` = list, `HatTypeWizard.tsx` = create, `HatTypeEditView.tsx` = edit; shared field components in `views/hatTypes/`): the old one-screen name+slug form is replaced by a proper flow. **List** = store dropdown + search + rows with front-angle **thumbnail**, status pill (`Active`/`Draft`/`Needs images`), colour/angle counts, Edit link, inline-confirm Delete. **Create** = guided 5-step **wizard** (Basics→Angles→Colourways→Zones & decoration→Review/Activate); Basics-Next POSTs a resumable draft so later steps have an id; `slug` is auto-derived from the name (never shown). **Edit** = scrollable page with independently-saveable sections + an Active toggle (gated on all 4 angles). Colourways (name+hex swatch), placement zones, and decoration types are all editable (via `ColourwayEditor`/`ChipListEditor`); `pricing_slabs` deliberately not surfaced (unused downstream). Store selection persists across the three views via a `?store=<id>` query param. Admin thumbnails work because the admin API now returns **`view_images`** proxy URLs (`admin_hat_types.py` list + angle-upload; note `PATCH` does NOT return `view_images`, so the wizard/edit preserve local image state on save). Routes: `hat-types` / `hat-types/new` / `hat-types/:id`.
- **Canvas Design Studio (Phase 1 — react-konva, replaces the Q&A deep-dive):** entry via `?product_id=` (customise) or `?mode=blank`→`BlankHatPicker` now lands on the interactive **`DesignStudio`** (`frontend/src/components/DesignStudio/`, `SessionView 'canvas'`, `flow_mode='canvas'`) instead of the chat Q&A. The customer places **text** + **uploaded logos** on four draggable/resizable/rotatable **face tabs** (front/back/left/right, `canvasStore.ts` = single source of truth), switches cap colour, then **"See it rendered"** flattens each decorated face (`stage.toDataURL()` via `canvasFlatten.ts`; images loaded through a shared `imageCache.ts` and **preloaded before flatten** so face-switch exports aren't stale/blank — the rAF-only wait was insufficient) → uploads the PNGs as **layout-guide images** (`POST /sessions/{id}/canvas-layouts`, validated via `sniff_image_mime`) → `POST /sessions/{id}/canvas-finalize` converts the canvas into the **existing `collected["elements"]` shape** (`services/canvas_describe.py`) + captures the lead (`leads.capture_lead_and_verify`) + sets state `generating`. Generation reuses the existing pipeline and **AI-renders EVERY decorated face** photorealistically (`_run_generation` canvas branch uses `prompt_builder.render_views` = front hero + every face carrying decoration): each face renders with its real product-angle photo (conditioning FIRST image) + that face's flattened canvas as a `layout_guide_url` image (`ImageProvider.generate`/`gemini_base.py`) + its per-face scoped description (`build_view_prompt`). The old behaviour — front-only AI render, non-front faces reusing their flat canvas PNG — is retired (the flat-PNG reuse splice is gone). The extracted description is coarse-but-complete: `canvas_describe` enumerates each component's identity/styling + coarse zone (curved text → `style:"curved"`; no raw pixel size — exact placement/size is owned by the layout-guide image). Trade-off: non-front faces are now subject to model variability vs the old pixel-exact flat mock; the real photo + layout guide keep them consistent. (Data-quality follow-up: a synced product with only a front image has `_map_views` alias back/side → front, so a back decoration renders onto the front angle — ensure canvas-enabled synced products carry real per-angle photos; blank sessions already carry all 4.) Spec/plan: `docs/superpowers/{specs,plans}/2026-07-13-canvas-photoreal-multiangle*`. Post-design it **hands off to the existing ChatPanel** (`chatStore.hydrate([], 'generating', {})` → verify-email → gated delivery → refine). **Layout guide = decorations only on a neutral-grey card, NOT the full mock** (bug fix): `canvasFlatten.flattenStage` hides the product photo + colour tint (`name="flatten-hide"`) during export, and `gemini_base._flatten_guide_on_grey` composites the transparent guide onto mid-grey before sending. Previously the guide baked in the product background, so the image model just echoed the flat canvas back ("it exported the canvas") instead of re-rendering; and a fully-transparent guide dropped **white** decorations when the model flattened alpha onto white. Grey keeps light+dark decorations visible for placement without looking like a finished product. Relatedly, `canvas_describe` now always records a text element's colour (**default white** — the canvas renders unset text white via `nodes.tsx: el.colour ?? '#ffffff'`; common hexes map to plain names) so a white text element is described (`in white`) and never dropped. New column `design_sessions.canvas_design jsonb`. **Blank-hat colour** works in the canvas: `BlankHatPicker`→`startCanvasBlankSession` seeds `sessionStore.blankColourways` from the hat type; `DesignStudio` shows the swatch row; `CanvasStage` multiply-tints the stage so flattened faces show the colour; the chosen `canvas_design.colourway` is mapped to `collected["hat_colour"]` at finalize and blank-canvas sessions (marked `collected["canvas_blank"]`) use `IMAGE_GEN_PROMPT_BLANK` to recolour the front hero (customise sessions set no colourway → no swatch/tint, colour stays locked to the product photo). AI chat helper + smart suggestions (Phase 3) are deferred. Spec/plan: `docs/superpowers/{specs,plans}/2026-07-13-canvas-design-studio-*`. Verified end-to-end in-browser (customise flow: flatten→layouts→finalize→handoff→VERIFY_EMAIL, no `toDataURL` taint; blank-flow taint-safety confirmed — `/media` streams bytes with CORS ACAO). The customise/blank chat Q&A code + states are retained (bypassed for canvas sessions), not deleted.
- **Canvas Studio UI polish** (all verified in-browser): the face navigator is a **left rail of live thumbnails** (`FaceThumbnails.tsx` renders a static mini Konva stage per face — angle photo + colour tint + placed elements at scale — updating as you edit, with a count badge), 3-column layout (thumbs / canvas / tools). **Curved text** via a per-element `curve` prop → Konva `TextPath` bezier arc + a Curve slider. **Fonts**: curated ~18 Google families (`lib/fonts.ts` + one `<link>`) + web-safe, grouped/previewed in the dropdown; `TextNode` awaits the family (CSS Font Loading API) before redraw and `doRender` awaits `document.fonts.ready` before flatten so exports use the real face. **Uploaded/graphic images insert at natural aspect** (`addImage(url, aspect)`). "Upload logo" → "Upload image".
- **Graphics: Clipart (built-in shapes) + Company graphics (admin images).** The tool rail's **"Graphics"** button opens a tabbed **`GraphicsPicker`** modal:
  - **Clipart tab = built-in editable vector shapes** (client-side, NOT company-uploaded): rectangle, square, rounded, circle, oval, triangle, diamond, pentagon, hexagon, star, line, arrow, double-arrow. Adding one drops a `shape` element (`canvasStore` fields `shapeKind`/`fill`/`stroke`/`strokeWidth`/`filled`); `ShapeNode`/`ShapePrimitive` (in `nodes.tsx`) render the matching Konva primitive (`Rect`/`Ellipse`/`RegularPolygon`/`Star`/`Line`/`Arrow`), drag/resize/rotate + live in the face thumbnails. `SelectedToolbar` shape controls: **fill + border colour, border width, filled↔outline** (line/arrow = single colour + width). `canvas_describe` maps shapes → a described `graphic` ("filled blue rectangle") for generation; the flattened layout PNG carries the exact geometry/colour.
  - **Company tab = admin-uploaded images** (patterns/logos/graphics the store finds trending): store-scoped `graphics` table (`category='company'`, migration `20260713000003_graphics.sql`), raster in the private bucket served via the **`/media` proxy** (taint-safe on the canvas). Customer `GET /graphics?category=company` → click drops an aspect-preserved image element. Admin: `services/graphics.py`, `POST/GET/DELETE /admin/graphics` (`X-Admin-Secret` + `X-Store-Key`, logo-upload validation) + the admin **Graphics** view (`admin/views/GraphicsView.tsx`, Company-only: store selector + upload + inline-confirm delete). (The `graphics.category` check still allows `clipart` for future use, but the UI no longer uses it.)
  - Verified live end-to-end: shapes palette → add/recolour on canvas; admin-uploaded company graphic surfaces in the customer Company tab.
- **Real background removal (uploaded images) + freehand draw tool.**
  - **Background removal** — the `SelectedToolbar` "Remove background" toggle was previously **inert** (the `removeBg` flag was captured into `GenerationParams.remove_bg` but never applied — no matting lib, no prompt instruction, `ImageNode` never read it). It now runs **client-side WASM matting** (`@imgly/background-removal`, lazy-loaded via a dynamic `import()` in `frontend/src/lib/bgRemove.ts` → a separate `ort` async chunk, not the main bundle). Toggling ON mattes the image and **re-uploads the transparent PNG through `uploadLogo`** so it becomes both the on-canvas `assetUrl` (→ clean flattened layout guide) AND the session `uploaded_asset_path` (→ clean crisp 2nd image at generation); `originalAssetUrl` is stored so toggling OFF re-uploads and restores the original. `BgRemoveToggle` sub-component has a busy/failed state and never half-applies on error. **New-dep gotcha:** `@imgly/background-removal` must be installed **inside** the frontend container for dev (`docker compose exec frontend npm install` → restart), not only on the host. Deferred ticket: OFF-toggle `fetch(originalAssetUrl)` can fail if that URL is a TTL-signed URL that expired mid-session.
  - **Draw tool** — a freehand pen. `canvasStore` adds a `drawing` element type (`points` = normalised x,y pairs; reuses `stroke`/`strokeWidth` stored **normalised**, ×stageW at render) + draw-mode state (`drawMode`/`drawColour`/`drawWidth` + setters + `addDrawing`). `CanvasStage` handles pointer down→move→up while `drawMode` (elements go `listening={!drawMode}` so events reach the stage; `e.evt.preventDefault()` gated to draw-mode so mobile `touchmove` doesn't scroll; in-progress stroke cleared on `activeFace` change; commit at ≥2 points). **On commit `addDrawing` exits draw mode** (`drawMode: false`) and selects the new element, so the stroke is immediately selectable/movable — otherwise the still-listening-disabled layer swallowed the click and the user couldn't select what they'd just drawn (bug fix). To draw another stroke, re-tap Draw. `DrawingNode` (`nodes.tsx`) = a Konva `Line` in a draggable `Group` — **move + rotate + delete** (rotate-only `Transformer`: `rotateEnabled resizeEnabled={false} enabledAnchors={[]}`; `onTransformEnd` persists x/y/rotation since Konva rotates around the stroke's bbox centre by adjusting all three). `ToolRail` has a **✎ Draw** toggle + colour picker + thickness slider; `SelectedToolbar` has a `drawing` stroke-colour control; `FaceThumbnails` renders strokes. `canvas_describe` maps a drawing → a described `graphic` ("a hand-drawn line in {colour}") so it flows through the existing multi-angle pipeline (`element_view`/`render_views`/`build_view_prompt`); the flattened layout PNG carries exact geometry. Deferred ticket: no window-level `mouseup` fallback (releasing the pointer off-stage discards the in-progress stroke). Spec/plan: `docs/superpowers/{specs,plans}/2026-07-13-canvas-bgremove-drawtool*`.
- **Chat-gated canvas flow (intro Q&A → unlock canvas → decoration → notes → generate):** the canvas Design Studio is now *led* by the chat instead of opening immediately. A canvas session starts at `GREETING` (was `canvas_design`); the split-screen `CustomiseStudio` keeps the canvas **locked behind an overlay** while the chat runs a short intro — `ASK_NAME → SAVE_PROGRESS_EMAIL (email captured right after name; verification fires non-blocking) → ASK_PURPOSE → ASK_QUANTITY`. The canvas **unlocks only at state `canvas_design`** (`DesignStudioSurface` overlay: intro copy before, "finishing up" copy during the outro); the render button reads **"Done designing"** (`ToolRail`, `disabled` until unlocked). `ChatColumn` now **kicks off** the greeting on mount (guarded `!kickoffDone && messagesLen===0`; resumed/hydrated sessions never re-greet). "Done designing" → `canvas-finalize` no longer routes to `generating`; it sets `collected["canvas_finalized"]`, loads the store's active decoration types into `collected["decoration_options"]`, and advances to **`ASK_DECORATION`** (a multi-select of admin-managed decoration types with a **cost caveat when 2+** chosen — chips comma-join into `collected["decoration_types"]`, folded into `brief_notes`; first pick sets the `decoration_type` render-style bucket via exact comma-token match) → **`ASK_NOTES`** (free text or "No, generate", stored in `collected["notes"]`) → `GENERATING`. `CONFIRM_BRIEF` is skipped for `flow_mode=='canvas'` (the notes step is the pre-gen gate). Routing lives in a canvas branch of `goal_planner._canvas_next_goal` + `state_machine` (`CANVAS_DESIGN` rests until `canvas_finalized`; `ASK_DECORATION`/`ASK_NOTES` new states). **Decoration types are a new store-scoped table** (`decoration_types`, migration `20260713000004`) with `services/decoration_types.py`, customer `GET /decoration-types` (active only), admin CRUD `GET/POST/DELETE /admin/decoration-types` (`X-Admin-Secret` + `X-Store-Key`, delete is store-scoped) + the admin **Decorations** view (`admin/views/DecorationTypesView.tsx`). Both entry points (customise `?product_id=` and blank `?mode=blank`) use the same intro/outro; blank keeps its existing colour-swatch + 4-face tooling (per-section colour deferred). Email is still captured in-chat (intro) and gated delivery is unchanged; the non-canvas customise/blank Q&A conversation is untouched (every branch is `flow_mode=='canvas'`-gated). Spec/plan: `docs/superpowers/{specs,plans}/2026-07-13-chat-gated-canvas-flow*`.
- **Per-store branding & themed emails:** each store configures its own **logo**, **primary colour**, **header bg/text**, and a **≤5-item external main menu** (no sub-menus), applied to the customer studio and to the customer-facing emails — all through the existing global admin console (single `X-Admin-Secret` + store selector; API shaped so a future per-store-owner login can reuse it). Stored in the existing `stores.brand` jsonb (`{logo_url, primary_colour, header_bg, header_text, watermark_asset_url, menu_items:[{label,url}]}`); one comment-only migration `20260714000002`. **Backend:** pure `services/branding.py` (`validate_brand` = source-of-truth for colour-hex + menu rules [≤5, `http(s)`-only, label non-empty ≤40]; `public_brand` = allow-listed customer subset with the logo as a `/media` proxy URL — never leaks `watermark_asset_url`/secrets); customer `GET /storefront` (via `require_store`); admin `GET`/`PATCH /admin/stores/{id}` (id-in-path + `require_admin`, **PATCH read-merges brand so a colour/menu edit never wipes the logo**) + `POST /admin/stores/{id}/logo` (magic-byte-validated, private bucket, merge-not-clobber). **Emails** (`prompts.py`/`email.py`/`delivery.py`/`leads.py`): the preview/delivery email is themed (header bar + buttons use `primary_colour`, logo inlined as a **CID attachment**, store name in header/footer) and verification + resume emails render a branded HTML shell (`BRANDED_EMAIL_HTML`); every customer email path resolves the session's store (preview via `delivery`, verification via `capture_lead_and_verify` **and** the `/leads/verify/send` resend route, resume via `_maybe_send_resume_email`) and falls back to MadHats defaults crash-safely. **Unconfigured stores are byte-identical to before** (the preview email default path was proven old==new). **Frontend:** Tailwind `accent`/`accentHover` promoted to CSS vars with MadHats fallbacks (`var(--brand-primary, #FF5C00)` — every `text-accent`/`bg-accent` becomes themeable for free); `store/brandStore.ts` fetches `/storefront` once on mount and sets `--brand-primary`/`-hover`(derived)/`--brand-header-bg`/`--brand-header-text` on `:root` (init is idempotent + error-swallowing, not run on `/admin`); `components/StoreHeader.tsx` renders the logo (or store-name fallback) + menu links (`target="_blank" rel="noopener noreferrer"`) in `CustomiseStudio`; admin **Branding** view (`admin/views/BrandingView.tsx`, nav "Branding", `?store=` param) with a live preview, logo upload, colour pickers, and a max-5 menu editor whose client `validate()` mirrors the server. Deferred tickets: logo CID always declared `image/png` (mime not carried — clients sniff); `/storefront` brand lags ≤60s after an admin save (stores cache TTL, no bust-on-write); preview-email button box-shadow/edit-button text stay orange under a themed primary (cosmetic); `VERIFICATION`/`RESUME_EMAIL_BODY` copy still says "MadHats" in the body text while the header is themed. Spec/plan: `docs/superpowers/{specs,plans}/2026-07-14-per-store-branding*`.
- **Step-by-step canvas orchestrator (v2), parallel to the chat-gated flow above:** a second, more directive canvas conversation engine — `backend/app/services/conversation/{state_machine_v2,orchestrator_v2}.py` — selected only when env flag `CANVAS_ORCHESTRATOR_V2` (`settings.canvas_orchestrator_v2`, default **off**) is set **and** the session's `flow_mode == "canvas"`, routed per-turn in `chat.py::_dispatch` (flag-off or non-canvas → the existing v1 `orchestrator.py`, byte-identical, untouched — v1 stays the retained backup). v2 owns a linear front half: `ASK_NAME` → the admin-configured intro (`SHOW_INTRO`, text from `stores.brand.canvas_intro`, edited via the admin **Branding** view, `V2_DEFAULT_INTRO` fallback) → a logo loop (`ASK_LOGO_PLACEMENT`→`LOGO_ADJUST`→`ASK_ANOTHER_LOGO`, capped at `MAX_LOGOS`=4) → a text/shape loop (`ASK_ADD_DECOR`→`DECOR_ADJUST`→`ASK_ANYTHING_ELSE`) → `ASK_QUANTITY` → `ASK_EMAIL` (double opt-in, same as v1) → `ASK_PURPOSE` → `FINALIZE_CANVAS`, which hands off into the **existing shared tail** (`GENERATING` → verify → deliver → refine/quote/upsell) — any state not in v2's owned set (`state_machine_v2.V2_OWNED` — the single source of truth, also driving `canvas_directive`, so routing and the canvas UI can't disagree) delegates the turn straight to v1's `handle_message`, so a canvas session is never stranded post-design. Each v2 state drives the canvas directly via a `canvas` directive blob in the chat response (`state_machine_v2.canvas_directive`: `allowed_tools`/`target_face`/`auto_open`/`instructions`/`show_done`), consumed by `frontend/.../DesignStudio/Surface.tsx` to switch faces, gate `ToolRail` to the one tool in play, show the step's instruction callout, and (when `show_done`) render a Done button that **locks the just-placed element** (`canvasStore.lockPlaced()` — locks every still-unlocked element, called from `postDone()` before sending "done"; each step adds then locks, so "lock all unlocked" == "lock what was just placed"). The face-answer and tool-open are deliberately two separate turns (`ASK_LOGO_PLACEMENT` asks the face with the upload tool merely highlighted/enabled — `auto_open: null`; only `LOGO_ADJUST`, once the face is known, sets `auto_open: "upload"`) — conflating them into one turn was a shipped bug (the file dialog opened before the face was answered, so the logo landed on whatever face was already active). **Every v2-owned state emits a directive** — the tool steps hand over their one tool, every other owned step (intro, mid-design questions, wrap-up, finalize) returns `allowed_tools: []` to lock all tools explicitly; a `null` directive means "not a v2 turn", which makes the frontend fall back to v1's whole-rail gating + status strip (that fallback firing mid-design showed "Design locked in — finishing up" during the design loop). **Flag-flip caveat:** flipping `CANVAS_ORCHESTRATOR_V2` on strands any in-flight v1 canvas session sitting at `canvas_design` — it would skip the deco/notes outro v1 expects, since v2 never reaches that state. Spec/plan: `docs/superpowers/{specs,plans}/2026-07-15-step-by-step-canvas-orchestrator-v2*`.
- **v2 is registry-driven (2026-07-17).** The flow is declared once as data in
  `services/conversation/canvas_steps.py`: one `Step` per step holding its copy,
  chips (**label AND the fields that label means, in the same literal**), slots,
  `done_when`, `apply` effect, and canvas tool. `state_machine_v2` is a generic
  engine over it — routing is **first-unmet resolution** (`next_step` = the first
  step whose `done_when(collected)` is False), a pure function of `collected`,
  testable with plain dicts. **Adding a step = adding one record**; the eight
  parallel per-state switches are gone. Understanding is split: a **chip tap
  resolves deterministically** by exact label match (0 LLM calls — we generated
  the label and shipped it, so matching it back is an identity lookup), while
  **free text goes to Haiku** (`intent_extractor.interpret_turn_v2`) which fills
  *slots only and never names a state*; validation (`validate_fields`) drops
  anything outside `WRITABLE_SLOTS` so internal flags like `email_captured` can
  never be model-written. **There is no keyword fallback** — on `LLMUnavailable`
  the turn **stalls** (state unchanged, nothing guessed) and after 2 consecutive
  failures re-renders the chips to nudge a tap, so an outage degrades to a
  tap-through wizard rather than stranding a pre-email session. **Three steps are
  the exception** (`Step.direct_answer`): `ask_name`/`ask_email`/`ask_purpose`
  have no chips, so the chip-nudge escape hatch can never fire for them — on
  `LLMUnavailable` they resolve the answer deterministically from the raw
  message instead (name still guarded by `canvas_steps._plausible_name`, email
  via `leads_service.extract_email`) so a Haiku outage (or no
  `ANTHROPIC_API_KEY`) can't dead-end the funnel at step 1; every other step
  still stalls. Replies are **LLM ack + scripted copy + tool tip concatenated
  verbatim** (the tip never passes through a model) — `write_ack(persona,
  fields)` takes no raw customer message (its `fields` are already
  `_safe_collected`-stripped), which matters at `ask_email` where the raw
  message IS the email address and must never reach the model. Flexibility
  comes from **slot-filling, not routing**: a volunteered answer ("no thanks,
  and I need 50 caps") fills a later slot, and the router simply never asks
  that step. **Loops are slot-clearing** — the logo loop is `logos` +
  `pending_logo`, and `_apply_another_logo` re-seeds `pending_logo`/clears
  `another_logo` so the router walks back on its own; no back-edges,
  `MAX_LOGOS`=4. There is **no gate concept**: first-unmet already never
  returns a step after an unmet one, and `FINALIZE_CANVAS` is unreachable
  without `email_captured` because `ask_email` precedes it and only
  `_apply_email` sets that flag. **Known landmine:** `state_machine.is_negative`
  still matches by **substring** ("a**no**ther" contains "no") and **v1 still
  routes on it** — v2 no longer calls it (proven by
  `test_v2_e2e.py::test_v2_no_longer_uses_the_shared_keyword_matchers`, a guard
  test over `orchestrator_v2.py`'s source; the e2e walk in the same file drives
  the exact chip labels the UI ships, including "Yes, another logo", with the
  interpreter raising `LLMUnavailable` for the whole walk — proving the entire
  front half needs no model at all). Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-17-llm-assisted-canvas-orchestration*`.
- Tests: backend `pytest` 660 passing (`CANVAS_ORCHESTRATOR_V2=false pytest -q` — the repo-root `.env` default of `true` flips 3 unrelated tests red). Frontend: full `vitest run` is not reliably re-measurable in one pass on this Windows host (stalls — a known tinypool flake, see below); the Windows-stall-safe targeted subset (`canvasStoreLock`, `lockedNode`, `ToolRail`, `chatStoreCanvasDirective`, `surfaceDirective`, `brandingCanvasIntro`, admin `BrandingView`) is 26 passing. Last full-run figure on record: `vitest run` 221 passing (2 pre-existing `adminQuotes` failures, unrelated — missing Router context; on Windows an intermittent tinypool "Worker exited" flake can appear in the full run — rerun focused).
- Open ticket: add a partial index on `leads(email_verified, preview_email_sent, verified_at)` before lead volume grows (backfill/cron query).

---

## 13c. Deployment — Production

> Prod runs on a self-hosted box (Docker), **not** Railway. Backend + frontend
> are containers on the same public IP, different ports (backend `:8000`,
> frontend `:5173`), reached via `http://madhats.getaiconsult.com.au:<port>`
> (plain HTTP). Supabase is the hosted project (URL/keys in `.env`).

**Golden rule — the frontend API URL is a BUILD-TIME value.** Vite inlines every
`VITE_*` var into the JS bundle when it builds; a hosted frontend never reads a
runtime `.env`. So `VITE_API_BASE_URL` must be correct *when the image is built*.
Symptom of getting this wrong: the browser calls `http://localhost:8000` or a
stale dev IP (e.g. a Tailscale `100.103.149.17:8000`) — that value was baked in.

**Two ways the frontend can run:**

| | `docker-compose.yml` (dev) | `docker-compose.prod.yml` (prod) |
|---|---|---|
| Frontend | Vite dev server + HMR (`Dockerfile.dev`) | static build (`frontend/Dockerfile`, `serve -s dist`) |
| Host check | needs `ALLOWED_HOSTS` (set `*` behind a proxy) | **none** (static server doesn't host-check) |
| API URL | runtime env, re-bakeable on restart | **compiled in** — rebuild to change |
| Backend | `uvicorn --reload` + source bind-mount | image CMD (no reload), no mount |

**Recommended prod deploy (static build, one command):**
```bash
git pull
# project-root .env must have (prod values):
#   VITE_API_BASE_URL=http://madhats.getaiconsult.com.au:8000   # baked into the bundle
#   VITE_STORE_KEY=mh_pk_madhats_local
#   ALLOWED_ORIGINS=http://madhats.getaiconsult.com.au:5173     # backend CORS — MUST include the site origin
#   (+ SUPABASE_URL/keys, ADMIN_SECRET, provider keys …)
docker compose down                                            # stop dev stack if running
docker compose -f docker-compose.prod.yml up -d --build
# after ANY VITE_API_BASE_URL change, rebuild the frontend (it's compiled in):
docker compose -f docker-compose.prod.yml up -d --build frontend
```

**If instead running the dev stack in prod** (`docker-compose.yml`): set
`VITE_API_BASE_URL` in the **project-root `.env`** (NOT `frontend/.env` — the
compose `environment:` block overrides that), set `ALLOWED_HOSTS=*` (the Vite
dev server otherwise blocks the public Host header, esp. with a `:5173` port in
it), then `docker compose up -d --force-recreate frontend`. Env is only read at
container **start**, so always `--force-recreate`; hard-refresh the browser
(old bundle is cached).

**Gotchas checklist:**
- `.env*` is git-ignored and excluded from images (`frontend/.dockerignore`) — a
  local `frontend/.env` can never leak into a build.
- Wrong API host in the browser → rebuild frontend with the right
  `VITE_API_BASE_URL` (prod) or fix root `.env` + recreate (dev).
- CORS error after the page loads → backend `ALLOWED_ORIGINS` missing the
  frontend origin; fix `.env`, recreate backend.
- "Blocked request … host not allowed" → dev server only; set `ALLOWED_HOSTS=*`
  and recreate, or switch to the static prod build (no host check).

---

## 14. Design Assets

| Asset | URL |
|---|---|
| Full User Flow (FigJam) | https://www.figma.com/board/QPoAL5zXOw66ACgxrMNioF/MadHats-Chatbot-%E2%80%94-Full-User-Flow |
| Wireframes & Screens (Figma design) | https://www.figma.com/design/fFPXYD7eIJPSo47tUPjK2r/MadHats-AI-Design-Studio-%E2%80%94-Wireframes---Screens |
