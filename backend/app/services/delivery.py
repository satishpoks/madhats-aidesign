"""Single delivery primitive: send the preview + sales emails iff ALL gates pass.

Generation (async background task, `app/api/routes/generate.py`) and email
verification (`app/api/routes/leads.py:confirm_verification`) are two
independent tracks. Whichever finishes last calls `maybe_send_preview` and it
sends; the other call is a no-op. This replaces the old behaviour of sending
at verification time using whatever generation happened to be `complete` at
that instant, which produced blank-image emails when generation was still
running or had failed.

PII safety: only session_id is logged, never name/email/phone.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services import email as email_service
from app.services.products import get_product
from app.storage import generate_signed_url

log = structlog.get_logger()


def _to_signed(path: str | None) -> str:
    """Sign a storage path; pass through external URLs (e.g. the stub
    adapter's placehold.co links, which are not storage objects). Empty/None
    -> ""."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return generate_signed_url(path)


def maybe_send_preview(session_id: str) -> bool:
    """Send the preview + sales emails iff ALL gates pass. Idempotent.

    Gates (ALL required, in order — return False if any fails):
      1. A lead exists for this session AND lead.email_verified is True.
         Email verification is the mandatory first gate.
      2. The latest 'complete' generation for this session has a non-empty
         image (watermarked_url or image_url) — never send a blank email.
      3. lead.preview_email_sent is False (idempotency guard).

    On success: sends the preview email (customer) + sales notification
    (store ops, gated on the existing quote_request_sent flag), then sets
    leads.preview_email_sent=True + preview_sent_at, and returns True.
    Email sends are best-effort (they never raise); the flag set + return
    value are the reliable part.
    """
    sb = get_supabase()

    lead_res = (
        sb.table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not lead_res.data:
        return False
    lead = lead_res.data[0]
    if not lead.get("email_verified"):
        return False

    gen_res = (
        sb.table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not gen_res.data:
        return False
    gen = gen_res.data[0]
    if not (gen.get("watermarked_url") or gen.get("image_url")):
        return False

    # Re-check right before sending — the idempotency guard.
    if lead.get("preview_email_sent"):
        return False

    session_res = (
        sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    )
    session = session_res.data[0] if session_res.data else {}
    collected = session.get("collected") or {}
    product_ref = session.get("product_ref") or {}
    product = get_product(product_ref.get("product_id", "")) or product_ref

    watermarked_url = _to_signed(gen.get("watermarked_url"))
    clean_url = _to_signed(gen.get("image_url"))

    brief = prompts.PREVIEW_EMAIL_BRIEF.format(
        product=product.get("name") or "your custom cap",
        decoration=collected.get("decoration_type") or "custom decoration",
        placement=(collected.get("placement_zone") or "front panel").replace("_", " "),
        quantity=collected.get("quantity") or "?",
    )
    # CTA links (Figma E1). "Edit" reopens the chatbot and resumes this session
    # (keyed by its share token); quote / talk are best-effort mailto fallbacks
    # to the Studio address (no dedicated customer endpoints yet). The sales
    # team is also notified automatically below.
    edit_url = f"{settings.studio_base_url}/?session={session.get('share_token', '')}"
    mailto = f"mailto:{settings.resend_from_address}"
    email_service.send_preview_email(
        lead["email"],
        lead["name"],
        watermarked_url,
        brief=brief,
        quote_url=f"{mailto}?subject=Quote%20request",
        edit_url=edit_url,
        talk_url=mailto,
    )

    if not lead.get("quote_request_sent"):
        from app.services.stores import get_store

        store = get_store(session.get("store_id")) if session.get("store_id") else None
        recipient = (store or {}).get("sales_notification_email")
        customer = {"name": lead["name"], "email": lead["email"], "phone": lead.get("phone")}
        email_service.send_quote_to_sales(customer, product, collected, clean_url, recipient=recipient)
        sb.table("leads").update(
            {"quote_request_sent": True, "quote_sent_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", lead["id"]).execute()

    sb.table("leads").update(
        {"preview_email_sent": True, "preview_sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", lead["id"]).execute()

    log.info("preview_delivered", session_id=session_id)
    return True
