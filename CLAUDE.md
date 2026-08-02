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
- **Onboarding a store:** `POST /admin/stores` (auto-generates `public_key`) → `POST /admin/stores/{id}/sync`, which **queues** a catalogue pull (`202 {"status":"queued"}`) picked up within ~30s by the `catalogue-sync` sidecar. It does not fetch inline — the backend container is refused by Shopify's edge; see the catalogue-sync entry under "Current implementation state" before changing anything here (`app/services/catalogue_ingest.py`, `scripts/catalogue-sync.sh`).
- **Known gaps:** CORS is global and currently **open to all origins** — `ALLOWED_ORIGINS` defaults to `*`, which `main.py:build_cors_kwargs` serves via `allow_origin_regex=".*"` (reflects the request Origin, since a literal `*` is illegal with `allow_credentials=True`); set a comma-separated list to lock it down (per-store CORS still not implemented). (`/products` **is** paginated — `{items,total,limit,offset}`, verified against a 1283-product catalogue; the old note here claiming an uncapped 1000-row PostgREST response was stale.)

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
> dev` on the host. **Since 2026-08-01 the default dev path is PLAIN HTTP:**
> frontend → http://localhost:5173, backend → http://localhost:8000, and the
> `caddy` TLS service is **opt-in** (`profiles: ["tls"]`), so a bare
> `docker compose up` no longer starts it. Nothing has to trust a private CA to
> work. `http://localhost` is still a **secure context** per the browser spec, so
> the microphone / Web Speech API is unaffected.
> Supabase runs on the **host** via `npx supabase start`; the backend container
> reaches it at `host.docker.internal:54321`.
>
> - **Why the default flipped.** Caddy's internal CA is untrusted until installed
>   by hand, and the failure it produces is actively misleading: the page loads
>   (its own origin was accepted) while every API call dies "Failed to fetch",
>   because a per-origin certificate exception does **not** extend to a
>   subresource origin. That reads as a broken backend, and it cost a real
>   verification pass. Binding :80/:443 was a second liability — compose aborts
>   the **whole** stack when a port is taken, so backend and frontend never
>   started either.
> - **Want the TLS path** (to exercise prod's proxy chain)? `docker compose
>   --profile tls up -d`, and set `VITE_API_BASE_URL=https://api.localhost` +
>   `TLS_PROXY_HOST=localhost` in the root `.env` — **those two must agree**, or
>   HMR is blocked as mixed content. Then trust the CA once:
>   docs/superpowers/plans/2026-07-25-ssl-all-servers.md Task 3 Step 8. Clicking
>   through the browser warning is **not** a substitute for that step, for the
>   subresource-origin reason above.
> - The five URL-ish vars must agree with whichever mode you pick:
>   `VITE_API_BASE_URL`, `TLS_PROXY_HOST`, `EMAIL_VERIFY_BASE_URL`,
>   `STUDIO_BASE_URL` (and `ALLOWED_ORIGINS`). `VITE_API_BASE_URL` is baked into
>   the bundle at **container start**, so always `--force-recreate frontend`
>   after changing it.
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
Onboard another store: `POST /admin/stores` → `POST /admin/stores/{id}/sync` (queues; the
`catalogue-sync` sidecar fetches within ~30s — it is a **prod-compose service**, so a dev
stack has no catalogue sync unless you run the script yourself:
`docker run --rm --network madhats-aidesign_default -e ADMIN_SECRET=… -e POLL_SECONDS=5 -v "$PWD/scripts/catalogue-sync.sh:/s.sh:ro" --entrypoint /bin/sh curlimages/curl:8.11.1 /s.sh`).

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
- **Background removal (a MARK, not an edit) + freehand draw tool.**
  - **Background removal** — "Remove background" in `SelectedToolbar` is a **flag only**, and deliberately so: ticking it just sets `removeBg` on the element (`SelectedToolbar.tsx` → `update(el.id, { removeBg })`) and draws a ✂ **marker badge** (`nodes.tsx`, `name="export-hide"` so it is NEVER baked into the layout guide or the preview, `listening={false}` so it can't steal clicks). **Nothing is matted client-side and nothing is re-uploaded — the canvas image does not change, by design.** The flag travels to the image model instead: `canvas_describe` emits `remove_bg` per element and `prompt_builder._element_line` appends an explicit instruction ("Remove/knock out the background of the uploaded artwork — apply only the logo/graphic itself…"), so the **AI render** is what knocks the background out. History worth knowing (the bullet here previously described the middle state and was wrong): the toggle was originally inert; `9b36fa5` wired real client-side `@imgly/background-removal` WASM matting; `8773c16` then removed that matting in favour of this mark-only design. The `@imgly/background-removal` dependency lingered in `frontend/package.json` with no importer until it was dropped (2026-07-17). **Do not reintroduce canvas-level processing** — and keep the customer copy honest: `prompts.V2_BG_INSTRUCTIONS` and the v2 `ASK_LOGO_BG` step must never promise processing or ask the customer to wait, because ticking is instant.
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
  never be model-written. **A second guard, `state_machine_v2.merge_fields`,
  keeps answered steps answered** — every `done_when` is a truthiness read, so
  the one write that can un-answer a settled step is truthy→falsy, and only the
  step that ASKED for a slot may make it falsy. The interpreter deliberately
  sees every `WRITABLE_SLOT` every turn (that is what banks a volunteered "and I
  need 50 caps"), which shipped a live loop: "no - i just want embroydary" at
  `ask_decoration_mix` made Haiku fill `decor_done:false`, so first-unmet walked
  BACKWARD and re-asked two settled questions. Writes to unset slots and truthy
  corrections (50→100 caps) still pass, so slot-filling stays flexible. This is
  why `decoration_mix` is a slot of `ask_decoration_mix` as well as
  `ask_decoration`: cancelling a mix is the one legitimate falsy write there, and
  it re-opens `ask_decoration` (the right question to land on).
  **There is no keyword fallback** — on `LLMUnavailable`
  the turn **stalls** (state unchanged, nothing guessed) and after 2 consecutive
  failures re-renders the chips to nudge a tap, so an outage degrades to a
  tap-through wizard rather than stranding a pre-email session. **Four steps are
  the exception** (`Step.direct_answer`):
  `ask_name`/`ask_email`/`ask_purpose`/`ask_decoration_mix` have no chips, so
  the chip-nudge escape hatch can never fire for them — on
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
  `_apply_email` sets that flag.
  **Flow (2026-07-17), 8 progress steps:** `ask_has_logo` opens the design half
  — "No — text only" sets `logos_done`, so first-unmet skips the whole logo
  branch (no branch, no back-edge). Each placed logo is followed by
  `ask_logo_bg`, which asks whether the background needs removing and points at
  the **existing** `SelectedToolbar` toggle (no auto-matting). **That step
  declares `tool="upload"` and it is load-bearing, not decoration:** it keeps
  frontend `v2Editing` (`allowedTools.length > 0`) true, so the just-placed logo
  is NOT locked (`Surface.tsx:111-113`) and stays *selectable*
  (`canvasStore.ts:36`) — the only way the toggle, which renders solely for a
  selected element, is reachable. Delete the tool and the bot instructs
  customers to tick a control they physically cannot reach, invisibly from the
  backend; `test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable`
  + the e2e walk pin it. `ask_decor_placement` then asks the face for text/shapes
  before the tool opens (fixing a live bug: `DECOR_ADJUST` set `face_target=True`
  while `_face` read `pending_logo`, which is `None` once the logo loop closes —
  so text had **always** silently landed on the front; `_face(step, collected)`
  is now step-aware via `_DECOR_STEPS`, and `_apply_anything_else` clears
  `decor_face` so a second decoration re-asks). After quantity,
  `ask_decoration` collects the decoration method — **single-select** chips, one
  per the store's `decoration_types` rows, whose choice sets the
  `decoration_type` render-style bucket the prompt builder reads (v2 never
  collected it before). It is the registry's only user of two capabilities added
  for it: `Step.prepare(collected, store)` (loads store-scoped data before
  the step renders; **may satisfy its own step** — a store with no methods
  configured, a missing store, or a DB error all auto-skip rather than
  dead-ending the funnel one step before email capture — so the orchestrator
  re-resolves `next_step` after it) and `Step.chips_from` (chips derived from
  `collected`; read ONLY via `chips_of`, never `step.chips`).
  `decoration_types` is store-dynamic so it cannot live in
  `SLOT_ENUMS` — `_apply_decoration`'s exact-token filter against
  `decoration_options` IS the interpreter guard. `Step.instructions` overrides
  the tool-keyed `V2_TOOL_TIPS` for a step whose tool is held open for a
  non-tool reason (`ask_logo_bg`).
  **A mix is single-select's escape hatch, not a second tick (2026-07-17):** one
  method is the normal answer and mixing costs more per hat, so a mix is a
  deliberate choice — a final `canvas_steps.MIX_CHIP_LABEL` chip sets
  `decoration_mix`, which satisfies `ask_decoration` and makes the conditional
  `ask_decoration_mix` first-unmet. That step takes the mix in free text
  (`decoration_mix_note` → `brief_notes` verbatim for the team; deliberately NOT
  filtered against `decoration_options`, since the point is that no offered
  method covers it) and derives the render bucket from the customer's own words
  via the same `_decoration_style_bucket` keyword table, falling back to the
  prompt builder's own "print" default. It collapses onto `ask_decoration` in
  `_PROGRESS_ANCHORS`, so asking for a mix never grows the counter (still 8).
  **The cost caveat lives in the ask copy** (both steps) because single-select
  can never trip `ChatColumn.tsx:597-600`, which only renders its own caveat at
  2+ ticks — that path is now **v1-only**, as is the registry's
  `Step.multiselect` field (retained, no v2 user; v1's `ASK_DECORATION` still
  ships `multiselect: true` from `orchestrator.py:1186`).
  **Known gap (pre-existing, not from this work):** resuming a v2 canvas session
  mid-design via `?session=<token>` does not rehydrate the `canvas` directive,
  so `isV2` is false and the customer gets v1's whole-rail lock + "Design locked
  in — finishing up" over a live design. Post-design resume (the preview email's
  edit link) is unaffected, since the tail states are v1-owned anyway.
  **No resume email in v2:** because `ask_email` sits at the END of the flow,
  the customer verifies while still in the tab watching the render — so
  `leads.py::_maybe_send_resume_email` returns early for v2 canvas sessions
  (same `settings.canvas_orchestrator_v2 and flow_mode == "canvas"` selector as
  `chat.py::_dispatch`; no guard flag written, so flipping the flag off restores
  it). The "Pick up where you left off" email is retained and unchanged for
  every other flow, which captures the email mid-design.
  Spec/plan: `docs/superpowers/{specs,plans}/2026-07-17-v2-canvas-flow-gaps*`. **Known landmine:** `state_machine.is_negative`
  still matches by **substring** ("a**no**ther" contains "no") and **v1 still
  routes on it** — v2 no longer calls it (proven by
  `test_v2_e2e.py::test_v2_no_longer_uses_the_shared_keyword_matchers`, a guard
  test over `orchestrator_v2.py`'s source; the e2e walk in the same file drives
  the exact chip labels the UI ships, including "Yes, another logo", with the
  interpreter raising `LLMUnavailable` for the whole walk — proving the entire
  front half needs no model at all). Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-17-llm-assisted-canvas-orchestration*`.
- **Canvas-led refine + self-ticking background removal (2026-07-17):** the
  backend can mutate the canvas via `data.canvas_ops` — fully-resolved flat
  patches (`{target, patch|remove}`), applied in `chatStore.sendMessage`'s
  response handler via `lib/canvasOps.ts`, **never in a React effect** (an
  effect fires on change, which would re-apply on resume and re-flag the wrong
  logo on a later loop pass) and never on `hydrate`. Two target kinds:
  `{kind:"element", id, face}` (refine — ids come from the persisted
  `canvas_design`) and `{kind:"pending_logo", face}` (v2 background removal —
  the backend has NO id there, since `canvas_design` is only written at
  finalize, so the frontend resolves "last unlocked image on that face", the
  same anchor `lockPlaced` uses). `canvasStore` gained face-aware
  `patchElement`/`removeElementOn`/`patchPendingLogo` because `updateElement`
  only ever sees `activeFace`.
  **Background removal now ticks itself** (`canvas_steps._ops_logo_bg`): the
  chip is "Yes, remove background" and emits the op. This fixed a live bug —
  `pending_logo["bg"]` routes (it is `ask_logo_bg`'s `done_when` marker, so do
  NOT delete it) but nothing on the RENDER path reads it; the knockout comes
  solely from `el.removeBg` on the canvas blob, so "Yes, I've ticked it"
  without ticking silently rendered no knockout. `tool="upload"` still stays —
  the toggle remains a manual override. Copy still must never promise
  processing or a wait.
  **A described change now edits the canvas, not the prompt**
  (`services/conversation/canvas_edit.py` + `ie.interpret_canvas_edit`):
  `OFFER_REFINE` → "Describe the change here" → Haiku returns a **closed
  vocabulary** (`move/resize/rotate/recolour/font/curve/set_text/delete`) and
  **never a number** — `canvas_edit.resolve_ops` does the arithmetic and
  clamping, a pure function over plain dicts (v2's "the LLM reads the customer,
  it never routes" extended to "it never computes geometry"). Element ids are
  validated against an inventory built from `canvas_design`, so a hallucinated
  id is dropped. Ops → `CONFIRM_CANVAS_EDIT` ("Looks right" / "Not quite");
  iteration before confirming is free and burns no edit cap. The confirm chip
  resolves by **exact** label match (0 model calls); other free text goes to
  `ie.interpret_edit_confirm` (a Haiku yes/no — the substring `is_affirmative`
  would read "that looks wrong" as yes and spend a render), and an outage sets
  `edit_confirm_stalled` → re-ask, never render. Render-level requests
  ("thicker embroidery") return `[]` → refused, appended to `brief_notes` for
  the team, back to `OFFER_REFINE` — **`change_request` is retired for canvas
  sessions** (the `last_change` write is now `flow_mode`-gated so it can't sneak
  back via `generate.py`'s fallback); non-canvas (`session`/`blank`) refine
  keeps it unchanged. `LLMUnavailable` on the edit read stalls rather than
  guessing geometry. **`CONFIRM_CANVAS_EDIT` must stay in
  `goal_planner.GATE_STATES`** — `_route` only consults `advance_state` for
  gate states; otherwise `next_goal` answers `GENERATING` for a finished canvas
  session, a fresh render that burns the daily cap (the same trap
  `ASK_CHANGE_METHOD` documents). Confirming reuses the existing rework path
  (`_mark_canvas_rework` sets `reworking=True` → `trigger_finalize` → `doRender`
  re-flattens the edited canvas → `sessions.py` → `REGENERATING`); `Surface`'s
  `finalizeStarted` ref is now **re-armed when `triggerFinalize` goes false**,
  without which the second finalize a refine needs was silently swallowed.
  Known gaps (tickets, not blockers): confirmed-edit ops are ephemeral (only a
  `canvas_edit_ops` flag is persisted, not the ops — a reload at the confirm
  gate loses them); a refused change gets no tailored acknowledgement (lands on
  the generic `OFFER_REFINE` ask); a no-`ANTHROPIC_API_KEY` deployment
  permanently stalls at canvas `DESCRIBE_CHANGES` (that state ships no chips to
  escape with). Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-17-canvas-led-refine*`.
- **Canvas quote-flow batch (2026-07-24) — MERGED BUT NOT LIVE-VERIFIED.** Four
  workstreams built in parallel: (A) universal rotate/move/size controls in
  `SelectedToolbar`, plus `canvasStore.unlockAll()` + a `fromCanvasDesign`
  lock-strip so a refined design is editable again (the unlock call is guarded on
  "something is actually locked" — calling it unconditionally clears `selectedId`
  on every mount, which makes the `ask_logo_bg` background-removal toggle
  unreachable); (B) a `needed_by` registry step between `ASK_EMAIL` and
  `ASK_PURPOSE`; (C) **quote-gated delivery** — a `REQUEST_QUOTE` step mints
  `leads.reference_code` (`MH-XXXXXX`), the customer is emailed the REFERENCE
  ONLY (never the design), sales is notified once with components attached, the
  render is admin-triggered via `POST /admin/quote-requests/{lead_id}/render`,
  plus the multi-angle fix (`_map_views` stops fabricating back/left/right
  aliases; faces with no genuine angle are skipped; per-face prompts carry
  front-to-back z-order); (D) per-store `brand.canvas_flow` enable/reorder of the
  safe subset (`ask_quantity`/`needed_by`/`ask_purpose`) through the pure
  `state_machine_v2.effective_registry`. Merged registry tail is now
  `ask_email → needed_by → ask_purpose → request_quote → finalize_canvas`.
  Both batch migrations (`20260724000001_leads_reference_code.sql`,
  `20260724000002_generation_render_notes.sql`) are now **APPLIED on the hosted
  Supabase** — verified directly (all four `leads` quote columns +
  `generations.render_notes` exist; a bogus column still errors `42703`). The
  earlier "UNAPPLIED — would PostgREST-error every generation-completion UPDATE"
  warning is resolved; leaving the history here in case a fresh env needs them.
  Spec/plan: `docs/superpowers/{specs,plans}/2026-07-24-canvas-quote-flow-*`.
- **Canvas v2 empty-turn dead-loop — FIXED (2026-07-24).** A live session was
  found stuck in a loop back at `ask_name` despite the customer completing
  name → logo → background-removal → email verification; 15 prior sessions in an
  hour showed the same fingerprint (customer reloading because the funnel was
  unfinishable). Root cause: an empty/whitespace `""` user turn at a
  non-`GREETING` v2 step matched no chip and fell through to
  `intent_extractor.interpret_turn_v2`, which — handed no real input but the full
  slot list — returned well-typed-but-spurious slot values; first-unmet routing
  then walked the conversation BACKWARD, twice all the way to `ask_name` (with
  `name` wiped). Only the `GREETING` kickoff (`chatStore.kickoff` →
  `sendChat(id, "")`) legitimately sends `""`. Fixed at BOTH layers (defense in
  depth): (backend) `orchestrator_v2.handle_message` now no-ops a blank turn —
  re-renders the current step, ingesting nothing, before the chip/interpreter
  logic; (frontend) `chatStore.sendMessage` drops a blank/whitespace turn at the
  single choke point every user message flows through (chips, typed input,
  `done`/`ok`/`none`, uploads), so no UI path can emit one. The exact UI handler
  that emitted the stray `""` was not isolated from the data alone, but the
  choke-point guard neutralises the whole class regardless. Regression tests:
  `test_orchestrator_v2.py::test_empty_turn_is_a_noop_and_never_reaches_the_interpreter`
  (backend), `chatStore.test.ts` "blank-turn guard" (frontend).
- **Adjust panel above the cap + formal v2 register (2026-07-26).**
  `SelectedToolbar` is now a titled panel that renders **before** `CanvasStage`
  in `Surface.tsx`'s centre column, `sticky top-0 z-20`, with a solid
  `bg-accent` header reading `Adjust — Text|Image|Shape|Drawing`. It used to
  render below the stage inside that scrolling column, so on a phone (the chat
  already owns `h-[45vh]`) it sat under the fold and selecting an element
  looked like it did nothing. **Two CSS facts are load-bearing and were both
  found in-browser, not by the tests** (jsdom performs no layout, so the suite
  can only pin the class names): (1) `shrink-0` on BOTH the panel root and the
  new `data-testid="canvas-stage-wrap"` wrapper — without it the fixed 480px
  Konva stage wins the flex-shrink and the panel collapsed to a **2px accent
  line**; (2) the controls region is `max-h-[9rem] md:max-h-[45vh]`, because
  `vh` measures the VIEWPORT while the panel lives in a column that is smaller
  than the viewport by the chat's 45vh plus two header bars — a flat `45vh`
  cap is larger than the region it bounds and would let the sticky panel hide
  the cap outright. Measured live at 1536×639: panel 174px in a 410px column,
  `flexShrink: 0` on both siblings, mobile clamp ≈172px. Copy follows the
  panel: `V2_TOOL_TIPS` and `V2_BG_INSTRUCTIONS` say "the **Adjust** panel
  above the cap" (never a colour — `bg-accent` is `var(--brand-primary)` and
  themes per store), and `test_v2_copy_guards.py` fails on any v2 string
  containing "under the cap". The same file guards the **formal register**:
  the whole v2 canvas conversation was rewritten out of its casual voice, and
  a `_CASUAL` word-boundary regex list ("pop your", "grab your", "love where",
  "no worries", "are you after", "tap") pins it. Two chip labels changed
  (`"No, that's all"`, `"No, it's fine as it is"`) — they resolve by exact
  literal, so `test_v2_e2e.py`'s walk types them verbatim. **`REQUEST_QUOTE`
  now promises the finished design WITH the quote**, and
  `SALES_QUOTE_REQUEST_EMAIL_BODY` tells the team to render it from the admin
  tools and send it — the promise is kept by a HUMAN, not by code: delivery is
  untouched and still reference-only (`delivery.py:96-130`). A conditional
  "with the logo background removed" clause was built and then removed by
  owner ruling: `collected["logos"][].bg` records the CHIP answer while the
  render reads the element's `removeBg`, and the manual toggle can diverge
  them with no way to read the truth at that step (`canvas_design` is
  persisted only after finalize). Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-26-canvas-adjust-panel-and-copy*`.
  Open tickets: the accent header is a plain `<div>` (not a heading/labelled
  region) and white-on-accent is ~3.1:1 contrast — spec-mandated and the same
  combo as the Done button, but unbounded for a store that picks a pale
  primary; the placement tests assert only the Text and Image header labels;
  and the **sub-768px stacked layout has never been observed in-browser** (the
  Chrome extension's `resize_window` is a no-op in this environment and the
  devtools MCP could not attach), so mobile rests on the clamp arithmetic plus
  the class-pinning tests.
- **Canvas screen space optimisation — responsive stage (2026-07-26).**
  Four changes, all verified in-browser at 1536×639: the `StoreHeader` logo is
  `h-8` (was `h-16`, header 92px → 49px); the `ChatColumn` voice block is a
  single compact ROW (7×7 mic, one `text-xs` line, listening-only halo) instead
  of a centred stack with two halo rings, a big label, a kbd chip and an "or
  type" line — it was eating ~140px of the scarcest column on the screen; the
  chat column widens with the viewport (`md:360 lg:420 xl:480 2xl:560`, mobile
  `w-full`+45vh untouched) while `ToolRail` narrows (`md:w-44 lg:w-52 xl:w-64`)
  so a laptop/iPad doesn't pay for it.
  **The Konva stage is now responsive, and the mechanism matters:** `STAGE_W`/
  `STAGE_H` stay a hard 480 — that is the LOGICAL space every element
  coordinate is normalised to, that `FaceThumbnails`' `SCALE` divides by, and
  that `canvasGeometry` is tested against — and only the *rendered* size moves,
  via a uniform `scaleX/scaleY` on the `<Stage>`. Two consequences that are
  easy to get wrong: (1) `stage.getPointerPosition()` returns CONTAINER pixels
  and Konva does NOT apply the stage transform to it, so `pointerNorm` (the
  draw tool) divides by the DISPLAYED size, not `STAGE_W`, while `livePts`
  still multiplies by `STAGE_W` because it is drawn inside the scaled stage;
  (2) `canvasFlatten` can no longer hardcode `pixelRatio: 2` — it derives the
  ratio from `stage.width()` so every export is exactly `EXPORT_EDGE_PX` (960)
  regardless of screen, which is what stops a short laptop from sending the
  image model a 560px layout guide where a desktop sends 1120px.
  `canvasFlattenExportSize.test.ts` pins that invariant; verified live that a
  339px on-screen stage exports 960×960 and that the far edges are opaque (i.e.
  the scale IS applied on export, nothing is cropped).
  Size = `clamp(280, min(columnWidth, availableHeight), 560)` where
  `availableHeight` is **measured, not assumed**: the column's inner height
  minus its other children. A fixed constant is wrong in both directions
  because the sticky Adjust panel comes and goes with the selection — too small
  and the cap is needlessly tiny with nothing selected, too large and selecting
  an element pushes the cap off the bottom. `col.clientHeight` is set by the
  flex row above it (viewport-derived, content-independent), so resizing the
  stage can never feed back into the number. Both a `ResizeObserver` (column +
  siblings) and a `MutationObserver` (childList) are needed — RO alone never
  sees a sibling that has not mounted yet — and **both must be
  feature-detected**, since jsdom ships neither and constructing one
  unconditionally throws through every Surface-mounting test. Measured live:
  484px with nothing selected (fits exactly, no scroll), 280px (the MIN floor)
  with the panel open in this unusually short 639px window, back to 366px on
  deselect. MIN is a usability floor, not a fit guarantee — on a very short
  window the column scrolls a little rather than shrinking to something you
  can't design on. Drag/select/transform re-verified at scale 0.76.
- **v2 email verification is now a HARD gate (2026-07-26).** Answering
  `ask_email` fires the double opt-in link and the flow **stops** — it no longer
  walks on with an unconfirmed address. One new registry step,
  `AWAIT_EMAIL_VERIFY` (`await_email_verify`), sits **immediately after**
  `ask_email` (that adjacency is the whole mechanism, and
  `test_registry_declares_the_v2_flow_in_order` pins it). It is a **wait, not a
  question**: no chips, no slots — so `orchestrator_v2` never calls the
  interpreter there, nothing the customer types is read, and any typed turn just
  re-renders it (`ask_retry` = `V2_AWAIT_VERIFY_RETRY`, the spam-folder line).
  Idling at the gate therefore costs zero model calls.
  **`done_when=lambda c: not c.get("email_captured") or c.get("email_verified")`
  — the `not email_captured` half is LOAD-BEARING, not defensive:** `ask_email`
  is deliberately *satisfied* early in the design (nothing placed yet), so a gate
  reading `email_verified` alone becomes first-unmet at the START of the design
  phase and blocks it before the address was ever asked for.
  The only exit is the real click: `leads.py::_mark_session_verified` flips
  `collected.email_verified`, and the tab's existing 4s poll
  (`GET /chat/{id}/verification`) advances the thread via a new
  `orchestrator_v2.check_verification`, which **delegates any non-gate state
  straight to v1** (the shared post-generation `VERIFY_EMAIL` wait uses the same
  endpoint, so v2 must not swallow it) and is dispatched from
  `chat.py::poll_verification` through the extracted `_is_v2_canvas` helper.
  It persists the **assistant row only** (`_persist(user_message=None)` — a new
  sentinel distinct from `""`, which the GREETING kickoff still uses to write an
  empty user row): a phantom user turn would show in the thread as something the
  customer never said. Reply = `V2_EMAIL_VERIFIED_ACK` + the next step's copy —
  **two messages, not one** (2026-08-01: sent via `data.extra_replies` so the
  confirmation lands as its own bubble and can't be read past on the way to
  the question; `ack=` is deliberately not passed to `reply_for`, which is what
  would merge them back into one).
  **Frontend** (`ChatColumn`, the only component v2 canvas renders — `ChatPanel`
  is `view==='session'`): `awaitingEmailVerify` → `inputLocked` disables the
  text box, Send, mic, every chip row and the Continue affordance, hides Back
  (nothing to rewind *to*, and the point is that nothing moves), and shows a
  `role="status"` waiting panel. `handleSubmit`/`handleChip` re-check the lock,
  so bypassing `disabled` still drops the turn. The poll effect now fires for
  `verify_email` **or** `await_email_verify`.
  Verified live end-to-end (state driven to the gate + `email_verified` flipped
  exactly as `leads.py` writes them, since Resend's sandbox 403s a `+alias`
  address): input/Send/mic all `disabled:true`, no Back, no chips, tool rail
  dead, and the release landed within one poll cycle with the ack + next
  question as a single assistant message.
  **Fixture consequence for every future v2 test:** `email_captured: True` alone
  now parks a session at the gate. "Past the email step" means
  `email_captured` **and** `email_verified` — 13 fixtures across
  `test_orchestrator_v2`/`test_state_machine_v2`/`test_canvas_steps`/`test_v2_e2e`/
  `test_request_quote_step` were updated, plus `canvas_step_helpers.satisfy`.
  Known gaps (both pre-existing, now reachable at a new state): the v2 **resume**
  gap means reloading at the gate rehydrates no `canvas` directive, so the canvas
  shows v1's "Design locked in — finishing up" strip over a live design; and
  there is **no in-chat "resend the link"** affordance — if the email never
  arrives the customer must reload, since `POST /leads/verify/send` needs a
  `lead_id` the browser is never given. Worth adding if support tickets appear.
- **The canvas can now ANSWER a step, not just receive ops (2026-07-28).** The
  background-removal toggle was write-only from the backend's side: `_ops_logo_bg`
  ticks it FOR the customer when they tap the chip, but a customer who ticked it
  themselves was still asked. `canvas_steps.observe_canvas(collected, canvas_design)`
  is the read direction — a pure function over plain dicts that finds the **last
  unlocked image on the pending logo's face** (the same anchor `canvasStore`'s
  `patchPendingLogo`/`lockPlaced` use, because there is still no element id: the
  blob is only persisted at finalize) and, if it carries `removeBg`, writes
  `pending_logo["bg"]="removed"`. That write satisfies `ASK_LOGO_BG.done_when`,
  so **first-unmet routing skips the step by itself** — no branch, no back-edge,
  and `orchestrator_v2` calls it unconditionally (a step-id guard there would be
  a second source of truth that can drift from the frontend's send condition).
  It is one-way: only ever writes `"removed"`, never over an existing answer.
  The `return False` INSIDE its scan loop is load-bearing — the first unlocked
  image found scanning backwards IS the pending logo, so an unticked one means
  "not ticked"; a `continue` would scan back to an older, locked, already-handled
  logo and answer with its setting.
  **The live canvas is now sent on TWO turns, not one:** `chatStore.sendMessage`
  attaches `toCanvasDesign()` at `describe_changes` (unchanged) **and**
  `logo_adjust`. `_dispatch`/`handle_message_v2` thread it to v2 only — v1's
  `handle_message` deliberately takes no blob — and `chat.py`'s
  `_persist_live_canvas_design` is untouched, so a `logo_adjust` blob is read
  but never written to `design_sessions.canvas_design`.
  **The landmine this shipped with, found only by the whole-branch review:**
  `Surface.postDone()` called `lockPlaced()` BEFORE `sendMessage`, and
  `sendMessage` reads `toCanvasDesign()` **synchronously** — so the blob shipped
  fully locked and `observe_canvas` never fired on the canvas **Done button**
  path (roughly half of live traffic; the step renders both a button and a chat
  chip). Neither suite caught it: the backend tests hand `observe_canvas` an
  unlocked element directly, and `surfaceDirective.test.tsx` drove `sendMessage`
  directly, i.e. the chip path. Fixed by **deleting `lockPlaced()` from
  `postDone`** — the directive effect (`Surface.tsx`, `if (isV2 && !v2Editing)
  lockPlaced()`) was already the authoritative locker for every answer path, as
  its own comment says. That deletion also repaired two PRE-EXISTING bugs on the
  button path: a locked element is unselectable, so the manual toggle the step's
  copy points at was unreachable, and `_ops_logo_bg`'s op silently no-opped
  (`patchPendingLogo` uses the same last-unlocked scan). Consequence to know:
  the button path's lock now happens on the reply rather than optimistically
  before the request, converging onto the chip path. **Any future test of a
  canvas turn must exercise the real button, not `sendMessage` directly** —
  that gap is exactly what hid this.
  Copy: the announcement that used to accompany the skip (`V2_BG_ALREADY_REMOVED`,
  "I can see you've already marked that logo's background for removal...") was
  **removed entirely by owner request (2026-08-01)** — the skip is now silent.
  `cs.observe_canvas` is still called unconditionally in `orchestrator_v2`; only
  its return value is now unused (kept, deliberately, for the side effect —
  see the comment at the call site so it isn't deleted as dead code later).
  Open ticket: if the customer UNTICKS after the auto-mark, `pending_logo["bg"]`
  stays `"removed"` and the step is permanently satisfied, while the render reads
  `el.removeBg` — widening the divergence this file already documents.
- **The verification landing page is store-branded (2026-07-28); the error page
  deliberately is not.** `VERIFICATION_SUCCESS_HTML` is a `string.Template` shell
  (not `.format()` — these are CSS blobs full of literal braces) taking
  `$store_name`/`$primary_colour`/`$header_html`, resolved in
  `leads.confirm_verification` (which now takes `request: Request` for
  `media_url`'s base). The default header is a **literal** `VERIFY_HEADER_DEFAULT_HTML`,
  never `store_name.upper()` — `"MadHats".upper()` is `"MADHATS"`, no space, the
  trap `email.py:205` already documents. The whole resolve-and-render block sits
  inside one best-effort `try`: the verification is COMMITTED before the page
  renders, so any branding failure must still return 200 with the MadHats
  defaults — `_default_success_html()` is built from literals so the fallback
  itself cannot throw. `_error_page` always renders defaults: two of its three
  branches reject the token before a lead is loaded, and the third isn't worth a
  DB round-trip for a dead-end page. **No Close button and no JavaScript** —
  browsers block `window.close()` on a tab the user opened themselves, which is
  what clicking an email link does, so the requirement is a highlighted callout
  ("You can close this page now and head back to the chat") instead.
- **Studio fixes batch (2026-07-28) — graded profanity, Adjust panel placement, remove_bg/assetPath plumbing.** A pure two-tier scanner, `app/services/profanity.py` (`scan`/`find_terms`, word-boundary-only regex, no LLM/network/DB — cannot fail, which is what lets it gate cap text without risking a stall): `MILD_TERMS` (common obscenity, tolerated in chat) and `SEVERE_TERMS` (slurs, declined on sight). `SEVERE_TERMS` deliberately **excludes** "tranny"/"spic"/bare "dick" — they collide with Australian automotive slang ("tranny swap"), the idiom "spic and span", and the given name/nickname "Dick" — tune the term sets, not the matching logic. Two enforcement points: (a) v2 canvas chat declines a severe message without advancing, and `chat.py`'s LLM moderation gate is skipped **only** when the session is v2-canvas **and** `profanity.scan(...) == "severe"` (`_is_v2_canvas(session_id)` + the severe check both gate the bypass — mild profanity and non-canvas sessions still go through the LLM moderation path); (b) canvas-finalize runs a STRICT gate blocking both mild and severe cap text before any write or sales notification. **The Adjust panel (`SelectedToolbar`) is now responsive**, via `frontend/src/lib/useIsDesktop.ts`: `md`-and-above renders it in the tool rail's free space, below `md` it stays above the cap (rendering it in both would duplicate `data-testid="adjust-panel"`). `useIsDesktop()` is feature-detected and **falls back to `true`** when `window.matchMedia` is absent (jsdom ships none) — desktop is the layout the existing test suite expects, so this keeps every prior test green without a `matchMedia` polyfill. `components.py` was reading `asset_path` while `canvas_describe` writes camelCase `assetPath` — per-element canvas images (uploaded logos/graphics) reached no admin component list and no sales-email attachment; fixed via `_element_asset_path()` reading `assetPath` first, falling back to `asset_path` for v1-shaped elements. Every admin/email surface now reads background-removal from **`elements[].remove_bg`** (the field the render actually acts on) and never `logos[].bg` (a chat-collection artifact) or the v1 top-level `collected.remove_bg` flag: the sales quote-request email's per-element `design_breakdown`, the admin quote-requests list (PII-free `elements` summary + a "Remove BG" badge), and `SessionDetailView`'s "Remove background" row (`sessionDetailRemoveBg.test.tsx` pins this against the old top-level flag).
- **Studio fixes batch (2026-07-28), continued — email format validation, the moderation-bypass predicate's third case, and brief_notes left unscanned.** `leads.is_valid_email(address)` is a new ANCHORED `fullmatch` validator, enforced only at the point of STORING an email — `canvas_steps._apply_email`/`_direct_email` — and deliberately kept separate from `leads.extract_email`, which stays a loose unanchored `search` because v1 and the Haiku-outage fallback both depend on pulling an address out of a sentence. Rejecting sets nothing in `collected`, so `ask_email` re-asks with the new `V2_ASK_EMAIL_RETRY` copy. Before this the live path had NO format check at all: Haiku filled the `email` slot, `validate_fields` passed it through untouched, and it was INSERTed raw into `leads`. **`chat.py::_v2_canvas_owns_turn`** gates the moderation bypass and is now precisely three-valued-false: state outside `V2_OWNED` (v1-delegated tail states get no v2 decline, so `check_text` must run), the identity steps `ask_name`/`ask_email` (`_ABUSE_EXEMPT_STEPS` — v2 exempts them from ITS decline, but `check_text` still runs), and `GREETING` (the kickoff branch returns before v2's decline guard is even reached — not exploitable, since that branch discards the turn's text and persists `user_message=""`, but included so the predicate's docstring is honest about every case). The identity-step exemption exists because `paki`/`heeb` are in `SEVERE_TERMS` and are also real (Māori and Swiss/German) surnames, and the flow asks name and email first — declining there would permanently block such customers. But exempting v2's decline alone is not enough: without the route-level `check_text` still running, a severe message at those steps would reach `interpret_turn_v2` unmoderated, which is handed every writable slot regardless of step and can bank `final_notes`, later appended verbatim into `brief_notes` and the sales email. `moderation.py:20-24` explicitly instructs the judge that names/emails are SAFE, so the LLM gate passes a surname while still catching abuse used as a slur. Separately, **`brief_notes` is deliberately NOT profanity-scanned at finalize** (owner ruling): notes are internal team text, never printed on the product, and a severe note is already declined at the point it was typed — scanning again at finalize would accept the note, show the customer their reference code, then 422 with no UI path to reword it, stranding the customer and never notifying sales. Cap text (what actually gets printed) stays strictly gated on both the mild and severe tiers. Additional `SEVERE_TERMS`/`MILD_TERMS` word-list collisions excluded for the Australian market, alongside the already-recorded "tranny"/"spic"/bare "dick": bare `ass` (`"NSW CRICKET ASS."` = Association), `fck` (FC København), `fuk` (a Cantonese given/surname) — tune the term sets, not the matching logic.
- **The backend CANNOT fetch the Shopify feed — the `catalogue-sync` sidecar does it (2026-07-29).** Shopify fronts `madhats.com.au` with Cloudflare, which refuses the **backend container's** HTTP client from a hosting ASN while accepting the **Alpine-curl sidecar's**, from the same droplet, same egress IP, seconds apart. The decisive measurement, both probes run back to back on the staging droplet (DigitalOcean SYD1):
  ```
  backend  container, 6 requests, no delay -> 429 429 429 429 429 429
  watchdog container, 6 requests, no delay -> 200 200 200 200 200 200
  ```
  **Three plausible explanations are already ruled out by that pair — do not re-litigate them:** NOT rate limiting (a six-request burst from the sidecar passes clean); NOT the User-Agent (a browser UA is refused from the backend too); NOT the request flags (bare `curl <url>` is refused from the backend too). `httpx`, `curl_cffi(impersonate="chrome")` and Debian curl 8.14.1/OpenSSL 3.5.6 are all refused; Alpine curl 8.11.1/OpenSSL 3.3.2 is accepted. **Every client works from a residential ASN (Superloop)**, which is the trap: this fails ONLY in production and passes in dev, reading like "the sync is broken". *(Diagnosis history worth knowing, because each wrong turn looked convincing: it was first called a leaky bucket, then UA bot-scoring, then a Python TLS fingerprint, then briefly rate-limiting again — that last reversal came from comparing a **burst** in one container against **isolated** requests in the other. Compare like with like, in the same window, before concluding.)*
  **Design:** `services/catalogue_ingest.py` + `scripts/catalogue-sync.sh`. The sidecar polls `GET /admin/catalogue/sync-targets` (plain text `<store_id> <base>` lines — busybox has no `jq`), curls each page itself, POSTs it to `/admin/stores/{id}/catalogue/pages/{n}` (returns the product count as text so the shell knows when to stop), then `/admin/stores/{id}/catalogue/commit`. **Pages buffer in memory and `product_references` is written exactly once, at commit** — a fetch that dies half way leaves the live catalogue untouched, which a page-at-a-time writer could not promise. `commit` **refuses an empty catalogue** rather than wiping (an empty feed is far likelier to be a broken fetch than a store selling nothing). `replace_catalogue` is now the single writer, shared with the direct-fetch path.
  **The sidecar carries no schedule** — Alpine ships no tzdata, so `TZ=Australia/Sydney date` prints UTC there and any shell-side midnight arithmetic fires at **10:00 Sydney**, silently, looking right in the logs. The backend decides who is due (`_nightly_due`, once per local calendar day, and deliberately NOT on the first poll after a restart or every deploy would refresh everything); claims have a TTL so a 30s poll can't start the same store twice mid-run.
  **`seconds_until_next_sync` must subtract in UTC**: Python ignores the offset when both operands share a `tzinfo` object, so `next_midnight - now` is wall-clock arithmetic and answers 24h for the 23h that actually elapse on a DST-transition night — pinned by a test on the 2026-10-04 AEDT boundary. `ZoneInfo` resolves **lazily** (`sync_timezone()`), never at import: Windows ships no tz database and a module-scope `ZoneInfo(...)` took down every import of the module, including an unrelated existing test file. `tzdata` is a declared dependency.
  **Landmine, found only by running the real sidecar:** `GET /admin/catalogue/sync-targets` must terminate **every** line with `\n`, including the last. POSIX `read` returns non-zero at EOF on an unterminated final line, so `while read` **skips it** — with one store queued that means the nightly sync does **nothing, forever, with no error anywhere**. The endpoint terminates every line and the script also guards with `|| [ -n "$store" ]`; both, because the failure is invisible. The tests passed while this was broken.
  **The manual sync button now QUEUES** (`POST /admin/stores/{store_id}/sync` → `202 {"status":"queued"}`) because the backend cannot fetch on demand; `SyncResult` and `StoresView` were updated to match ("Queued — the sync runs within a minute") instead of showing counts.
  **Verified end to end locally**: queue → sidecar poll → 6 pages (250×5 + 36) → commit → `/products` total 1283.
  **Interim unblock worth remembering:** the local backend's `.env` points at the **hosted** Supabase, so running the sync from a dev machine on a residential ASN writes straight into the production catalogue — that is how the 1283-product catalogue was first loaded, with zero code. **Durable alternative if the ASN block ever widens:** the Shopify **Admin API** with a private-app `read_products` token (authenticated, exempt from anonymous edge gating, returns `X-Shopify-Shop-Api-Call-Limit`) — needs MadHats' in-house Shopify developer, per §2.
  **Data-quality finding from the first real sync:** 1286 fetched / 1283 imported / 3 skipped (no images → no reference photo). Only **~5%** of products carry a genuine second angle (11 of 200 sampled have anything beyond `front`). Since `_map_views` no longer fabricates aliases, the canvas render loop **skips** faces with no real photo — so for most of this catalogue a back/side decoration renders nothing but the front hero. This is the norm, not the exception; a photography ask for MadHats if multi-angle matters at launch. Also note `/products` **is** paginated (`{items,total,limit,offset}`, `total`=1283) — the §3b "known gap" claiming a 1000-row PostgREST cap is stale.
- **Canvas Studio UX batch (2026-08-01): focus cue, five-section Adjust panel, split verified-turn bubble, and per-step verbatim answers.** `useActiveSurface()` (`frontend/src/lib/useActiveSurface.ts`) derives which half of the split screen owns the turn from the backend's canvas directive alone (`allowed_tools` non-empty = canvas's turn) rather than a separately-tracked frontend flag, with two carve-outs: a REJECTED finalize forces `'canvas'` back open via `finalizeFailed` even though that state hands over no tool, and a null directive (v1-delegated states) falls back to v1's `chatState === 'canvas_design'` gate. `finalizeFailed` moved out of `Surface.tsx`'s local `useState` and into `chatStore` for exactly this reason — a hook living outside `Surface` needs to read it, and component-local state is invisible to a sibling hook. `CustomiseStudio/index.tsx` renders the cue as a ring + themed glow on the active column, `opacity-60` on the other, plus a `role="status"` pill — deliberately NOT `pointer-events-none` on the dimmed side, since dimming is a cue, not a lock (real locking stays per-affordance), and blocking events would stop the customer scrolling back through chat history while the canvas has focus.
  **`SelectedToolbar` (the Adjust panel) is now five labelled sections** — Content / Style / Position / Layer order / Actions, each rendered only when it has content for the selected element's type — replacing the old `compact` caption-hiding mode and the `Sep` divider (both retired). Move is a 3×3 D-pad cross with a recentre button at its centre. `ROTATE_STEP` dropped from 45° to 12.5° (**11.25° since 2026-08-01** — 32 steps, so the sequence lands exactly on every 45°/90°), with a `fmtDeg` helper so the readout shows the true `11.25` rather than a rounded `11.3` — a bare `Math.round`/template-literal would silently reintroduce the old granularity's readout under a finer step (it now keeps two decimals; one decimal was enough for 12.5 and lies about 11.25).
  **The ⊕ recentre button was centring the element's CORNER (fixed 2026-08-01).** `canvasStore` x/y is the normalised **top-left**, so the original `{x: 0.5, y: 0.5}` put the corner in the middle and the element half its own size down-and-right of it — ~96px on both axes for a 0.4-wide logo. `canvasGeometry.centredTopLeft(el, stageW, stageH, measuredTextBox?)` (pure, unit-tested) backs the element's own origin out of the stage centre, per type, mirroring exactly the `offsetX/offsetY` origin `nodes.tsx` registers: half the stored box for image/shape, the stroke's own bbox centre for a drawing (its normalised `points` go straight into `drawingBoundsCenter`), half the **measured** box for text. Text is the one type with no stored size — it auto-sizes to its glyphs — so the live `TextNode` publishes its `getClientRect` into `lib/textMetrics.ts` (a module-level Map keyed by element id, deliberately NOT store state: it is a measurement OF the render, and in `canvasStore` it would land in the persisted `canvas_design` blob and re-render on every measurement). Only the live node publishes — `FaceThumbnails` draws text at thumbnail scale and must never overwrite a full-stage box. The `estimateTextBox` heuristic remains the fallback when nothing has measured yet (jsdom tests), and it is genuinely coarse: measured "Your text"@36 is 140.8×36 against an estimate of 178.2×43.2. `STAGE_W`/`STAGE_H` moved into `lib/canvasGeometry` (Konva-free) so plain-geometry callers can do px↔normalised arithmetic without importing react-konva; `CanvasStage` re-exports them, so every existing `from './CanvasStage'` import is unchanged. **Careful when reading the stage in the browser: `stage.width()` is the DISPLAYED size (419 here), not the logical 480** — the logical space comes from `stage.width()/stage.scaleX()`. Verified live: after ⊕, the text node's on-screen `getClientRect` centre was exactly the stage centre (209.5, 209.5), and four ⟳ clicks read exactly `45`. Suite after this change: `docker compose exec -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx` = **322 passing** (was 305; +17), `npx tsc --noEmit` clean.
  **`data.extra_replies`** (`orchestrator_v2._persist`) lets one backend turn write more than one assistant chat row — used so the "your email's verified" acknowledgement lands as its own bubble instead of being glued to the next question with a space. Consumed at all seven `chatStore` `parseData` call sites, but `hydrate` DISCARDS it on resume: the backend already persisted each extra as its own row, so appending again on rehydrate would duplicate every split message on every resume. The five `state_machine_v2.reply_for`/`orchestrator_v2` join sites that build a single reply now join with `"\n\n"` instead of a space, so a trailing instruction renders as its own paragraph under the question (the chat bubble is `whitespace-pre-wrap`).
  **`Step.accept_verbatim`** (`canvas_steps.py`), set on `ASK_PURPOSE` only: when the LLM interpreter returns nothing for a step's own slot, the raw customer message is banked into it instead of leaving the step unmet forever. Fixes a real dead-end — `ASK_PURPOSE` ships no chips, so a refusal ("rather not say") or a misspelling the interpreter declined to read left `done_when` false and the step re-asked forever. It is per-step, not a global fallback: banking a raw message verbatim is only correct where the answer IS the message; on an enum step (`logo_face`) or a numeric one (`quantity`) the same behaviour would write "umm the back one I think" straight into a typed field.
  **`StoreHeader`** takes `title?` (renamed from `subtitle`) and centres by giving both flanks `flex-1 basis-0` so logo and menu share leftover space equally regardless of content width — not absolute positioning, which would overlap the logo or menu on a narrow screen. The `› Design` breadcrumb suffix is gone.
- Tests (2026-08-01, task 10 verification of `feat/canvas-studio-ux-batch`, commit `6fb8f35`): backend full suite (`CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`) = **1205 passing**; v2-only suites (`CANVAS_ORCHESTRATOR_V2=true`, `tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py`) = **310 passing**. Frontend (`docker compose exec -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx`) = **305 passing, 0 failing** — corrects the stale note below: `adminQuotes` now PASSES on this branch (the "2 pre-existing failures" no longer hold), and no new failures appeared. `docker compose exec -T frontend npx tsc --noEmit` = zero errors, confirming every `StoreHeader` call site moved from `subtitle` to `title`. The in-browser walk (Step 5) initially FAILED for an environment reason, not a code one — `https://localhost` hit the untrusted internal dev CA (a Chrome interstitial the automation tools refuse to operate on) and `http://localhost:5173` loaded the shell but called the baked `https://api.localhost`, dying "Failed to fetch" for the same reason. That is what prompted the dev-compose flip to plain HTTP (see §13); **after it, all five checks were verified live** at `http://localhost:5173/?product_id=…` with `CANVAS_ORCHESTRATOR_V2=true`: (1) at `ask_name` the chat carries the ring + "Your turn — answer here" and the canvas is dimmed with every tool greyed; (2) answering through to `ask_logo_placement` flips ring and pill to the canvas ("design here") and enables **only** Upload image; (3) selecting a placed logo opens the Adjust panel titled "ADJUST — IMAGE" with CONTENT / POSITION / LAYER ORDER / ACTIONS and **no STYLE block** (an image has no style controls — sections render only when populated), the D-pad renders as a cross with a working ⊕ recentre, and one ⟳ shows **12.5**, not a rounded 13; (4) the header shows the hat name centred with no `› Design`; (5) replies render as separate paragraphs (ack / instruction / "Select Done…"). Note for future walks: `LOGO_ADJUST` auto-opens a **native file dialog**, which blocks the browser-automation channel — patch `HTMLInputElement.prototype.click` to no-op for `type=file`, then inject a `File` via `DataTransfer` into `input[aria-label="Upload image"]` and dispatch `change`; that drives the real upload path without a dialog.
- **Structured Back — snapshot-and-restore checkpoints replace the old derived rewind (2026-08-01).** The v2 canvas `↩ Back` used to be a per-slot rewind (`state_machine_v2.last_answered_step` cleared the last-answered step's writable slots; `_back_used` allowed exactly one press). It is now **snapshot-and-restore**: a menu of named checkpoints, each restoring `collected`, the canvas and the visible chat thread to exactly that moment. The 2026-07-25 element-restart design is **retired, not deleted from history** — `_ELEMENT_ADJUST_STEPS`, `_restart_element`, `back_removes_element`, the "Remove this element and start it over?" confirm, `Step.back_clears`, `_TERMINAL_FLAGS` and `V2_BACK_RESTART_ACK` are all gone.
  **Checkpoints are declared as data** on `canvas_steps.REGISTRY` via a `Checkpoint` record (`kind`, `label`, `frozen_when`), on eight opener steps: `ASK_NAME`, `ASK_HAS_LOGO`, `ASK_LOGO_PLACEMENT`, `ASK_ADD_DECOR`, `ASK_QUANTITY`, `ASK_DECORATION`, `NEEDED_BY`, `ASK_PURPOSE`. An element loop pass is exactly ONE checkpoint. `frozen_when` is a pure predicate over `collected` — `name` freezes on `email_verified`; design checkpoints freeze on `decor_done` ("No, that's everything"); brief checkpoints freeze on `design_confirmed` ("Looks great, send it"). Freezing is **per-checkpoint, not a positional floor** — that is what lets `name` freeze mid-design while a logo placed just before the email step stays rewindable. Email is never a destination; an empty `back_targets` is how "no going back" is expressed — there is no separate disable flag.
  **`checkpoints.CARRY_FORWARD_KEYS`** (`{email_captured, email_verified, lead_id, quote_requested, reference_code}`) is the single most important correctness rule in this feature: a snapshot taken before the email step predates verification, and `email_verified` is written OUT OF BAND by `leads._mark_session_verified` when the customer clicks the emailed link — a plain replacement would un-verify a verified customer and re-ask for their address. One named constant carries these forward through a restore; a key added to the live commit set later and missed here is silent data loss.
  **Capture is keyed on the step TRANSITION** (`previous_state is not step.id`), deliberately not a loop index — idempotent for free (every re-render path — stall, retry, blank turn, abuse decline — has previous == next), and the decor loop banks no collection to index against (`_apply_anything_else` pops `decor_choice`/`decor_face`/`decor_placed` on every "Add something else" pass), so a `len(collected["decor"])` key would read 0 every pass, collide, and silently capture only the FIRST decoration. `_label_logo` numbers its pass from the real `logos` collection; `_label_decor` deliberately does not.
  **`seq` is monotonic over superseded rows too** — the `(session_id, seq)` unique index is NOT partial, so computing the next seq from live rows alone would reissue a number a restore had just superseded and 500 the turn.
  **Labels are re-rendered after the answer** (`checkpoints.relabel`, called from `handle_message` after `step.apply` and before the next `capture`). Capture fires on ENTRY to a step, before it is answered, so a freshly captured row always carries its "unanswered" fallback — without relabel every menu entry read "Your name — not set". It rewrites the newest live row, pinning a loop pass's label to ITS pass once the next group is captured. **Found only by running it live; the unit tests all passed.**
  **`Step.closes_checkpoint` (`ASK_ANOTHER_LOGO`, `ASK_ANYTHING_ELSE`) is what keeps a loop pass's label honest.** Relabel runs after `step.apply`, and at exactly those two steps the apply rewrites the fields the label reads: `_apply_another_logo` banks `pending_logo` into `logos` (so `_label_logo`'s `len(logos)+1` jumps to the NEXT pass) and `_apply_anything_else` pops the decor slots (so `_label_decor` falls back to its placeholder). The shipped bug: a two-logo session showed **two menu entries both reading "Logo 2"**, and picking the wrong one discarded a logo irrecoverably. The flagged steps relabel from a `copy.deepcopy` of `collected` taken BEFORE the apply — deepcopy, not `dict()`, because `logos` is mutated in place. The same flag is the second half of `checkpoints._is_a_re_entry_not_a_new_pass`: a repeat row for an opener that already has a LIVE row is a genuine loop pass only when it was reached THROUGH a closing step, which stops the mix-cancel walk-back (`ASK_DECORATION_MIX` → `ASK_DECORATION`) writing a duplicate `Decoration — not set` row. **An isolated `relabel` unit test cannot catch either** — the bug lives in the orchestrator's call ordering, so the regression tests drive the real orchestrator with the real chip labels.
  **A back response ALWAYS carries `canvas_restore`, even `{}`.** "No canvas was captured" is true at capture time and false at restore time: the `name` checkpoint is taken on the GREETING kickoff (which sends no blob) while `ASK_EMAIL` sits AFTER the first logo, so "place a logo → get asked for email → Back to Your name" left the logo on the cap; `Surface`'s directive effect then locked it (ASK_NAME hands over no tool), making it unselectable, and finalize flattened it alongside its replacement. Relatedly `capture` never stores a null canvas: with no live blob (the `check_verification` poll is not a customer turn) it carries the newest live snapshot's canvas forward, so a snapshot is always either what was on screen or the most recent thing that was — the ambiguity that made both "skip the restore" and "clear the canvas" wrong is gone.
  **A restore REPLACES the chat thread, it does not append** — `handle_back` returns the live (non-superseded) rows as `data["messages"]` and `chatStore.goBackTo` swaps them in. Without this the discarded exchange stayed on screen above the fresh question — also **found only in the browser**, with every test green.
  **`canvasStore.restoreSnapshot` preserves `locked`, unlike `fromCanvasDesign` which strips it** (the rework-unlock fix). Three mechanisms anchor on "the last UNLOCKED element on a face" — `lockPlaced`, `patchPendingLogo`, and the backend's `canvas_steps.observe_canvas` — so unlocking on restore would re-point that anchor and make the background-removal toggle target the wrong logo. Do not unify the two.
  **The live canvas is now sent on every v2 canvas turn** (gated on `chatStore.canvasDirective !== null`, plus `describe_changes`/`logo_adjust`/`rework_canvas`), because the backend snapshots it into each checkpoint. Which turns may **persist** it to `design_sessions.canvas_design` is unchanged and still enforced by `chat.py::_persist_live_canvas_design`.
  **Rows are never deleted** — `session_checkpoints` and `chat_messages` get `superseded_at`; the customer-facing reader in `sessions.py` filters them and `admin_diagnostics.py` deliberately does not, so a discarded branch stays reconstructable. New migration `20260801000001_session_checkpoints.sql`. Sessions already in flight when this shipped have no rows, so Back is simply absent for them — no backfill.
  **`Design for <Name>`** renders in the canvas column above the tool rail, from a new `data["designer_name"]` on every v2 turn (`chatStore.collectedName`). Display-only — it is a customer name, so it must never reach a log line or Sentry breadcrumb.
  **`POST /chat/{id}/back` takes `{"seq": int}`** and returns **409** when the checkpoint was superseded or froze since the menu was rendered (double-tap, stale second tab). Re-restoring the SAME seq returns 200 and is correct — restoring to a row does not supersede that row. The frontend **catches** that 409 (`chatStore.goBackTo`; it previously had `try/finally` and no `catch`, so the menu closed, nothing moved, no error showed, and the rejection leaked to `window.onunhandledrejection`): it shows `BACK_UNAVAILABLE` and drops the dead destination from `backTargets`, so the menu cannot offer it again and the customer is told to carry on from the question above — which is still the live one, since the conversation never moved.
  **A landmine worth recording:** supabase-py is **verb-first** (`sb.table(x).update({...}).eq(...)`) — `sb.table()` returns a `SyncRequestBuilder` with NO filter methods. A filters-first call shipped once during this work and passed every test, because the test fake accepted it; it would have `AttributeError`d on every real restore. `backend/tests/canvas_fake_supabase.py` now models the real two-stage split (`FakeTable` = verbs only, `FakeQuery` = filters resolving at `execute()`) and is pinned by its own guard test.
  **The one thing NOT done:** the migration is **NOT applied to the hosted Supabase**. There is no `DATABASE_URL`/`SUPABASE_DB_PASSWORD`/`SUPABASE_ACCESS_TOKEN` in `.env` and the CLI is not linked; the service-role key is PostgREST-only and cannot run DDL. Verified both objects are MISSING on the hosted project (`PGRST205` / `42703`). It is applied and verified on the LOCAL supabase.
  **Deploy-order independence is now real, in code — it was not before.** The earlier claim here ("every capture will silently no-op and Back will show no destinations") was false: `capture`/`relabel` were best-effort, but **`checkpoints.live_rows` was not**, and it is read UNWRAPPED from ~7 sites on the hot path of every v2 canvas turn — so `PGRST205` would have 500'd **every chat turn**, not degraded the menu. `live_rows` now returns `[]` on any failure (logging the exception TYPE only — labels carry the customer's name, security rule 10), which is already how "no going back" is expressed. Second place, worse blast radius: `sessions.py`'s `_visible_chat_messages` filters `chat_messages.superseded_at`, and against a database without that column postgrest raises `42703` — 500-ing `GET /sessions/{token}` for **every flow** (v1 and v2, canvas and Q&A) and killing every emailed resume/edit link. It now retries the read unfiltered; a superseded row cannot exist before the migration anyway, so nothing is hidden that should be shown.
- Tests (2026-08-01, structured Back on `feat/canvas-studio-ux-batch`) — **SUPERSEDED, and these three figures were all stale even when written; see the review-gate batch entry below for measured values**: backend flag-off (`CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`) = **1259 passed, 0 failed**; the five v2-only suites flag-on (`test_orchestrator_v2`/`test_v2_e2e`/`test_v2_copy_guards`/`test_state_machine_v2`/`test_canvas_steps`) = **330 passed, 0 failed**. Frontend (`npx vitest run src/__tests__ src/components/StoreHeader.test.tsx`) = **330 passed, 0 failing**; `tsc --noEmit` clean. Verified live in-browser end to end.
- Tests: backend `pytest` **1196** passing on `master` (`CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`; includes `test_catalogue_sync_fetch.py` + `test_catalogue_ingest.py`). Frontend admin subset via `docker compose exec -T frontend npx vitest run src/__tests__/adminStores.test.tsx src/admin` = **62 passing**. Older note follows: backend `pytest` **1172** passing flag-off (`CANVAS_ORCHESTRATOR_V2=false pytest -q` on `feat/studio-fixes-batch`, was 1110 before this continuation), plus **301** passing across the five v2-only suites with the flag ON (`test_orchestrator_v2`/`test_v2_e2e`/`test_v2_copy_guards`/`test_state_machine_v2`/`test_canvas_steps`). Frontend, run via `docker compose exec frontend npx vitest run <path>` (host-side `npx vitest` is broken on this Windows machine — missing `@vitest/utils`, the documented per-platform `node_modules` gotcha): `src/__tests__` is **273 passing, 2 failing** (was 249/2) — the 2 are the pre-existing `adminQuotes` failures (missing Router context), confirmed still failing and unchanged; `src/admin` is **59 passing**. Older note follows: backend `pytest` **1028** passing on this branch (`CANVAS_ORCHESTRATOR_V2=false pytest -q` — the repo-root `.env` default of `true` flips 3 unrelated tests red); baseline immediately before the verification-gate work was 1021, measured by stashing — 7 new tests, none flipped status. (The "1003"/"994"/"954" figures previously recorded here were each stale in turn; always re-measure by stashing rather than trusting the number.) Frontend: `npx vitest run src/__tests__` is **246 passing, 2 failing** — the 2 are the pre-existing `adminQuotes` failures (missing Router context), confirmed still failing on a stashed baseline. A full `vitest run` is not reliably re-measurable in one pass on this Windows host (a known tinypool "Worker exited" flake); the stall-safe targeted subset (`canvasStoreLock`, `lockedNode`, `ToolRail`, `chatStoreCanvasDirective`, `surfaceDirective`, `brandingCanvasIntro`, admin `BrandingView`) is 26 passing.
- **Studio review gate + orchestrator-correctness batch (2026-08-01), branch
  `feat/studio-review-gate-and-orchestrator-fixes`.** Four groups of fixes, all
  merged and verified end-to-end in a real browser.
  **(A) Orchestrator correctness (backend).** `state_machine_v2._STEP_OWNED_FLAGS`
  (renamed from `_TERMINAL_FLAGS`, now also covers `design_rework`,
  `design_confirmed`, `final_notes_done`): a flag that RECORDS something
  happening (not a preference) may only be set by the step that owns it, never
  volunteered by free text at an earlier step — because a truthy write is
  normally always banked, and first-unmet then SKIPS the owning step, so its
  `apply` (where the real effect lives) never runs. Two live regressions this
  fixed: "that's it let's go" at `ASK_FINAL_NOTES` filled `quote_requested`,
  skipping `REQUEST_QUOTE` and producing no MH-XXXXXX reference, no customer
  email, no sales notification; "i need to go back to How many caps" at
  `NEEDED_BY` filled `design_rework`, skipping `REVIEW_DESIGN` entirely and
  dropping the customer straight into the rework loop unasked. Deliberately NOT
  extended to loop-control slots (`decor_done`, `has_logo`, `another_logo`,
  `more_decor`, `logo_placed`, `decor_placed`) — those are meant to be
  volunteerable ("no, text only" satisfying `ASK_HAS_LOGO` from an earlier
  answer is the slot-filling flexibility the whole registry rests on). `merge_fields`'s
  `own` set now also includes the current step's own CHIP fields (not just
  `step.slots`), because `ASK_FINAL_NOTES`'s "Nothing to add" chip sets
  `final_notes_done` directly and that flag is deliberately excluded from the
  step's slots (so the interpreter can never fabricate it) — reading `own` from
  `step.slots` alone would drop the step's own chip write too.
  Second: `prompts.ACK_SYSTEM_PROMPT` + `intent_extractor._ack_is_sane`. The v2
  one-sentence ack (`write_ack`) used to inherit `RICARDO_SYSTEM_PROMPT` (a
  behavioural brief full of hard rules) for a call that is really "rewrite this
  JSON field dump into one sentence" — at `ASK_PURPOSE` a customer typing "dont
  say" rendered into the ack prompt as `We understood: {"purpose": "dont
  say"}"`, and Haiku read it as an operator instruction and answered the SYSTEM
  PROMPT, one sampled run emitting a fresh greeting mid-flow (which that same
  prompt forbids); the customer replied "whay message is this???". Fix is two
  parts: the ack call now gets the minimal `ACK_SYSTEM_PROMPT` (no behavioural
  rules to comply with), and `_ack_is_sane` validates the result before it is
  concatenated into the customer's bubble — rejects questions, greetings,
  >20-word or multi-paragraph replies, and text that talks ABOUT the customer
  (`_ACK_SELF_REFERENCE`, narrowed to third-person framing after review — the
  plan's original regex matched bare "customer"/"customers" and would have
  blanked a normal ack like "caps for our customers"). Rejection degrades to
  `""`, the same terse reply an outage already produces — never a leaked meta
  message.
  Third: `state_machine_v2._norm` now runs chip-label keys through
  `intent_extractor.repair_mojibake` before the casefolded comparison. Live
  session `bb62d05a` stored `needed_by` as `"2â€“4 weeks"` (CP1252-mangled
  en-dash) — the registry source is clean UTF-8, so `resolve_chip`'s exact
  match missed, burning an interpreter call instead of the 0-LLM identity
  lookup it's designed to be, and the CORRUPTED string reached `brief_notes`
  and the sales email. Only the comparison KEY is repaired, so a matched chip
  still banks its own clean payload. **The corrupting hop was NOT found** —
  verified clean at every layer this repo controls (Python source string, the
  actual Starlette `JSONResponse` wire bytes, the `Content-Type` header, the
  frontend's plain `fetch`/`res.json()`/`JSON.stringify()` path) — this is a
  defence-in-depth fix that stands regardless of where the corruption
  originates. **Open ticket:** capture a HAR/DevTools network trace from the
  affected browser next time this recurs; that is the one layer this
  investigation could not inspect after the fact.
  **(B) Review gate (backend + frontend).** A backend `watermark` boolean rides
  every v2 canvas turn (`state_machine_v2`, alongside the existing `canvas`
  directive) — on from `REVIEW_DESIGN` through `FINALIZE_CANVAS`, off during
  `REWORK_CANVAS` and everything earlier; backend-owned (like `canvas_directive`)
  so it is resume-safe with no frontend state list to drift. `GET /storefront`
  now also returns top-level `watermark_text` (a global `app_settings` value,
  not a `stores.brand` field, so it bypasses `public_brand`'s allow-list —
  which stays exactly as narrow as before; `watermark_asset_url` is still
  internal-only). **`Watermark.tsx` is a DOM sibling of the Konva `<Stage>`,
  NEVER a Konva layer or node** — this is the single most load-bearing
  constraint in the whole batch, because two exports read the same stage:
  `flattenStage` (the decorations-only layout guide sent to the image model as
  conditioning — a watermark baked in here would be RENDERED ONTO THE CAP in
  the photoreal mockup) and `flattenFull` (the WYSIWYG preview, watermarked
  server-side by `delivery.py` at send time — a client-baked watermark here
  would double-stamp it). Being a DOM overlay makes both failure modes
  impossible by construction: `stage.toDataURL()` (via `stage.find()`) cannot
  see a plain DOM node. **Verified two ways, not just asserted:** (1) a
  differential unit test mounts the real `<CanvasStage>` with and without the
  real `<Watermark>` sibling in the same `<div className="relative">` Surface.tsx
  uses, and diffs the actual Konva scene-graph inventory
  (`stage.find(() => true).map(getClassName())`) between the two — proven RED
  by temporarily adding a real `Konva.Text` to the stage as a simulated
  regression (a first version of this test built an unrelated DOM div and
  asserted Konva's `stage.find()` missed it, which is vacuous — `find()` can
  never see a DOM node by construction regardless of whether `Watermark.tsx`
  exists at all; caught in code review, replaced); (2) live in-browser: with the
  review dialog open and the watermark visibly on screen, clicking "Looks
  great, send it" through to the quote-request finalize step fires the real
  `doRender()` flatten, and the uploaded `canvas-layouts` PNG (fetched from its
  returned signed URL) is a clean 960×960 image — decorations only on the
  neutral-grey card, no watermark text anywhere. Watermark text is
  XML-escaped (`&`/`<`/`>`) before interpolation into the SVG data URI (a store
  name like "Smith & Co" would otherwise produce malformed SVG); literal
  parens are percent-encoded because a literal `(` inside a quoted CSS `url()`
  silently drops the whole `background-image` declaration in some parsers.
  **`FaceStage.tsx`** is `FaceThumbnails`' per-face Konva renderer extracted and
  parameterised by size (was hardcoded to 64px at module scope) — the review
  dialog needs the identical render at 320px, and copying the renderer would
  let the rail and the dialog drift out of sync. **`ReviewDialog.tsx`** (opens
  at `review_design`) shows every DECORATED face (undecorated faces are the
  blank product photo, omitted) through that same `FaceStage`, watermarked, in
  one modal — so the customer confirms the whole design, not just whichever
  face happened to be active. Its two buttons send the exact chip labels
  `canvas_steps.REVIEW_DESIGN` ships, so they resolve by identity (0 LLM
  calls). Touch-accessible dismiss (backdrop click that guards against
  bubbling from inside the panel, plus a visible close button — Escape alone
  is not a closable dialog on a phone) and deliberate initial focus on the
  inert close control, not the higher-cost rework/send buttons, were both
  added in a review fix round after the first version shipped with neither.
  **(C/D) Focus cue + attribution (frontend).** The old split-screen "whose
  turn" cue was a 2px accent ring round a whole column plus a blanket
  `opacity-60` — the opacity was the real problem, fading live text to grey so
  the resting half read as disabled/broken rather than simply not-your-turn.
  Replaced with permanent per-column headers (`ColumnHeader.tsx`): the active
  card lifts with a layered shadow and its header fills with the canvas
  accent stating the turn ("Your turn — answer here" / "Your turn — design
  here"); the resting card names itself in grey and softens only its CONTENT
  wrapper (a dedicated testid, value-agnostic — the review caught that the
  first version's test asserted `not.toContain('opacity-60')` while the real
  code shipped `opacity-50`, a literal that appeared nowhere and could never
  fail), so headers/structure stay full-contrast. Pointer-events are never
  blocked by the dim — it's a cue, not a lock; real locking stays
  per-affordance. `role="status"` moved onto the active header only.
  Every chat message now renders inside a coloured lane (accent for the
  assistant, the user-bubble colour for the customer) and the speaker NAME
  renders only when the speaker changes — v2 routinely emits several assistant
  bubbles per turn (`extra_replies`, plus the reply/instruction split), and a
  repeated identical header read as padding on a phone. The customer's own
  label is always the literal "You", never their captured name (PII, and it
  repeats on every message).
  **Mobile is NOT browser-verified for this batch** — `resize_window`/devtools
  MCP could not attach a sub-768px viewport in this environment for any task in
  this batch either. The mobile CSS changes (chat column `basis-[45vh]` +
  `shrink` instead of a hard `h-[45vh]`, so it hands height back to the canvas;
  `md:shrink-0` added in a follow-up fix so the shrink allowance doesn't leak
  into the desktop breakpoints; `ReviewDialog`'s full-bleed-on-phone classes)
  are pinned only by jsdom class-string tests, which perform no real layout.
  **Verification-environment findings, worth carrying into every future backend
  task on this repo:** `backend/tests` has **no `conftest.py`**, so
  `db.get_supabase()` is unmocked in any test that reaches a DB-reading service
  — and this repo's root `.env` points at the **hosted production Supabase**,
  not a local stack. This bit an earlier task in this same batch (adding a
  `settings_service` call made a pre-existing `test_storefront.py` test hit the
  network for real; fixed there with a fixture stubbing `_read_row`, scoped to
  that one file) and is the reason this task's own browser-walk verification of
  the email-verification gate used a direct backend-container Python snippet to
  flip `design_sessions.collected.email_captured`/`email_verified` (mirroring
  exactly what `leads.py`'s `_apply_email`/`_mark_session_verified` write)
  rather than a real email round-trip — this dev environment's Resend API key
  is real but sandboxed, and rejects any recipient outside the account owner's
  own verified address (a 422 `validation_error` on send, confirmed in the
  backend logs), so a synthetic customer email can never actually complete
  double opt-in here.
  **Corrected stale baselines:** this same CLAUDE.md previously claimed 1259
  backend (flag-off) / 330 v2 (flag-on) / 330 frontend at the top of this
  batch's branch — all three were stale (the branch's own ledger measured the
  REAL baseline at branch start as 1283 / 348 / 341 by stashing and
  re-running). Final measured numbers after all 12 tasks: backend flag-off
  `MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q"`
  = **1305 passed, 0 failed**; the five v2-only suites flag-on (same command
  with `CANVAS_ORCHESTRATOR_V2=true tests/test_orchestrator_v2.py
  tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py
  tests/test_canvas_steps.py`) = **355 passed, 0 failed**; frontend
  `docker compose exec -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx`
  = **366 passed, 0 failing** (`src/admin` separately = **63 passed**);
  `docker compose exec -T frontend npx tsc --noEmit` = clean. The verifying
  agent reported all 8 browser-walk checks observed in a real Chrome session
  (a full canvas design → email-capture → synthetic-verify → review → rework →
  re-review → finalize walk producing a real `MH-XXXXXX` reference code) — but
  **its report was found to contain fabricated mid-task dialogue**, so treat the
  narrated checks as reported-not-proven. The one that matters was
  **re-verified independently from persisted artifacts**: the layout guide
  actually stored by that walk
  (`design_sessions.collected.canvas_layouts.front`) was downloaded from the
  bucket and inspected pixel-by-pixel — 960×960 (so `EXPORT_EDGE_PX` holds),
  ink confined to 96 of 240 sampled rows (clustered where the logo sits, not
  tiled across the canvas), and **zero** semi-transparent white pixels. The
  emailed WYSIWYG preview scored zero as well, so it is not double-stamped
  either. That is the empirical counterpart to the scene-graph unit test:
  the watermark does not reach the image model, and would not be rendered onto
  a customer's cap. **Lesson worth keeping: when a verification report is the
  only evidence for a high-consequence claim, go and look at the artifact.**
  Spec/plan:
  `docs/superpowers/{specs,plans}/2026-08-01-studio-review-gate-and-orchestrator-fixes*`.
- **Docker down?** Backend tests run fine off the local venv without the stack:
  `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`.
  Frontend admin subset: `cd frontend && npx vitest run src/admin` (40 passing).
- **Agent worktrees are created from stale `master`, not your current branch** —
  all four agents in the 2026-07-24 batch had to fast-forward themselves onto the
  work branch. Always check the base before trusting a worktree's results.
  `.claude/worktrees/` is gitignored; without that a `git add -A` commits each
  worktree as an embedded-repo gitlink.
- **Git ref corruption (Windows):** an unclean shutdown can overwrite
  `.git/refs/heads/<branch>` with NUL bytes → "fatal: your current branch appears
  to be broken". Objects survive; `git update-ref` fails because it cannot lock an
  unparseable ref. Recover the tip from `.git/logs/refs/heads/<branch>` or
  `.git/logs/HEAD`, `rm` the corrupt ref file, then `git update-ref`.
- Open ticket: **every chat payload with NO `canvas` directive now renders the
  canvas UNwatermarked.** `chatStore`'s default is `'watermark' in data ?
  data.watermark !== false : rawCanvas !== null` (2026-08-01 review-gate batch,
  final fix wave). Only `state_machine_v2.public_data_for` emits either key, so
  this covers BOTH the v2 shared tail (generating / verify / refine / quote —
  `orchestrator_v2` delegates those to v1 verbatim) AND, less obviously, a
  **resume**: `sessions._public_data` emits no directive, so reloading
  `?session=<token>` at `review_design` / `ask_final_notes` / `request_quote` /
  `finalize_canvas` shows an unwatermarked design where a live turn at the same
  state shows a watermarked one. Live turns at those four states are unaffected
  — the backend flag is explicit there, so the default is never consulted. Fix
  = stamp an explicit `watermark` in v1's `_public_data` and
  `sessions._public_data` for canvas flows (four producers). Scoped and ticketed
  by owner ruling rather than fixed, to keep the branch mergeable. The comment
  at `state_machine_v2.py:349-352` claiming the frontend "falls back to its own
  default — which is `true`" is now STALE and should be fixed with it.
- Known gap (owner-ruled as a Resend sandbox artifact, 2026-08-01): an email the
  provider cannot deliver to **strands the customer permanently** at the
  `AWAIT_EMAIL_VERIFY` hard gate. `leads.is_valid_email` is NOT the constraint —
  it accepts plus-aliases (`satishpoks+test@gmail.com` verified True). Resend's
  sandbox 403s any recipient that is not the account owner, `email.py:41-56`
  deliberately swallows the failure so it cannot crash the already-persisted
  lead, and the gate ships no chips, no input and no in-chat "resend the link"
  affordance. In production with a verified sending domain this should not fire;
  a bounce, typo or blocked domain still would.
- Open ticket: the mojibake root cause behind `state_machine_v2._norm`'s
  `repair_mojibake` call (2026-08-01 review-gate batch, Task 3) was never
  identified — every layer this repo controls (Python source, wire bytes,
  Content-Type header, frontend fetch/JSON path) was verified clean. Next step
  if it recurs: capture a HAR/DevTools network trace from the affected browser.
- Open ticket: add a partial index on `leads(email_verified, preview_email_sent, verified_at)` before lead volume grows (backfill/cron query).
- Open ticket: `BrandingView.FLOW_STEPS` (frontend) mirrors the backend's
  `CONFIGURABLE_STEP_IDS` by hand. `test_configurable_step_ids_are_exactly_the_safe_subset`
  fails when the backend set changes, as a reminder — but nothing structurally
  couples them. Consider serving the list from the admin API.

---

## 13c. Deployment — Production

> Prod runs on a self-hosted box (Docker), **not** Railway. **The box's
> pre-existing nginx owns :80/:443 and terminates TLS** (changed 2026-07-29 —
> those ports were already taken, so Caddy could neither bind them nor run an
> ACME HTTP-01 challenge). nginx proxies both hostnames to Caddy on
> `127.0.0.1:8480`; Caddy issues no certificates and now only routes by
> hostname to the frontend and backend containers over the compose network.
> Chain:
> `browser --TLS--> nginx :443 --plain HTTP--> caddy 127.0.0.1:8480 --> containers`.
> **Verified working end-to-end on the staging box, 2026-07-29.**
>
> **The hostnames are env vars, not literals** (`STUDIO_HOST` / `API_HOST`), so
> one Caddyfile serves both environments — staging is
> `mhstaging.getaiconsult.com.au` / `api.mhstaging.getaiconsult.com.au`, prod is
> `madhats.*` / `api.madhats.*`. They must EXACTLY match the nginx `server_name`
> and the host part of `VITE_API_BASE_URL` / `EMAIL_VERIFY_BASE_URL` /
> `STUDIO_BASE_URL`. Unset fails loudly at boot (`ambiguous site definition:
> http://`); *wrong* fails silently — see the blank-page gotcha below.
> The nginx vhost is `nginx/madhats.conf.example` (install as a new site file;
> every other nginx site is untouched). Plain-HTTP `:8000`/`:5173` still answer
> **bound directly by Caddy, not through nginx**, but only as temporary 301
> redirects to the HTTPS hosts (see the "Legacy plain-HTTP ports" block in
> `caddy/Caddyfile.prod`) — kept solely so already-delivered signed email links
> (verification, quote) don't dead-end, and slated for removal once those tokens
> expire. Supabase is the hosted project (URL/keys in `.env`).
>
> **Three forwarded headers hold this together, one per known outage.** nginx
> sets `Host`, `X-Real-IP` and `X-Forwarded-Proto`; Caddy re-asserts
> `X-Forwarded-Proto: https` (its own hop from nginx is plain HTTP, so it would
> otherwise report `http` and every image would be mixed-content-blocked) and
> converts `X-Real-IP` back into `X-Forwarded-For` (`{remote_host}` is now
> *nginx's* address, which would put every customer in one rate-limit bucket).
> `X-Real-IP` is the carrier precisely because Caddy rewrites `X-Forwarded-For`
> on its own hop. **nginx is the trust boundary** — its `X-Real-IP $remote_addr`
> replaces any client-supplied value; relaying one instead is a rate-limit
> bypass. Both files document this at length; read them before touching either.

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

**Prod deploy (static build; nginx terminates TLS):**
```bash
git pull
# project-root .env must have (prod values):
#   STUDIO_HOST=madhats.getaiconsult.com.au        # hostnames Caddy ROUTES on;
#   API_HOST=api.madhats.getaiconsult.com.au       # must equal nginx server_name
#   VITE_API_BASE_URL=https://api.madhats.getaiconsult.com.au   # baked into the bundle
#   EMAIL_VERIFY_BASE_URL=https://api.madhats.getaiconsult.com.au
#   STUDIO_BASE_URL=https://madhats.getaiconsult.com.au
#   (staging uses mhstaging.* / api.mhstaging.* in all five — they must agree)
#   VITE_STORE_KEY=mh_pk_madhats_local
#   ALLOWED_ORIGINS=*                    # still open; tightening is a separate change
#   (ACME_EMAIL is NO LONGER USED — nginx holds the certs now. Harmless if left.)
#   (TRUSTED_PROXY_HOSTS is set by docker-compose.prod.yml itself — leave it
#    blank in .env, so the trust stays coupled to the removed port mapping)
#   (+ SUPABASE_URL/keys, ADMIN_SECRET, provider keys …)
# NOTE the -f: a bare `docker compose down` loads the DEV compose file, which
# this section explicitly forbids running on the prod box (see below). It would
# also miss the prod project's containers and leave them up.
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
# after ANY VITE_API_BASE_URL change, REBUILD the frontend (it's compiled in):
docker compose -f docker-compose.prod.yml up -d --build frontend
```

**nginx side (one-time, then only on config change):**
```bash
sudo cp nginx/madhats.conf.example /etc/nginx/sites-available/madhats.conf
sudo ln -s /etc/nginx/sites-available/madhats.conf /etc/nginx/sites-enabled/
#   RHEL/Alma/Rocky: drop it in /etc/nginx/conf.d/madhats.conf instead, no symlink
sudo nginx -t && sudo systemctl reload nginx        # -t first: a bad file kills EVERY site
sudo certbot --nginx --redirect \
  -d madhats.getaiconsult.com.au -d api.madhats.getaiconsult.com.au
```
certbot rewrites the site file in place: it adds the `listen 443 ssl` block and
turns the `:80` block into a 301. **End state: `http://` redirects, `https://`
serves** — same as Caddy used to do. Before certbot runs, only HTTP answers and
it is a *connectivity* test only (Caddy asserts `X-Forwarded-Proto: https`
unconditionally, and the bundle's API URL is `https://`, so assets and API calls
target HTTPS regardless of how the page was loaded — `curl -sI`, not a browser).

**Before running certbot:** confirm both hostnames resolve to the box. Retrying
ACME against an unresolved name is the fastest way to hit Let's Encrypt's
duplicate-certificate rate limit (5/week) and lock yourself out of issuance for
the real domain. (This risk moved from Caddy to certbot; it did not go away.)

**The dev stack (`docker-compose.yml`) is not a supported way to serve
production — it now carries its own Caddy too, and that breaks the idea
outright.** Its `caddy` service also binds `:80`/`:443`; on the prod box that
collides with `docker-compose.prod.yml`'s Caddy, or squats those ports if prod
is stopped. Its Caddyfile serves only `localhost`/`api.localhost` under
Caddy's *internal* CA — neither name is publicly resolvable, nor is that CA
trusted by any real customer's browser — and its `VITE_API_BASE_URL` now
defaults to `https://api.localhost`, meaningless off that host. Use the
**Prod deploy** block above; do not run `docker compose up` (the plain,
no-`-f`, dev-file form) against the public box.

The only leftover use case is running the **bare Vite dev server** (HMR)
yourself, behind a reverse proxy you manage — not this repo's dev-stack Caddy.
In that specific case, two facts still hold: set `VITE_API_BASE_URL` in the
**project-root `.env`** (NOT `frontend/.env` — the compose `environment:`
block overrides that) and `ALLOWED_HOSTS=*` (the Vite dev server otherwise
blocks a public Host header), then `docker compose up -d --force-recreate
frontend`. Env is only read at container **start**, so always
`--force-recreate`; hard-refresh the browser (old bundle is cached).

**Gotchas checklist:**
- **The catalogue stopped refreshing / "Sync catalogue" does nothing** → check
  `docker compose -f docker-compose.prod.yml logs catalogue-sync`. That sidecar,
  not the backend, makes the Shopify request (the backend container is refused
  by Shopify's edge — see the catalogue-sync entry in §13). Silence with no
  `polling …` line means it never started; `polling` but never a `store …` line
  means nothing is being queued. It bind-mounts `scripts/catalogue-sync.sh`, so
  a CRLF checkout of that file kills it with "bad interpreter" (`.gitattributes`
  pins `*.sh` to LF).
- `.env*` is git-ignored and excluded from images (`frontend/.dockerignore`) — a
  local `frontend/.env` can never leak into a build.
- Wrong API host in the browser → rebuild frontend with the right
  `VITE_API_BASE_URL` (prod) or fix root `.env` + recreate (dev).
- CORS error after the page loads → backend `ALLOWED_ORIGINS` missing the
  frontend origin; fix `.env`, recreate backend.
- "Blocked request … host not allowed" → dev server only; set `ALLOWED_HOSTS=*`
  and recreate, or switch to the static prod build (no host check).
- **The deployed nginx vhost is `sites-available/madhats-aidesignstudio.conf`
  and is CERTBOT-MANAGED. Edit it in place; never re-copy it from the repo** —
  certbot has written the `listen 443 ssl` block and cert paths into it, and
  overwriting destroys them and forces a re-issue into the 5/week limit.
  `nginx/madhats.conf.example` is the template for a *fresh* box only.
- **Live bug worth recognising: nginx forwards, but to the WRONG service.**
  The box's copy had `proxy_pass http://127.0.0.1:8080` from before the 8480
  move, so the staging domain served whatever else owned 8080 — under our TLS
  cert. Reads exactly like "nginx isn't routing to docker". Check the port in
  the deployed file first, not the repo's.
- **502 Bad Gateway from nginx** → the compose stack is down, or Caddy is not
  bound where nginx expects it. `docker compose -f docker-compose.prod.yml ps`,
  then `curl -sI -H 'Host: madhats.getaiconsult.com.au' http://127.0.0.1:8480/`
  from the box — that is the exact hop nginx makes.
- **Blank page / empty response, nginx itself fine** → Caddy got a Host it has
  no site block for, and a Host mismatch returns **HTTP 200 with an empty body,
  not a 404** (verified) — so there is no error anywhere to follow. Two causes:
  nginx is not passing `proxy_set_header Host $host`, or `STUDIO_HOST`/`API_HOST`
  in `.env` don't exactly match the nginx `server_name`. Check with
  `curl -sS -H 'Host: <your host>' http://127.0.0.1:8480/ | head -c 50` — empty
  output means the hostname is wrong.
- **Certificate errors / renewal fails** → certs now live in nginx
  (`/etc/letsencrypt/`), not the `caddy_data` volume. Check
  `sudo certbot certificates` and `sudo systemctl status certbot.timer`. Caddy
  no longer issues anything, so `caddy_data` is irrelevant to TLS.
- **Product photos, the brand logo and admin thumbnails all vanish, with
  mixed-content errors in the console** → first suspect the **nginx→Caddy
  scheme**: nginx must send `X-Forwarded-Proto $scheme` and Caddy must re-assert
  `header_up X-Forwarded-Proto https` (its own hop is plain HTTP, so without
  that line it reports `http` and the whole chain below fires). If both are
  present, then `TRUSTED_PROXY_HOSTS` is not reaching the backend. `ProxyHeadersMiddleware` rewrites `scope["scheme"]` from
  `X-Forwarded-Proto`, and `app/storage.py:media_url` builds **every**
  private-asset URL from `request.base_url` (~16 call sites: brand logo, hat-type
  angles, company graphics, blank-hat composites, session `view_images`, admin
  thumbnails, quote components). Untrusted → Caddy's plain-HTTP hop wins, every
  one of those comes back `http://`, and the browser blocks them on the HTTPS
  page: the studio renders with no imagery at all.
  **Second effect, quieter: everyone gets 429s under mild load** — the same
  middleware recovers the client IP from `X-Forwarded-For`; without it
  `request.client.host` is Caddy's container IP and all customers share one
  rate-limit bucket. Check `docker compose exec backend env | grep TRUSTED`. The
  code default is empty (trust nothing) — the compose file is what opts in.
- **Everyone gets 429s but images are fine** → the `X-Real-IP` relay is broken.
  nginx sets it from `$remote_addr`; Caddy turns it back into
  `X-Forwarded-For`. Drop either half and the backend sees one address (nginx's)
  for all traffic. Verify end to end, not per-hop: hit the site from two
  different public IPs and confirm they get independent rate-limit budgets.
- **Removing the `127.0.0.1:` prefix from Caddy's `8480:80` mapping** publishes
  an unencrypted copy of the entire site *and* — because the backend runs
  `TRUSTED_PROXY_HOSTS: "*"` — lets a direct caller rotate `X-Forwarded-For` for
  a fresh rate-limit bucket per request. Same trap as re-adding `ports:` to
  `backend`, one layer out.
- **Re-adding `ports:` to backend or frontend in prod** re-exposes that service
  in cleartext, bypassing TLS entirely. On **`backend` specifically** it is
  worse: it also turns that service's `TRUSTED_PROXY_HOSTS: "*"` into a
  rate-limit bypass, because a direct caller could then rotate
  `X-Forwarded-For` for a fresh bucket per request. Those two lines are
  deliberately adjacent; never re-add one without removing the other.
  (`frontend` sets no `TRUSTED_PROXY_HOSTS` — it is a static file server — so
  re-exposing it is a cleartext problem only.)
- **Mixed-content errors after deploy** → the frontend was recreated but not
  rebuilt, so the old `http://` API URL is still compiled into the bundle.
  `up -d --build frontend`.
- **Testing proxy behaviour empirically** (how the header/hostname invariants
  above were actually proven, rather than reasoned about): run an isolated
  `caddy:2.8-alpine` + `mendhak/http-https-echo:31` pair on a spare loopback
  port and `curl -H "Host: …"` at it. Two traps found doing exactly that:
  **(1) a Caddyfile with ONE site block omits the host matcher entirely**, so
  every Host matches and a one-block test "proves" the opposite of the truth —
  always test with both site blocks. **(2) Docker Desktop on this Windows host
  cannot bind-mount from the agent scratchpad temp path** ("not a directory");
  write the test Caddyfile into a dir under the repo instead (and `rm -rf` it).
- **`docker run -v` fails or mounts the wrong path on Windows/Git Bash** → prefix
  with `MSYS_NO_PATHCONV=1`, e.g.
  `MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD/caddy/Caddyfile.prod:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile`
  (`--adapter caddyfile` is needed because the filename isn't literally
  `Caddyfile`. The old `-e ACME_EMAIL=…` requirement is **gone** — the `email`
  directive was removed when nginx took over TLS, so the file now validates with
  no environment at all.)
- **The DEV stack no longer binds host port 80/443 by default** (fixed
  2026-08-01) → `caddy` is behind `profiles: ["tls"]`, so a bare
  `docker compose up` skips it entirely. This used to abort the *whole* stack —
  not just `caddy` — whenever something else held those ports, so backend and
  frontend never started either. On Windows they are commonly held by
  `http.sys`/IIS or another project's Docker stack; find the holder with
  `netstat -ano | findstr ":443"` (PowerShell:
  `Get-NetTCPConnection -LocalPort 443`). If you opt into `--profile tls` you
  inherit that constraint again.
  **On the prod box the ports are guaranteed taken** — nginx holds 80 and 443 —
  which is one more reason the dev stack must never be run there. The prod stack
  is unaffected: its Caddy binds `127.0.0.1:8480` instead.

---

## 14. Design Assets

| Asset | URL |
|---|---|
| Full User Flow (FigJam) | https://www.figma.com/board/QPoAL5zXOw66ACgxrMNioF/MadHats-Chatbot-%E2%80%94-Full-User-Flow |
| Wireframes & Screens (Figma design) | https://www.figma.com/design/fFPXYD7eIJPSo47tUPjK2r/MadHats-AI-Design-Studio-%E2%80%94-Wireframes---Screens |
