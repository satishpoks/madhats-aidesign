"""Admin center: confirmed quote requests.

Lists leads that explicitly requested a quote via the emailed quote link
(quote_confirmed = true) — the "customer likes the design and wants a quote"
signal — enriched with a compact design/session summary. Gated by X-Admin-Secret.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_admin
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
