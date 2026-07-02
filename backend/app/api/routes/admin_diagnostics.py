"""Admin diagnostics: design-session transcripts, generation audit logs, and a
system health summary. All routes gated by X-Admin-Secret.

These are read-only ops/observability endpoints for the admin panel:
- GET /admin/sessions            — browse design sessions (paginated)
- GET /admin/sessions/{id}       — full chat transcript + generations + lead
- GET /admin/generation-logs     — per-call image-generation audit trail
- GET /admin/diagnostics         — counts + provider config (no secrets)

No customer PII is logged; lead contact details are returned in the response
body for ops use but never written to application logs.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import require_admin
from app.config import settings
from app.db import get_supabase

router = APIRouter(tags=["admin-diagnostics"], dependencies=[Depends(require_admin)])


def _product_name(product_ref: dict | None) -> str | None:
    if not product_ref:
        return None
    return product_ref.get("name") or product_ref.get("product_id")


@router.get("/admin/sessions")
async def list_sessions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    state: str | None = None,
    store_id: str | None = None,
) -> dict:
    sb = get_supabase()
    q = sb.table("design_sessions").select(
        "id, store_id, share_token, state, status, channel, entry_path, product_ref, created_at",
        count="exact",
    )
    if state:
        q = q.eq("state", state)
    if store_id:
        q = q.eq("store_id", store_id)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    items = [
        {
            "id": r["id"],
            "store_id": r.get("store_id"),
            "share_token": r.get("share_token"),
            "state": r.get("state"),
            "status": r.get("status"),
            "channel": r.get("channel"),
            "entry_path": r.get("entry_path"),
            "product": _product_name(r.get("product_ref")),
            "created_at": r.get("created_at"),
        }
        for r in (res.data or [])
    ]
    return {"items": items, "total": res.count or 0, "limit": limit, "offset": offset}


@router.get("/admin/sessions/{session_id}")
async def get_session_detail(session_id: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]

    msgs = (
        sb.table("chat_messages")
        .select("role, content, state_before, state_after, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    gens = (
        sb.table("generations")
        .select("id, tier, model, status, image_url, watermarked_url, cost_usd, latency_ms, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    leads = (
        sb.table("leads")
        .select("id, name, email, phone, email_verified, verified_at, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    return {
        "id": session["id"],
        "store_id": session.get("store_id"),
        "share_token": session.get("share_token"),
        "state": session.get("state"),
        "status": session.get("status"),
        "channel": session.get("channel"),
        "entry_path": session.get("entry_path"),
        "product": _product_name(session.get("product_ref")),
        "product_ref": session.get("product_ref"),
        "collected": session.get("collected") or {},
        "created_at": session.get("created_at"),
        "messages": msgs.data or [],
        "generations": gens.data or [],
        "leads": leads.data or [],
    }


@router.get("/admin/generation-logs")
async def list_generation_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = None,
    status: str | None = None,
) -> dict:
    sb = get_supabase()
    q = sb.table("generation_logs").select(
        "id, generation_id, job_id, session_id, attempt, tier, status, model, "
        "full_prompt, params, reference_image_url, uploaded_asset_url, output_image_url, "
        "response_meta, error, latency_ms, request_at, response_at",
        count="exact",
    )
    if session_id:
        q = q.eq("session_id", session_id)
    if status:
        q = q.eq("status", status)
    res = q.order("request_at", desc=True).range(offset, offset + limit - 1).execute()
    return {
        "items": res.data or [],
        "total": res.count or 0,
        "limit": limit,
        "offset": offset,
    }


def _count(table: str, **filters: object) -> int:
    sb = get_supabase()
    q = sb.table(table).select("id", count="exact")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.limit(1).execute().count or 0


@router.get("/admin/diagnostics")
async def diagnostics() -> dict:
    """System health summary: counts + non-secret provider config."""
    return {
        "app_env": settings.app_env,
        "providers": {
            "image_provider_preview": settings.image_provider_preview,
            "image_provider_final": settings.image_provider_final,
            "gemini_preview_model": settings.gemini_preview_model,
            "gemini_final_model": settings.gemini_final_model,
            "claude_haiku_model": settings.claude_haiku_model,
            # Booleans only — never expose the keys themselves.
            "gemini_api_key_set": bool(settings.gemini_api_key),
            "anthropic_api_key_set": bool(settings.anthropic_api_key),
            "resend_api_key_set": bool(settings.resend_api_key),
            "sentry_enabled": bool(settings.sentry_dsn),
        },
        "counts": {
            "stores": _count("stores"),
            "sessions": _count("design_sessions"),
            "generations": _count("generations"),
            "generations_failed": _count("generations", status="failed"),
            "leads": _count("leads"),
            "leads_verified": _count("leads", email_verified=True),
            "submissions_pending": _count("approval_submissions", review_status="pending"),
        },
    }
