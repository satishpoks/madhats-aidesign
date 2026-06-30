# MadHats AI Design Studio

An AI-powered, **conversational** design studio for [MadHats](https://madhats.com.au) — an Australian custom-headwear company. A named chatbot ("Ricardo") guides each customer through designing a custom cap — purpose, quantity, decoration, logo upload or description, placement — then generates a watermarked preview and captures the lead for the sales team.

Embedded in the MadHats Shopify storefront via a "Customize with AI" widget; runs alongside (not replacing) the existing InkyBay personaliser.

---

## What It Does

The customer journey (the **Ricardo** conversation, per the Figma user flow):

```
Shopify product → "Customize with AI" → Ricardo greets → name → purpose
→ youth check → quantity → decoration engine (print / embroidery / patch)
→ logo upload (+ background removal) OR describe the design
→ placement zone + position → optional pin-annotate (drop pins on the cap)
→ generate preview (composited onto the real product photo, watermarked)
→ capture email/phone → sales quote → upsell (max 2) → done
```

The customer can say "go back" at any step. Generated concepts are **previews only** — the MadHats design team approves before anything becomes production artwork.

---

## Architecture

| Layer | Choice |
|---|---|
| Backend | Python 3.12 / FastAPI (async) |
| Frontend | React 18 / Vite / TypeScript / Tailwind 3 / Zustand |
| Conversation LLM | Claude Haiku (`CLAUDE_HAIKU_MODEL`) — falls back to canned replies if no key |
| Image gen — preview | Gemini Flash image model (`GEMINI_PREVIEW_MODEL`) |
| Image gen — final | Gemini Pro image model (`GEMINI_FINAL_MODEL`) |
| Database + storage | **Supabase** (Postgres + Storage) via `supabase-py`; **local stack** via the Supabase CLI |
| Email | Resend (`RESEND_API_KEY`) |
| Rate limiting | slowapi · **Observability** Sentry + structlog |

**Multi-tenant (pooled):** one backend + one database serve many Shopify stores. A `stores` table holds each tenant; `store_id` scopes products and sessions. Each storefront widget sends its publishable key as the `X-Store-Key` header. Provider API keys are shared (env vars), never per-store. Onboard a store with `POST /admin/stores` then `POST /admin/stores/{id}/sync` (pulls its `products.json`).

---

## Repository Structure

```
madhats-aidesign/
  .env.example                 # all env vars (committed)
  docker-compose.yml           # backend + frontend (Supabase via `supabase start`)
  backend/                     # FastAPI service
    app/                       # main, config, db, storage, prompts, api/, services/, models/
    supabase/                  # config.toml, migrations/, seed.sql (local Supabase stack)
    tests/
  frontend/                    # React/Vite chatbot UI
    src/lib/api.ts             # API client (injects X-Store-Key)
    src/store/                 # sessionStore, chatStore, generationStore
    src/components/ChatPanel/  # Ricardo conversation UI
  docs/superpowers/{specs,plans}/
```

---

## Getting Started (local)

### Prerequisites
- **Docker Desktop** (running) — for the local Supabase stack
- **Supabase CLI** — `npx supabase ...` works without a global install
- **Python 3.12+** and **Node 20+**

### 1. Start the local Supabase stack
```bash
cd backend
npx supabase start          # boots Postgres + Storage + Studio; applies migrations + seed
```
This creates the schema, the private `madhats-assets` bucket, the default `madhats` store, and seeds the real MadHats catalogue. Studio UI: http://localhost:54323

### 2. Configure env
The repo-root `.env` is pre-filled for local dev (Supabase keys are the CLI defaults). Add the keys you have:
```bash
ANTHROPIC_API_KEY=sk-ant-...      # enables real Ricardo replies (else canned)
GEMINI_API_KEY=...                # enables image generation
IMAGE_PROVIDER_PREVIEW=gemini_flash   # or `stub` for a placeholder preview
SENTRY_DSN=...                    # optional
```

### 3. Backend
```bash
cd backend
python -m venv .venv && .venv/Scripts/activate    # source .venv/bin/activate on *nix
pip install -e ".[dev]"
uvicorn app.main:app --reload                     # http://localhost:8000/docs
```

### 4. Frontend
```bash
cd frontend
npm install
npm run dev                                        # http://localhost:5173
```
`frontend/.env` sets `VITE_API_BASE_URL` and `VITE_STORE_KEY` (default store key: `mh_pk_madhats_local`).

| Service | URL |
|---|---|
| Frontend (Ricardo studio) | http://localhost:5173 |
| Backend API + docs | http://localhost:8000 · /docs |
| Supabase Studio | http://localhost:54323 |
| Mailpit (captured emails) | http://localhost:54324 |

**Shopify-widget entry:** the studio also accepts `?product_id=&variant_id=&colour=` to start a session for a specific product (matches the production embed); without params it shows a dev product picker.

---

## Key Environment Variables

See `.env.example` for the full list.

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY` | Supabase connection |
| `SUPABASE_STORAGE_BUCKET` | Private bucket for uploads + generated images |
| `ANTHROPIC_API_KEY` / `CLAUDE_HAIKU_MODEL` | Ricardo conversation LLM |
| `GEMINI_API_KEY` / `GEMINI_PREVIEW_MODEL` / `GEMINI_FINAL_MODEL` | Image generation |
| `IMAGE_PROVIDER_PREVIEW` / `IMAGE_PROVIDER_FINAL` | Adapter: `gemini_flash` \| `gemini_pro` \| `stub` |
| `RESEND_API_KEY` / `SALES_NOTIFICATION_EMAIL` | Email + sales lead routing |
| `ADMIN_SECRET` | Gates `/admin/*` routes (`X-Admin-Secret` header) |
| `RATE_LIMIT_RPM` / `SIGNED_URL_TTL` / `ALLOWED_ORIGINS` | Rate limit, signed-URL TTL, CORS |
| `SENTRY_DSN` | Error tracking (optional) |

---

## Running Tests

```bash
cd backend && pytest -q          # 49 tests
cd frontend && npx vitest run    # 63 tests  (npm test = watch mode)
```

---

## Hard Constraints

- All mockups composite onto **real product reference photos** — never generate a cap shape from scratch
- No customer face uploads — "worn" mode uses a generic model only
- All model IDs live in env vars — zero code change to swap models
- No secrets in code; no PII (name/email/phone) in logs or Sentry
- All customer-facing image URLs are signed (TTL-limited); the bucket is never public
- Do not modify the live InkyBay personaliser; coordinate Shopify storefront changes with the MadHats in-house developer

---

## Notes / Current State

- **Conversation** runs on canned replies until `ANTHROPIC_API_KEY` is set, then real Haiku.
- **Image generation** needs `GEMINI_API_KEY` + `IMAGE_PROVIDER_PREVIEW=gemini_flash` and a Gemini account with quota/billing; use `stub` for a placeholder preview otherwise.
- **Email verification** is skipped locally without a Resend key (the lead is still recorded).
- Per-store CORS is not yet enforced at the middleware layer (origins are stored on each tenant; the global `ALLOWED_ORIGINS` applies for now).
