"""Admin center: confirmed quote requests.

Lists leads that explicitly requested a quote via the emailed quote link
(quote_confirmed = true) — the "customer likes the design and wants a quote"
signal — enriched with a compact design/session summary. Gated by X-Admin-Secret.

The on-demand render endpoint additionally requires X-Store-Key: rendering is a
store-scoped action, so the lead's session must belong to that store.
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.api.deps import require_admin, require_store
from app.api.routes import generate
from app.db import get_supabase

router = APIRouter(tags=["admin-leads"], dependencies=[Depends(require_admin)])


@router.get("/admin/quote-requests")
async def list_quote_requests() -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("leads")
        .select("*")
        .eq("quote_confirmed", True)
        .order("quote_confirmed_at", desc=True)
        .execute()
    )
    rows = res.data or []

    out: list[dict] = []
    for lead in rows:
        sess = (
            sb.table("design_sessions")
            .select("*")
            .eq("id", lead["session_id"])
            .limit(1)
            .execute()
        )
        session = sess.data[0] if sess.data else {}
        collected = session.get("collected") or {}
        product_ref = session.get("product_ref") or {}
        out.append(
            {
                "lead_id": lead["id"],
                "session_id": lead["session_id"],
                "name": lead.get("name"),
                "email": lead.get("email"),
                "phone": lead.get("phone"),
                "notify_by_phone": lead.get("notify_by_phone", False),
                "quote_note": lead.get("quote_note"),
                "quote_confirmed_at": lead.get("quote_confirmed_at"),
                "product": product_ref.get("name") or product_ref.get("product_id"),
                "decoration_type": collected.get("decoration_type"),
                "placement_zone": collected.get("placement_zone"),
                "quantity": collected.get("quantity"),
                "share_token": session.get("share_token"),
            }
        )
    return out


@router.post("/admin/quote-requests/{lead_id}/render")
async def render_quote_request(
    lead_id: str,
    background: BackgroundTasks,
    store: dict = Depends(require_store),
) -> dict:
    """Sales-triggered on-demand render for a quote request (C4).

    Store-scoped: the lead's session must belong to the X-Store-Key store. Reuses
    the canvas render pipeline (with the C6 fix). Returns the job_id to poll.
    """
    sb = get_supabase()
    lead_res = sb.table("leads").select("*").eq("id", lead_id).limit(1).execute()
    if not lead_res.data:
        raise HTTPException(status_code=404, detail="Lead not found")
    session_id = lead_res.data[0]["session_id"]

    sess_res = (
        sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    )
    session = sess_res.data[0] if sess_res.data else None
    if not session or session.get("store_id") != store["id"]:
        raise HTTPException(status_code=404, detail="Quote request not found for this store")

    job_id = generate.enqueue_render_for_session(background, session)
    return {"job_id": job_id}
