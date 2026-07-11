# Smarter, More Transparent Studio — Design

**Date:** 2026-07-11
**Status:** Approved (ready for implementation plan)
**Author:** Ricardo build (studio UX + cost control)

---

## 1. Problem

The Studio chatbot (Ricardo) works but feels rigid and opaque, and has no ceiling
on AI spend:

1. **Rigid conversation.** `services/conversation/state_machine.py` is a strict linear
   flow. The LLM only interprets an answer to *the current question* (via crude
   per-state keyword heuristics in `orchestrator._ingest`) and words a scripted reply.
   If the customer volunteers information out of order, asks a question, revises an
   earlier answer, or goes off-topic, the bot mis-reads it or drops it. There is a
   narrow backtrack LLM call but nothing that makes the bot feel natural or lets it
   *lead* the customer toward completing the design.
2. **Opaque generation.** By design the generated preview is delivered by email only
   and never shown on-screen (gated delivery). Customers get no visual payoff in the
   session even *after* they verify their email.
3. **No progress cue.** The customer can't tell how many steps remain.
4. **Unbounded regeneration & no config home.** There is no regenerate-with-changes
   flow at all today, and no admin-editable settings store — config is env-vars +
   per-store rows. Nothing caps how many designs a customer can generate, so AI cost
   is unbounded and non-configurable without a developer.

## 2. Goals

- Make the conversation **feel natural and goal-directed** while keeping the
  deterministic state machine as the single source of truth for routing (testable,
  cost-predictable). Handle: info out of order, side-questions, revising an earlier
  answer, and chit-chat — always steering back toward completing the required facts.
- Show the generated design **on the left panel** once it is released (same gate as
  the emailed preview: email verified **and** generation complete), with product-angle
  thumbnails and any regenerations as clickable thumbnails. **No extra AI cost.**
- Show a **"Step X of N"** progress counter each turn.
- Add a **regenerate-with-changes loop** capped by **admin-configurable, global**
  limits, and a **DB-backed global settings store** editable in the admin panel with
  no developer involvement.

## 3. Non-Goals (roadmap, not this build)

- The broader client questionnaire (Shopify product/order sync, user-level RBAC,
  reporting dashboards, per-IP/guest/registered limits, blacklisting, session/file
  timeouts, theme/font/template configurability, AI-model routing per complexity).
- Per-store settings overrides — this build is **global-only** config.
- A message queue / external worker — stays on FastAPI `BackgroundTasks`.
- Multi-variation generation (generating N designs per request) — thumbnails are
  product angles + sequential regenerations, never parallel variants.

---

## 4. Design

### 4.1 Conversation engine — interpreter-first turn

The state machine (`ConversationState`, `TRANSITIONS`, `advance_state`) stays the
authority on routing. The LLM never routes; it only interprets input into structured
data and words the scripted reply. What changes is the interpretation layer.

**Turn interpreter (`intent_extractor.interpret_turn`).** One Haiku call per turn
replaces today's separate backtrack call + per-state keyword `_ingest`. Given the
current state, the required-field schema, `collected` so far, the allowed backtrack
targets, and the FAQ/knowledge blob (§4.4), it returns:

```json
{
  "intent": "answer | provide_info | ask_question | revise | chitchat | backtrack",
  "fields": { "quantity": 50, "decoration_type": "embroidery", "...": "..." },
  "revise_target": "ask_quantity",
  "backtrack_target": "ask_purpose",
  "question_answer": "Embroidery suits logos with a few solid colours…",
  "on_topic": true
}
```

`fields` may include values for **future** steps (out-of-order capture). Everything is
validated against the field schema by the orchestrator; unknown or ill-typed values are
dropped. The LLM proposes; the machine disposes.

**Orchestrator reaction (deterministic):**

- Merge validated `fields` into `collected`.
- `intent == ask_question` or `chitchat` → reply with `question_answer` (or a warm
  redirect) **and re-ask the current state's question; do not advance.** This is the
  goal-leading behaviour: the bot always ends on the next needed question.
- `intent == revise` / `backtrack` → rewind to the target state (must be in
  `ALLOWED_BACKTRACKS[current]`), applying any new value.
- Otherwise advance — but through a new **skip-filled** walk (below), so any upcoming
  question whose field is already present is skipped instead of re-asked.

**Skip-filled advance.** Add `next_unfilled_state(state, collected)` that walks
`TRANSITIONS` from the computed next state and skips any *question* state whose required
field is already set in `collected`. Routing/branch states are resolved as today. This
is what makes out-of-order capture actually save steps.

**Natural wording.** `generate_reply` additionally receives a short summary of what the
interpreter understood this turn, so the scripted reply can acknowledge it
("Got it — 50 caps, embroidered. Where should the logo go?"). System prompt and
per-state instruction templates (`app/prompts.py`) are unchanged in structure.

**Guardrails.**
- The FAQ answer path must **never invent pricing, turnaround, or stock**. If the FAQ
  blob doesn't cover the question, the bot says the team will confirm the exact figure.
- No-key fallback (CI/local without `ANTHROPIC_API_KEY`) keeps today's deterministic
  heuristics: interpret as an answer to the current state only; no side-question or
  out-of-order handling. Behaviour degrades gracefully, tests stay hermetic.
- Net LLM calls per turn: **≤ 2** (interpret + reply), same or fewer than today.

**Field schema.** A single declarative map (state → field name + type + allowed values)
drives extraction validation, skip-filled logic, and progress counting (§4.3). It lives
next to the state machine so all three stay in sync.

### 4.2 On-screen design display

The left pane (`ProductViewer`) is restructured from a 2×2 angle grid into **one large
main image + a horizontal thumbnail strip**.

- **Release gate — identical to email delivery.** The design appears only when the
  email is **verified** *and* a generation is **complete with a real image** — the same
  condition `delivery.maybe_send_preview` uses. Until then the pane shows the product
  angles exactly as today. `ChatPanel` passes the watermarked `previewUrl` from
  `generationStore` into `ProductViewer` only once `chatState` is `email_verified` or
  later.
- **Main image** = watermarked design. **Thumbnails** = product angle photos +
  every regenerated design (§4.4) appended in order. Clicking a thumbnail promotes it to
  the main image; the design thumbnail returns to the design. Pure client-side state, no
  network/AI cost.
- Watermarking is unchanged (`services/watermark.py`); we always show the watermarked
  URL, never the clean one.

### 4.3 Progress indicator — "Step X of N"

Add `progress(state, collected) → {step, total}` to the state machine. It counts only
**customer-facing question states** on the path the customer is currently on; branch
decisions already in `collected` (youth, upload-vs-describe, pins, upsell) resolve which
branch's states to count, and unresolved branches use a sensible default length. The
orchestrator returns `progress` in the existing `data` payload each turn; the frontend
renders "Step {step} of {total}" in the studio header. `total` may shift slightly when a
branch resolves — accepted trade-off; counting only question states keeps it stable.
Statement-only and routing states are excluded so the number never advances without the
customer acting.

### 4.4 Regeneration loop + limits

**New states** appended after the design is released (post-verification/display):

```
EMAIL_VERIFIED → SEND_PREVIEW_EMAIL → SHOW_DESIGN → OFFER_REFINE
OFFER_REFINE  --"request changes"--> DESCRIBE_CHANGES → REGENERATING → OFFER_REFINE
OFFER_REFINE  --"looks good"------->  (final-design email) → QUOTE_REQUESTED → …
```

- **DESCRIBE_CHANGES** captures the tweak; **REGENERATING** starts a new generation that
  **reuses the locked product reference** and the existing prompt-builder pipeline,
  layering the change onto the accumulated design intent. On completion the new
  watermarked image becomes the main image and a new thumbnail (§4.2). Regenerations are
  **on-screen only — never emailed.**
- Each regeneration is one `generations` row for the session, tagged as an edit
  (`tier`/metadata distinguishes it from the initial). The session's **selected design**
  (which thumbnail is active) is what the quote captures.

**Emails.** First design emailed on verification (unchanged). **Final design emailed on
completion** (when the customer chooses "looks good" / requests the quote), attaching the
currently selected design — **deduped**: skip the final email if no regeneration occurred
(selected == first), so we never send a duplicate.

**Two limits (both global, admin-set):**

- `regen_edits_per_session` (**N**): the first design is free; after **N** edits within a
  session `OFFER_REFINE` stops offering changes, the bot says so warmly, and routes to
  the quote / contact path.
- `designs_per_customer_per_day` (**D**): counted by **verified email** across sessions
  over a rolling 24 h. Enforced at generation start (initial and regenerations). When
  exceeded, the bot explains today's limit is reached and points to the quote/contact
  path — never an error.

Limit checks read from the settings service (§4.5). Per-day counting is a `count` query
on `generations` joined to the session's verified `leads.email` within the window.

### 4.5 Global settings store + admin Settings view

New single-row **`app_settings`** table (Supabase migration) holding:

| key | type | default (from env) |
|---|---|---|
| `regen_edits_per_session` | int | `REGEN_EDITS_PER_SESSION` (e.g. 3) |
| `designs_per_customer_per_day` | int | `DESIGNS_PER_CUSTOMER_PER_DAY` (e.g. 10) |
| `faq_knowledge` | text | "" |

- **`services/settings_service.py`** — `get_settings()` returns the row merged over env
  defaults, with a short in-process TTL cache (invalidated on write). All limit checks
  and the interpreter FAQ read through it.
- **Admin API** — `GET /admin/settings` and `PATCH /admin/settings` (gated by
  `X-Admin-Secret`, `require_admin`, like the rest of the dashboard). PATCH validates
  ranges (non-negative ints) and updates the single row.
- **Admin frontend** — a new `SettingsView` in `frontend/src/admin/views/` with a simple
  form (the two numbers + the FAQ textarea), wired through `adminApi.ts` and added to the
  admin nav.

Env vars provide the initial defaults so a fresh deploy behaves sanely before anyone
opens the panel; the DB row wins once set.

---

## 5. Data & schema touchpoints

- **New:** `app_settings` (single-row global config).
- **Reused:** `generations` (regenerations are additional rows per session);
  `design_sessions.collected` gains fields (selected-design pointer, edit count, captured
  future-step values); `leads` for per-customer/day counting by verified email.
- **New env vars:** `REGEN_EDITS_PER_SESSION`, `DESIGNS_PER_CUSTOMER_PER_DAY`
  (documented in `.env.example`).

## 6. Testing

- **Conversation:** unit tests feed canned `interpret_turn` outputs (no live LLM) to
  assert: out-of-order capture skips the right states; side-question answers and does not
  advance; revise/backtrack rewinds correctly; chit-chat redirects; no-key heuristic path
  unchanged. Existing state-machine tests stay green.
- **Progress:** table-driven tests of `progress()` across each branch.
- **Display:** frontend tests that `ProductViewer` shows the design only when gated,
  swaps main/thumbnail on click, and appends regenerations.
- **Limits:** tests that the Nth+1 edit stops offering changes; that the per-day cap
  blocks at D and messages (not errors); that settings reads honour DB-over-env.
- **Settings:** admin GET/PATCH auth + validation; cache invalidation on write.
- Full suites (`pytest`, `vitest run`) must stay green.

## 7. Risks / open points

- **N stability in progress count** when branches resolve — mitigated by counting only
  question states; acceptable per product decision.
- **Regeneration prompt fidelity** — must keep the fidelity-locked reference so a "change"
  edits, not replaces, the design; reuse the existing prompt-builder path.
- **Per-day limit correctness** hinges on the verified email; unverified sessions can't
  reach generation anyway (gated), so counting verified-email generations is well-defined.
