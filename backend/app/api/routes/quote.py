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
