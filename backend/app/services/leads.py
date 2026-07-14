"""Lead capture used by the conversation flow.

The chatbot asks for the customer's email inline (in the GENERATING message) and
we already have their name from earlier in the chat, so there is no separate
contact form. We still keep the double opt-in: creating the lead sends a
verification email, and clicking its link (handled by ``api/routes/leads.py``)
is what releases the design preview + sales notification.

PII safety: name/email/phone are never written to logs.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

import jwt
import structlog

from app.config import settings
from app.db import get_supabase
from app.services import email as email_service

log = structlog.get_logger()

# Conservative email matcher — good enough to decide "did the user give us an
# email yet?" without depending on a heavyweight validator.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_email(message: str) -> str | None:
    """Return the first email-looking token in the message, or None."""
    match = _EMAIL_RE.search(message or "")
    return match.group(0) if match else None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def send_verification(lead: dict, store: dict | None = None) -> bool:
    """Generate a verification token, store its hash, and email the link.

    ``store`` (a row from app.services.stores.get_store), when provided, brands
    the email with the store's name and primary colour; when omitted the email
    falls back to MadHats defaults.

    Returns True iff the verification email was actually dispatched to the
    provider (so a caller can re-ask a mistyped/undeliverable address)."""
    sb = get_supabase()
    ttl = settings.verification_token_ttl_seconds
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = jwt.encode(
        {"lead_id": lead["id"], "exp": expires},
        settings.admin_secret,  # reuse server secret for signing
        algorithm="HS256",
    )
    sb.table("email_verifications").insert(
        {
            "lead_id": lead["id"],
            "token_hash": hash_token(token),
            "expires_at": expires.isoformat(),
        }
    ).execute()
    verify_url = f"{settings.email_verify_base_url}/leads/verify/{token}"
    brand = (store or {}).get("brand") or {}
    sent = email_service.send_verification_email(
        lead["email"],
        lead["name"],
        verify_url,
        store_name=(store or {}).get("name") or "MadHats",
        primary_colour=brand.get("primary_colour") or "#ff5c00",
    )
    log.info("verification_email_dispatched", lead_id=lead["id"], sent=bool(sent))  # no PII
    return bool(sent)


def capture_lead_and_verify(session: dict, collected: dict, email: str) -> tuple[str | None, bool]:
    """Create the lead (name already known) and send a verification email.

    Returns ``(lead_id, delivery_ok)``:
    - ``lead_id`` is the new lead id, or None if the row could not be created.
    - ``delivery_ok`` is True when the verification email was dispatched OR when
      no email provider is configured (dev/CI — nothing to deliver, so the flow
      proceeds as before). It is False ONLY when a provider IS configured and
      the send failed (e.g. a mistyped / undeliverable address the provider
      rejects), so the caller can re-ask the email.
    """
    sb = get_supabase()
    session_id = session["id"]
    name = collected.get("name") or "there"

    try:
        res = (
            sb.table("leads")
            .insert(
                {
                    "session_id": session_id,
                    "name": name,
                    "email": email,
                    "phone": None,
                }
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.error("lead_create_failed", session_id=session_id, error=str(exc))
        return None, False

    lead = res.data[0]
    log.info("lead_created", session_id=session_id)  # no PII

    from app.services.stores import get_store

    store = get_store(session.get("store_id")) if session.get("store_id") else None

    provider_configured = bool(settings.resend_api_key)
    sent = False
    try:
        sent = send_verification(lead, store)
    except Exception as exc:  # noqa: BLE001
        log.error("verification_send_failed", session_id=session_id, error=str(exc))

    # Only a REAL provider rejection (provider configured but send failed) should
    # make us re-ask; with no provider (dev/CI) there's nothing to deliver, so
    # proceed as before.
    delivery_ok = sent or not provider_configured
    return lead["id"], delivery_ok


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
