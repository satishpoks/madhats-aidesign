# MadHats — AI Design Studio (MVP) · Build Brief

> Purpose of this document: a build-ready brief for an AI coding agent (Claude Code) and the dev team. It captures the client context, the product goal, the exact MVP scope, the feature flows, the technical architecture, data shapes, edge cases, and acceptance criteria. Use it to generate detailed use cases, plan deployment, and start building.

---

## 1. Client & Product Context

### 1.1 Who the client is
**MadHats** (madhats.com.au) is an Australian custom-headwear and printing company running on **Shopify**. They sell 500+ headwear styles (caps, trucker, snapback, bucket, beanies, visors, scarves, kids) across their own and partner brands (Otto, FlexFit, Richardson, Inivi, GTO). They serve **both B2C and B2B** — schools, clubs, corporates, events and resellers — and are trusted by large brands (Toyota, ANZ, McDonald's, Australia Post, Football Australia).

Their core model is **"buy it blank, add a logo, or go full custom."** Customisation (embroidery and print) is not a feature — it is the foundation of the business. They have **a full-time in-house Shopify developer** and a small dev team; the AI work is delivered by an external AI Manager working alongside them.

### 1.2 Current state
- **Customiser today:** InkyBay (a generic Shopify product personaliser). Functional but basic — this is what the new Design Studio will eventually replace. **InkyBay stays live in parallel during this MVP; do not remove it.**
- **Email:** Google Workspace / Gmail for business email.
- **Sales motion:** highly relationship-driven (quotes and reorders happen over email, chat and phone). Reply speed is already a competitive strength.

### 1.3 The business goal (the "why")
Modernise the on-site design experience so that:
1. **More browsers become buyers** — let customers see their idea on a cap instantly, removing the main hesitation on custom orders.
2. **Less manual concept time** — reduce the design team's effort spent producing free concept mockups by hand.
3. **A visible competitive edge** — most competitors still say "email us for a quote." MadHats wants "describe it and see it in seconds."
4. **Move customers from exploring → ordering** in one flow rather than across disconnected steps.

### 1.4 What this service is (scope of THIS build)
An **AI Design Studio MVP** focused on one headline capability — **"Describe it, see it" + Photo-to-product visuals** — delivered as a custom, owned system that sits on top of Shopify (not a third-party SaaS the client rents per seat/contact).

### 1.5 Guiding principles / hard constraints
- **Product fidelity is paramount.** Mockups must show MadHats' *actual* product (correct SKU/shape/colour), achieved by compositing the design onto **real product photos used as reference images** — NOT by generating a cap from scratch. A hallucinated/wrong cap is a credibility failure for a custom-merch business.
- **Human-in-the-loop on anything that becomes an order.** Generated concepts are previews; the design team approves before production. The MVP does not auto-commit production artwork.
- **Build on Shopify, work with their Shopify dev.** Anything touching the storefront/theme/checkout is coordinated with the in-house Shopify developer, not rebuilt from scratch.
- **Model-agnostic / swappable.** Image models change monthly; keep them behind a thin abstraction so they can be A/B tested and swapped via config, not code rewrites.
- **Custom-built and owned.** No per-image SaaS lock-in; usage-based model APIs are fine.
- **Cost-aware by design.** Previews dominate volume — keep them on the cheap/fast tier; reserve the premium tier for finals.

### 1.6 Explicitly OUT of scope for this MVP (do not build)
- **"Wear It" with a real customer's own photo/face** — that is a separate, later feature with consent/age-gating obligations (MadHats serves schools/minors). In THIS build, "worn" means a **generic model** wearing the cap, generated from the product + design only. **Do not build any end-user face-upload flow here.**
- Advanced logo vectorisation / auto-cleanup pipeline (light handling only; full version is a later sub-phase).
- Full Shopify-native configurator UI that fully replaces InkyBay (this MVP is a lightweight preview surface).
- Full 500-SKU coverage on day one (launch with a curated set of top-selling styles; design for expansion).
- Quoting/pricing logic (lives in a separate Chatbot service; this MVP can hand off but does not own pricing).

---

## 2. Engagement Scope (client has opted for these three items)

1. **Discovery & infra setup** — confirm API/vendor choices, Shopify access and field schema, and design-approval workflow expectations; stand up core infrastructure (API architecture, environments, image-gen pipeline wiring).
2. **"Describe it, see it" / Photo-to-product visuals** — text/voice input → instant on-cap mockup; prompt engineering for cap-specific rendering; live preview UI; upload a logo or reference photo → photorealistic mockup, worn or in context.
3. **Production testing, refining, fixes, deployment, documentation & handover** — end-to-end QA across all flows, edge-case handling, staging → production deploy, written handover docs, and a team walkthrough.

---

## 3. The Feature in Depth

### 3.1 The three core flows (this is what "all three flows" refers to in QA)
- **Flow A — Describe it, see it (text/voice → mockup):** customer describes a design in words (typed or spoken); system generates an on-cap mockup of a selected/!inferred product.
- **Flow B — Photo-to-product (upload → mockup):** customer uploads a logo/artwork/reference image; system composites it onto the chosen product photorealistically (print or embroidery look).
- **Flow C — Worn / in-context (presentation mode):** the chosen design is shown on a **generic model** wearing the cap, or staged in a lifestyle/context scene, for a more convincing preview.

### 3.2 Entry paths (how a session starts)
- **Pick-product-first (default, lower-risk):** customer selects a product (style + colour) from a curated catalogue subset, then describes or uploads the design to put on it. AI only has to interpret the *design*, not guess the product.
- **Describe-first (advanced):** customer describes the whole idea in free text; AI infers the best-matching product from the catalogue + the design, then renders. Always resolves to a real catalogue product before rendering.

### 3.3 Use cases / user stories (seed list — expand during discovery)
- As a **club organiser**, I type "navy snapback, gold embroidered club crest, rope front" and see it on a real MadHats snapback within seconds.
- As a **small-business owner**, I upload my logo PNG, pick a black trucker cap, and see my logo placed and sized correctly on the front panel.
- As a **mobile user**, I tap the mic and speak my design idea instead of typing.
- As a **corporate buyer**, I preview my logo on three different cap styles to compare before requesting a concept.
- As a **shopper**, I see the finished cap on a model (worn) so I can judge how it looks in real life, then hit "request this concept."
- As the **MadHats design team**, I receive a submitted concept (design + product + reference assets + the customer's intent) in an approval queue so I can refine and approve before it becomes artwork.
- As a **returning visitor**, I can save/share a generated design via a link.

### 3.4 Functional requirements
**Input & capture**
- Accept typed text prompts; accept voice input (speech-to-text) on supported browsers/mobile.
- Accept image upload (logo/artwork/reference): PNG/JPG/SVG/WebP; size/type validation; reject unusable uploads with a helpful message.
- Product selection from a curated catalogue subset (style + colourway), sourced from Shopify.

**Generation**
- Generate an on-cap mockup grounded in the **real product reference image** for the selected SKU/colour.
- Support a **fast live-preview** generation (low latency, lower cost) and a **high-fidelity final** generation ("see the good version" / "request this concept").
- Support "worn / in context" presentation rendering (generic model; no customer face).
- Cap-specific prompt engineering: correct placement zones (front panel, side, back, under-brim), decoration style (embroidery vs print look), curvature/lighting realism, legible logo text.

**Preview UI**
- Live preview surface (lightweight; embeddable on the storefront, coordinated with the Shopify dev). Not the full InkyBay replacement.
- Show generation progress/loading state; allow quick iteration (tweak prompt, re-place logo, change colour).
- Mobile-responsive.
- Save / share a design (shareable link or saved session id).

**Concept → approval (HITL)**
- "Request this concept" submits the design package to a **design-team approval queue** (design team are the reviewers).
- Submission package includes: chosen product (SKU/colour), the generated final image(s), the source prompt and/or uploaded asset, and any customer notes/contact.
- Design team can view, refine externally, approve/reject. (MVP can be a simple internal queue/dashboard or a structured notification + record; confirm in discovery.)

### 3.5 Model stack & routing (recommended; keep swappable)
Two-tier image strategy, all behind a single internal `ImageProvider` interface (one method to generate/edit given prompt + reference image(s) + params):
- **Live preview tier (fast/cheap):** `Nano Banana 2` (Gemini 3.1 Flash Image) or `FLUX.2 Flex` — low latency, low cost per image; used for iterative tweaking.
- **Final/hero tier (high fidelity):** `Nano Banana Pro` (Gemini 3 Pro Image) — best at compositing a logo onto a real product photo, legible text on curved surfaces, and consistent lighting/shadows.
- **Alternative / A-B for photoreal "in context":** `FLUX.2 Pro` (strongest raw photorealism, exact brand-colour control).
- **Voice → text:** Whisper (self-host) or Deepgram, or Gemini native audio. This is a thin STT layer in front of the same text-prompt path.
- **Selection is config-driven**, so the team can A/B on real MadHats caps during the build and let results decide. Aggregators (fal, Replicate) make swapping a ~one-line endpoint change.

**Non-negotiable architectural rule:** every generation call passes the **real product photo as a reference/conditioning image**. The model edits/composites onto that, it does not invent the cap.

### 3.6 Cost controls (build these in)
- Default previews to **standard/low resolution**; only render **2K finals** on "request concept"; reserve 4K for explicit print-ready needs.
- **Cache** generations keyed by (product + colour + normalised prompt + asset hash) to avoid re-billing identical requests.
- Rate-limit per session/IP to prevent abuse-driven spend.
- Track per-generation cost + tier in logs for the cost dashboard.

---

## 4. Technical Architecture

### 4.1 High-level components
- **Frontend preview widget** — embeddable UI on the storefront (text/voice input, product picker, upload, live preview, save/share, "request concept"). Coordinate embedding with the Shopify dev.
- **Backend API service** — orchestrates input handling, product/reference lookup, prompt assembly, model calls (via `ImageProvider`), caching, persistence, and the approval-submission endpoint.
- **Image-gen pipeline** — `ImageProvider` abstraction + per-model adapters; tier routing (preview vs final); reference-image injection; resolution control.
- **STT layer** — voice → text before prompt assembly.
- **Storage** — generated images (object storage / CDN), session/design records (DB), product reference images + metadata (synced/cached from Shopify).
- **Shopify integration** — read product catalogue, variants (style/colour), and product images; field-schema mapping; storefront embedding. (No checkout/quote logic in this MVP.)
- **Approval queue / handoff** — internal surface or structured notification + record for the design team.
- **Observability** — request logs, generation cost/latency metrics, error tracking.

### 4.2 Data flow (happy path, Flow B example)
1. Customer picks product (SKU + colour) → frontend fetches the **real product reference image** + metadata from backend (cached from Shopify).
2. Customer uploads a logo → backend validates, stores asset, computes asset hash.
3. Backend assembles a cap-specific prompt (placement zone, decoration style, product description) + reference image(s).
4. Backend calls `ImageProvider` **preview tier** → returns a fast mockup → shown in live preview.
5. Customer iterates (reposition/colour/prompt). Each change = new preview generation (cache-checked).
6. Customer clicks "request this concept" → backend calls **final tier** at 2K → stores final image(s).
7. Backend creates an **approval submission** (product, final image, prompt/asset, notes) → design-team queue/notification.
8. Customer gets a confirmation + optional shareable link/saved session.

### 4.3 Suggested data shapes (adapt to chosen stack)
```
DesignSession {
  id, createdAt, channel(web|mobile),
  entryPath(pick_first|describe_first),
  productRef { shopifyProductId, variantId, style, colour, referenceImageUrl },
  inputs { promptText?, voiceTranscript?, uploadedAssetId?, assetHash? },
  generations [ { id, tier(preview|final), model, params, imageUrl, costUsd, latencyMs, createdAt } ],
  status(draft|concept_requested|submitted|approved|rejected),
  share { token, url }?
}
ApprovalSubmission {
  id, sessionId, productRef, finalImageUrls[], sourcePromptOrAssetRef,
  customer { name?, email?, notes? },
  reviewStatus(pending|approved|rejected|needs_changes),
  reviewerNotes?, decidedAt?
}
ProductReference {  // synced/cached from Shopify
  shopifyProductId, variantId, style, colour,
  referenceImageUrl, placementZones[], decorationTypes[print|embroidery]
}
```

### 4.4 Shopify integration notes
- Read-only catalogue/variant/image access for the curated product subset (Admin API / Storefront API as appropriate — confirm with Shopify dev).
- **Field schema** to confirm in discovery: which product fields map to style, colourway, available decoration types, and which image is the canonical "reference" image per variant.
- Storefront embedding approach (theme app extension / app block / script) decided with the Shopify dev.
- No write-back to Shopify products in the MVP; no checkout/cart manipulation (that's the chatbot/ordering work, separate).

---

## 5. Non-Functional Requirements
- **Latency:** live preview target a few seconds end-to-end (tier + resolution chosen to hit this). Final render can take longer.
- **Scalability:** stateless backend that scales horizontally; queue/async for final renders if needed.
- **Security/privacy:** uploaded assets stored securely; signed URLs; retention policy for uploaded assets and generated images (confirm with client); no PII in logs; secrets in env/secret manager. (Note: full consent/age-gating is only needed for the out-of-scope "Wear It" feature; this MVP uses generic models, not customer photos.)
- **Cost:** per-generation cost tracked; preview/final tiering enforced; caching + rate limiting on.
- **Reliability:** graceful fallback if a model/provider errors (retry, fallback provider, or friendly failure state); never block the storefront.
- **Observability:** structured logs, error tracking, basic metrics (generations/day, cost/day, avg latency, cache hit rate, concept-request rate).

---

## 6. Edge Cases & Failure Handling
- Poor-quality / tiny / non-image uploads → validate and prompt for a better file.
- Logo with transparency / odd aspect ratio → handle background + placement gracefully.
- Describe-first prompt that matches no real product → ask the user to pick from nearest catalogue matches rather than inventing a product.
- Text-heavy logos on curved surface → route finals to the strongest-text model tier; verify legibility.
- Model/provider timeout or error → retry, then fallback provider, then friendly error with "try again."
- Inappropriate/abusive prompt or upload → moderation check; reject.
- Very high request volume from one session → rate limit.
- Mobile/browser without mic support → hide/disable voice, keep text.
- Product image missing for a variant → exclude from the curated set or fall back to a base style image.

---

## 7. Acceptance Criteria (per flow)
**Flow A — Describe it, see it**
- Given a typed or spoken design + a selected product, the system returns an on-cap mockup of the **correct real product** within the latency target.
- Voice input transcribes accurately and produces the same result path as typed input.

**Flow B — Photo-to-product**
- An uploaded logo is placed on the correct placement zone of the selected product, correctly sized, legible, with believable lighting/curvature — on the actual product, not a generated cap.

**Flow C — Worn / in context**
- The approved design renders on a **generic model** (no customer face) or staged scene, recognisably the same product + design.

**Cross-cutting**
- "Request this concept" creates an approval submission with all assets and reaches the design team.
- Previews use the cheap tier; finals use the high-fidelity tier; costs are logged.
- InkyBay remains fully functional throughout.
- Works on desktop and mobile.

---

## 8. Deployment Plan
- **Environments:** local → staging → production, with separate API keys/quotas per env.
- **Infra (item 1):** API service scaffold, env/secret management, object storage + CDN, DB, image-gen pipeline wiring with the `ImageProvider` abstraction and at least one preview + one final model wired.
- **Rollout:** soft-launch the preview widget to a limited subset of storefront traffic (or behind a flag) before full rollout; monitor cost, latency, concept-request rate, and output quality on real caps.
- **Handover (item 3):** written docs (architecture, runbook, model config & how to swap, cost dashboard, env setup), plus a walkthrough session with the MadHats team and Shopify dev.

---

## 9. Open Decisions to Confirm in Discovery (item 1)
- Final model choices per tier (A/B Nano Banana Pro vs FLUX.2 Pro on real MadHats caps; pick preview-tier model).
- Curated initial product subset (which top-selling styles/colours launch first).
- Shopify field-schema mapping (style, colour, decoration types, canonical reference image per variant) — with the Shopify dev.
- Approval-queue form factor (internal dashboard vs structured notification + record) and who the reviewers are.
- Asset/image retention policy and any moderation requirements.
- Storefront embedding method (theme app extension / app block / script) — with the Shopify dev.
- Hosting target and whether voice input is in the MVP or fast-follow.

---

## 10. Suggested Build Sequence (for Claude Code)
1. **Scaffold** backend API service + `ImageProvider` abstraction + one preview adapter + one final adapter (mock first, then real).
2. **Product reference layer:** sync/cache a small curated product set + reference images + placement metadata (stub from sample data until Shopify access is granted).
3. **Flow B (photo-to-product) end to end** first — it's the clearest value and exercises the whole pipeline (upload → reference-conditioned generate → preview → final → submission).
4. **Flow A (describe / pick-first + describe-first)** reusing the same pipeline; add STT for voice.
5. **Flow C (worn / in context)** presentation rendering.
6. **Preview UI** (lightweight, embeddable), then concept→approval submission + queue/notification.
7. **Cost controls** (tiering, caching, rate limits) + **observability**.
8. **Edge-case hardening, QA across all three flows, staging→prod, docs + handover.**

## 11. Suggested Tech Stack Defaults (adjust to team preference)
- Backend: Node/TypeScript or Python (FastAPI). Keep the `ImageProvider` interface clean and provider-agnostic.
- Frontend widget: framework-light, embeddable; mobile-first; no browser storage of secrets.
- Storage: object storage + CDN for images; Postgres for session/approval records.
- Models via aggregator (fal/Replicate) or direct provider APIs, config-driven per tier.
- STT: Whisper/Deepgram/Gemini audio behind a small interface.
- Secrets via env/secret manager; never hard-coded.

---

### Reminder for the agent
- Composite onto **real product photos**; never invent the cap.
- **No customer-face uploads** in this build ("worn" = generic model only).
- Keep models **swappable via config**.
- **Human-in-the-loop**: concepts are previews until the design team approves.
- Coordinate anything Shopify-storefront-related with the **in-house Shopify developer**.
- Keep **InkyBay running** in parallel.
