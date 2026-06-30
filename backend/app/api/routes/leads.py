from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import jwt
import structlog
from fastapi import APIRouter, HTTPException

from app.config import settings
from app.db import get_supabase
from app.services.products import get_product
from app.models.lead import CreateLeadRequest, LeadResponse, VerifySendRequest
from app.services import email as email_service
from app.storage import generate_signed_url

router = APIRouter(tags=["leads"])
log = structlog.get_logger()


@router.post("/leads", response_model=LeadResponse)
async def create_lead(body: CreateLeadRequest) -> LeadResponse:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("id").eq("id", body.session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")

    res = (
        sb.table("leads")
        .insert(
            {
                "session_id": body.session_id,
                "name": body.name,
                "email": str(body.email),
                "phone": body.phone,
            }
        )
        .execute()
    )
    # Do NOT log name/email/phone (PII).
    log.info("lead_created", session_id=body.session_id)
    return LeadResponse(lead_id=res.data[0]["id"])


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@router.post("/leads/verify/send")
async def send_verification(body: VerifySendRequest) -> dict:
    sb = get_supabase()
    res = sb.table("leads").select("*").eq("id", body.lead_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = res.data[0]

    ttl = settings.verification_token_ttl_seconds
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl)
    token = jwt.encode(
        {"lead_id": body.lead_id, "exp": expires},
        settings.admin_secret,  # reuse server secret for signing
        algorithm="HS256",
    )

    sb.table("email_verifications").insert(
        {
            "lead_id": body.lead_id,
            "token_hash": _hash_token(token),
            "expires_at": expires.isoformat(),
        }
    ).execute()

    verify_url = f"{settings.email_verify_base_url}/leads/verify/{token}"
    email_service.send_verification_email(lead["email"], lead["name"], verify_url)
    log.info("verification_email_dispatched", lead_id=body.lead_id)
    return {"sent": True}


@router.get("/leads/verify/{token}")
async def confirm_verification(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.admin_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=400, detail="Verification link expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=400, detail="Invalid verification link") from exc

    lead_id = payload["lead_id"]
    sb = get_supabase()

    ver = (
        sb.table("email_verifications")
        .select("*")
        .eq("token_hash", _hash_token(token))
        .is_("used_at", "null")
        .limit(1)
        .execute()
    )
    if not ver.data:
        raise HTTPException(status_code=400, detail="Link already used or invalid")

    now = datetime.now(timezone.utc).isoformat()
    sb.table("email_verifications").update({"used_at": now}).eq("id", ver.data[0]["id"]).execute()
    sb.table("leads").update({"email_verified": True, "verified_at": now}).eq("id", lead_id).execute()

    lead = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute().data[0]
    session_id = lead["session_id"]

    _post_verification_actions(lead, session_id)

    log.info("lead_verified", lead_id=lead_id, session_id=session_id)
    return {"verified": True, "session_id": session_id}


def _post_verification_actions(lead: dict, session_id: str) -> None:
    """After verification: send the preview email and notify sales (once)."""
    sb = get_supabase()
    session = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute().data[0]
    collected = session.get("collected") or {}
    product_ref = session.get("product_ref") or {}
    product = get_product(product_ref.get("product_id", "")) or product_ref

    gen = (
        sb.table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    watermarked_url = clean_url = ""
    if gen.data:
        watermarked_url = generate_signed_url(gen.data[0].get("watermarked_url") or "")
        clean_url = generate_signed_url(gen.data[0].get("image_url") or "")

    email_service.send_preview_email(lead["email"], lead["name"], watermarked_url)

    if not lead.get("quote_request_sent"):
        from app.services.stores import get_store

        store = get_store(session.get("store_id")) if session.get("store_id") else None
        recipient = (store or {}).get("sales_notification_email")
        customer = {"name": lead["name"], "email": lead["email"], "phone": lead.get("phone")}
        email_service.send_quote_to_sales(customer, product, collected, clean_url, recipient=recipient)
        sb.table("leads").update(
            {"quote_request_sent": True, "quote_sent_at": datetime.now(timezone.utc).isoformat()}
        ).eq("id", lead["id"]).execute()
