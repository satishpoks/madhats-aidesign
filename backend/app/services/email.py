"""Resend email integration. All bodies come from app.prompts.

PII safety: recipient addresses and customer names are NEVER written to logs.
"""
from __future__ import annotations

import structlog

from app import prompts
from app.config import settings

log = structlog.get_logger()

try:
    import resend  # type: ignore
except ImportError:  # pragma: no cover
    resend = None


def _send(to: str, subject: str, body: str) -> bool:
    if not settings.resend_api_key or resend is None:
        log.info("email_skipped_no_provider", subject=subject)
        return False
    resend.api_key = settings.resend_api_key
    html = "<pre style='font-family:inherit;white-space:pre-wrap'>" + body + "</pre>"
    resend.Emails.send(
        {
            "from": settings.resend_from_address,
            "to": [to],
            "subject": subject,
            "html": html,
        }
    )
    log.info("email_sent", subject=subject)  # no recipient logged (PII)
    return True


def send_verification_email(to: str, name: str, verify_url: str) -> bool:
    body = prompts.VERIFICATION_EMAIL_BODY.format(name=name, verify_url=verify_url)
    return _send(to, prompts.VERIFICATION_EMAIL_SUBJECT, body)


def send_preview_email(to: str, name: str, image_url: str) -> bool:
    body = prompts.PREVIEW_EMAIL_BODY.format(name=name, image_url=image_url)
    return _send(to, prompts.PREVIEW_EMAIL_SUBJECT, body)


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
