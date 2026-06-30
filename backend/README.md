# MadHats AI Design Studio — Backend

FastAPI service driving the "Ricardo" chatbot, image generation, lead capture, and the admin approval queue. Backed by Supabase (Postgres + Storage).

## Quick start

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on *nix
pip install -e ".[dev]"

cp ../.env.example ../.env       # then fill in real values
uvicorn app.main:app --reload    # http://localhost:8000/docs
```

## Environment

All config is read in `app/config.py` via pydantic-settings. The app **fails to start**
if a required var is missing. See `../.env.example` for the full list. Required to boot:
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `ANTHROPIC_API_KEY`,
`ADMIN_SECRET`.

Image generation defaults to `stub` adapters, so you can run the full flow with no
Gemini key. Switch `IMAGE_PROVIDER_PREVIEW`/`IMAGE_PROVIDER_FINAL` to `gemini_flash` /
`gemini_pro` once `GEMINI_API_KEY` is set.

## Database

Apply `supabase/migrations/001_initial_schema.sql` to your Supabase project (SQL editor,
`supabase db push`, or the MCP `apply_migration` tool). Create a **private** Storage
bucket named to match `SUPABASE_STORAGE_BUCKET` (default `madhats-assets`).

## Tests

```bash
pytest -q
```

## Architecture

| Path | Responsibility |
|---|---|
| `app/main.py` | App wiring: CORS, Sentry, structlog, slowapi, routers |
| `app/config.py` | All env vars (the only place they are read) |
| `app/prompts.py` | Every prompt + email string (single source of truth) |
| `app/services/conversation/` | State machine, orchestrator, Haiku intent extraction |
| `app/services/image/` | ImageProvider ABC, Gemini/stub adapters, env-driven router |
| `app/services/` | prompt_builder, watermark, moderation, email, generation_cache |
| `app/api/routes/` | health, products, sessions, chat, uploads, generate, leads, submissions |

### Conversation engine
Strict state machine (`state_machine.py`) owns all routing. Claude Haiku is called only
to interpret freeform input into structured data and to word Ricardo's reply — it never
decides the next state.

### Hard constraints enforced
- Every generation passes the real product reference photo as conditioning input.
- All model IDs come from env vars; none hardcoded.
- Customer-facing image URLs are always signed (TTL from `SIGNED_URL_TTL`).
- No PII (name/email/phone) in logs or Sentry.
- Admin routes gated by `X-Admin-Secret`; CORS locked to `ALLOWED_ORIGINS`.
