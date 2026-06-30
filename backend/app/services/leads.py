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


def send_verification(lead: dict) -> None:
    """Generate a verification token, store its hash, and email the link."""
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
    email_service.send_verification_email(lead["email"], lead["name"], verify_url)
    log.info("verification_email_dispatched", lead_id=lead["id"])  # no PII


def capture_lead_and_verify(session: dict, collected: dict, email: str) -> str | None:
    """Create the lead (name already known) and send a verification email.

    Returns the new lead id, or None if the lead row could not be created.
    Sending is best-effort: a failure is logged but never blocks the
    conversation (the customer still sees the on-screen "check your inbox" step).
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
        return None

    lead = res.data[0]
    log.info("lead_created", session_id=session_id)  # no PII

    try:
        send_verification(lead)
    except Exception as exc:  # noqa: BLE001
        log.error("verification_send_failed", session_id=session_id, error=str(exc))

    return lead["id"]
