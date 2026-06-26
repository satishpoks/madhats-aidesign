# MadHats AI Design Studio — Design Spec
**Date:** 2026-06-26
**Milestone:** 1 — Visual design + feature list + infra scaffold
**Status:** Approved

---

## 1. Context & Constraints

**Client:** MadHats (madhats.com.au) — Australian custom headwear & printing on Shopify.
**Goal:** AI Design Studio MVP — "Describe it, see it" + Photo-to-product visuals.

**Hard constraints (agents must never violate these):**
- Composite onto real product reference photos — never invent a cap from scratch
- No customer face uploads in this build ("worn" = generic model only)
- InkyBay stays live in parallel — do not touch it
- All image models swappable via config (env vars), zero code change required
- Human-in-the-loop: generated concepts are previews until design team approves
- Coordinate anything Shopify-storefront-related with the in-house Shopify developer
- No secrets in code — env vars only, always
- No PII in logs

**Out of scope (do not build):**
- "Wear It" with customer's own photo (consent/age-gating required — later phase)
- Logo vectorisation / auto-cleanup pipeline
- Full InkyBay replacement configurator
- Quoting/pricing logic (separate chatbot service)
- Full 500-SKU Shopify catalogue sync (stub data for prototype; real sync is Standard tier)

---

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 / FastAPI |
| Frontend | React 18 / Vite / Tailwind CSS v4 |
| Image gen — preview tier | Gemini Flash (via Google GenAI SDK) |
| Image gen — final tier | Gemini Pro (via Google GenAI SDK) |
| Image gen — photoreal / A-B | fal.ai / FLUX |
| Database | Postgres 16 (Railway managed) |
| Object storage | Cloudflare R2 (S3-compatible) |
| Hosting | Railway (backend + frontend as separate services) |
| State management | Zustand |
| ORM | SQLAlchemy (async) + Alembic migrations |
| Observability | Sentry + structlog + Railway log streaming |
| Local dev | Docker Compose |

---

## 3. Feature & Function List

### Core (prototype must have)

| ID | Feature | Description |
|---|---|---|
| F1 | Product picker | Curated stub catalogue (5–10 SKUs); cards show blank cap silhouette in correct shape + colourway swatches |
| F2 | Text prompt input | Multiline text area; cap-specific prompt assembled server-side |
| F3 | Preview generation (Flow A) | Text + product ref → Gemini Flash mockup; target <5s |
| F4 | Logo upload (Flow B) | PNG/JPG/SVG/WebP; validated (type, size, magic bytes); composited onto product ref via Gemini Pro |
| F5 | Live preview surface | Generated image display; animated shimmer loading state; re-prompt / re-upload iteration |
| F6 | ImageProvider abstraction | Single async interface; Gemini Flash adapter (preview); Gemini Pro adapter (final); fal.ai/FLUX adapter (photoreal) |
| F7 | Request concept (HITL) | Submit package (product + final image + prompt/asset + customer notes) to approval queue |
| F8 | Approval queue (internal) | `/admin/queue` — table of submissions; status badges; reviewer notes; approve/reject actions |
| F9 | Session persistence | DesignSession saved to Postgres; shareable link via token |
| F10 | Cost logging | Per-generation log: tier, model, cost_usd, latency_ms stored in DB |

### Standard (full MVP)

| ID | Feature | Description |
|---|---|---|
| F11 | Voice input (Flow A) | Browser mic → STT (Whisper/Gemini audio) → same text prompt path; hidden when mic unavailable |
| F12 | Worn / in-context (Flow C) | Generic model wearing cap; lifestyle scene staging |
| F13 | Final-tier generation | "See the good version" → Gemini Pro at 2K; separate button from preview |
| F14 | Generation caching | Cache keyed by (product_id + colour + normalised_prompt + asset_hash) |
| F15 | Rate limiting | Per session/IP; configurable via RATE_LIMIT_RPM env var (slowapi middleware) |
| F16 | Input moderation | Prompt + uploaded image safety check before any model call |
| F17 | Describe-first path | Free text → AI infers best-matching catalogue product → user confirms → render |
| F18 | Shopify catalogue sync | Read Shopify product/variant/image data via Admin API; cache in ProductReference table |
| F19 | Mobile-responsive UI | Single-column stack on mobile; voice input conditional on mic availability |
| F20 | Observability | Sentry error tracking; structured logs; DB-queryable cost/latency metrics |

---

## 4. UI Look & Feel

**Design language:**
- Dark-first: deep charcoal background `#0F0F11`
- Accent: vivid orange `#FF5C00`
- Typography: Inter
- Rounded corners, glass/blur effects on overlays
- Smooth transitions; shimmer loading states

### Screen 1 — Studio Entry (product picker)
Full-width header: MadHats logo + "AI Design Studio". Horizontal scrollable grid of product cards — each card shows the **blank cap silhouette in the correct shape** (snapback, trucker, bucket, beanie, visor) with colourway swatches below. Selecting a card (orange border highlight) advances to the Studio Canvas. "Describe your idea instead" link activates the describe-first path.

### Screen 2 — Design Studio Canvas (main workspace)
Two-column layout on desktop, stacked on mobile:

**Left panel (40%) — inputs:**
- Tab switcher: "Describe it" / "Upload logo"
- Describe tab: multiline textarea with example placeholder; mic button (voice input) in corner
- Upload tab: drag-and-drop zone; thumbnail preview on upload
- Placement zone selector: pill buttons (Front / Side / Back / Under-brim)
- Decoration style toggle: Embroidery / Print
- "Generate Preview" CTA — orange, full-width

**Right panel (60%) — live preview:**
- Shows blank product reference image at rest
- Replaced by generated mockup on completion
- Shimmer animation during generation
- Below image: "Generate Final" + "Request This Concept" buttons (disabled until preview exists)
- Metadata strip: model, latency, tier

### Screen 3 — Concept Submission
Bottom sheet (mobile) / centred modal (desktop). Fields: name, email, notes. Thumbnail of selected image + product name. On submit: confirmation + shareable link.

### Screen 4 — Approval Queue (`/admin/queue`)
Protected internal route. Table: date, customer, product, thumbnail, status badge (pending / approved / rejected / needs changes), reviewer notes input, action buttons.

---

## 5. Architecture

### Backend structure

```
backend/
  app/
    main.py                   ← FastAPI app, CORS, lifespan hooks
    api/routes/
      generate.py             ← POST /generate/preview, /generate/final
      sessions.py             ← GET/POST /sessions, GET /sessions/{token}
      submissions.py          ← POST /submissions, GET /submissions
      products.py             ← GET /products
      uploads.py              ← POST /uploads
    services/
      image_provider.py       ← ImageProvider ABC
      adapters/
        gemini_flash.py
        gemini_pro.py
        fal_flux.py
      prompt_builder.py       ← cap-specific prompt assembly
      moderation.py           ← input safety check
      cache.py                ← generation cache
      stt.py                  ← voice → text
    models/
      session.py              ← DesignSession
      submission.py           ← ApprovalSubmission
      product.py              ← ProductReference
      generation.py           ← Generation log
    db.py                     ← SQLAlchemy async engine
    storage.py                ← R2 / S3-compatible client
    config.py                 ← pydantic-settings from env
```

### ImageProvider interface

```python
class ImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,
        uploaded_asset_url: str | None,
        params: GenerationParams,
    ) -> GenerationResult:
        ...
```

Active adapter per tier set in config — swap by env var, zero code change.

### Frontend structure

```
frontend/src/
  components/
    ProductPicker/            ← silhouette cards + swatch selector
    StudioCanvas/
      DescribeTab.tsx
      UploadTab.tsx
      PlacementSelector.tsx
      GenerateButton.tsx
    PreviewPanel/             ← mockup surface + shimmer
    ConceptModal/             ← submission form + share link
    AdminQueue/               ← approval table
  hooks/
    useGeneration.ts
    useSession.ts
    useVoiceInput.ts
  api/client.ts               ← typed fetch wrapper
  store/studioStore.ts        ← Zustand
```

### Data models (Postgres)

```
DesignSession       id, created_at, channel, entry_path, product_ref (JSON),
                    inputs (JSON), status, share_token

Generation          id, session_id, tier, model, image_url, cost_usd,
                    latency_ms, prompt_hash, created_at

ApprovalSubmission  id, session_id, product_ref (JSON), final_image_urls[],
                    source_ref (JSON), customer (JSON), review_status,
                    reviewer_notes, decided_at

ProductReference    id, shopify_product_id, variant_id, style, colour,
                    reference_image_url, placement_zones[], decoration_types[]
```

---

## 6. Infrastructure

### Local development

```yaml
# docker-compose.yml services
backend:   FastAPI + uvicorn (hot reload)
frontend:  Vite dev server
postgres:  Postgres 16
localstack: S3-compatible local object storage
```

Single `docker compose up` starts everything. `.env.local` (git-ignored) supplies secrets.

### Railway deployment

| Service | Source | Start |
|---|---|---|
| `madhats-backend` | `backend/Dockerfile` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| `madhats-frontend` | `frontend/Dockerfile` | nginx serving Vite build |
| `madhats-postgres` | Railway managed Postgres | — |

### Environment variables

```bash
# Image generation
GEMINI_API_KEY=
FAL_API_KEY=

# Provider routing (swap without code change)
IMAGE_PROVIDER_PREVIEW=gemini_flash
IMAGE_PROVIDER_FINAL=gemini_pro
IMAGE_PROVIDER_PHOTOREAL=fal_flux

# Storage (Cloudflare R2)
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_URL=

# Database
DATABASE_URL=

# Security
ADMIN_SECRET=
RATE_LIMIT_RPM=10
SIGNED_URL_TTL=3600

# Optional
SENTRY_DSN=
```

### Security controls

- All image storage bucket is private; access via signed URLs (TTL from env)
- CORS locked to `madhats.com.au` + `localhost` in non-production
- `/admin/queue` gated by `X-Admin-Secret` header vs `ADMIN_SECRET` env var
- Rate limiting via `slowapi` middleware; configurable threshold
- Alembic migrations run on deploy, never in app startup
- All file uploads validated: MIME type, file size limit, magic bytes check
- Input moderation before every model call
- No PII in logs; Sentry scrubbed for sensitive fields

---

## 7. Agent / Subagent Map

| Agent | Owns | Scope |
|---|---|---|
| Orchestrator | root, CLAUDE.md, docs/ | Reads plan, dispatches subagents, reviews output |
| Backend subagent | `backend/` | FastAPI routes, ImageProvider, DB models, services |
| Frontend subagent | `frontend/` | React components, Tailwind, API client, Zustand |
| Infra subagent | `docker-compose.yml`, `railway.toml`, `Dockerfile`s | Docker, Railway config, env setup, storage wiring |
| QA subagent | tests/ | Runs tests, checks acceptance criteria, flags regressions |

---

## 8. Acceptance Criteria (Milestone 1)

- [ ] Repo initialised with monorepo structure; `docker compose up` starts all services
- [ ] CLAUDE.md committed with full project memory
- [ ] `.env.example` committed; `.env.local` git-ignored
- [ ] FastAPI app runs; health endpoint returns 200
- [ ] React + Tailwind app runs; product picker screen renders with blank cap silhouettes
- [ ] `ImageProvider` abstraction implemented with Gemini Flash adapter wired to the real Gemini API; Gemini Pro and fal.ai adapters may return stub responses for prototype
- [ ] Database schema created via Alembic migration
- [ ] End-to-end Flow B (upload → preview generation → session saved) works in local dev
- [ ] Sentry configured in both backend and frontend
- [ ] Security controls in place: signed URLs, rate limiting, CORS, admin route gating
