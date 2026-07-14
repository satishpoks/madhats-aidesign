"""Resend email integration. All bodies come from app.prompts.

PII safety: recipient addresses and customer names are NEVER written to logs.
"""
from __future__ import annotations

import base64
import html as html_lib
from string import Template

import structlog

from app import prompts
from app.config import settings
from app.services import design_summary

log = structlog.get_logger()

try:
    import resend  # type: ignore
except ImportError:  # pragma: no cover
    resend = None


def _dispatch(
    to: str, subject: str, html: str, attachments: list[dict] | None = None
) -> bool:
    """Send a ready-to-go HTML body via Resend. Best-effort (never raises)."""
    if not settings.resend_api_key or resend is None:
        log.info("email_skipped_no_provider", subject=subject)
        return False
    resend.api_key = settings.resend_api_key
    payload: dict = {
        "from": settings.resend_from_address,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    if attachments:
        payload["attachments"] = attachments
    try:
        resend.Emails.send(payload)
    except Exception as exc:  # noqa: BLE001
        # Email delivery is best-effort: a provider error (Resend test-mode
        # recipient limits, quota, network) must NEVER crash the request that
        # triggered the send — e.g. email verification, which has already
        # persisted. We log the error TYPE/code only, never the provider message
        # (it can echo a recipient address → PII).
        log.warning(
            "email_send_failed",
            subject=subject,
            error_type=getattr(exc, "error_type", type(exc).__name__),
            code=getattr(exc, "code", None),
        )
        return False
    log.info("email_sent", subject=subject)  # no recipient logged (PII)
    return True


def _send(to: str, subject: str, body: str) -> bool:
    """Send a plain-text body (wrapped in <pre> for a mono, line-preserving look)."""
    html = "<pre style='font-family:inherit;white-space:pre-wrap'>" + body + "</pre>"
    return _dispatch(to, subject, html)


def send_verification_email(to: str, name: str, verify_url: str) -> bool:
    body = prompts.VERIFICATION_EMAIL_BODY.format(name=name, verify_url=verify_url)
    return _send(to, prompts.VERIFICATION_EMAIL_SUBJECT, body)


def send_resume_email(to: str, name: str, resume_url: str) -> bool:
    """Email a link back into the chat when the design isn't ready yet."""
    body = prompts.RESUME_EMAIL_BODY.format(name=name, resume_url=resume_url)
    return _send(to, prompts.RESUME_EMAIL_SUBJECT, body)


# Content-ID for the inline preview image (referenced as cid:<this> in the HTML).
_PREVIEW_CID = "madhats-preview"


def send_preview_email(
    to: str,
    name: str,
    image_url: str,
    brief: str = "",
    quote_url: str = "",
    edit_url: str = "",
    talk_url: str = "",
    image_bytes: bytes | None = None,
    subject: str | None = None,
    images: list[dict] | None = None,
    image_groups: list[dict] | None = None,
    brand: dict | None = None,
    store_name: str = "MadHats",
    logo_bytes: bytes | None = None,
) -> bool:
    """Send the branded design preview (Figma E1 template).

    Supports one OR several stacked images (a design may render multiple
    angles — front hero + decorated back/side views). Pass ``images`` as a list
    of ``{"url": str, "bytes": bytes | None, "label": str}`` to render each view
    full-width, stacked, same size. When ``images`` is omitted the single
    ``image_url``/``image_bytes`` pair is used (backward-compatible).

    When an image's ``bytes`` are supplied it rides along as an inline CID
    attachment (``<img src="cid:…">``) so the recipient's mail client never has
    to fetch it from storage. This is what makes the image show up: a signed
    storage URL points at the private Supabase stack (``127.0.0.1`` in dev,
    a TTL-limited link in prod) which Gmail's image proxy can't reach — so a
    bare ``<img src=http…>`` renders broken. Inlining the bytes side-steps
    reachability and TTL expiry entirely. Falls back to a plain URL ``src`` when
    no bytes are available (best-effort, never a blank image).

    All caller-supplied values are HTML-escaped before templating so a name,
    URL or label can never break out of the markup.
    """
    if images is None:
        images = [{"url": image_url, "bytes": image_bytes, "label": ""}]

    # Grouped mode: two labelled sections ("Your design" + "On the real hat").
    # Flat mode (image_groups=None): one untitled group, backward-compatible.
    groups = image_groups if image_groups else [{"title": "", "images": images}]

    attachments: list[dict] = []
    blocks: list[str] = []
    idx = 0  # global attachment index so CIDs stay unique across sections
    for group in groups:
        title = (group.get("title") or "").strip()
        if title:
            blocks.append(prompts.PREVIEW_EMAIL_SECTION_HEADER.format(title=html_lib.escape(title)))
        for im in group.get("images") or []:
            raw = im.get("bytes")
            if raw:
                cid = f"{_PREVIEW_CID}-{idx}"  # literal + index, safe — no user input
                attachments.append(
                    {
                        "filename": f"madhats-preview-{idx}.png",
                        "content": base64.b64encode(raw).decode("ascii"),
                        "content_type": "image/png",
                        "content_id": cid,
                    }
                )
                src = f"cid:{cid}"
            else:
                src = html_lib.escape(im.get("url") or "", quote=True)
            label = (im.get("label") or "").strip()
            caption = html_lib.escape(f"{label} — watermarked preview") if label else "Watermarked preview"
            blocks.append(prompts.PREVIEW_EMAIL_IMAGE_BLOCK.format(src=src, caption=caption))
            idx += 1

    b = brand or {}
    primary = b.get("primary_colour") or "#ff5c00"
    if logo_bytes:
        logo_cid = f"{_PREVIEW_CID}-logo"
        attachments.append(
            {
                "filename": "logo.png",
                "content": base64.b64encode(logo_bytes).decode("ascii"),
                "content_type": "image/png",
                "content_id": logo_cid,
            }
        )
        header_html = (
            f'<img src="cid:{logo_cid}" alt="{html_lib.escape(store_name)}" '
            'style="max-height:36px;display:block;" />'
        )
    else:
        # Preserve today's exact header text ("MAD HATS", with a space) for the
        # unbranded default rather than deriving it from store_name.upper()
        # ("MadHats".upper() == "MADHATS", no space) — that would silently
        # change bytes for every session with no store brand configured.
        # Any real (non-default) store_name is upper-cased as designed.
        display_name = "MAD HATS" if store_name == "MadHats" else store_name.upper()
        header_html = (
            f'<div style="font-size:22px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">'
            f'{html_lib.escape(display_name)}</div>\n'
            '          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>'
        )

    html = Template(prompts.PREVIEW_EMAIL_HTML).substitute(
        name=html_lib.escape(name or "there"),
        brief=html_lib.escape(brief),
        images_block="".join(blocks),
        quote_url=html_lib.escape(quote_url or "#", quote=True),
        edit_url=html_lib.escape(edit_url or "#", quote=True),
        talk_url=html_lib.escape(talk_url or "#", quote=True),
        primary_colour=primary,
        header_html=header_html,
        store_name=html_lib.escape(store_name),
    )
    return _dispatch(to, subject or prompts.PREVIEW_EMAIL_SUBJECT, html, attachments=attachments or None)


def send_quote_to_sales(
    customer: dict, product: dict, collected: dict, image_url: str, recipient: str | None = None
) -> bool:
    to = recipient or settings.sales_notification_email
    subject = prompts.SALES_QUOTE_EMAIL_SUBJECT.format(
        product_name=product.get("name", "Custom cap"),
        quantity=collected.get("quantity", "?"),
    )
    zone_label, position = design_summary.primary_placement(collected)
    body = prompts.SALES_QUOTE_EMAIL_BODY.format(
        customer_name=customer.get("name", ""),
        customer_email=customer.get("email", ""),
        customer_phone=customer.get("phone", "") or "—",
        product_name=product.get("name", ""),
        product_style=product.get("style", ""),
        product_colour=product.get("colour", ""),
        quantity=collected.get("quantity", "?"),
        decoration_type=collected.get("decoration_type", "?"),
        placement_zone=zone_label,
        placement_position=position,
        design_brief=design_summary.summarise_elements(collected) or "No design details captured.",
        image_url=image_url,
    )
    return _send(to, subject, body)


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
    zone_label, position = design_summary.primary_placement(collected)
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
        placement_zone=zone_label,
        placement_position=position,
        design_brief=design_summary.summarise_elements(collected) or "No design details captured.",
        note=note or "—",
        image_url=image_url,
    )
    return _send(to, subject, body)


def send_generation_alert(
    store_email: str, session_id: str, product: str, brief: str, error: str
) -> bool:
    """Alert ops that a generation failed all retries and needs manual regeneration.

    Best-effort like every other send in this module. No customer name/email
    is included — this is an internal notification keyed on session_id.
    """
    to = store_email or settings.sales_notification_email
    subject = prompts.GENERATION_ALERT_EMAIL_SUBJECT.format(product_name=product)
    body = prompts.GENERATION_ALERT_EMAIL_BODY.format(
        session_id=session_id, product_name=product, brief=brief, error=error
    )
    return _send(to, subject, body)
