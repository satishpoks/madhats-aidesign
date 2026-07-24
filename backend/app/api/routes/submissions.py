from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import AdminContext, assert_store_allowed, require_admin_ctx
from app.db import get_supabase
from app.models.submission import (
    CreateSubmissionRequest,
    SubmissionResponse,
    UpdateSubmissionRequest,
)

router = APIRouter(tags=["submissions"])
log = structlog.get_logger()


def _store_id_for_submission_session(session_id: str | None) -> str | None:
    """Resolve a submission's session's store_id (used to scope the cross-store
    admin listing to a non-super admin's assigned stores)."""
    if not session_id:
        return None
    sb = get_supabase()
    res = sb.table("design_sessions").select("store_id").eq("id", session_id).limit(1).execute()
    return res.data[0].get("store_id") if res.data else None


@router.post("/submissions", response_model=SubmissionResponse)
async def create_submission(body: CreateSubmissionRequest) -> SubmissionResponse:
    sb = get_supabase()
    res = (
        sb.table("approval_submissions")
        .insert(
            {
                "session_id": body.session_id,
                "product_ref": body.product_ref,
                "final_image_urls": body.final_image_urls,
                "source_ref": body.source_ref,
                "customer": body.customer,
                "review_status": "pending",
            }
        )
        .execute()
    )
    log.info("submission_created", session_id=body.session_id)
    return SubmissionResponse(submission_id=res.data[0]["id"])


@router.get("/admin/submissions")
async def list_submissions(ctx: AdminContext = Depends(require_admin_ctx)) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("approval_submissions")
        .select("*")
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        rows = [
            r for r in rows
            if _store_id_for_submission_session(r.get("session_id")) in allowed
        ]
    return rows


@router.patch("/admin/submissions/{submission_id}")
async def update_submission(
    submission_id: str,
    body: UpdateSubmissionRequest,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    sb = get_supabase()
    existing = (
        sb.table("approval_submissions")
        .select("id, session_id")
        .eq("id", submission_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status_code=404, detail="Submission not found")

    store_id = _store_id_for_submission_session(existing.data[0].get("session_id"))
    assert_store_allowed(ctx, store_id)

    sb.table("approval_submissions").update(
        {
            "review_status": body.review_status,
            "reviewer_notes": body.reviewer_notes,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", submission_id).execute()
    log.info("submission_updated", submission_id=submission_id, status=body.review_status)
    return {"updated": True}
