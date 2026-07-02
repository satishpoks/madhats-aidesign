# Request-a-Quote Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the preview email's "request a quote" button into a real server-rendered page where the customer confirms their design (editable quantity + optional note), optionally leaves a phone number for follow-up, and — on submit — is tagged in the admin center as a confirmed quote lead while the sales team gets a "customer confirmed" notification.

**Architecture:** A backend-only flow mirroring the existing email-verification landing pages. A signed JWT token (same pattern as verification) gates a public `GET /quote/{token}` confirm page and its `POST /quote/{token}` submit handler. Submit persists to the existing `leads` + `design_sessions` tables (new lead columns), fires a one-time enriched sales email, and the lead surfaces through a new admin-gated `GET /admin/quote-requests` endpoint. The existing auto-notify-at-delivery behaviour is left untouched.

**Tech Stack:** Python 3.12 / FastAPI, supabase-py (service-role), PyJWT (HS256), Resend (email), `string.Template` for HTML pages, pytest + FastAPI `TestClient`.

## Global Constraints

- No secrets in code — all config via `app.config.settings` (pydantic-settings reading env vars). Quote token signed with the existing `ADMIN_SECRET`.
- No PII in logs or Sentry — customer name/email/phone/note must NEVER appear in log lines. Log `session_id` / `lead_id` only. (Returning PII in the admin API *response* is fine — that endpoint is admin-gated.)
- All stored images served via signed URLs (`app.storage.generate_signed_url`); the bucket is never public.
- `/admin/*` routes gated by `X-Admin-Secret` via `Depends(require_admin)`.
- Email sends are best-effort: a provider error must never raise out of a request handler.
- No SQLAlchemy/Alembic — schema changes are SQL migration files in `backend/supabase/migrations/`.
- Follow existing code style: `from __future__ import annotations`, `structlog.get_logger()`, HTML templates live in `app.prompts`, all interpolated HTML values HTML-escaped.
- Run all backend commands from `backend/` with the venv active. Test command: `pytest -q`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `backend/supabase/migrations/20260702000001_quote_requests.sql` | **New.** Adds `notify_by_phone`, `quote_note`, `quote_confirmed`, `quote_confirmed_at` to `leads`. |
| `backend/app/config.py` | **Modify.** Add `quote_token_ttl_seconds` (default 2592000). |
| `.env.example` | **Modify.** Document `QUOTE_TOKEN_TTL_SECONDS`. |
| `backend/app/services/leads.py` | **Modify.** Add `QuoteTokenError`, `make_quote_token(lead)`, `decode_quote_token(token)`. |
| `backend/app/prompts.py` | **Modify.** Add `QUOTE_CONFIRM_HTML`, `QUOTE_IMAGE_BLOCK`, `QUOTE_SUCCESS_HTML`, `QUOTE_ERROR_HTML`, `SALES_QUOTE_CONFIRMED_EMAIL_SUBJECT`, `SALES_QUOTE_CONFIRMED_EMAIL_BODY`. |
| `backend/app/services/email.py` | **Modify.** Add `send_quote_confirmation_to_sales(...)`. |
| `backend/app/services/delivery.py` | **Modify.** Replace the `mailto:` `quote_url` with a real `/quote/{token}` link. |
| `backend/app/api/routes/quote.py` | **New.** `GET /quote/{token}` (confirm page) + `POST /quote/{token}` (submit). |
| `backend/app/api/routes/admin_leads.py` | **New.** `GET /admin/quote-requests`. |
| `backend/app/main.py` | **Modify.** Register the two new routers. |
| `backend/tests/test_config.py` | **New.** Config default assertion. |
| `backend/tests/test_quote_token.py` | **New.** Token helper unit tests. |
| `backend/tests/test_email.py` | **Modify.** Add sales-confirmation email test. |
| `backend/tests/test_quote_routes.py` | **New.** GET/POST route tests. |
| `backend/tests/test_admin_leads.py` | **New.** Admin listing tests. |
| `backend/tests/test_delivery.py` | **Modify.** Assert the preview email's `quote_url` is a real quote link. |

---

## Task 1: Migration + config setting

**Files:**
- Create: `backend/supabase/migrations/20260702000001_quote_requests.sql`
- Modify: `backend/app/config.py:52` (after `verification_token_ttl_seconds`)
- Modify: `.env.example`
- Test: `backend/tests/test_config.py`

**Interfaces:**
- Produces: `settings.quote_token_ttl_seconds: int` (default `2592000`); four new `leads` columns: `notify_by_phone bool`, `quote_note text`, `quote_confirmed bool`, `quote_confirmed_at timestamptz`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config.py`:

```python
"""The quote link TTL is configurable via env, defaulting to 30 days."""
from __future__ import annotations


def test_quote_token_ttl_default():
    from app.config import settings

    # 30 days in seconds. Longer than the 15-min verify link because a quote
    # offer stays valid a while and the customer may click days later.
    assert settings.quote_token_ttl_seconds == 2592000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'quote_token_ttl_seconds'`.

- [ ] **Step 3: Add the config setting**

In `backend/app/config.py`, in the `--- Security ---` group, add the new line directly after `verification_token_ttl_seconds`:

```python
    verification_token_ttl_seconds: int = 900  # 15 min
    quote_token_ttl_seconds: int = 2592000  # 30 days — quote link stays valid a while
```

- [ ] **Step 4: Create the migration**

Create `backend/supabase/migrations/20260702000001_quote_requests.sql`:

```sql
-- Request-a-Quote flow: an explicit, customer-initiated quote request.
-- Distinct from quote_request_sent (auto-notify at preview delivery). These
-- columns record that the customer opened the emailed quote link, confirmed
-- their design, and asked us to prepare a quote — the "hot lead" signal.
alter table leads add column if not exists notify_by_phone   bool not null default false;
alter table leads add column if not exists quote_note         text;
alter table leads add column if not exists quote_confirmed    bool not null default false;
alter table leads add column if not exists quote_confirmed_at timestamptz;
```

- [ ] **Step 5: Document the env var**

In `.env.example`, near the other TTL / security vars (e.g. after the line documenting `VERIFICATION_TOKEN_TTL_SECONDS`, or in the security group if that var isn't listed), add:

```bash
# Quote link TTL in seconds (how long the emailed "request a quote" link stays valid). Default 30 days.
QUOTE_TOKEN_TTL_SECONDS=2592000
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py .env.example backend/supabase/migrations/20260702000001_quote_requests.sql backend/tests/test_config.py
git commit -m "feat(quote): add quote-request schema columns + token TTL setting"
```

---

## Task 2: Quote token helpers

**Files:**
- Modify: `backend/app/services/leads.py`
- Test: `backend/tests/test_quote_token.py`

**Interfaces:**
- Consumes: `settings.quote_token_ttl_seconds`, `settings.admin_secret` (Task 1); existing `jwt`, `datetime` imports in `leads.py`.
- Produces:
  - `class QuoteTokenError(Exception)` — raised for invalid/expired/wrong-purpose tokens.
  - `make_quote_token(lead: dict) -> str` — expects `lead["id"]` and `lead["session_id"]`.
  - `decode_quote_token(token: str) -> dict` — returns the payload `{"lead_id", "session_id", "purpose", "exp"}` or raises `QuoteTokenError`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_quote_token.py`:

```python
"""Quote link token — signed with ADMIN_SECRET, purpose-scoped, expiring."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from app.services import leads as leads_service


def test_round_trip():
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})
    payload = leads_service.decode_quote_token(token)
    assert payload["lead_id"] == "lead-1"
    assert payload["session_id"] == "sess-1"
    assert payload["purpose"] == "quote"


def test_expired_token_rejected():
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    token = jwt.encode(
        {"lead_id": "lead-1", "session_id": "sess-1", "purpose": "quote", "exp": past},
        settings.admin_secret,
        algorithm="HS256",
    )
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token(token)


def test_wrong_purpose_rejected():
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    token = jwt.encode(
        {"lead_id": "lead-1", "session_id": "sess-1", "purpose": "verify", "exp": future},
        settings.admin_secret,
        algorithm="HS256",
    )
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token(token)


def test_tampered_token_rejected():
    with pytest.raises(leads_service.QuoteTokenError):
        leads_service.decode_quote_token("not-a-real-jwt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_quote_token.py -v`
Expected: FAIL — `AttributeError: module 'app.services.leads' has no attribute 'make_quote_token'`.

- [ ] **Step 3: Implement the helpers**

In `backend/app/services/leads.py`, add at the end of the file (the module already imports `jwt`, `structlog`, `datetime, timedelta, timezone`, and `settings`):

```python
class QuoteTokenError(Exception):
    """Raised when a quote link token is invalid, expired, or not a quote token."""


def make_quote_token(lead: dict) -> str:
    """Sign a purpose-scoped quote link token for the emailed 'request a quote' CTA.

    Mirrors send_verification's signing (HS256 with the server secret) but with
    a longer TTL — the quote offer stays valid for days, not 15 minutes.
    """
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.quote_token_ttl_seconds)
    return jwt.encode(
        {
            "lead_id": lead["id"],
            "session_id": lead["session_id"],
            "purpose": "quote",
            "exp": expires,
        },
        settings.admin_secret,
        algorithm="HS256",
    )


def decode_quote_token(token: str) -> dict:
    """Decode + validate a quote link token. Raises QuoteTokenError on any problem."""
    try:
        payload = jwt.decode(token, settings.admin_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise QuoteTokenError("expired") from exc
    except jwt.InvalidTokenError as exc:
        raise QuoteTokenError("invalid") from exc
    if payload.get("purpose") != "quote":
        raise QuoteTokenError("wrong purpose")
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_quote_token.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/leads.py backend/tests/test_quote_token.py
git commit -m "feat(quote): signed quote-link token helpers"
```

---

## Task 3: Sales "customer confirmed" email

**Files:**
- Modify: `backend/app/prompts.py`
- Modify: `backend/app/services/email.py`
- Test: `backend/tests/test_email.py`

**Interfaces:**
- Consumes: existing `email_service._send(to, subject, body) -> bool`, `prompts`, `settings`.
- Produces: `send_quote_confirmation_to_sales(customer: dict, product: dict, collected: dict, note: str = "", notify_by_phone: bool = False, image_url: str = "", recipient: str | None = None) -> bool`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_email.py` (the `_capture_send` helper already exists in that file):

```python
def test_quote_confirmation_to_sales_includes_confirmed_details(monkeypatch):
    """The 'customer confirmed' sales email must carry the confirmed quantity,
    phone, phone-notify consent, and any customer note so the rep can follow up."""
    captured = _capture_send(monkeypatch)

    ok = email_service.send_quote_confirmation_to_sales(
        customer={"name": "Ann", "email": "ann@example.com", "phone": "0400000000"},
        product={"name": "Snapback", "style": "6-panel", "colour": "black"},
        collected={
            "quantity": 50,
            "decoration_type": "embroidery",
            "placement_zone": "front_panel",
            "placement_position": "centre",
        },
        note="Need them before the expo",
        notify_by_phone=True,
        image_url="https://cdn/clean.png",
        recipient="sales@store.example",
    )

    assert ok is True
    params = captured["params"]
    assert params["to"] == ["sales@store.example"]
    assert "50" in params["subject"]
    body = params["html"]
    assert "0400000000" in body
    assert "Need them before the expo" in body
    # phone-notify consent surfaced for the rep
    assert "yes" in body.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_email.py::test_quote_confirmation_to_sales_includes_confirmed_details -v`
Expected: FAIL — `AttributeError: module 'app.services.email' has no attribute 'send_quote_confirmation_to_sales'`.

- [ ] **Step 3: Add the email templates**

In `backend/app/prompts.py`, after `SALES_QUOTE_EMAIL_BODY` (ends ~line 389), add:

```python
# Sent to store ops when a customer explicitly confirms their design and requests
# a quote via the emailed quote link (distinct from the auto delivery-time
# heads-up in SALES_QUOTE_EMAIL_BODY). This is the "hot lead" — they've seen the
# design, confirmed the details, and asked us to quote.
SALES_QUOTE_CONFIRMED_EMAIL_SUBJECT = (
    "Customer confirmed — quote requested: {product_name} x{quantity}"
)

SALES_QUOTE_CONFIRMED_EMAIL_BODY = """The customer confirmed their design and requested a quote from the AI Design Studio.

Customer: {customer_name}
Email: {customer_email}
Phone: {customer_phone}
Wants phone/text follow-up: {notify_by_phone}

Product: {product_name} ({product_style}, {product_colour})
Quantity (confirmed): {quantity}
Decoration: {decoration_type}
Placement: {placement_zone} / {placement_position}

Customer note: {note}

Design image (internal, clean): {image_url}

Please verify the quote and send it directly to the customer.
"""
```

- [ ] **Step 4: Add the email function**

In `backend/app/services/email.py`, after `send_quote_to_sales` (ends ~line 146), add:

```python
def send_quote_confirmation_to_sales(
    customer: dict,
    product: dict,
    collected: dict,
    note: str = "",
    notify_by_phone: bool = False,
    image_url: str = "",
    recipient: str | None = None,
) -> bool:
    """Notify sales that a customer explicitly confirmed their design + requested a quote."""
    to = recipient or settings.sales_notification_email
    subject = prompts.SALES_QUOTE_CONFIRMED_EMAIL_SUBJECT.format(
        product_name=product.get("name", "Custom cap"),
        quantity=collected.get("quantity", "?"),
    )
    body = prompts.SALES_QUOTE_CONFIRMED_EMAIL_BODY.format(
        customer_name=customer.get("name", ""),
        customer_email=customer.get("email", ""),
        customer_phone=customer.get("phone", "") or "—",
        notify_by_phone="yes" if notify_by_phone else "no",
        product_name=product.get("name", ""),
        product_style=product.get("style", ""),
        product_colour=product.get("colour", ""),
        quantity=collected.get("quantity", "?"),
        decoration_type=collected.get("decoration_type", "?"),
        placement_zone=collected.get("placement_zone", "?"),
        placement_position=collected.get("placement_position", "?"),
        note=note or "—",
        image_url=image_url,
    )
    return _send(to, subject, body)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_email.py::test_quote_confirmation_to_sales_includes_confirmed_details -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/prompts.py backend/app/services/email.py backend/tests/test_email.py
git commit -m "feat(quote): 'customer confirmed' sales notification email"
```

---

## Task 4: Quote landing-page templates + real email link

**Files:**
- Modify: `backend/app/prompts.py`
- Modify: `backend/app/services/delivery.py`
- Test: `backend/tests/test_delivery.py`

**Interfaces:**
- Consumes: `leads_service.make_quote_token`, `leads_service.decode_quote_token` (Task 2); `settings.email_verify_base_url`.
- Produces: `prompts.QUOTE_CONFIRM_HTML` (`string.Template`; placeholders `$action_url $image_block $product $decoration $placement $quantity`), `prompts.QUOTE_IMAGE_BLOCK` (`string.Template`; `$image_url`), `prompts.QUOTE_SUCCESS_HTML` (static), `prompts.QUOTE_ERROR_HTML` (`.format(message=...)`). Delivery now emits `quote_url = f"{settings.email_verify_base_url}/quote/{token}"`.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_delivery.py`:

```python
def test_preview_email_quote_url_is_quote_page(monkeypatch):
    """The preview email's 'request a quote' CTA must link to the real quote
    page (/quote/<token>), not a mailto: placeholder, and the token must decode
    back to this lead."""
    from app.services import leads as leads_service

    lead = _lead_row()
    tables = {
        "leads": [lead],
        "generations": [_generation_row()],
        "design_sessions": [_session_row()],
    }
    fake = _FakeSB(tables)
    sent: dict = {}
    _patch_common(monkeypatch, fake, sent)

    result = delivery.maybe_send_preview("sess-1")

    assert result is True
    _args, kwargs = sent["preview"][0]
    quote_url = kwargs["quote_url"]
    assert "/quote/" in quote_url
    assert "mailto:" not in quote_url
    token = quote_url.rsplit("/quote/", 1)[1]
    payload = leads_service.decode_quote_token(token)
    assert payload["lead_id"] == "lead-1"
    assert payload["session_id"] == "sess-1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delivery.py::test_preview_email_quote_url_is_quote_page -v`
Expected: FAIL — `assert '/quote/' in 'mailto:studio@madhats.com.au?subject=Quote%20request'`.

- [ ] **Step 3: Add the HTML templates**

In `backend/app/prompts.py`, at the end of the file, add:

```python
# ---------------------------------------------------------------------------
# Request-a-Quote pages (server-rendered, opened from the preview email's CTA).
# QUOTE_CONFIRM_HTML uses string.Template ($placeholders); the route HTML-escapes
# every interpolated value. QUOTE_IMAGE_BLOCK is substituted separately (or left
# empty when there's no image) and injected as $image_block.
# ---------------------------------------------------------------------------

QUOTE_IMAGE_BLOCK = """\
        <tr><td style="padding:20px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fcf7f2;border:2px solid #ff5c00;border-radius:12px;">
            <tr><td align="center" style="padding:14px;">
              <img src="$image_url" alt="Your MadHats design preview" width="100%" style="display:block;width:100%;max-width:504px;border-radius:8px;" />
              <div style="margin-top:8px;font-size:10px;color:#9e9eab;">Watermarked preview</div>
            </td></tr>
          </table>
        </td></tr>
"""

QUOTE_CONFIRM_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Request your quote — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:16px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:28px 32px 0 32px;">
          <h1 style="font-size:22px;color:#1a1a2e;margin:0;">Request your quote</h1>
          <p style="font-size:13px;line-height:20px;color:#6b6b80;margin:10px 0 0 0;">Confirm your design details below and our team will put a quote together for you.</p>
        </td></tr>
$image_block
        <tr><td style="padding:20px 32px 0 32px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:14px;color:#1a1a2e;">
            <tr><td style="padding:6px 0;color:#6b6b80;">Product</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$product</td></tr>
            <tr><td style="padding:6px 0;color:#6b6b80;">Decoration</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$decoration</td></tr>
            <tr><td style="padding:6px 0;color:#6b6b80;">Placement</td><td style="padding:6px 0;text-align:right;font-weight:bold;">$placement</td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:16px 32px 28px 32px;">
          <form method="post" action="$action_url">
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:14px 0 4px 0;">How many hats?</label>
            <input type="number" name="quantity" value="$quantity" min="1" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;" />
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:16px 0 4px 0;">Anything else we should know? (optional)</label>
            <textarea name="note" rows="3" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;"></textarea>
            <label style="display:block;font-size:13px;color:#1a1a2e;font-weight:bold;margin:16px 0 4px 0;">Phone number (optional)</label>
            <input type="tel" name="phone" placeholder="So a rep can reach you" style="width:100%;box-sizing:border-box;padding:12px;border:1px solid #e0e1ea;border-radius:8px;font-size:15px;" />
            <label style="display:flex;align-items:center;font-size:13px;color:#6b6b80;margin:12px 0 0 0;">
              <input type="checkbox" name="notify_by_phone" value="yes" style="margin-right:8px;" /> Text or call me when my quote's ready
            </label>
            <button type="submit" style="display:block;width:100%;margin-top:22px;background:#ff5c00;color:#ffffff;border:none;text-align:center;font-weight:bold;font-size:15px;padding:16px;border-radius:10px;cursor:pointer;box-shadow:0 4px 12px rgba(255,92,0,0.35);">Confirm &amp; request my quote</button>
          </form>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

QUOTE_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quote requested — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9989;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">Quote request received</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">Thanks for confirming your design! One of our MadHats consultants will verify your quote and send it through to you soon.</p>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:12px 0 0 0;">If you left a phone number, we may text or call you when it's ready. You can close this page.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

QUOTE_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Quote link problem — MadHats</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:#ff5c00;padding:18px 28px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">MAD HATS</div>
          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9888;&#65039;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">We couldn't open that quote link</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">{message}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
```

- [ ] **Step 4: Wire the real quote link in delivery**

In `backend/app/services/delivery.py`, add the leads-service import near the other `from app.services import ...` imports at the top:

```python
from app.services import leads as leads_service
```

Then in `maybe_send_preview`, replace the CTA-link block (currently ~lines 148-149 and the `quote_url=` kwarg ~line 159). Change:

```python
    edit_url = f"{settings.studio_base_url}/?session={session.get('share_token', '')}"
    mailto = f"mailto:{settings.resend_from_address}"
```

to:

```python
    edit_url = f"{settings.studio_base_url}/?session={session.get('share_token', '')}"
    mailto = f"mailto:{settings.resend_from_address}"
    quote_token = leads_service.make_quote_token(lead)
    quote_url = f"{settings.email_verify_base_url}/quote/{quote_token}"
```

and change the `send_preview_email(...)` call's quote kwarg from:

```python
        quote_url=f"{mailto}?subject=Quote%20request",
```

to:

```python
        quote_url=quote_url,
```

(`mailto` stays — `talk_url=mailto` still uses it.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_delivery.py -v`
Expected: PASS (all existing delivery tests + the new one).

- [ ] **Step 6: Commit**

```bash
git add backend/app/prompts.py backend/app/services/delivery.py backend/tests/test_delivery.py
git commit -m "feat(quote): quote landing-page templates + real email CTA link"
```

---

## Task 5: GET /quote/{token} — confirm page

**Files:**
- Create: `backend/app/api/routes/quote.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_quote_routes.py`

**Interfaces:**
- Consumes: `leads_service.decode_quote_token` / `QuoteTokenError` (Task 2); `prompts.QUOTE_CONFIRM_HTML` / `QUOTE_IMAGE_BLOCK` / `QUOTE_ERROR_HTML` (Task 4); `get_product`, `generate_signed_url`.
- Produces (used by Task 6, same file): module-level helpers `_load_context(token) -> tuple[dict, dict]` (returns `(lead, session)`, raises `QuoteTokenError`), `_latest_complete_gen(sb, session_id) -> dict | None`, `_sign(path) -> str`; and `router` with `GET /quote/{token}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_quote_routes.py`:

```python
"""GET/POST /quote/{token} — the customer-facing Request-a-Quote page."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services import leads as leads_service


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    """Chainable supabase-py stand-in. Deferred update/insert mutate the shared
    row dicts on execute() so a second request in the same test sees the change."""

    def __init__(self, table, rows, sink):
        self._table = table
        self._rows = rows
        self._sink = sink
        self._pending_update = None

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if self._pending_update is not None:
            self._sink.setdefault(self._table, []).append(self._pending_update)
            for row in self._rows:
                row.update(self._pending_update)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables
        self.sink: dict = {}

    def table(self, name):
        return _Query(name, list(self._tables.get(name, [])), self.sink)


def _tables(**overrides):
    lead = {"id": "lead-1", "session_id": "sess-1", "name": "Ann",
            "email": "ann@example.com", "phone": None, "quote_confirmed": False}
    session = {"id": "sess-1", "store_id": None, "share_token": "share-tok",
               "product_ref": {"product_id": "prod-1"},
               "collected": {"decoration_type": "embroidery",
                             "placement_zone": "front_panel",
                             "placement_position": "centre", "quantity": 24}}
    gen = {"id": "gen-1", "session_id": "sess-1", "status": "complete",
           "watermarked_url": "generations/wm.png", "image_url": "generations/clean.png",
           "created_at": "2026-07-02T00:00:00Z"}
    lead.update(overrides.get("lead", {}))
    return {"leads": [lead], "design_sessions": [session], "generations": [gen]}, lead, session


@pytest.fixture()
def client(monkeypatch):
    from app.api.routes import quote
    from app.main import app

    fake_holder = {}

    def _install(tables):
        fake = _FakeSB(tables)
        fake_holder["fake"] = fake
        monkeypatch.setattr(quote, "get_supabase", lambda: fake)
        monkeypatch.setattr(quote, "get_product", lambda *a, **k: {"name": "Snapback", "style": "6-panel", "colour": "black"})
        monkeypatch.setattr(quote, "generate_signed_url", lambda p: f"signed:{p}")
        return fake

    with TestClient(app, raise_server_exceptions=True) as c:
        c.install = _install  # type: ignore[attr-defined]
        c.holder = fake_holder  # type: ignore[attr-defined]
        yield c


def test_get_renders_confirm_page(client):
    tables, _lead, _session = _tables()
    client.install(tables)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.get(f"/quote/{token}")

    assert resp.status_code == 200
    body = resp.text
    assert "Snapback" in body
    assert "embroidery" in body
    assert 'name="quantity"' in body
    assert 'value="24"' in body
    assert 'name="notify_by_phone"' in body


def test_get_bad_token_renders_error(client):
    tables, _lead, _session = _tables()
    client.install(tables)

    resp = client.get("/quote/not-a-real-jwt")

    assert resp.status_code == 400
    assert "couldn't open that quote link" in resp.text.lower()


def test_get_missing_lead_renders_error(client):
    tables, _lead, _session = _tables()
    tables["leads"] = []  # token is valid but the lead is gone
    client.install(tables)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.get(f"/quote/{token}")

    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_quote_routes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.routes.quote'` (collection error).

- [ ] **Step 3: Create the route module (GET + shared helpers)**

Create `backend/app/api/routes/quote.py`:

```python
"""Customer-facing Request-a-Quote page (server-rendered, no SPA).

Opened from the preview email's 'request a quote' CTA. A purpose-scoped signed
token (app.services.leads.make_quote_token) gates the page; GET shows a confirm
form (editable quantity + optional note/phone), POST records the request, tags
the lead as a confirmed quote lead, and notifies sales once.

PII safety: name/email/phone/note are never logged — session_id/lead_id only.
"""
from __future__ import annotations

import html as html_lib
from string import Template

import structlog
from fastapi import APIRouter, Form
from fastapi.responses import HTMLResponse

from app import prompts
from app.db import get_supabase
from app.services import email as email_service
from app.services import leads as leads_service
from app.services.products import get_product
from app.storage import generate_signed_url

router = APIRouter(tags=["quote"])
log = structlog.get_logger()

_BAD_LINK_MESSAGE = (
    "This quote link is invalid or has expired. Head back to the chat and we'll help you out."
)


def _error_page() -> HTMLResponse:
    return HTMLResponse(
        prompts.QUOTE_ERROR_HTML.format(message=_BAD_LINK_MESSAGE), status_code=400
    )


def _load_context(token: str) -> tuple[dict, dict]:
    """Decode the token and load (lead, session). Raises QuoteTokenError if the
    token is bad OR the lead no longer exists (both are 'bad link' outcomes)."""
    payload = leads_service.decode_quote_token(token)  # raises QuoteTokenError
    sb = get_supabase()
    lead_res = sb.table("leads").select("*").eq("id", payload["lead_id"]).limit(1).execute()
    if not lead_res.data:
        raise leads_service.QuoteTokenError("lead not found")
    lead = lead_res.data[0]
    sess_res = (
        sb.table("design_sessions").select("*").eq("id", lead["session_id"]).limit(1).execute()
    )
    session = sess_res.data[0] if sess_res.data else {}
    return lead, session


def _latest_complete_gen(sb, session_id: str) -> dict | None:
    res = (
        sb.table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _sign(path: str | None) -> str:
    """Sign a storage path; pass external URLs through; empty -> ''."""
    if not path:
        return ""
    return path if path.startswith("http") else generate_signed_url(path)


def _render_confirm_page(token: str, product: dict, collected: dict, image_url: str) -> str:
    esc = lambda v: html_lib.escape(str(v), quote=True)  # noqa: E731
    image_block = (
        Template(prompts.QUOTE_IMAGE_BLOCK).substitute(image_url=esc(image_url))
        if image_url
        else ""
    )
    placement = "{} / {}".format(
        collected.get("placement_zone") or "front panel",
        collected.get("placement_position") or "centre",
    ).replace("_", " ")
    return Template(prompts.QUOTE_CONFIRM_HTML).substitute(
        action_url=esc(f"/quote/{token}"),
        image_block=image_block,
        product=esc(product.get("name") or "your custom cap"),
        decoration=esc(collected.get("decoration_type") or "custom decoration"),
        placement=esc(placement),
        quantity=esc(collected.get("quantity") or 1),
    )


@router.get("/quote/{token}", response_class=HTMLResponse)
async def quote_page(token: str) -> HTMLResponse:
    try:
        lead, session = _load_context(token)
    except leads_service.QuoteTokenError:
        return _error_page()

    sb = get_supabase()
    collected = session.get("collected") or {}
    product_ref = session.get("product_ref") or {}
    product = get_product(product_ref.get("product_id", "")) or product_ref
    gen = _latest_complete_gen(sb, lead["session_id"])
    image_url = _sign((gen or {}).get("watermarked_url") or (gen or {}).get("image_url")) if gen else ""
    return HTMLResponse(_render_confirm_page(token, product, collected, image_url))
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add `quote` to the routes import (keep alphabetical-ish with the existing group):

```python
from app.api.routes import (
    admin_deliveries,
    admin_prompt,
    admin_stores,
    chat,
    generate,
    health,
    leads,
    products,
    quote,
    sessions,
    submissions,
    uploads,
)
```

and add `quote.router,` to the `for router in (...)` include tuple (e.g. after `leads.router,`):

```python
        leads.router,
        quote.router,
        submissions.router,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_quote_routes.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/quote.py backend/app/main.py backend/tests/test_quote_routes.py
git commit -m "feat(quote): GET /quote/{token} confirm page"
```

---

## Task 6: POST /quote/{token} — submit

**Files:**
- Modify: `backend/app/api/routes/quote.py`
- Test: `backend/tests/test_quote_routes.py`

**Interfaces:**
- Consumes: `_load_context`, `_latest_complete_gen`, `_sign`, `_error_page`, `router` (Task 5); `email_service.send_quote_confirmation_to_sales` (Task 3); `prompts.QUOTE_SUCCESS_HTML` (Task 4).
- Produces: `POST /quote/{token}` handler; module helpers `_parse_int(raw) -> int | None`, `_sales_recipient(session) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_quote_routes.py`:

```python
def _install_email_capture(client, monkeypatch):
    from app.api.routes import quote

    sent: list = []
    monkeypatch.setattr(
        quote.email_service,
        "send_quote_confirmation_to_sales",
        lambda *a, **k: sent.append((a, k)) or True,
    )
    return sent


def test_post_records_quote_and_notifies_sales(client, monkeypatch):
    tables, lead, session = _tables()
    client.install(tables)
    sent = _install_email_capture(client, monkeypatch)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.post(
        f"/quote/{token}",
        data={"quantity": "60", "note": "Need by expo", "phone": "0400000000",
              "notify_by_phone": "yes"},
    )

    assert resp.status_code == 200
    assert "Quote request received" in resp.text
    # design_sessions.collected.quantity updated (source of truth)
    assert session["collected"]["quantity"] == 60
    # lead tagged + details persisted
    assert lead["quote_confirmed"] is True
    assert lead["quote_confirmed_at"]
    assert lead["notify_by_phone"] is True
    assert lead["quote_note"] == "Need by expo"
    assert lead["phone"] == "0400000000"
    # sales notified exactly once
    assert len(sent) == 1


def test_post_resubmit_updates_but_does_not_reemail(client, monkeypatch):
    tables, lead, _session = _tables(lead={"quote_confirmed": True})
    client.install(tables)
    sent = _install_email_capture(client, monkeypatch)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    resp = client.post(f"/quote/{token}", data={"quantity": "12", "notify_by_phone": ""})

    assert resp.status_code == 200
    assert lead["notify_by_phone"] is False
    assert len(sent) == 0  # already confirmed → no second email


def test_post_bad_token_renders_error(client, monkeypatch):
    tables, _lead, _session = _tables()
    client.install(tables)
    _install_email_capture(client, monkeypatch)

    resp = client.post("/quote/not-a-real-jwt", data={"quantity": "10"})

    assert resp.status_code == 400


def test_post_does_not_log_pii(client, monkeypatch, caplog):
    import logging

    tables, _lead, _session = _tables()
    client.install(tables)
    _install_email_capture(client, monkeypatch)
    token = leads_service.make_quote_token({"id": "lead-1", "session_id": "sess-1"})

    with caplog.at_level(logging.INFO):
        client.post(
            f"/quote/{token}",
            data={"quantity": "5", "note": "secret note", "phone": "0400111222"},
        )

    logged = caplog.text
    assert "0400111222" not in logged
    assert "secret note" not in logged
    assert "ann@example.com" not in logged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_quote_routes.py -k post -v`
Expected: FAIL — `405 Method Not Allowed` (no POST handler yet).

- [ ] **Step 3: Implement the POST handler**

In `backend/app/api/routes/quote.py`, add the `datetime` import at the top (with the stdlib imports):

```python
from datetime import datetime, timezone
```

Then append to the module:

```python
def _parse_int(raw: str) -> int | None:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _sales_recipient(session: dict) -> str | None:
    store_id = session.get("store_id")
    if not store_id:
        return None
    from app.services.stores import get_store

    store = get_store(store_id)
    return (store or {}).get("sales_notification_email")


@router.post("/quote/{token}", response_class=HTMLResponse)
async def submit_quote(
    token: str,
    quantity: str = Form(default=""),
    note: str = Form(default=""),
    phone: str = Form(default=""),
    notify_by_phone: str = Form(default=""),
) -> HTMLResponse:
    try:
        lead, session = _load_context(token)
    except leads_service.QuoteTokenError:
        return _error_page()

    sb = get_supabase()
    # Pre-update value — the idempotency guard for the one-time sales email.
    already_confirmed = bool(lead.get("quote_confirmed"))
    collected = session.get("collected") or {}

    qty = _parse_int(quantity)
    if qty is not None:
        collected["quantity"] = qty
        sb.table("design_sessions").update({"collected": collected}).eq(
            "id", lead["session_id"]
        ).execute()

    notify_flag = notify_by_phone.strip().lower() in ("yes", "on", "true", "1")
    note_clean = note.strip()
    phone_clean = phone.strip()
    lead_update: dict = {
        "notify_by_phone": notify_flag,
        "quote_note": note_clean or None,
        "quote_confirmed": True,
        "quote_confirmed_at": datetime.now(timezone.utc).isoformat(),
    }
    if phone_clean:
        lead_update["phone"] = phone_clean
    sb.table("leads").update(lead_update).eq("id", lead["id"]).execute()

    if not already_confirmed:
        product_ref = session.get("product_ref") or {}
        product = get_product(product_ref.get("product_id", "")) or product_ref
        gen = _latest_complete_gen(sb, lead["session_id"])
        image_url = _sign((gen or {}).get("image_url") or (gen or {}).get("watermarked_url")) if gen else ""
        customer = {
            "name": lead["name"],
            "email": lead["email"],
            "phone": phone_clean or lead.get("phone"),
        }
        email_service.send_quote_confirmation_to_sales(
            customer,
            product,
            collected,
            note=note_clean,
            notify_by_phone=notify_flag,
            image_url=image_url,
            recipient=_sales_recipient(session),
        )

    log.info("quote_confirmed", session_id=lead["session_id"], lead_id=lead["id"])  # no PII
    return HTMLResponse(prompts.QUOTE_SUCCESS_HTML)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_quote_routes.py -v`
Expected: PASS (all GET + POST tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/quote.py backend/tests/test_quote_routes.py
git commit -m "feat(quote): POST /quote/{token} submit — tag lead + notify sales"
```

---

## Task 7: GET /admin/quote-requests — admin center listing

**Files:**
- Create: `backend/app/api/routes/admin_leads.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_admin_leads.py`

**Interfaces:**
- Consumes: `require_admin` dependency, `get_supabase`.
- Produces: `GET /admin/quote-requests` → `list[dict]` of confirmed quote leads (each with `lead_id, session_id, name, email, phone, notify_by_phone, quote_note, quote_confirmed_at, product, decoration_type, placement_zone, quantity, share_token`), newest first.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_admin_leads.py`:

```python
"""GET /admin/quote-requests — confirmed quote leads for the admin center."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, field, value):
        self._rows = [r for r in self._rows if r.get(field) == value]
        return self

    def order(self, field, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(field) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Query(list(self._tables.get(name, [])))


def _tables():
    confirmed = {"id": "lead-1", "session_id": "sess-1", "name": "Ann",
                 "email": "ann@example.com", "phone": "0400000000",
                 "notify_by_phone": True, "quote_note": "asap",
                 "quote_confirmed": True, "quote_confirmed_at": "2026-07-02T10:00:00Z"}
    not_confirmed = {"id": "lead-2", "session_id": "sess-2", "name": "Ben",
                     "email": "ben@example.com", "quote_confirmed": False}
    session = {"id": "sess-1", "share_token": "share-tok",
               "product_ref": {"product_id": "prod-1", "name": "Snapback"},
               "collected": {"decoration_type": "embroidery",
                             "placement_zone": "front_panel", "quantity": 60}}
    return {"leads": [confirmed, not_confirmed], "design_sessions": [session]}


@pytest.fixture()
def admin_client(monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "admin_secret", "test-secret-123")
    app.dependency_overrides.clear()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


def _patch_sb(monkeypatch, tables):
    from app.api.routes import admin_leads

    monkeypatch.setattr(admin_leads, "get_supabase", lambda: _FakeSB(tables))


def test_rejects_missing_secret(admin_client):
    resp = admin_client.get("/admin/quote-requests")
    assert resp.status_code in (401, 403)


def test_returns_only_confirmed_with_summary(admin_client, monkeypatch):
    _patch_sb(monkeypatch, _tables())
    resp = admin_client.get(
        "/admin/quote-requests", headers={"X-Admin-Secret": "test-secret-123"}
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["lead_id"] == "lead-1"
    assert row["notify_by_phone"] is True
    assert row["quote_note"] == "asap"
    assert row["product"] == "Snapback"
    assert row["decoration_type"] == "embroidery"
    assert row["quantity"] == 60
    assert row["share_token"] == "share-tok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_admin_leads.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.routes.admin_leads'`.

- [ ] **Step 3: Create the admin route**

Create `backend/app/api/routes/admin_leads.py`:

```python
"""Admin center: confirmed quote requests.

Lists leads that explicitly requested a quote via the emailed quote link
(quote_confirmed = true) — the "customer likes the design and wants a quote"
signal — enriched with a compact design/session summary. Gated by X-Admin-Secret.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.db import get_supabase

router = APIRouter(tags=["admin-leads"], dependencies=[Depends(require_admin)])


@router.get("/admin/quote-requests")
async def list_quote_requests() -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("leads")
        .select("*")
        .eq("quote_confirmed", True)
        .order("quote_confirmed_at", desc=True)
        .execute()
    )
    rows = res.data or []

    out: list[dict] = []
    for lead in rows:
        sess = (
            sb.table("design_sessions")
            .select("*")
            .eq("id", lead["session_id"])
            .limit(1)
            .execute()
        )
        session = sess.data[0] if sess.data else {}
        collected = session.get("collected") or {}
        product_ref = session.get("product_ref") or {}
        out.append(
            {
                "lead_id": lead["id"],
                "session_id": lead["session_id"],
                "name": lead.get("name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "notify_by_phone": lead.get("notify_by_phone", False),
                "quote_note": lead.get("quote_note"),
                "quote_confirmed_at": lead.get("quote_confirmed_at"),
                "product": product_ref.get("name") or product_ref.get("product_id"),
                "decoration_type": collected.get("decoration_type"),
                "placement_zone": collected.get("placement_zone"),
                "quantity": collected.get("quantity"),
                "share_token": session.get("share_token"),
            }
        )
    return out
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, add `admin_leads` to the routes import block:

```python
from app.api.routes import (
    admin_deliveries,
    admin_leads,
    admin_prompt,
    admin_stores,
    ...
)
```

and add `admin_leads.router,` to the `for router in (...)` include tuple (e.g. after `admin_deliveries.router,`):

```python
        admin_deliveries.router,
        admin_leads.router,
        admin_prompt.router,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_admin_leads.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Full suite + commit**

Run the whole backend suite to confirm no regressions:

Run: `pytest -q`
Expected: PASS (all prior tests + the new ones).

```bash
git add backend/app/api/routes/admin_leads.py backend/app/main.py backend/tests/test_admin_leads.py
git commit -m "feat(quote): GET /admin/quote-requests admin listing"
```

---

## Task 8: Docs — update project memory

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update the implementation-state notes**

In `CLAUDE.md`, in the "Current implementation state" section (§13), add a bullet describing the new flow, and update the `Lead` data-model line in §5. Add under the delivery bullet:

```markdown
- **Request-a-Quote flow** (`api/routes/quote.py`, `services/leads.py` quote-token helpers, `api/routes/admin_leads.py`): the preview email's "request a quote" CTA links to a signed, server-rendered page (`GET /quote/{token}`) where the customer confirms their design (editable quantity + optional note) and optionally leaves a phone number + phone-notify consent. Submitting (`POST /quote/{token}`) updates `collected.quantity`, tags the lead (`quote_confirmed`, `quote_confirmed_at`, `notify_by_phone`, `quote_note`), and sends a one-time "customer confirmed" sales email. Confirmed leads surface via `GET /admin/quote-requests` (X-Admin-Secret). The auto-notify-at-delivery behaviour (`quote_request_sent`) is unchanged — this is a second, richer signal.
```

Update the test counts note if you wish (backend `pytest` count will have grown by ~14).

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note Request-a-Quote flow in project memory"
```

---

## Self-Review Notes

- **Spec coverage:** §2 entry point → Task 4 (link) + Task 5 (page). §2 token → Task 2. §3.3 confirm page fields → Task 5. §3.4 submit (quantity→collected, lead tag, one-time email, PII) → Task 6. §3.5 admin listing → Task 7. §4 migration → Task 1. §2 "keep auto-notify at delivery" → Task 4 leaves `send_quote_to_sales` / `quote_request_sent` untouched. §6 test list → Tasks 2–7.
- **Type consistency:** `make_quote_token`/`decode_quote_token`/`QuoteTokenError` names identical across Tasks 2, 4, 5, 6. `_load_context` returns `(lead, session)` (Task 5) and is consumed with that shape in Task 6. `send_quote_confirmation_to_sales` signature identical in Tasks 3 and 6. `_latest_complete_gen`/`_sign` defined in Task 5, reused in Task 6.
- **Placeholder scan:** none — every code/step is complete.
- **Idempotency:** the one-time sales email uses the pre-update `quote_confirmed` value (Task 6 Step 3), matching spec §3.4 step 5.
