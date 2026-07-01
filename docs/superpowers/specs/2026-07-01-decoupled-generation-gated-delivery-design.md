# Decoupled Async Generation + Gated Preview Delivery — Design

**Date:** 2026-07-01
**Status:** Approved (ready for implementation)
**Author:** Ricardo build (customer-flow fix)

---

## 1. Problem

Image generation runs as an async background task (`generate.py:_run_generation`),
but the customer-facing preview email is sent at **email-verification time**
(`leads.py:_post_verification_actions`) using whatever `generations` row happens to
be `complete` at that instant. Because the two tracks are independent, three race
conditions produce broken outcomes:

1. **Generation still running** when the customer clicks the verify link → no
   complete row → preview email sent with a **blank image**.
2. **Generation failed** (e.g. Gemini quota/429) → no complete row → **blank/broken
   email**, and the customer is never told anything went wrong.
3. **Generation completes _after_ verification** → the blank email already went out;
   the finished design is never delivered.

Additionally, the frontend still surfaces a red **"Generation failed"** message to
the customer, which contradicts the desired experience.

## 2. Goals

- Treat generation and email verification as two **independent async tracks**.
- **Email verification is the mandatory first gate.** No preview email is ever sent
  to an unverified address.
- The preview email is sent **only when a real image exists** — never blank.
- Whichever track finishes **last** triggers delivery, **exactly once** (idempotent).
- On generation failure: **auto-retry with backoff**, then **alert ops** so a human
  can regenerate. The customer is never shown a failure.
- Customer on-screen: always reassured that the design will arrive by email once
  their address is confirmed — regardless of backend success/failure/timeout.

## 3. Non-Goals

- No message queue / external worker infra. We stay on FastAPI `BackgroundTasks`.
- No change to how generation is triggered (frontend still POSTs `/generate/preview`
  on reaching the GENERATING state; the background task is already fire-and-forget).
- No customer-facing display of the generated image in-chat (already email-only).

## 4. Design

### 4.1 Single delivery primitive — `services/delivery.py`

New module with one idempotent function:

```python
def maybe_send_preview(session_id: str) -> bool:
    """Send the preview + sales emails iff all gates pass. Idempotent.

    Gates (ALL required):
      1. Lead exists for the session AND lead.email_verified is True.
      2. Latest generation for the session is status='complete' AND has an image.
      3. lead.preview_email_sent is False (not already delivered).

    On success: sends preview email (to customer) + sales notification (to store
    ops), sets lead.preview_email_sent=True + preview_sent_at, and preserves the
    existing quote_request_sent behaviour. Returns True if it sent, else False.
    """
```

- Re-loads fresh session + lead + latest generation from the DB (never trusts stale
  `collected` passed through a background task).
- The `preview_email_sent` flag is the exactly-once guard. Two concurrent callers
  (verify handler + generation worker firing near-simultaneously) are made safe by
  re-checking the flag immediately before send; a duplicate is acceptable-to-avoid
  but not catastrophic (worst case: one extra identical email). We keep it simple
  with a flag check + set; a follow-up can add a conditional UPDATE guard if needed.
- This is the **only** place preview/sales emails are dispatched. The existing
  `_post_verification_actions` body moves here (adapted to the gate checks).

### 4.2 Trigger points

`maybe_send_preview(session_id)` is called from **both** completion points:

- **Verification handler** — `leads.py:confirm_verification`, after it marks the lead
  verified and flips `collected.email_verified`. Replaces the current direct
  `_post_verification_actions(...)` call.
- **Generation worker** — `generate.py:_run_generation`, at the end of a **successful**
  completion (after the row is updated to `complete`). Requires `session_id` to be
  passed into `_run_generation` (currently it only receives `job_id`).

Whichever finishes last is the one that finds all gates satisfied and sends.

### 4.3 Generation worker: retry + ops alert

`_run_generation` wraps the provider call in a bounded retry loop:

- **Max 3 attempts.** Exponential backoff between attempts (e.g. ~2s, ~8s; capped).
- **Retry only transient failures**: `google.api_core.exceptions.ResourceExhausted`
  (429), timeouts, and 5xx-class errors. Permanent errors (e.g. 400 InvalidArgument,
  `ValueError` from a missing reference image) fail fast with no retry.
- Record `attempts` on the `generations` row.
- **On final failure:**
  - Set `status='failed'` and store the provider error text in `generations.error`
    (a provider message — non-PII, safe to store; still never logged with customer
    data).
  - Send an **ops alert** email to the store's `sales_notification_email` ("a design
    needs manual attention"), including session id / product / brief so ops can
    regenerate. No customer PII in application logs.
  - When ops later re-runs generation and it completes, the worker calls
    `maybe_send_preview` → email already verified → the design is delivered. The loop
    closes itself with no special-case code.

### 4.4 Email templates — `prompts.py` + `email.py`

Add:
- `GENERATION_ALERT_EMAIL_SUBJECT` / `GENERATION_ALERT_EMAIL_BODY` (plain text, via
  the existing `_send` path).
- `email_service.send_generation_alert(store_email, session_id, product, brief, error)`.

Existing `send_preview_email` / `send_quote_to_sales` are unchanged; they're just now
invoked exclusively from `delivery.maybe_send_preview`.

### 4.5 Frontend — always reassure

`frontend/src/store/generationStore.ts` + `ChatPanel/index.tsx` (`GenerationPanel`):

- **Remove the `status === 'error'` red-text branch entirely.**
- `generating` → spinner + "Generating your design…".
- `done`, `failed`, and `timeout` all render the **same** reassurance:
  > "Your design is being prepared — we'll email it to you once your address is
  > confirmed."
- The store may keep an internal `error`/`status` for diagnostics, but the panel
  never shows a failure to the customer.
- Generation remains a fire-and-forget backend task, so a closed tab does not stop
  delivery.

### 4.6 Schema — one migration

New migration `backend/supabase/migrations/<ts>_decoupled_delivery.sql`:

```sql
alter table leads        add column if not exists preview_email_sent bool not null default false;
alter table leads        add column if not exists preview_sent_at    timestamptz;
alter table generations  add column if not exists error              text;
alter table generations  add column if not exists attempts           int  not null default 0;
```

## 5. Files Touched

**Backend**
- `app/services/delivery.py` — **new**: `maybe_send_preview`.
- `app/api/routes/generate.py` — retry loop, record `attempts`/`error`, ops alert on
  final failure, pass `session_id` into `_run_generation`, call `maybe_send_preview`
  on success.
- `app/api/routes/leads.py` — `confirm_verification` calls `maybe_send_preview`
  instead of `_post_verification_actions`; move that logic into `delivery.py`.
- `app/services/email.py` — `send_generation_alert(...)`.
- `app/prompts.py` — ops-alert subject/body.
- `backend/supabase/migrations/<ts>_decoupled_delivery.sql` — **new**.

**Frontend**
- `src/store/generationStore.ts` — drop customer-facing error surfacing.
- `src/components/ChatPanel/index.tsx` — `GenerationPanel` reassurance-only.

## 6. Testing

**Backend**
- `maybe_send_preview` idempotency: sends exactly once; second call is a no-op.
- Trigger order A: verify **then** generation completes → email sends on completion.
- Trigger order B: generation completes **then** verify → email sends on verify.
- Gate: unverified email → never sends. No image / failed generation → never sends
  (no blank email).
- Retry: transient error retried up to 3×; permanent error fails fast; final failure
  marks `failed`, stores `error`, sends ops alert; `attempts` recorded.

**Frontend**
- `GenerationPanel` shows reassurance on `done`, `failed`, and `timeout`; never shows
  a "failed" message.

## 7. Rollout

- Migration is additive (nullable / defaulted columns) — safe to apply before deploy.
- No env var changes.
- Backwards compatible: existing verified leads without `preview_email_sent` default
  to `false`, so a re-trigger would resend once — acceptable.
