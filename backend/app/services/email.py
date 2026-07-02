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
) -> bool:
    """Send the branded design preview (Figma E1 template).

    When ``image_bytes`` is supplied the design rides along as an inline CID
    attachment (``<img src="cid:…">``) so the recipient's mail client never has
    to fetch it from storage. This is what makes the image show up: a signed
    storage URL points at the private Supabase stack (``127.0.0.1`` in dev,
    a TTL-limited link in prod) which Gmail's image proxy can't reach — so a
    bare ``<img src=http…>`` renders broken. Inlining the bytes side-steps
    reachability and TTL expiry entirely.

    Falls back to a plain URL ``src`` when no bytes are available (best-effort,
    never a blank image).

    All caller-supplied values are HTML-escaped before templating so a name or
    URL can never break out of the markup.
    """
    attachments: list[dict] | None = None
    if image_bytes:
        img_src = f"cid:{_PREVIEW_CID}"  # literal, safe — no user input
        attachments = [
            {
                "filename": "madhats-preview.png",
                "content": base64.b64encode(image_bytes).decode("ascii"),
                "content_type": "image/png",
                "content_id": _PREVIEW_CID,
            }
        ]
    else:
        img_src = html_lib.escape(image_url, quote=True)

    html = Template(prompts.PREVIEW_EMAIL_HTML).substitute(
        name=html_lib.escape(name or "there"),
        brief=html_lib.escape(brief),
        image_url=img_src,
        quote_url=html_lib.escape(quote_url or "#", quote=True),
        edit_url=html_lib.escape(edit_url or "#", quote=True),
        talk_url=html_lib.escape(talk_url or "#", quote=True),
    )
    return _dispatch(to, prompts.PREVIEW_EMAIL_SUBJECT, html, attachments=attachments)


def send_quote_to_sales(
    customer: dict, product: dict, collected: dict, image_url: str, recipient: str | None = None
) -> bool:
    to = recipient or settings.sales_notification_email
    subject = prompts.SALES_QUOTE_EMAIL_SUBJECT.format(
        product_name=product.get("name", "Custom cap"),
        quantity=collected.get("quantity", "?"),
    )
    body = prompts.SALES_QUOTE_EMAIL_BODY.format(
        customer_name=customer.get("name", ""),
        customer_email=customer.get("email", ""),
        customer_phone=customer.get("phone", "") or "—",
        product_name=product.get("name", ""),
        product_style=product.get("style", ""),
        product_colour=product.get("colour", ""),
        quantity=collected.get("quantity", "?"),
        decoration_type=collected.get("decoration_type", "?"),
        placement_zone=collected.get("placement_zone", "?"),
        placement_position=collected.get("placement_position", "?"),
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
