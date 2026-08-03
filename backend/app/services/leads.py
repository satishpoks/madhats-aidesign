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
import secrets
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
    """Return the first email-looking token in the message, or None.

    Deliberately LOOSE and deliberately unchanged: v1 and the v2 Haiku-outage
    fallback use it to answer "did the customer give us an address yet?", where
    over-rejecting a real address is worse than passing a bad one along. Callers
    that are about to STORE the result validate it with `is_valid_email`.
    """
    match = _EMAIL_RE.search(message or "")
    return match.group(0) if match else None


# Anchored counterpart to `_EMAIL_RE` above — the one used to decide whether an
# address may be written to the `leads` table. Same shape as
# `admin_stores.py:_EMAIL_RE`, which is already stricter than the
# customer-facing extractor: exactly one `@`, no whitespace anywhere, a
# non-empty local part, and a domain carrying at least one dot. The remaining
# rules (dot placement, TLD length, RFC length caps) are explicit checks below
# rather than more regex, because a regex that encodes all of them is
# unreviewable and this is a security boundary. No `email_validator` dependency:
# the goal is "cannot store junk", not RFC 5322 completeness.
_VALID_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

_MAX_EMAIL_LEN = 254        # RFC 5321 forward-path limit
_MAX_LOCAL_LEN = 64         # RFC 5321 local-part limit


def is_valid_email(address: str | None) -> bool:
    """Whether `address` is well-formed enough to store and send to.

    Strict by design — it never trims, so a caller decides for itself whether a
    stray space is a typo to forgive or input to reject. `canvas_steps._apply_email`
    strips first; `_direct_email` feeds it an already-tokenised match.
    """
    if not address or not isinstance(address, str):
        return False
    if len(address) > _MAX_EMAIL_LEN:
        return False
    if not _VALID_EMAIL_RE.fullmatch(address):
        return False
    if ".." in address:
        return False
    local, _, domain = address.partition("@")
    if len(local) > _MAX_LOCAL_LEN:
        return False
    if local.startswith(".") or local.endswith("."):
        return False
    if domain.startswith(".") or domain.endswith("."):
        return False
    return len(domain.rsplit(".", 1)[-1]) >= 2


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# Base32 alphabet with the ambiguous glyphs 0/O/1/I removed (24 letters + 8
# digits = 32 symbols). Customer-facing, so readability over a phone matters.
_REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_reference_code() -> str:
    """A short customer-facing tracking reference, e.g. ``MH-7F3K2A``."""
    return "MH-" + "".join(secrets.choice(_REF_ALPHABET) for _ in range(6))


def assign_reference_code(sb, lead_id: str) -> str:
    """Allocate a unique reference code and persist it on the lead row.

    Collision-checked against ``leads.reference_code`` (unique-indexed). Retries
    a bounded number of times before giving up — with a 32^6 space a collision is
    astronomically unlikely, so 10 attempts is ample headroom.
    """
    for _ in range(10):
        code = generate_reference_code()
        existing = (
            sb.table("leads").select("id").eq("reference_code", code).limit(1).execute()
        )
        if not existing.data:
            sb.table("leads").update({"reference_code": code}).eq("id", lead_id).execute()
            return code
    raise RuntimeError("could not allocate a unique reference code")


def _latest_lead(sb, session_id: str) -> dict | None:
    res = (
        sb.table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def record_quote_request(session: dict, collected: dict) -> str | None:
    """Record an explicit customer quote request against the session's lead.

    Sets ``quote_requested`` (+ timestamp), allocates a reference code (idempotent
    — an existing code is reused), and best-effort converges with the async
    email-verification track: if the email is already verified the customer
    reference email + sales notification fire now; otherwise they fire when
    verification completes (see delivery.maybe_send_quote_confirmation). Returns
    the reference code, or None when no lead exists yet.

    PII-safe: session_id / lead_id only in logs.
    """
    sb = get_supabase()
    session_id = session["id"]
    lead = _latest_lead(sb, session_id)
    if not lead:
        log.warning("record_quote_request_no_lead", session_id=session_id)
        return None

    code = lead.get("reference_code") or assign_reference_code(sb, lead["id"])
    sb.table("leads").update(
        {
            "quote_requested": True,
            "quote_requested_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", lead["id"]).execute()
    log.info("quote_requested", session_id=session_id, lead_id=lead["id"])  # no PII

    try:
        from app.services import delivery  # noqa: PLC0415 — avoid import cycle

        delivery.maybe_send_quote_confirmation(session_id)
    except Exception as exc:  # noqa: BLE001 — never fail the request over a side effect
        log.error("quote_converge_failed", session_id=session_id, error_type=type(exc).__name__)
    return code


def flag_over_daily_limit(lead_id: str | None) -> None:
    """Mark a lead whose email was over the daily design cap at email capture.

    Best-effort and idempotent-ish (a re-flag just rewrites the same truthy
    value). Persisted so the admin can see which emails exceeded the limit even
    after the rolling 24h window later drops the count. No-ops on a missing id.
    PII-safe: lead id only.
    """
    if not lead_id:
        return
    try:
        get_supabase().table("leads").update(
            {
                "over_daily_limit": True,
                "over_daily_limit_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", lead_id).execute()
        log.info("lead_over_daily_limit_flagged", lead_id=lead_id)  # no PII
    except Exception as exc:  # noqa: BLE001 — an admin signal must never fail the funnel
        # e.g. the migration not yet applied (missing column) — PostgREST raises.
        log.error("lead_over_daily_limit_flag_failed",
                  lead_id=lead_id, error_type=type(exc).__name__)


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
    sent = email_service.send_verification_email(
        lead["email"],
        lead["name"],
        verify_url,
        **email_service.brand_kit(store),
    )
    log.info("verification_email_dispatched", lead_id=lead["id"], sent=bool(sent))  # no PII
    return bool(sent)


def abandon_verification(lead_id: str | None) -> None:
    """Burn any unopened verification links for a lead the customer replaced.

    Called when the customer says the address they gave is wrong. The token they
    were sent stays cryptographically valid for the rest of its TTL, so without
    this a later click on the old link would verify the session against an
    address the customer has explicitly disowned — and the design would be
    released to it. Marking the rows `used_at` makes the route render its
    already-used page instead.

    Best-effort and PII-safe (lead id only): failing to burn a token must never
    block the customer from giving us a working address, which is the whole
    point of the step that calls this.
    """
    if not lead_id:
        return
    try:
        (get_supabase().table("email_verifications")
         .update({"used_at": datetime.now(timezone.utc).isoformat()})
         .eq("lead_id", lead_id).is_("used_at", "null").execute())
        log.info("verification_tokens_abandoned", lead_id=lead_id)  # no PII
    except Exception as exc:  # noqa: BLE001
        log.warning("verification_abandon_failed",
                    lead_id=lead_id, error_type=type(exc).__name__)


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
