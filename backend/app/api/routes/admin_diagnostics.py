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

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx, require_super
from app.config import settings
from app.db import get_supabase
from app.services.products import get_product
from app.storage import media_url

router = APIRouter(tags=["admin-diagnostics"], dependencies=[Depends(require_admin_ctx)])


def _img(path: str | None, request: Request) -> str | None:
    """Turn a private storage path into a backend media-proxy URL the admin
    browser can fetch. External URLs (Shopify product images, stub placeholders)
    pass through unchanged. The bucket is private, so generated/uploaded objects
    can't be linked directly — they're streamed via /media/{token} instead."""
    return media_url(path, str(request.base_url))


def _product_name(product_ref: dict | None) -> str | None:
    if not product_ref:
        return None
    return product_ref.get("name") or product_ref.get("product_id")


def _best_generated_image(generations: list[dict]) -> str | None:
    """Pick the most recent completed generation's image (watermarked preferred)."""
    done = [g for g in generations if g.get("status") == "complete" and (g.get("watermarked_url") or g.get("image_url"))]
    done.sort(key=lambda g: g.get("created_at") or "", reverse=True)
    for g in done:
        url = g.get("watermarked_url") or g.get("image_url")
        if url:
            return url
    return None


@router.get("/admin/sessions")
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    state: str | None = None,
    store_id: str | None = None,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    sb = get_supabase()
    # Embed the captured lead contact and this session's generations so each row
    # is a full "lead" — who they are, the cap they picked, and the AI mockups.
    q = sb.table("design_sessions").select(
        "id, store_id, share_token, state, status, channel, entry_path, product_ref, "
        "collected, created_at, "
        "leads(name, email, phone, email_verified), "
        "generations(watermarked_url, image_url, status, created_at)",
        count="exact",
    )
    if state:
        q = q.eq("state", state)
    if not ctx.is_super:
        allowed = list(ctx.allowed_store_ids or set())
        if store_id is not None:
            assert_store_allowed(ctx, store_id)
            q = q.eq("store_id", store_id)
        elif allowed:
            q = q.in_("store_id", allowed)
        else:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
    elif store_id:
        q = q.eq("store_id", store_id)
    res = q.order("created_at", desc=True).range(offset, offset + limit - 1).execute()

    items = []
    for r in res.data or []:
        product_ref = r.get("product_ref") or {}
        collected = r.get("collected") or {}
        leads = r.get("leads") or []
        lead = leads[0] if leads else None
        gens = r.get("generations") or []
        items.append(
            {
                "id": r["id"],
                "store_id": r.get("store_id"),
                "share_token": r.get("share_token"),
                "state": r.get("state"),
                "status": r.get("status"),
                "channel": r.get("channel"),
                "entry_path": r.get("entry_path"),
                "product": _product_name(product_ref),
                "reference_image_url": _img(product_ref.get("reference_image_url"), request),
                "customer": (
                    {
                        "name": lead.get("name"),
                        "email": lead.get("email"),
                        "phone": lead.get("phone"),
                        "email_verified": lead.get("email_verified", False),
                    }
                    if lead
                    else None
                ),
                "decoration_type": collected.get("decoration_type"),
                "placement_zone": collected.get("placement_zone"),
                "quantity": collected.get("quantity"),
                "generated_image_url": _img(_best_generated_image(gens), request),
                "generation_count": len(gens),
                "created_at": r.get("created_at"),
            }
        )
    return {"items": items, "total": res.count or 0, "limit": limit, "offset": offset}


@router.get("/admin/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]
    assert_store_allowed(ctx, session.get("store_id"))

    msgs = (
        sb.table("chat_messages")
        .select("role, content, state_before, state_after, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    gens_res = (
        sb.table("generations")
        .select("id, tier, model, status, image_url, watermarked_url, cost_usd, latency_ms, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )
    generations = [
        {**g, "image_url": _img(g.get("image_url"), request), "watermarked_url": _img(g.get("watermarked_url"), request)}
        for g in (gens_res.data or [])
    ]
    leads = (
        sb.table("leads")
        .select("id, name, email, phone, email_verified, verified_at, created_at")
        .eq("session_id", session_id)
        .order("created_at")
        .execute()
    )

    # 360° product visibility: the session's product_ref only stores the front
    # reference image, so pull the full catalogue entry for all view angles.
    product_ref = session.get("product_ref") or {}
    view_images: dict = {}
    reference_image_url = product_ref.get("reference_image_url")
    product_id = product_ref.get("product_id")
    if product_id:
        product = get_product(product_id, store_id=session.get("store_id"))
        if product:
            view_images = product.get("view_images") or {}
            reference_image_url = reference_image_url or product.get("reference_image_url")

    return {
        "id": session["id"],
        "store_id": session.get("store_id"),
        "share_token": session.get("share_token"),
        "state": session.get("state"),
        "status": session.get("status"),
        "channel": session.get("channel"),
        "entry_path": session.get("entry_path"),
        "product": _product_name(product_ref),
        "product_ref": product_ref,
        "reference_image_url": _img(reference_image_url, request),
        "view_images": {angle: _img(url, request) for angle, url in view_images.items()},
        "collected": session.get("collected") or {},
        "created_at": session.get("created_at"),
        "messages": msgs.data or [],
        "generations": generations,
        "leads": leads.data or [],
    }


@router.get("/admin/generation-logs")
async def list_generation_logs(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session_id: str | None = None,
    status: str | None = None,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    sb = get_supabase()
    if not ctx.is_super:
        if not session_id:
            raise HTTPException(status_code=403, detail="Select a store/session")
        sess = sb.table("design_sessions").select("store_id").eq("id", session_id).limit(1).execute()
        sess_store_id = sess.data[0].get("store_id") if sess.data else None
        assert_store_allowed(ctx, sess_store_id)
    q = sb.table("generation_logs").select(
        "id, generation_id, job_id, session_id, attempt, tier, status, model, "
        "full_prompt, request_payload, reference_image_url, uploaded_asset_url, output_image_url, "
        "response_meta, error, latency_ms, request_at, response_at",
        count="exact",
    )
    if session_id:
        q = q.eq("session_id", session_id)
    if status:
        q = q.eq("status", status)
    res = q.order("request_at", desc=True).range(offset, offset + limit - 1).execute()
    items = [
        {
            **r,
            "output_image_url": _img(r.get("output_image_url"), request),
            "uploaded_asset_url": _img(r.get("uploaded_asset_url"), request),
            "reference_image_url": _img(r.get("reference_image_url"), request),
        }
        for r in (res.data or [])
    ]
    return {
        "items": items,
        "total": res.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/admin/generation-logs/{log_id}")
async def get_generation_log(
    log_id: str,
    request: Request,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    """Full detail for one audit row — INCLUDING the raw provider response.

    ``raw_response`` is deliberately excluded from the list endpoint (a successful
    row carries the returned image as base64 — MBs per row). Here it's returned in
    full so a failed call's raw upstream error, or a success's raw payload, can be
    inspected from the admin panel."""
    sb = get_supabase()
    res = sb.table("generation_logs").select("*").eq("id", log_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Generation log not found")
    row = res.data[0]
    if not ctx.is_super:
        sess = sb.table("design_sessions").select("store_id").eq("id", row.get("session_id")).limit(1).execute()
        sess_store_id = sess.data[0].get("store_id") if sess.data else None
        assert_store_allowed(ctx, sess_store_id)
    row["output_image_url"] = _img(row.get("output_image_url"), request)
    row["uploaded_asset_url"] = _img(row.get("uploaded_asset_url"), request)
    row["reference_image_url"] = _img(row.get("reference_image_url"), request)
    return row


def _count(table: str, **filters: object) -> int:
    sb = get_supabase()
    q = sb.table(table).select("id", count="exact")
    for k, v in filters.items():
        q = q.eq(k, v)
    return q.limit(1).execute().count or 0


@router.get("/admin/diagnostics")
async def diagnostics(ctx: AdminContext = Depends(require_admin_ctx)) -> dict:
    """System health summary: counts + non-secret provider config."""
    require_super(ctx)
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
