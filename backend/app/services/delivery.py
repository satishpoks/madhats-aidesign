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

from datetime import datetime, timedelta, timezone

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

    # Idempotency guard. This checks the same in-memory `lead` dict loaded at
    # the top of this call (a single flag check at function scope) — it is
    # NOT a fresh re-read from the DB immediately before send. Two callers
    # racing in the same instant (verify handler + generation worker) could
    # both pass this check and both send; per spec §4.1 that is tolerated
    # (one extra identical email), not treated as a correctness bug. A
    # follow-up could upgrade this to a conditional UPDATE for a stronger
    # guarantee if it becomes a problem in practice.
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
    # _make_watermarked can fail (fetch/watermark error) and leave
    # watermarked_url empty while the clean image_url is still valid — that
    # row still passes gate 2. Prefer the watermarked image for the
    # customer-facing email, but fall back to the signed clean URL so the
    # email is never sent with a blank image. The sales/ops notification
    # keeps using the clean URL as before.
    customer_image_url = watermarked_url or clean_url

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
    preview_sent = email_service.send_preview_email(
        lead["email"],
        lead["name"],
        customer_image_url,
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

    if not preview_sent:
        # send_preview_email is best-effort and returns False (Resend outage
        # / quota) without raising. Do NOT set preview_email_sent here — the
        # design has not actually been delivered, and setting the flag would
        # permanently block every future retrigger via gate 3. Leaving it
        # False lets a later call (manual re-run, or the other track firing)
        # retry the send.
        log.warning("preview_email_send_failed", session_id=session_id)
        return False

    sb.table("leads").update(
        {"preview_email_sent": True, "preview_sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", lead["id"]).execute()

    log.info("preview_delivered", session_id=session_id)
    return True


def backfill_pending(limit: int = 100, max_age_hours: int = 72) -> dict:
    """Re-attempt delivery for verified leads whose preview never sent.

    Self-heal sweep for the case where `maybe_send_preview` was invoked by
    both async tracks (generation completion + email verification) but the
    send failed both times (e.g. a Resend outage) — nothing else re-triggers
    delivery after that point, so this job does.

    Selects leads where email_verified=true AND preview_email_sent=false,
    verified within the last max_age_hours (skip long-dead leads, which are
    very unlikely to still be wanted and would otherwise be retried forever),
    newest first, capped at `limit`. Calls the existing idempotent
    maybe_send_preview(session_id) for each; it re-checks all gates itself
    and is the only place the preview_email_sent flag is set.

    Safe to run repeatedly (e.g. from a Railway cron): an already-delivered
    lead is filtered out by the query itself, and a still-failing send simply
    leaves the flag false for the next run.

    Returns {"scanned": int, "delivered": int, "still_pending": int}.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()

    res = (
        sb.table("leads")
        .select("*")
        .eq("email_verified", True)
        .eq("preview_email_sent", False)
        .gte("verified_at", cutoff)
        .order("verified_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = res.data or []

    delivered = 0
    still_pending = 0
    for row in rows:
        session_id = row.get("session_id")
        try:
            sent = maybe_send_preview(session_id)
        except Exception:  # noqa: BLE001 — one bad row must not abort the sweep
            log.warning("backfill_row_failed", session_id=session_id)
            still_pending += 1
            continue
        if sent:
            delivered += 1
        else:
            still_pending += 1

    tally = {"scanned": len(rows), "delivered": delivered, "still_pending": still_pending}
    log.info("backfill_complete", **tally)
    return tally
