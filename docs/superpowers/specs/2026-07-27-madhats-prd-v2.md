# MadHats AI Design Studio — Product Requirements Document v2
**Date:** 2026-07-27  
**Source:** Client meeting 27 July 2026 + existing design spec (2026-06-26)  
**Status:** Draft — pending client review  

---

## 1. Executive Summary

MadHats AI Design Studio is a conversational AI-powered customisation experience embedded in the MadHats (madhats.com.au) Shopify storefront. Customers select a hat, then interact with a named AI chatbot ("Ricardo" — placeholder) that guides them through their design — gathering requirements, uploading their logo, choosing decoration type and placement — before generating a watermarked preview and capturing contact details mid-flow. Human salespeople handle final quoting; the chatbot handles design generation and lead capture only.

This PRD supersedes the June 2026 design spec in all areas where the two conflict. The tech stack and hard constraints from that spec remain valid.

---

## 2. Goals & Success Metrics

| Goal | Metric |
|---|---|
| Increase design enquiry conversion | % of product page visitors who complete the chatbot flow |
| Capture qualified leads | Contact details (email + phone) verified before design delivery |
| Reduce manual quoting effort | Structured quote requests sent to sales team with full context |
| Reduce customer decision friction | <5 min median time from "Customize" click to design generation |
| Protect IP | 100% of designs delivered with Mad Hats watermark |

---

## 3. User Personas

### Primary: First-Time B2B Buyer
Small business owner wanting branded headwear for staff or a promotional event. Has a logo. Unsure about decoration types or quantities. Likely on desktop during business hours.

### Secondary: Consumer Gift Buyer
Individual ordering 1–5 personalised hats as gifts. May not have a logo. Needs guidance on cost-effective options. May be on mobile.

### Internal: MadHats Salesperson
Receives chatbot-generated quote requests with full context (customer name, email, phone, product, quantity, decoration preference, generated design). Reviews and sends final quote.

### Internal: MadHats Admin / Design Reviewer
Reviews generated designs for quality before approval. Uses the internal approval queue.

---

## 4. Feature List

### 4.1 Core — Prototype (must-have for milestone delivery)

| ID | Feature | Description | Changed from v1? |
|---|---|---|---|
| F1 | Product picker | Curated stub catalogue (5–10 SKUs); cards show blank cap silhouette per style + colourway swatches | No change |
| F2 | Multi-view product images | Per product: front, side, back, overhead, underhead views; thumbnail strip on product card | **NEW** |
| F3 | Chatbot entry point | "Customize This Product" button on product page launches the AI chatbot (Ricardo) | **NEW** |
| F4 | Conversational onboarding | Chatbot collects: customer name → hat purpose → quantity → decoration preference | **NEW** |
| F5 | Decoration recommendation engine | AI recommends print / embroidery / patch based on qty, logo complexity, cost rules | **NEW** |
| F6 | Logo upload in chat | Customer uploads logo during conversation; chatbot offers background removal | Replaces F4 in v1 |
| F7 | Placement selection (conversational) | Chatbot asks: which panel (front/side/back), which zone (center/left/right, upper/lower) | Extends v1 |
| F8 | Mid-flow lead capture | Chatbot requests email + phone while design is "being prepared"; non-intrusive timing | **NEW** |
| F9 | Email verification | Chatbot triggers verification email; waits for confirmation before sending design | **NEW** |
| F10 | Design generation (AI) | Composites customer logo onto real product reference photo; Gemini Flash for preview | Extends v1 F3 |
| F11 | Watermarked design delivery | Design sent to customer email/SMS with Mad Hats watermark overlay | **NEW** |
| F12 | On-screen preview (post-verification) | Generated design shown on screen after email verified | **NEW** |
| F13 | Quote request to sales | Chatbot packages full context (customer, product, qty, design) and notifies sales team | **NEW** |
| F14 | Voice input | Browser mic → STT → same chatbot conversation path; voice-first UI | From v1 F11 |
| F15 | Click / typed fallback | When voice unavailable: click options or free-text input in chat | **NEW** |
| F16 | Session persistence | DesignSession saved to Postgres; shareable link via token | No change |
| F17 | ImageProvider abstraction | Single async interface; Gemini Flash (preview), Gemini Pro (final), fal.ai (photoreal) | No change |
| F18 | Approval queue (internal) | `/admin/queue` — table of submissions; status badges; reviewer notes; approve/reject | No change |
| F19 | Cost logging | Per-generation log: tier, model, cost_usd, latency_ms | No change |
| F20 | Input moderation | Prompt + image safety check before any model call | No change |
| F21 | Rate limiting | Per session/IP; configurable via env var | No change |

### 4.2 Standard — Full MVP

| ID | Feature | Description |
|---|---|---|
| F22 | Upsell prompts | After primary design: chatbot suggests additional logo placements or add-ons ("Would you like the same logo on the side?") |
| F23 | Conditional discount messaging | Chatbot applies discount logic: no discount for 1pc; volume discounts from pricing slab; day-of-week promo (Mon–Wed) |
| F24 | Chatbot persona customisation | Name, avatar, greeting message configurable via CMS/admin without code change |
| F25 | Final-tier generation | "See it in full quality" → Gemini Pro at 2K; triggered after quote request |
| F26 | Worn / in-context (Flow C) | Generic model wearing designed cap; lifestyle scene staging |
| F27 | Describe-first path | Free text → AI infers best-matching product → user confirms → chatbot flow |
| F28 | Shopify catalogue sync | Read Shopify product/variant/image data; cache in ProductReference table |
| F29 | Generation caching | Cache keyed by (product_id + colour + normalised_prompt + asset_hash) |
| F30 | Mobile-responsive UI | Single-column chat UI on mobile; voice input conditional on mic availability |
| F31 | SMS delivery option | Customer can opt to receive design + quote link via SMS instead of (or alongside) email |
| F32 | Observability | Sentry error tracking; structured logs; DB-queryable cost/latency metrics |

---

## 5. User Stories

### Chatbot Conversation Flow

**US-01** As a customer, I want to click "Customize This Product" on a hat I like, so I can start designing it without leaving the product page.

**US-02** As a customer, I want the chatbot to greet me by name and ask what I'm trying to achieve, so I feel like I'm talking to a real consultant rather than filling out a form.

**US-03** As a customer, I want the chatbot to recommend the best decoration type for my budget and quantity, so I don't waste time exploring options that don't suit my needs.

**US-04** As a customer, I want to upload my logo directly in the chat, so I don't have to navigate to a separate form.

**US-05** As a customer, I want the chatbot to offer to remove the white background from my logo, so the final design looks professional.

**US-06** As a customer, I want to tell the chatbot where to place my logo (front center, left side, etc.) using simple language or clicks, so I don't need design software knowledge.

**US-07** As a customer, I want to speak my answers rather than type them, so the interaction feels fast and natural, especially on mobile.

**US-08** As a customer who can't use a microphone, I want click-option cards or a text field as a fallback, so I can still complete the design without voice.

**US-09** As a customer, I want my email and phone number requested politely while the design is generating — not before I've done anything, so I don't feel like I'm being data-mined.

**US-10** As a customer, I want to verify my email with a one-click link, so I know the design will reach the right inbox.

**US-11** As a customer, I want to receive the generated design in my email with the MadHats branding on it, so I have a record to share with my team.

**US-12** As a customer, I want to see the design on screen (after verifying my email), so I can assess it immediately.

**US-13** As a customer, I want the chatbot to ask if I'd like to add anything else to the hat (other sides, different logo zones), so I can build a more complete vision.

### Product & Catalogue

**US-14** As a customer, I want to view multiple angles of a hat (front, side, back, overhead, underhead) before customising, so I understand the product before designing.

**US-15** As a customer, I want to select a colourway and see the hat silhouette update, so I'm designing on the right base.

### Sales & Admin

**US-16** As a MadHats salesperson, I want to receive a structured quote request (customer name, email, phone, product, quantity, decoration type, design image) from every completed chatbot session, so I can respond quickly with a relevant quote.

**US-17** As a MadHats admin, I want to review generated designs in an approval queue and approve or reject them, so only quality designs reach the customer.

**US-18** As a MadHats admin, I want to configure discount rules (volume slabs, day-of-week promos, stock-level overrides) without touching code, so I can run promotions independently.

---

## 6. Functional Requirements

### 6.1 Chatbot Conversation Engine

**FR-01** The chatbot must collect the following in order, adapting based on responses:
1. Customer first name
2. Purpose of hat (gift / staff uniforms / resale / event giveaway / personal use)
3. Quantity required (drives decoration recommendation)
4. Decoration preference or guided recommendation (print / embroidery / patch)
5. Logo upload (or text-only design description)
6. Background removal preference (if logo has background)
7. Placement zone (front panel / side / back / under-brim)
8. Position within zone (center / left / right; upper / center / lower)
9. Contact details (email + phone) — collected mid-generation, not upfront
10. Email verification confirmation

**FR-02** The chatbot must recommend decoration type using these rules:
- Quantity = 1: recommend print (embroidery setup fee ~$50 makes single units expensive; patches even more so)
- Quantity 2–11: recommend print or embroidery based on logo complexity
- Quantity 12+: show pricing slab from ProductReference; recommend embroidery if logo is simple text/icon
- Logo with fine details (<2mm equivalent at embroidery size): warn against embroidery; recommend print
- Logo area > 90% of standard embroidery frame: warn against embroidery; recommend print or patch
- Patch: flag as most expensive (multi-step); only recommend if customer explicitly requests it

**FR-03** Chatbot input must support three modes simultaneously:
- Voice (browser Web Speech API / STT backend): primary mode; mic button always visible
- Click options: chatbot renders option chips (2–4 choices) alongside text for key questions
- Free text: chat input field always available as fallback

**FR-04** Contact capture must be triggered asynchronously while image generation is in progress. The chatbot's prompt: "While I'm putting the design together, could I grab your email so I can send it over when it's ready?"

**FR-05** The chatbot must send a verification email immediately after contact capture. The design is NOT shown on-screen or emailed until verification is confirmed. Verification link TTL: 15 minutes.

**FR-06** After verification, the chatbot must:
1. Show the watermarked design on-screen
2. Send the watermarked design to the customer's email (and SMS if provided)
3. Package a quote request to the sales team (customer info + product + qty + decoration type + design image)

**FR-07** The chatbot must deliver a post-design upsell prompt:
- "Would you also like to add something to the side panel?"
- "Have you thought about adding a message under the brim?"
- Maximum 2 upsell prompts per session; stop if customer declines.

**FR-08** The chatbot must apply discount messaging based on:
- Qty = 1: no discount offered
- Qty 2–11: standard pricing slab from database
- Qty 12+: volume discount tier from database
- Day-of-week promo (Mon–Wed): configurable extra % off, loaded from config table
- Never auto-apply discount without salesperson confirmation; chatbot only *mentions* the discount

**FR-09** The chatbot persona name, avatar, and greeting are configurable via admin settings. Default persona: "Ricardo". Greeting: "Hi [name], I'm Ricardo — MadHats' AI design assistant. Let me help you get the perfect look."

### 6.2 Product & Catalogue

**FR-10** Each product in the catalogue must expose at minimum: front view, left-side view, right-side view, back view. Overhead and underhead views are optional per SKU.

**FR-11** The product picker must show colourway swatches; selecting a swatch updates the displayed cap silhouette image to that colour variant.

**FR-12** All generated images must composite the customer's logo/design onto the real product reference photo for the selected colourway. Generating a cap shape from scratch is prohibited.

### 6.3 Image Generation

**FR-13** Generation pipeline: PromptBuilder assembles the prompt → ImageProvider dispatched to active adapter → result stored in R2 → signed URL returned.

**FR-14** All generated images are stored in private R2 bucket. Customer-facing URLs must be signed with a configurable TTL.

**FR-15** Watermark must be composited onto the generated image before delivery to customer. The watermark is "MAD HATS" text/logo tiled or placed at fixed position. The clean (unwatermarked) version is stored in R2 for internal use.

**FR-16** Input moderation check runs before every model call (text prompt + uploaded image).

### 6.4 Lead Capture & CRM

**FR-17** Every chatbot session that reaches contact capture creates a Lead record in the database (name, email, phone, product_id, qty, decoration_type, session_id, verified: bool).

**FR-18** Only verified leads (email confirmed) trigger a quote request notification to the sales team.

**FR-19** Quote request notification must include: customer name, email, phone, product name + SKU, quantity, decoration type, placement zone, generated design image (clean, internal URL), estimated price range from pricing slab (informational only).

**FR-20** The sales team is notified via email. Notification email address is configurable via `SALES_NOTIFICATION_EMAIL` env var.

### 6.5 Security & Compliance

**FR-21** No PII (name, email, phone) stored in logs or Sentry breadcrumbs.  
**FR-22** All API keys in environment variables; never hardcoded.  
**FR-23** Rate limiting on all generation and chatbot endpoints.  
**FR-24** Admin queue protected by `X-Admin-Secret` header.  
**FR-25** CORS locked to `ALLOWED_ORIGINS` env var.  

---

## 7. User Flows

### 7.1 Primary Flow — Chatbot Customisation (voice or click)

```
Customer lands on product page
    │
    ▼
[Selects colourway] → views multi-angle images
    │
    ▼
Clicks "Customize This Product"
    │
    ▼
Chatbot opens (slide-in panel or full-screen on mobile)
Ricardo: "Hi! May I ask your name?"
    │
    ├─► Voice input ──┐
    ├─► Click chips   ├──► Name captured
    └─► Type input ───┘
    │
    ▼
Ricardo: "Hi [Name]! What's the occasion for this hat?"
[Gift / Staff uniforms / Resale / Event giveaway / Personal / Other]
    │
    ▼
Ricardo: "How many pieces are you thinking?"
[1 / 2–11 / 12–49 / 50–99 / 100+ / Not sure]
    │
    ▼
⚙ Decoration Recommendation Engine runs
Ricardo: "Based on your order of [qty], I'd recommend [print/embroidery].
         Here's why: [explanation]. Does that work for you?"
[Yes, that works / Tell me more / I prefer embroidery / I prefer print / What about a patch?]
    │
    ▼
Ricardo: "Great! Do you have a logo or artwork to add?"
[Upload logo / Describe what I want instead]
    │
    ├─► Upload path:
    │     Customer uploads file
    │     Ricardo: "Got it! Does this logo have a background you'd like removed?"
    │     [Yes, remove it / No, keep as-is]
    │     │
    │     ▼
    │     Ricardo: "Where would you like it placed?"
    │     [Front panel / Side / Back / Under-brim]
    │     │
    │     ▼
    │     Ricardo: "And within the front panel — left, center, or right?"
    │     [Left / Center / Right]
    │     + "Upper, middle, or lower?" [Upper / Middle / Lower]
    │
    └─► Describe path:
          Customer describes design in text or voice
          │
          ▼
          Same placement questions as above
    │
    ▼
⚙ Design generation starts (async)
Ricardo: "Perfect — I'm putting the design together now.
         While I'm working on it, could I grab your email so I can 
         send you the design when it's ready?"
    │
    ▼
Customer provides email
Ricardo: "And your phone number? (Optional — I can SMS it too)"
    │
    ▼
⚙ Verification email sent
Ricardo: "I've sent you a quick verification email. Could you click the 
         link to confirm I've got it right? Check your spam if you don't 
         see it in a moment."
    │
    ▼
Customer clicks verification link (separate tab)
    │
    ▼
⚙ Design generation completes (if not already done)
Ricardo: "Thanks for confirming, [Name]! Here's your design:"
    │
    ▼
[Design shown on screen — watermarked]
[Email/SMS sent with watermarked design]
[Quote request sent to sales team]
    │
    ▼
Ricardo: "Would you also like to see how it'd look on the side panel?"
[Yes, add more / No, I'm happy with this]
    │
    ├─► Upsell accepted → repeat placement flow for second zone
    └─► Upsell declined:
        Ricardo: "Great choice! One of our team will be in touch with your 
                 quote shortly. [Optional: Order today and mention my name 
                 for an extra 5% off!]"
    │
    ▼
Session ends / customer returns to storefront
```

### 7.2 Voice Input Sub-Flow

```
Customer clicks mic button
    │
    ▼
Browser requests mic permission (first time only)
    │
    ├─► Granted:
    │     Mic indicator activates (pulsing ring)
    │     Customer speaks
    │     Real-time STT transcript shown in chat
    │     Customer confirms or re-records
    │     Text submitted to chatbot
    │
    └─► Denied / unavailable:
          Click chips and text input shown
          Voice button hidden for session
```

### 7.3 Email Verification Sub-Flow

```
Chatbot collects email
    │
    ▼
POST /leads/verify/send {email, session_id}
    │
    ▼
Backend sends email with verification link (JWT token, TTL 15 min)
    │
    ▼
Customer clicks link → GET /leads/verify/{token}
    │
    ▼
Backend marks lead as verified
    │
    ▼
WebSocket / polling → chatbot UI notified of verification
    │
    ▼
Chatbot reveals design on screen
Design email sent to customer
Quote request sent to SALES_NOTIFICATION_EMAIL
```

### 7.4 Sales Team Quote Request Flow

```
Chatbot session completes (design generated + lead verified)
    │
    ▼
Backend generates quote request package:
  - Customer: name, email, phone
  - Product: name, SKU, colour
  - Quantity: N
  - Decoration type: print / embroidery / patch
  - Placement: zone + position
  - Design image: internal signed URL (clean, no watermark)
  - Price range: from pricing slab (informational)
    │
    ▼
Email sent to SALES_NOTIFICATION_EMAIL
(+ optionally: entry in admin queue for tracking)
    │
    ▼
Salesperson reviews, prepares final quote, sends to customer directly
```

### 7.5 Admin Approval Queue Flow

```
Salesperson / design reviewer logs into /admin/queue
    │
    ▼
Table shows all sessions: date, customer name, product, thumbnail, status
    │
    ▼
Reviewer clicks session row → expands detail:
  - All generated images (clean versions)
  - Customer notes from chatbot
  - Decoration type, placement, quantity
    │
    ▼
Reviewer marks: Approved / Rejected / Needs Changes
(optionally adds reviewer notes)
    │
    ▼
Status updated in DB; customer notified (future feature)
```

---

## 8. Non-Functional Requirements

| Requirement | Target |
|---|---|
| Preview generation latency | < 5 seconds (p95) |
| Email verification delivery | < 30 seconds |
| Chatbot response latency | < 2 seconds per turn |
| Concurrent sessions | Support 50 simultaneous chatbot sessions |
| Image storage | Private R2 bucket; signed URL TTL configurable |
| Uptime | 99.5% (Railway managed) |
| Mobile support | iOS Safari 16+, Android Chrome 110+ |
| Accessibility | WCAG 2.1 AA for chatbot panel |
| Data retention | Session data retained 90 days (configurable) |

---

## 9. Updated Data Models

```
DesignSession
  id, created_at, channel, entry_path
  product_ref (JSON)       -- product_id, SKU, colour
  inputs (JSON)            -- chatbot-collected: name, purpose, qty, decoration, placement
  status                   -- active | completed | abandoned
  share_token

Generation
  id, session_id, tier, model
  image_url                -- internal R2 URL (clean)
  watermarked_url          -- R2 URL (watermarked version)
  cost_usd, latency_ms, prompt_hash, created_at

Lead
  id, session_id
  name, email, phone
  email_verified (bool), verified_at
  quote_request_sent (bool), quote_sent_at
  created_at

ApprovalSubmission
  id, session_id
  product_ref (JSON)
  final_image_urls[]       -- clean versions
  watermarked_image_urls[] -- customer-facing versions
  source_ref (JSON)        -- chatbot inputs
  customer (JSON)          -- name, email, phone (from Lead)
  review_status            -- pending | approved | rejected | needs_changes
  reviewer_notes, decided_at

ProductReference
  id, shopify_product_id, variant_id
  style, colour
  reference_image_url      -- base product photo used for compositing
  view_images (JSON)       -- {front, left, right, back, overhead, underhead}
  placement_zones[]
  decoration_types[]
  pricing_slabs (JSON)     -- [{min_qty, max_qty, price_per_unit}]

ChatbotConfig
  id, persona_name, persona_avatar_url
  greeting_template
  upsell_prompts (JSON)
  discount_rules (JSON)    -- day_of_week, qty_thresholds, percentages
  updated_at

EmailVerification
  id, lead_id, token (hashed)
  expires_at, used_at
```

---

## 10. Updated API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | /products | List products with all views |
| GET | /products/{id} | Single product detail |
| POST | /sessions | Create design session |
| GET | /sessions/{token} | Retrieve session by share token |
| POST | /chat/message | Send message to chatbot (text or transcribed voice) |
| GET | /chat/{session_id}/history | Retrieve conversation history |
| POST | /uploads | Upload logo/asset; returns R2 URL |
| POST | /generate/preview | Trigger preview generation |
| POST | /generate/final | Trigger final-tier generation |
| POST | /leads | Create lead record from chatbot |
| POST | /leads/verify/send | Send verification email |
| GET | /leads/verify/{token} | Confirm email verification |
| GET | /submissions | List approval submissions (admin) |
| PATCH | /submissions/{id} | Update review status (admin) |
| GET | /admin/config | Get chatbot config |
| PATCH | /admin/config | Update chatbot config |
| GET | /health | Health check |

---

## 11. Environment Variables (additions to v1)

```bash
# Lead capture & notifications
SALES_NOTIFICATION_EMAIL=           # where quote requests go
EMAIL_FROM=noreply@madhats.com.au   # sender address
EMAIL_PROVIDER=                     # sendgrid | ses | smtp
SENDGRID_API_KEY=                   # if using SendGrid
TWILIO_ACCOUNT_SID=                 # if using SMS
TWILIO_AUTH_TOKEN=
TWILIO_FROM_NUMBER=

# Verification
VERIFICATION_TOKEN_TTL_SECONDS=900  # 15 min default

# Watermark
WATERMARK_IMAGE_URL=                # R2 URL of watermark asset

# Chatbot
CHATBOT_PERSONA_NAME=Ricardo        # default persona name
```

---

## 12. Open Questions / Pending Decisions

| # | Question | Owner | Notes from meeting |
|---|---|---|---|
| OQ-01 | Chatbot name / persona finalised? | Client (MadHats) | "Ricardo" is placeholder; client to confirm |
| OQ-02 | Design shown on-screen before email OR email-only? | Client | Meeting: show on screen after verification; confirm this is correct |
| OQ-03 | Promotional discount triggers (stock levels, exact qty thresholds) | Client | Pricing slabs exist on website; client to export data |
| OQ-04 | Large-brand / prestigious order handling (e.g. Qantas, ANZ) | Client | Meeting: salesperson handles manually; chatbot just routes normally |
| OQ-05 | Patch decoration guidance rules (when to recommend against patches) | Client | Meeting: patches most expensive; exact rule thresholds TBD |
| OQ-06 | Email provider choice (SendGrid / SES / SMTP) | Satish | Affects VERIFICATION email latency |
| OQ-07 | SMS: required for prototype or Standard tier only? | Client | Meeting mentioned as option; confirm priority |
| OQ-08 | Gemini model IDs for preview and final tiers | Satish | Verify against live Google API docs |
| OQ-09 | Initial product subset (which 5–10 SKUs launch first) | Client | Confirm with MadHats |
| OQ-10 | Sales team notification: email only, or also Slack / CRM? | Client | Confirm preferred channel |
| OQ-11 | Voice STT provider: browser Web Speech API / Whisper / Gemini audio | Satish | Browser API is simplest for prototype; Whisper for accuracy |

---

## 13. Out of Scope (do not build)

- Customer face uploads or "try-on" with customer photo
- Logo vectorisation / auto-cleanup pipeline
- Full InkyBay replacement
- Automated quoting / pricing engine (salesperson handles quotes)
- Full Shopify catalogue sync (500+ SKUs) — stub data for prototype
- Admin dashboard beyond the approval queue

---

## 14. Alignment with Existing Spec

The following from the 2026-06-26 design spec remain **unchanged**:
- Tech stack (FastAPI, React, Vite, Tailwind, Gemini, fal.ai, Postgres, R2, Railway)
- ImageProvider abstraction and adapter pattern
- Hard constraints (composite onto real product photos, no face uploads, InkyBay untouched, etc.)
- Security rules (env vars, signed URLs, rate limiting, CORS, admin auth, no PII in logs)
- Agent / subagent map
- Docker Compose local dev setup

The following are **revised** by this document:
- Primary UX paradigm: conversational AI chatbot replaces static design studio form
- User flows: chatbot-driven sequence replaces tab-based left/right panel layout
- Feature list: 21 core features (expanded from 10) + 11 standard features
- Data models: Lead, ChatbotConfig, EmailVerification added; Generation extended with watermarked_url
- API surface: chat endpoints, lead/verification endpoints, config admin endpoint added
