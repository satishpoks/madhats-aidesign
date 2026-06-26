# MadHats AI Design Studio

An AI-powered design preview tool for [MadHats](https://madhats.com.au) — an Australian custom headwear and printing company. Customers describe or upload a design idea and instantly see it composited onto a real product photo.

Runs alongside (not replacing) the existing InkyBay personaliser on Shopify.

---

## What It Does

| Flow | Description |
|---|---|
| **A — Describe it, see it** | Type a design idea → AI generates an on-cap mockup |
| **B — Photo-to-product** | Upload a logo/artwork → AI composites it onto the chosen cap |
| **C — Worn / in context** | View the designed cap on a generic model or lifestyle scene |

Generated concepts are previews only. The MadHats design team approves before anything becomes production artwork.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 / FastAPI |
| Frontend | React 18 / Vite / Tailwind CSS 3 |
| State | Zustand |
| Image gen — preview | Gemini Flash (`GEMINI_PREVIEW_MODEL`) |
| Image gen — final | Gemini Pro (`GEMINI_FINAL_MODEL`) |
| Image gen — photoreal | fal.ai / FLUX (`FAL_PHOTOREAL_MODEL`) |
| Database | Postgres 16 (Railway managed) |
| Object storage | Cloudflare R2 (S3-compatible) |
| ORM | SQLAlchemy (async) + Alembic |
| Observability | Sentry + structlog |
| Hosting | Railway (backend + frontend as separate services) |
| Local dev | Docker Compose |

---

## Repository Structure

```
madhats-aidesign/
  .env.example             # documents all required env vars
  docker-compose.yml       # local dev: backend + frontend + postgres + localstack
  railway.toml             # Railway deployment config
  backend/                 # FastAPI service
  frontend/                # React/Vite service
  docs/
    superpowers/
      specs/               # design specs
      plans/               # implementation plans
```

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Node 20+ (frontend dev only)
- Python 3.12+ (backend dev only)

### 1. Environment

```bash
cp .env.example .env
# Fill in API keys and config values
```

### 2. Local dev (all services)

```bash
docker compose up
```

| Service | URL |
|---|---|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

### 3. Backend only

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

### 4. Frontend only

```bash
cd frontend
npm install
npm run dev
```

---

## Key Environment Variables

See `.env.example` for the full list.

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `FAL_API_KEY` | fal.ai API key |
| `IMAGE_PROVIDER_PREVIEW` | Adapter: `gemini_flash` \| `fal_flux` \| `stub` |
| `IMAGE_PROVIDER_FINAL` | Adapter: `gemini_pro` \| `fal_flux` \| `stub` |
| `IMAGE_PROVIDER_PHOTOREAL` | Adapter: `fal_flux` \| `gemini_pro` \| `stub` |
| `DATABASE_URL` | Postgres connection string |
| `R2_*` | Cloudflare R2 storage credentials |
| `ADMIN_SECRET` | Gates `/admin/*` routes |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins |
| `SENTRY_DSN` | Error tracking (optional) |

---

## Running Tests

```bash
# Backend
cd backend && pytest

# Frontend
cd frontend && npm test
```

---

## Deployment

Deployed to Railway as two separate services (backend + frontend). Migrations run on deploy:

```bash
alembic upgrade head
```

Config lives in `railway.toml`.

---

## Hard Constraints

- All mockups composite onto **real product reference photos** — never generate a cap shape from scratch
- No customer face uploads — "worn" mode uses a generic model only
- All model IDs live in env vars — zero code change required to swap models
- No secrets in code; no PII in logs or Sentry
- Do not modify the live InkyBay personaliser
- Coordinate any Shopify storefront changes with the MadHats in-house Shopify developer
