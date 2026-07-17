from __future__ import annotations

from datetime import datetime, timezone

import jwt
import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.models.lead import CreateLeadRequest, LeadResponse, VerifySendRequest
from app.services import delivery
from app.services import email as email_service
from app.services import leads as leads_service

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


@router.post("/leads/verify/send")
async def send_verification(body: VerifySendRequest) -> dict:
    sb = get_supabase()
    res = sb.table("leads").select("*").eq("id", body.lead_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead = res.data[0]

    # Derive the store from the lead's session so a resent verification email
    # is themed the same as the initial one (capture_lead_and_verify already
    # does this). Falls back to None (MadHats defaults) if the session or its
    # store_id is missing — never crash the resend over branding.
    store = None
    sess = (
        sb.table("design_sessions")
        .select("store_id")
        .eq("id", lead["session_id"])
        .limit(1)
        .execute()
    )
    if sess.data and sess.data[0].get("store_id"):
        from app.services.stores import get_store

        store = get_store(sess.data[0]["store_id"])

    leads_service.send_verification(lead, store)
    return {"sent": True}


def _error_page(message: str) -> HTMLResponse:
    """A friendly HTML page for a bad/expired/used verification link.

    The customer clicks this link in their inbox, so every outcome must render
    as a browser page — never raw JSON or a stack trace.
    """
    return HTMLResponse(
        prompts.VERIFICATION_ERROR_HTML.format(message=message), status_code=400
    )


@router.get("/leads/verify/{token}", response_class=HTMLResponse)
async def confirm_verification(token: str) -> HTMLResponse:
    try:
        payload = jwt.decode(token, settings.admin_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        return _error_page(
            "This link has expired. Head back to the chat and we'll send you a fresh one."
        )
    except jwt.InvalidTokenError:
        return _error_page("This verification link doesn't look right. Please try again.")

    lead_id = payload["lead_id"]
    sb = get_supabase()

    ver = (
        sb.table("email_verifications")
        .select("*")
        .eq("token_hash", leads_service.hash_token(token))
        .is_("used_at", "null")
        .limit(1)
        .execute()
    )
    if not ver.data:
        return _error_page(
            "This link has already been used. Your design is already on its way to your inbox."
        )

    now = datetime.now(timezone.utc).isoformat()
    sb.table("email_verifications").update({"used_at": now}).eq("id", ver.data[0]["id"]).execute()
    sb.table("leads").update({"email_verified": True, "verified_at": now}).eq("id", lead_id).execute()

    lead = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute().data[0]
    session_id = lead["session_id"]

    # Flip the session's collected flag so the (still-open) chat tab can detect
    # the out-of-band verification on its next poll and surface it in the thread.
    # This is a reliable state write, distinct from the best-effort email sends.
    _mark_session_verified(sb, session_id)

    # The email is verified at this point; sending the preview / sales emails is
    # a best-effort side effect that must never turn a successful verification
    # into an error page for the customer clicking the link. maybe_send_preview
    # is idempotent and gated on generation being complete with a real image —
    # see app/services/delivery.py.
    preview_sent = False
    try:
        preview_sent = delivery.maybe_send_preview(session_id)
    except Exception as exc:  # noqa: BLE001
        log.error("post_verification_actions_failed", lead_id=lead_id, error_type=type(exc).__name__)

    # If the preview did NOT go out, the customer verified EARLY — before the
    # design finished generating. Email them a link to resume the session so they
    # can continue if they've closed the chat tab. Fires at most once (guarded by
    # collected.resume_email_sent). The finished-design preview email still goes
    # out later via the normal delivery path.
    if not preview_sent:
        try:
            _maybe_send_resume_email(sb, session_id, lead)
        except Exception as exc:  # noqa: BLE001
            log.error("resume_email_failed", lead_id=lead_id, error_type=type(exc).__name__)

    log.info("lead_verified", lead_id=lead_id, session_id=session_id)
    # Confirmation only — NO design image/preview here. The design is delivered
    # exclusively via the preview email dispatched above.
    return HTMLResponse(prompts.VERIFICATION_SUCCESS_HTML)


def _mark_session_verified(sb, session_id: str) -> None:
    """Set collected.email_verified so the chat can advance past VERIFY_EMAIL."""
    row = (
        sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
    )
    if not row.data:
        return
    collected = row.data[0].get("collected") or {}
    collected["email_verified"] = True
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()


def _maybe_send_resume_email(sb, session_id: str, lead: dict) -> None:
    """Send a 'continue your design' email with a resume link, at most once.

    Called only when the preview email hasn't gone out yet (design not ready),
    i.e. the customer verified early. Reads the session fresh (after
    _mark_session_verified) so the guard write preserves email_verified. The
    resume link reuses the same ``?session=<share_token>`` deep link the preview
    email's edit CTA uses. PII (name/email) is never logged.

    Skipped for v2 canvas sessions: v2 asks for the email at the END of the flow
    (ask_email sits right before FINALIZE_CANVAS), so the customer is still in
    the tab watching their design render — "pick up where you left off" is
    nonsense there, and the preview email follows on its own. Every other flow
    captures the email mid-design, where the resume link earns its place.
    """
    row = (
        sb.table("design_sessions")
        .select("collected, share_token, store_id")
        .eq("id", session_id)
        .limit(1)
        .execute()
    )
    if not row.data:
        return
    collected = row.data[0].get("collected") or {}
    # Same selector as chat.py::_dispatch — no guard flag is written, so
    # flipping the flag back off restores the v1 behaviour for these sessions.
    if settings.canvas_orchestrator_v2 and collected.get("flow_mode") == "canvas":
        return
    if collected.get("resume_email_sent"):
        return
    share_token = row.data[0].get("share_token") or ""
    resume_url = f"{settings.studio_base_url}/?session={share_token}"

    # Resolve the session's store so the resume email is themed the same as
    # the initial verification/preview emails. Falls back to MadHats defaults
    # if the session has no store_id or the lookup fails to resolve.
    store = None
    store_id = row.data[0].get("store_id")
    if store_id:
        from app.services.stores import get_store

        store = get_store(store_id)
    store_name = (store or {}).get("name") or "MadHats"
    primary_colour = ((store or {}).get("brand") or {}).get("primary_colour") or "#ff5c00"

    email_service.send_resume_email(
        lead["email"],
        lead.get("name") or "there",
        resume_url,
        store_name=store_name,
        primary_colour=primary_colour,
    )
    collected["resume_email_sent"] = True
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()
    log.info("resume_email_sent", session_id=session_id)  # no PII
