# MadHats AI Design Studio — Backend Design Spec
**Date:** 2026-06-30
**Status:** Approved
**Scope:** FastAPI backend — conversation engine, image generation pipeline, storage, email, admin queue

---

## 1. Overview

The backend is the sole orchestrator for the MadHats AI Design Studio. It drives the "Ricardo" chatbot conversation, handles image generation, manages session state, and submits approved concepts to the sales team. The frontend is a thin client — all business logic lives here.

**Hard constraints (never violate):**
- Composite onto real product reference photos; never generate a cap shape from scratch
- No customer face uploads — "worn" mode uses a generic model only
- All model IDs in env vars; swap without code change
- Human-in-the-loop — generated concepts are previews until the design team approves
- No secrets in code — `config.py` only
- No PII in logs or Sentry breadcrumbs
- All stored images accessed via signed URLs — bucket never public

---

## 2. Tech Stack

| Layer | Choice |
|---|---|
| Runtime | Python 3.12 |
| Framework | FastAPI (async) |
| Database | Supabase (Postgres) via supabase-py |
| Object storage | Supabase Storage |
| Conversation LLM | Claude Haiku (`CLAUDE_HAIKU_MODEL` env var) |
| Image gen — preview | Gemini Flash (`GEMINI_PREVIEW_MODEL` env var) |
| Image gen — final | Gemini Pro (`GEMINI_FINAL_MODEL` env var) |
| Email | Resend |
| Rate limiting | slowapi |
| Observability | Sentry + structlog |
| Local dev | Docker Compose |

---

## 3. Conversation Architecture — Hybrid State Machine + Claude Haiku

### 3.1 Design principle

Ricardo's conversation follows a **strict state machine**. Every step and every allowed transition is defined in code. Claude Haiku is called **only** for:

1. Interpreting freeform user input into structured data (e.g. "a dozen" → `quantity=12`, detecting kids/youth mentions)
2. Detecting back-tracking intent ("go back", "actually change that")
3. Generating the natural-language wording of Ricardo's scripted response from a state template
4. Assembling the design description into a structured prompt context

Haiku **cannot** skip states, reorder steps, or make routing decisions. All branching is handled by the state machine after Haiku returns structured output.

### 3.2 ConversationState enum

```python
class ConversationState(str, Enum):
    GREETING               = "greeting"
    ASK_NAME               = "ask_name"
    ASK_PURPOSE            = "ask_purpose"
    CHECK_YOUTH            = "check_youth"
    YOUTH_REFERRAL         = "youth_referral"
    ASK_QUANTITY           = "ask_quantity"
    DECORATION_ENGINE      = "decoration_engine"
    WARN_PRINT_SETUP       = "warn_print_setup"
    RECOMMEND_DECORATION   = "recommend_decoration"
    RECOMMEND_EMBROIDERY   = "recommend_embroidery"
    CONFIRM_DECORATION     = "confirm_decoration"
    ASK_HAS_LOGO           = "ask_has_logo"
    UPLOAD_LOGO            = "upload_logo"
    ASK_REMOVE_BG          = "ask_remove_bg"
    DESCRIBE_DESIGN        = "describe_design"
    ASK_PLACEMENT_ZONE     = "ask_placement_zone"
    ASK_PLACEMENT_POSITION = "ask_placement_position"
    ASK_PIN_ANNOTATION     = "ask_pin_annotation"
    PIN_ANNOTATE_MODE      = "pin_annotate_mode"
    GENERATING             = "generating"
    ASK_EMAIL              = "ask_email"
    VERIFY_EMAIL           = "verify_email"
    EMAIL_VERIFIED         = "email_verified"
    SEND_PREVIEW_EMAIL     = "send_preview_email"
    QUOTE_REQUESTED        = "quote_requested"
    UPSELL_PROMPT          = "upsell_prompt"
    SESSION_END            = "session_end"
```

### 3.3 Transition table (abbreviated)

```
GREETING              → ASK_NAME
ASK_NAME              → ASK_PURPOSE
ASK_PURPOSE           → CHECK_YOUTH
CHECK_YOUTH           → YOUTH_REFERRAL (if youth detected)
                      → ASK_QUANTITY   (otherwise)
YOUTH_REFERRAL        → ASK_QUANTITY   (after product confirmed)
ASK_QUANTITY          → DECORATION_ENGINE
DECORATION_ENGINE     → WARN_PRINT_SETUP       (qty == 1)
                      → RECOMMEND_DECORATION   (qty 2–11)
                      → RECOMMEND_EMBROIDERY   (qty >= 12)
WARN_PRINT_SETUP      → CONFIRM_DECORATION
RECOMMEND_DECORATION  → CONFIRM_DECORATION
RECOMMEND_EMBROIDERY  → CONFIRM_DECORATION
CONFIRM_DECORATION    → ASK_HAS_LOGO
ASK_HAS_LOGO          → UPLOAD_LOGO    (has logo)
                      → DESCRIBE_DESIGN (no logo)
UPLOAD_LOGO           → ASK_REMOVE_BG
ASK_REMOVE_BG         → ASK_PLACEMENT_ZONE
DESCRIBE_DESIGN       → ASK_PLACEMENT_ZONE
ASK_PLACEMENT_ZONE    → ASK_PLACEMENT_POSITION
ASK_PLACEMENT_POSITION → ASK_PIN_ANNOTATION
ASK_PIN_ANNOTATION    → PIN_ANNOTATE_MODE (yes)
                      → GENERATING       (no, skip)
PIN_ANNOTATE_MODE     → PIN_ANNOTATE_MODE (add another pin)
                      → GENERATING       (done)
GENERATING            → ASK_EMAIL
ASK_EMAIL             → VERIFY_EMAIL
VERIFY_EMAIL          → EMAIL_VERIFIED  (link clicked)
                      → VERIFY_EMAIL    (resend)
EMAIL_VERIFIED        → SEND_PREVIEW_EMAIL
SEND_PREVIEW_EMAIL    → QUOTE_REQUESTED
QUOTE_REQUESTED       → UPSELL_PROMPT
UPSELL_PROMPT         → ASK_PLACEMENT_ZONE (yes, max 2 additional zones)
                      → SESSION_END          (declined)
SESSION_END           → (terminal)
```

### 3.4 Back-tracking

On every `/chat` message, before advancing state, the orchestrator calls `intent_extractor.detect_backtrack(message)`. If back-track intent is detected, Haiku returns the target state slug (e.g. `"ask_quantity"`) and the state machine rewinds to that state. Allowed back-track targets are defined per-state to prevent rewinding past the product selection.

### 3.5 Haiku call points

| Step | What Haiku does |
|---|---|
| `ASK_PURPOSE` response | Detect youth/kids mention → sets `youth_flag` |
| `ASK_QUANTITY` response | Parse freeform quantity text → integer |
| `DESCRIBE_DESIGN` response | Extract structured design context for prompt builder |
| Every turn | Detect back-track intent |
| Every state transition | Generate natural-language wording for Ricardo's reply |

---

## 4. API Routes

```
GET    /health                          → { "status": "ok" }
GET    /products                        → stub product catalogue (5–10 SKUs)

POST   /sessions                        → create session, return { session_id, share_token }
GET    /sessions/{token}                → resume session by share link

POST   /chat/{session_id}               → { message: str } → { reply: str, state: str, data?: {} }
POST   /uploads/logo/{session_id}       → multipart file → { asset_url, asset_hash }
POST   /uploads/pin/{session_id}        → { view, x_pct, y_pct, comment } → { pin_id }

POST   /generate/preview/{session_id}   → trigger async preview generation → { job_id }
POST   /generate/final/{session_id}     → trigger async final generation → { job_id }
GET    /generate/status/{job_id}        → { status, image_url?, watermarked_url? }

POST   /verify-email/{session_id}       → send verification email via Resend
POST   /verify-email/confirm            → { token } → marks email verified, triggers preview email send

POST   /submissions                     → create approval submission → { submission_id }
GET    /admin/submissions               → list submissions (X-Admin-Secret required)
PATCH  /admin/submissions/{id}          → update review_status + reviewer_notes
```

---

## 5. File Structure

```
backend/
  app/
    main.py                   ← FastAPI app, CORS, lifespan hooks, Sentry init, slowapi middleware
    config.py                 ← pydantic-settings; all env vars validated here, nowhere else
    db.py                     ← Supabase async client singleton
    storage.py                ← Supabase Storage: upload asset, generate signed URL, write watermarked image
    prompts.py                ← ALL prompt strings: Ricardo system prompt, per-state response templates,
    │                            intent-extraction prompts, image-gen prompt templates, email bodies
    │                            Imported by orchestrator, adapters, email service — never inlined elsewhere
    │
    api/
      deps.py                 ← shared FastAPI dependencies (get_session, admin_auth, rate_limit)
      routes/
        health.py
        products.py
        sessions.py
        chat.py
        uploads.py
        generate.py
        email_verify.py
        submissions.py
    │
    services/
      conversation/
        state_machine.py      ← ConversationState enum, transition table, back-track resolver,
        │                        allowed_backtracks map, advance_state() function
        orchestrator.py       ← main chat handler:
        │                        1. load session
        │                        2. detect back-track intent (Haiku)
        │                        3. advance state via state_machine
        │                        4. extract structured data (Haiku) if freeform state
        │                        5. update session.collected in DB
        │                        6. generate Ricardo's reply wording (Haiku)
        │                        7. persist chat_message to DB
        │                        8. return reply + new state
        intent_extractor.py   ← Claude Haiku calls (all use prompts.py templates):
                                 detect_backtrack(), parse_quantity(), detect_youth(),
                                 extract_design_description(), generate_reply()
      image/
        image_provider.py     ← ImageProvider ABC with generate() method signature
        adapters/
          gemini_flash.py     ← preview tier; always passes reference_image_url
          gemini_pro.py       ← final tier; always passes reference_image_url
          stub.py             ← returns placeholder; used in tests and local dev
        router.py             ← reads IMAGE_PROVIDER_PREVIEW / IMAGE_PROVIDER_FINAL env vars,
                                 returns correct adapter instance
      prompt_builder.py       ← assembles image-gen prompt from session.collected + prompts.py;
                                 enforces reference_image_url always present; appends pin annotations
      moderation.py           ← safety check on text prompt + uploaded image before any model call;
                                 raises ModerationError on failure
      watermark.py            ← stamps "MadHats Preview Only" + logo onto generated image (Pillow)
      email.py                ← Resend integration:
                                 send_verification_email(), send_preview_email(), send_quote_to_sales()
                                 all email body strings sourced from prompts.py
      generation_cache.py     ← cache keyed by sha256(product_id + colour + prompt_hash + asset_hash);
                                 checks generations table before calling image provider
    │
    models/
      session.py              ← DesignSession dataclass / Pydantic model
      message.py              ← ChatMessage
      generation.py           ← Generation log entry
      submission.py           ← ApprovalSubmission
      product.py              ← ProductReference
```

---

## 6. Data Models (Supabase / Postgres)

### `design_sessions`
```sql
id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
share_token   text UNIQUE NOT NULL,
state         text NOT NULL DEFAULT 'greeting',
channel       text NOT NULL DEFAULT 'web',        -- web | mobile
entry_path    text NOT NULL DEFAULT 'pick_first', -- pick_first | describe_first
product_ref   jsonb,     -- { shopify_product_id, variant_id, style, colour, reference_image_url }
collected     jsonb DEFAULT '{}',  -- { name, purpose, quantity, decoration_type, has_logo,
              --   placement_zone, placement_position, pin_annotations[],
              --   design_description, remove_bg, email }
status        text NOT NULL DEFAULT 'draft',
upsell_count  int NOT NULL DEFAULT 0,             -- max 2
created_at    timestamptz NOT NULL DEFAULT now(),
updated_at    timestamptz NOT NULL DEFAULT now()
```

### `chat_messages`
```sql
id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
session_id    uuid REFERENCES design_sessions(id) ON DELETE CASCADE,
role          text NOT NULL,    -- user | assistant
content       text NOT NULL,
state_before  text NOT NULL,
state_after   text NOT NULL,
created_at    timestamptz NOT NULL DEFAULT now()
```

### `generations`
```sql
id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
session_id       uuid REFERENCES design_sessions(id) ON DELETE CASCADE,
job_id           uuid UNIQUE NOT NULL DEFAULT gen_random_uuid(),
tier             text NOT NULL,   -- preview | final
model            text NOT NULL,
status           text NOT NULL DEFAULT 'pending',  -- pending | complete | failed
image_url        text,
watermarked_url  text,
prompt_hash      text,
cost_usd         numeric(10,6),
latency_ms       int,
created_at       timestamptz NOT NULL DEFAULT now()
```

### `approval_submissions`
```sql
id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
session_id        uuid REFERENCES design_sessions(id),
product_ref       jsonb NOT NULL,
final_image_urls  text[] NOT NULL DEFAULT '{}',
source_ref        jsonb,    -- { prompt_text, asset_url, asset_hash, pin_annotations }
customer          jsonb,    -- { name, email } — never written to logs
review_status     text NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | needs_changes
reviewer_notes    text,
decided_at        timestamptz,
created_at        timestamptz NOT NULL DEFAULT now()
```

### `product_references` *(stub data for prototype)*
```sql
id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
shopify_product_id    text,
variant_id            text,
style                 text NOT NULL,
colour                text NOT NULL,
reference_image_url   text NOT NULL,
placement_zones       text[] NOT NULL DEFAULT '{}',
decoration_types      text[] NOT NULL DEFAULT '{}'
```

---

## 7. `prompts.py` — Single Source of Truth for All Prompt Strings

All strings that are sent to any AI model or used as email templates live in `prompts.py`. No other file contains inline prompt text.

```python
# prompts.py (structure — not exhaustive)

# --- Ricardo system prompt ---
RICARDO_SYSTEM_PROMPT: str        # persona, constraints, tone, brand voice

# --- Per-state response templates (filled by Haiku at runtime) ---
STATE_PROMPTS: dict[str, str]     # keyed by ConversationState value

# --- Intent extraction prompts ---
BACKTRACK_DETECTION_PROMPT: str
QUANTITY_EXTRACTION_PROMPT: str
YOUTH_DETECTION_PROMPT: str
DESIGN_EXTRACTION_PROMPT: str

# --- Image generation prompt templates ---
IMAGE_GEN_BASE_TEMPLATE: str      # base cap-specific context
PLACEMENT_CONTEXT_TEMPLATE: str   # placement zone + position
EMBROIDERY_STYLE_MODIFIER: str
PRINT_STYLE_MODIFIER: str
PIN_ANNOTATION_TEMPLATE: str      # appended when pins present

# --- Email body templates ---
VERIFICATION_EMAIL_SUBJECT: str
VERIFICATION_EMAIL_BODY: str
PREVIEW_EMAIL_SUBJECT: str
PREVIEW_EMAIL_BODY: str
SALES_QUOTE_EMAIL_SUBJECT: str
SALES_QUOTE_EMAIL_BODY: str
```

---

## 8. ImageProvider Interface

```python
# image_provider.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class GenerationParams:
    tier: str              # preview | final
    placement_zone: str
    placement_position: str
    decoration_type: str   # embroidery | print
    remove_bg: bool
    pin_annotations: list[dict]  # [{ view, x_pct, y_pct, comment }]
    resolution: str        # standard | 2k

@dataclass
class GenerationResult:
    image_url: str
    cost_usd: float
    latency_ms: int
    model: str

class ImageProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,           # real product photo — always required
        uploaded_asset_url: str | None,      # customer logo, if any
        params: GenerationParams,
    ) -> GenerationResult: ...
```

---

## 9. Security Controls

| Control | Implementation |
|---|---|
| Secrets | `config.py` via pydantic-settings; startup fails if any required var is missing |
| File upload validation | MIME type + magic bytes + size limit in `uploads.py` before any processing |
| Signed URLs | `storage.py` — never returns raw bucket path; TTL from `SIGNED_URL_TTL` env var |
| Rate limiting | slowapi on `/chat` and `/generate` routes; threshold from `RATE_LIMIT_RPM` |
| Input moderation | `moderation.py` called before every model call in orchestrator + generate routes |
| CORS | `ALLOWED_ORIGINS` env var; locked to `madhats.com.au` + `localhost` in dev |
| Admin auth | `X-Admin-Secret` header checked in `deps.py`; compared to `ADMIN_SECRET` env var |
| PII in logs | `orchestrator.py` and `email.py` never log `session.collected.email` or `customer` fields |

---

## 10. Environment Variables

```bash
# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
SUPABASE_STORAGE_BUCKET=madhats-assets

# Claude (conversation LLM)
ANTHROPIC_API_KEY=
CLAUDE_HAIKU_MODEL=claude-haiku-4-5-20251001

# Image generation
GEMINI_API_KEY=
IMAGE_PROVIDER_PREVIEW=gemini_flash
IMAGE_PROVIDER_FINAL=gemini_pro
GEMINI_PREVIEW_MODEL=
GEMINI_FINAL_MODEL=

# Email
RESEND_API_KEY=
RESEND_FROM_ADDRESS=studio@madhats.com.au
SALES_EMAIL=sales@madhats.com.au

# Security
ADMIN_SECRET=
RATE_LIMIT_RPM=10
SIGNED_URL_TTL=3600
ALLOWED_ORIGINS=https://madhats.com.au,http://localhost:5173

# App
APP_ENV=development
SENTRY_DSN=
EMAIL_VERIFY_BASE_URL=https://studio.madhats.com.au
```

---

## 11. Acceptance Criteria (Backend)

- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] `GET /products` returns at least 5 stub products with correct shape
- [ ] `POST /sessions` creates a session in Supabase, returns `share_token`
- [ ] `GET /sessions/{token}` retrieves full session including chat history
- [ ] `POST /chat/{session_id}` advances state correctly through the full flow end-to-end
- [ ] Back-tracking ("go back to change quantity") rewinds to the correct state
- [ ] Youth detection from `ASK_PURPOSE` redirects correctly
- [ ] Quantity parsing handles freeform text ("a dozen", "twelve", "1")
- [ ] `POST /uploads/logo/{session_id}` validates MIME + magic bytes; rejects invalid files
- [ ] `POST /generate/preview/{session_id}` triggers Gemini Flash with `reference_image_url`
- [ ] `GET /generate/status/{job_id}` returns correct status and signed image URL
- [ ] Watermark applied to all generated images before storage
- [ ] `POST /verify-email/{session_id}` sends verification email via Resend
- [ ] `POST /verify-email/confirm` marks session email-verified and triggers preview email
- [ ] `POST /submissions` creates approval record in Supabase
- [ ] `GET /admin/submissions` requires `X-Admin-Secret`; returns 401 without it
- [ ] Rate limiting returns 429 when threshold exceeded
- [ ] No PII appears in structlog output or Sentry events
- [ ] All image URLs returned to client are signed (TTL-limited), never raw bucket paths
- [ ] All prompt strings sourced from `prompts.py`; none inline in other files
- [ ] All model IDs read from env vars; no model ID string hardcoded
