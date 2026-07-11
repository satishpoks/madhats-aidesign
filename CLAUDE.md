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
- **Known gaps:** CORS middleware is still global (`ALLOWED_ORIGINS` env); `/products` returns PostgREST's default 1000-row cap (large catalogues need pagination).

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
- **Decoupled generation + gated delivery** (`services/delivery.py`, `api/routes/generate.py`, `services/leads.py`): image generation runs async in the background; the emailed preview is sent only when the lead's email is **verified** AND a generation is **complete with a real image**. Transient model failures (e.g. Gemini 429/quota) are retried; on final failure ops is alerted and the customer never sees an error. `POST /admin/deliveries/backfill` is a self-heal sweep for designs that finished after verification or whose send failed. The preview image is inlined as a CID attachment so it renders in the inbox.
- **Request-a-Quote flow** (`api/routes/quote.py`, `services/leads.py` quote-token helpers, `api/routes/admin_leads.py`): the preview email's "request a quote" CTA links to a signed, server-rendered page (`GET /quote/{token}`) where the customer confirms their design (editable quantity + optional note) and optionally leaves a phone number + phone-notify consent. Submitting (`POST /quote/{token}`) updates `collected.quantity`, tags the lead (`quote_confirmed`, `quote_confirmed_at`, `notify_by_phone`, `quote_note`), and sends a one-time "customer confirmed" sales email. Confirmed leads surface via `GET /admin/quote-requests` (X-Admin-Secret). The auto-notify-at-delivery behaviour (`quote_request_sent`) is unchanged — this is a second, richer signal.
- **Per-call audit log** (`services/generation_logger.py`, append-only `generation_logs` table): every provider call logs inputs (full prompt, reference/logo image refs, params) before and outputs (response meta + full raw response) after — one row per attempt, including retries.
- **Admin/ops routes** (`X-Admin-Secret`): `GET /admin/prompt-preview/{session_id}` (exact prompt Gemini would receive), `POST /admin/deliveries/backfill` (delivery self-heal), plus store onboarding/sync.
- **Frontend:** email is captured **inline in the chat** (the redundant contact form is gone).
- **Smarter Studio conversation:** the engine is now **interpreter-first** — out-of-order answers, side-questions, "revise X", and chit-chat are handled via an LLM interpreter, while the deterministic state machine still owns routing and goal-leads the conversation back on track (no-advance on unmet fields). The frontend shows the on-screen design (main image + product-angle + regeneration thumbnails) gated at email verification, plus a "Step X of N" progress indicator. Customers can regenerate-with-changes up to admin-configurable per-session/per-day caps (`REGEN_EDITS_PER_SESSION`, `DESIGNS_PER_CUSTOMER_PER_DAY`), backed by a global `app_settings` table and an admin Settings view; the final design is emailed once on completion (deduped).
- Tests: backend `pytest` 176, frontend `vitest run` 107 (2 pre-existing `adminQuotes` failures, unrelated).
- Open ticket: add a partial index on `leads(email_verified, preview_email_sent, verified_at)` before lead volume grows (backfill/cron query).

---

## 14. Design Assets

| Asset | URL |
|---|---|
| Full User Flow (FigJam) | https://www.figma.com/board/QPoAL5zXOw66ACgxrMNioF/MadHats-Chatbot-%E2%80%94-Full-User-Flow |
| Wireframes & Screens (Figma design) | https://www.figma.com/design/fFPXYD7eIJPSo47tUPjK2r/MadHats-AI-Design-Studio-%E2%80%94-Wireframes---Screens |
