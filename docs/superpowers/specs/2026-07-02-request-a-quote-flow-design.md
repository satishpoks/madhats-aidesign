# Request-a-Quote Flow — Design

**Date:** 2026-07-02
**Status:** Approved (design phase)

---

## 1. Problem & Goal

When a customer's preview email is delivered, the email already contains a
"Yes, I love it — request a quote" call-to-action. Today that link is a dead
`mailto:` placeholder (`app/services/delivery.py`). We want it to open a real
page where the customer:

1. Sees their design and confirms the details (product / decoration / placement
   read-only; **quantity editable**; optional free-text note).
2. Optionally leaves a **phone number** and opts in to be "notified when the
   quote is ready on the phone" so a MadHats sales rep can follow up.
3. Confirms — and sees a message that **our representative will verify the quote
   and send it to them soon**.

On submit, the lead is **tagged in the backend admin center** as having
requested a quote and liked the design, and the sales team gets a richer,
"customer confirmed" notification.

---

## 2. Decisions (locked)

| # | Decision |
|---|----------|
| Sales notification timing | **Keep** the existing auto-notify at preview delivery, **and** send a second, richer "customer confirmed" notification on explicit request. Two distinct signals, two flags. |
| Page fields | Read-only design summary (product, decoration, placement) + preview image; **editable quantity** + **optional note**; optional phone + "notify me" consent. No editing of decoration/placement. |
| Phone / notification | **Capture only** — store phone + consent flag on the lead and include them in the sales notification. A human rep calls/texts. **No SMS provider** wired up in this build. |
| Admin surfacing | **New dedicated endpoint** `GET /admin/quote-requests` (not folded into the existing `approval_submissions` queue). |
| Page hosting | **Server-rendered backend HTML**, matching the existing email-verification landing pages. No React/SPA. |

---

## 3. Architecture

### 3.1 Entry point & flow

```
Preview email  "request a quote" CTA
      │  (real link, replaces mailto:)
      ▼
GET /quote/{token}          → brand-styled confirm page (design summary + form)
      │  form submit (POST)
      ▼
POST /quote/{token}         → persist + tag admin + notify sales
      │
      ▼
QUOTE_SUCCESS_HTML          → "our representative will verify the quote and send
                              it to you soon"
```

The flow is entirely email → page. There is **no** chat-thread reflection of the
quote request in this build (out of scope).

### 3.2 Secure link token

Reuse the email-verification JWT pattern (`app/services/leads.py:send_verification`):

- HS256, signed with `ADMIN_SECRET` (the existing server signing secret).
- Payload: `{ "lead_id": <id>, "session_id": <id>, "purpose": "quote", "exp": <ttl> }`.
- TTL from a new setting `QUOTE_TOKEN_TTL_SECONDS`, default **2592000** (30 days).
  Longer than the 15-minute verify link because the design offer stays valid a
  while and the customer may click days later.
- Generated in `delivery.py` when the preview email is assembled; the email's
  `quote_url` becomes `{EMAIL_VERIFY_BASE_URL}/quote/{token}` (backend base, same
  base the verification links use).
- On decode: reject expired/invalid tokens and any token whose `purpose != "quote"`.

### 3.3 `GET /quote/{token}` — confirm page

1. Decode the token (invalid/expired → `QUOTE_ERROR_HTML`, HTTP 400).
2. Load the lead (`lead_id`); if missing → `QUOTE_ERROR_HTML`.
3. Load the session (`collected`, `product_ref`) and the **latest `complete`
   generation** for the session.
4. Sign the watermarked preview image (`generate_signed_url`); fall back to the
   clean image, then to no image (render summary only) — never crash.
5. Render `QUOTE_CONFIRM_HTML`:
   - Watermarked preview image.
   - Read-only summary: product name, decoration type, placement zone/position.
   - Editable **quantity** input, prefilled from `collected.quantity`.
   - Optional **note** textarea.
   - Optional **phone** input + a "📱 Text me when my quote's ready" checkbox
     (plain HTML, no JS).
   - Submit button (POSTs the form to the same `/quote/{token}` URL).

All interpolated values HTML-escaped (same discipline as the email templates).

### 3.4 `POST /quote/{token}` — submit

Accepts `application/x-www-form-urlencoded` fields via FastAPI `Form(...)`:
`quantity`, `note`, `phone`, `notify_by_phone`.

1. Decode + validate the token exactly as GET (bad token → error page).
2. Load lead + session. **Capture the lead's current `quote_confirmed` value now**
   (before the update in step 4) — this pre-update value is the idempotency guard
   used in step 5.
3. Update `design_sessions.collected.quantity` (single source of truth for
   design details) with the submitted quantity, if a valid integer was provided.
4. Update the lead row:
   - `phone` (only overwrite if a value was submitted),
   - `notify_by_phone` (bool from checkbox),
   - `quote_note` (nullable),
   - `quote_confirmed = true`,
   - `quote_confirmed_at = now()`.
5. If the lead was **not already** `quote_confirmed` (the pre-update value from
   step 2), send the
   "hot lead — customer confirmed" sales email
   (`send_quote_confirmation_to_sales`) to the store's
   `sales_notification_email` (falling back to the env default). Re-submits update
   the stored details silently but do not re-email.
6. Render `QUOTE_SUCCESS_HTML`.

Email send is best-effort (never raises — same policy as all other sends). The
DB writes (tag + details) are the reliable part.

PII safety: phone / note / name / email are **never** logged. Log lines carry
`session_id` / `lead_id` only.

### 3.5 Admin center tagging — `GET /admin/quote-requests`

- Gated by `X-Admin-Secret` (`Depends(require_admin)`), like the other admin
  routes.
- Returns leads where `quote_confirmed = true`, newest first (by
  `quote_confirmed_at`), each enriched with a compact design/session summary
  (product, decoration, placement, quantity, preview image path, share token).
- This is the "tag in the backend admin center that the user has requested a
  quote and likes the design."

---

## 4. Data model changes

Migration `backend/supabase/migrations/20260702000001_quote_requests.sql`:

```sql
alter table leads add column if not exists notify_by_phone   bool not null default false;
alter table leads add column if not exists quote_note         text;
alter table leads add column if not exists quote_confirmed    bool not null default false;
alter table leads add column if not exists quote_confirmed_at timestamptz;
```

`phone` already exists on `leads`. No new tables. The confirmed quantity lives in
`design_sessions.collected.quantity` (existing), not duplicated on the lead.

---

## 5. Files touched

| File | Change |
|------|--------|
| `backend/supabase/migrations/20260702000001_quote_requests.sql` | New — the 4 lead columns above. |
| `backend/app/config.py` | Add `quote_token_ttl_seconds` (default 2592000). |
| `backend/app/prompts.py` | Add `QUOTE_CONFIRM_HTML`, `QUOTE_SUCCESS_HTML`, `QUOTE_ERROR_HTML`, `SALES_QUOTE_CONFIRMED_EMAIL_SUBJECT`, `SALES_QUOTE_CONFIRMED_EMAIL_BODY`. |
| `backend/app/services/leads.py` | Add `make_quote_token(lead)` / `decode_quote_token(token)` helpers (mirroring the verification token helpers). |
| `backend/app/services/email.py` | Add `send_quote_confirmation_to_sales(customer, product, collected, note, notify_by_phone, image_url, recipient)`. |
| `backend/app/services/delivery.py` | Build a real `quote_url` from a quote token instead of the `mailto:` placeholder. |
| `backend/app/api/routes/quote.py` | New router: `GET /quote/{token}`, `POST /quote/{token}`. |
| `backend/app/api/routes/admin_leads.py` | New router: `GET /admin/quote-requests`. |
| `backend/app/main.py` | Register the two new routers. |
| Tests (see §6) | New backend tests. |

---

## 6. Testing (TDD — write failing tests first)

Backend (`pytest`):

- **Quote token:** round-trip encode/decode; expired token rejected; wrong
  `purpose` rejected; tampered token rejected.
- **`GET /quote/{token}`:** valid token renders the confirm page containing the
  product/decoration/placement summary and the prefilled quantity; invalid/expired
  token renders the error page (HTTP 400); missing lead renders the error page.
- **`POST /quote/{token}`:** updates `collected.quantity`; sets lead
  `phone` / `notify_by_phone` / `quote_note` / `quote_confirmed` /
  `quote_confirmed_at`; sends the confirmation sales email once; re-submit does
  not re-email but does update details; renders the success page.
- **`GET /admin/quote-requests`:** requires `X-Admin-Secret` (401/403 without);
  returns only `quote_confirmed = true` leads, newest first, with the design
  summary shape.
- **PII:** assert phone / note / name / email never appear in captured log
  output for the POST path.

No frontend tests — the pages are server-rendered HTML with no React.

---

## 7. Security & constraints checklist

- Secrets via env only; token signed with existing `ADMIN_SECRET`. ✔
- No PII in logs (phone/note/name/email). ✔
- Signed URLs for the preview image (bucket stays private). ✔
- Admin route gated by `X-Admin-Secret`. ✔
- Unguessable, expiring, purpose-scoped token gates the customer page. ✔
- Best-effort email sends never break the request. ✔
- No live-storefront / InkyBay impact. ✔

---

## 8. Out of scope (YAGNI)

- Automated SMS (no provider wired up; rep follows up manually).
- Chat-thread reflection of the quote request.
- Editing decoration / placement on the quote page.
- A visual admin dashboard (admin remains API-only).
