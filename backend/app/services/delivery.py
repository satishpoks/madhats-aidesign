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

import httpx
import structlog

from app import prompts, storage
from app.config import settings
from app.db import get_supabase
from app.services import design_summary
from app.services import email as email_service
from app.services import leads as leads_service
from app.services.products import get_product
from app.storage import generate_signed_url

log = structlog.get_logger()

# Order + friendly labels for the multi-view preview email.
_VIEW_ORDER = ("front", "back", "left", "right")
_VIEW_LABELS = {"front": "Front", "back": "Back", "left": "Left side", "right": "Right side"}


def _to_signed(path: str | None) -> str:
    """Sign a storage path; pass through external URLs (e.g. the stub
    adapter's placehold.co links, which are not storage objects). Empty/None
    -> ""."""
    if not path:
        return ""
    if path.startswith("http"):
        return path
    return generate_signed_url(path)


def _canvas_design_images(collected: dict) -> list[dict]:
    """Build the "Your design" image group — the full WYSIWYG canvas exports the
    customer placed (``collected['canvas_previews']``), watermarked at send time
    with the configured watermark text. Returns [] for non-canvas / legacy
    sessions so the caller falls back to the single flat image list."""
    previews = collected.get("canvas_previews") or {}
    if not previews:
        return []
    from app.services import settings_service  # noqa: PLC0415
    from app.services.watermark import apply_watermark  # noqa: PLC0415

    text = settings_service.get_settings().watermark_text
    out: list[dict] = []
    for view in _VIEW_ORDER:
        path = previews.get(view)
        if not path:
            continue
        url = _to_signed(path)
        raw = _fetch_image_bytes(url)
        if raw:
            try:
                raw = apply_watermark(raw, text=text)
            except Exception:  # noqa: BLE001 — keep the clean bytes if watermark fails
                pass
        out.append({"url": url, "bytes": raw, "label": _VIEW_LABELS.get(view, view)})
    return out


def _fetch_image_bytes(url: str) -> bytes | None:
    """Download the image so it can be inlined into the email (CID attachment).

    The backend CAN reach the storage URL (the local Supabase stack / a signed
    prod URL); the customer's mail client cannot (Gmail proxies images and can't
    hit 127.0.0.1, and signed URLs expire). Fetching here and shipping the bytes
    inline is what makes the design actually render in the inbox. Best-effort:
    on any failure return None and let the caller fall back to a URL src rather
    than crash delivery.
    """
    if not url:
        return None
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.content
    except Exception as exc:  # noqa: BLE001
        log.warning("preview_image_fetch_failed", error=str(exc))
        return None


def _is_quote_gated(sb, session_id: str) -> bool:
    """True when the session is the quote-gated canvas flow.

    For these sessions the customer NEVER receives the design by email — they get
    a tracking reference only (C2). Delivery of the design to the customer is
    fully out of scope this batch, so both the preview and the final-design sends
    are refused here regardless of generation state.
    """
    row = (
        sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
    )
    if not row.data:
        return False
    return bool((row.data[0].get("collected") or {}).get("quote_requested"))


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

    if _is_quote_gated(sb, session_id):
        # Quote-gated flow: the customer gets a reference, never the design.
        return False

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

    zone_label, _position = design_summary.primary_placement(collected)
    brief = prompts.PREVIEW_EMAIL_BRIEF.format(
        product=product.get("name") or "your custom cap",
        decoration=collected.get("decoration_type") or "custom decoration",
        placement=zone_label,
        quantity=collected.get("quantity") or "?",
    )
    # CTA links (Figma E1). "Quote" links to the server-rendered /quote/{token}
    # Request-a-Quote page; "edit" resumes this session by its share token — the
    # frontend routes a canvas-flow session back into the interactive Design
    # Studio (with the saved layout reloaded) and a chat-flow session into the
    # chatbot; "talk" is a best-effort mailto fallback to the Studio address (no
    # dedicated customer endpoint for it yet). The sales team is also notified
    # automatically below.
    edit_url = f"{settings.studio_base_url}/?session={session.get('share_token', '')}"
    mailto = f"mailto:{settings.resend_from_address}"
    quote_token = leads_service.make_quote_token(lead)
    quote_url = f"{settings.email_verify_base_url}/quote/{quote_token}"
    # Gather every rendered view (front hero + any decorated back/side view) so
    # the email shows them all, stacked at equal size. Inline each image's bytes
    # so the recipient's mail client never has to fetch (and fail to reach) the
    # private storage URL; fall back to the URL src if a fetch fails. Legacy /
    # single-view rows (no view_images) fall back to the single hero image.
    raw_views = gen.get("view_images") or {}
    preview_images: list[dict] = []
    for view in _VIEW_ORDER:
        entry = raw_views.get(view)
        if not entry:
            continue
        url = _to_signed(entry.get("watermarked_url") or entry.get("image_url"))
        if not url:
            continue
        preview_images.append(
            {"url": url, "bytes": _fetch_image_bytes(url), "label": _VIEW_LABELS.get(view, view)}
        )
    if not preview_images:
        preview_images = [
            {"url": customer_image_url, "bytes": _fetch_image_bytes(customer_image_url), "label": ""}
        ]

    # Segregate the email into "Your design" (the customer's own WYSIWYG canvas
    # export) and "On the real hat" (the photorealistic AI render). Both groups
    # are watermarked. Sessions with no canvas previews (legacy / non-canvas)
    # fall back to the single flat image list.
    design_images = _canvas_design_images(collected)
    image_groups = None
    if design_images:
        image_groups = [
            {"title": "Your design", "images": design_images},
            {"title": "How it looks on the real hat", "images": preview_images},
        ]

    from app.services.stores import get_store

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    brand = (store or {}).get("brand") or {}
    store_name = (store or {}).get("name") or "MadHats"
    logo_bytes = storage.download_asset(brand.get("logo_url")) if brand.get("logo_url") else None

    preview_sent = email_service.send_preview_email(
        lead["email"],
        lead["name"],
        customer_image_url,
        brief=brief,
        quote_url=quote_url,
        edit_url=edit_url,
        talk_url=mailto,
        image_bytes=preview_images[0]["bytes"],
        images=preview_images,
        image_groups=image_groups,
        brand=brand,
        store_name=store_name,
        logo_bytes=logo_bytes,
    )

    if not lead.get("quote_request_sent"):
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


def _completed_generations(session_id: str) -> list[dict]:
    res = (
        get_supabase()
        .table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at")
        .execute()
    )
    return res.data or []


def _lead_for_session(session_id: str) -> dict | None:
    res = (
        get_supabase()
        .table("leads")
        .select("*")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _mark_final_sent(lead_id: str) -> None:
    get_supabase().table("leads").update(
        {"final_email_sent": True, "final_email_sent_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", lead_id).execute()


def _deliver_final(lead: dict, image_path: str) -> bool:
    from app.services.stores import get_store

    url = _to_signed(image_path)
    image_bytes = _fetch_image_bytes(url)

    store = None
    session_id = lead.get("session_id")
    if session_id:
        session_res = (
            get_supabase().table("design_sessions").select("store_id").eq("id", session_id).limit(1).execute()
        )
        store_id = session_res.data[0].get("store_id") if session_res.data else None
        store = get_store(store_id) if store_id else None
    brand = (store or {}).get("brand") or {}
    store_name = (store or {}).get("name") or "MadHats"
    logo_bytes = storage.download_asset(brand.get("logo_url")) if brand.get("logo_url") else None

    return email_service.send_preview_email(
        lead["email"],
        lead["name"],
        url,
        brief="Here's your updated design based on your latest changes.",
        quote_url="",
        edit_url="",
        talk_url=f"mailto:{settings.resend_from_address}",
        image_bytes=image_bytes,
        subject=prompts.FINAL_DESIGN_EMAIL_SUBJECT,
        brand=brand,
        store_name=store_name,
        logo_bytes=logo_bytes,
    )


def send_final_design(session_id: str) -> bool:
    """Email the final (latest) design once, iff it differs from the first
    delivered design. Idempotent via leads.final_email_sent. Best-effort."""
    if _is_quote_gated(get_supabase(), session_id):
        return False
    gens = _completed_generations(session_id)
    if len(gens) < 2:
        return False  # no regeneration -> the first preview email already covered it
    lead = _lead_for_session(session_id)
    if not lead or lead.get("final_email_sent") or not lead.get("email"):
        return False
    latest = gens[-1]
    image_path = latest.get("watermarked_url") or latest.get("image_url")
    if not image_path:
        return False
    if not _deliver_final(lead, image_path):
        return False
    _mark_final_sent(lead["id"])
    log.info("final_design_delivered", session_id=session_id)
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


def maybe_send_quote_confirmation(session_id: str) -> bool:
    """Send the customer reference email + sales notification, once. Idempotent.

    Gates (ALL required): a lead exists, email_verified, quote_requested, a
    reference_code is allocated, the session's canvas has been FINALIZED, and
    quote_confirmation_sent is False. On success the customer is emailed their
    reference (no design image) and sales is emailed a summary with every
    uploaded component attached, then the dedup flag is set.

    This is the quote-gated analogue of maybe_send_preview: the async tracks
    (explicit quote request, email verification, canvas finalize) converge here,
    whichever finishes last — every one of them calls this. The canvas_finalized
    gate is load-bearing: REQUEST_QUOTE runs BEFORE canvas-finalize persists the
    elements/layout guides/previews, so a customer who verified early would
    otherwise trigger the one-and-only sales email with NO components attached,
    and the dedup flag would stop a better one ever being sent.

    Best-effort sends; the flag is set only after the customer email dispatches,
    so a failed run stays retriable. PII-safe: session/lead ids only.
    """
    # Local imports: `components` is only needed here, and `stores` would be a
    # module-level cycle. `email_service`/`storage` are already module-level.
    from app.services import components as components_service  # noqa: PLC0415
    from app.services.stores import get_store  # noqa: PLC0415

    sb = get_supabase()
    lead = _lead_for_session(session_id)
    if not lead:
        return False
    if not (lead.get("email_verified") and lead.get("quote_requested")):
        return False
    if not lead.get("reference_code"):
        return False
    if lead.get("quote_confirmation_sent"):
        return False

    session_res = (
        sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    )
    session = session_res.data[0] if session_res.data else {}
    collected = session.get("collected") or {}
    if not collected.get("canvas_finalized"):
        # The design isn't persisted yet — sending now would attach nothing and
        # the dedup flag would make it permanent. The finalize route re-calls us.
        return False

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    brand = (store or {}).get("brand") or {}
    store_name = (store or {}).get("name") or "MadHats"
    primary = brand.get("primary_colour") or "#ff5c00"

    customer_ok = email_service.send_quote_reference_email(
        lead["email"], lead.get("name") or "there", lead["reference_code"],
        store_name=store_name, primary_colour=primary,
    )

    # Build component attachments (base64), reusing the download primitive.
    import base64  # noqa: PLC0415

    attachments: list[dict] = []
    for comp in components_service.enumerate_components(collected):
        data = storage.download_asset(comp["path"])
        if not data:
            continue
        attachments.append(
            {
                "filename": comp["path"].rsplit("/", 1)[-1],
                "content": base64.b64encode(data).decode("ascii"),
                "content_type": "image/png",
            }
        )
    email_service.send_quote_request_to_sales(
        (store or {}).get("sales_notification_email"),
        lead["reference_code"], store_name, lead["email"], collected, attachments,
    )

    if not customer_ok:
        # Leave the flag unset so a later retry (backfill / re-verify) re-sends.
        log.warning("quote_reference_email_failed", session_id=session_id)
        return False

    sb.table("leads").update(
        {"quote_confirmation_sent": True}
    ).eq("id", lead["id"]).execute()
    log.info("quote_confirmation_delivered", session_id=session_id)  # no PII
    return True
