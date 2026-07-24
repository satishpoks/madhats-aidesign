"""Generation watchdog — admin-triggered self-heal for stalled renders.

Generation is decoupled and non-blocking (the request returns a job_id
immediately; the worker renders in the background and delivery emails the design
when it's ready). But the provider call has no timeout, so a hung upstream
connection can pin a job at 'pending' forever — never produced, never delivered.

This route sweeps such jobs: it marks them failed and re-enqueues a fresh
generation (bounded per session) so the design still gets produced and
delivered. Intended to be invoked by an external scheduler (a cron hitting this
endpoint periodically) or manually by ops. Gated by X-Admin-Secret like the rest
of `/admin/*`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.api.deps import AdminContext, require_admin_ctx, require_super
from app.api.routes import generate
from app.db import get_supabase

router = APIRouter(tags=["admin-generations"], dependencies=[Depends(require_admin_ctx)])

# Operational job fields surfaced to the admin panel. Deliberately excludes
# prompt / raw_response / collected / lead details — this is a triage view, not
# an audit dump (that's /admin/generation-logs), and must carry no customer PII.
_JOB_FIELDS = (
    "job_id", "session_id", "tier", "status", "model",
    "error", "attempts", "created_at",
)


def _parse_created(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@router.get("/admin/generations")
async def list_generations(
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    stuck_minutes: int = generate.STUCK_MINUTES_DEFAULT,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    """List recent generation jobs + status for the Ops panel.

    Read-only triage view: newest-first, optionally filtered by ``status``.
    A job is ``stalled`` when it is still ``pending`` past ``stuck_minutes``
    (the same threshold the watchdog reaps at). ``summary`` counts are computed
    over the returned window so the tiles reflect exactly what the table shows.

    A non-super store admin only sees jobs whose session belongs to one of
    their assigned stores (``generations`` has no store_id column of its own —
    resolved via ``design_sessions``).
    """
    sb = get_supabase()
    q = sb.table("generations").select(",".join(_JOB_FIELDS))
    if status:
        q = q.eq("status", status)
    rows = q.order("created_at", desc=True).limit(limit).execute().data or []

    if not ctx.is_super:
        allowed = ctx.allowed_store_ids or set()
        if not allowed:
            rows = []
        else:
            session_ids = [r.get("session_id") for r in rows if r.get("session_id")]
            store_by_session: dict[str, str | None] = {}
            if session_ids:
                sess_res = (
                    sb.table("design_sessions")
                    .select("id, store_id")
                    .in_("id", session_ids)
                    .execute()
                )
                store_by_session = {s["id"]: s.get("store_id") for s in (sess_res.data or [])}
            rows = [r for r in rows if store_by_session.get(r.get("session_id")) in allowed]

    now = datetime.now(timezone.utc)
    cutoff_seconds = stuck_minutes * 60
    summary = {"pending": 0, "stalled": 0, "failed": 0, "complete": 0}
    items = []
    for r in rows:
        created = _parse_created(r.get("created_at"))
        age = int((now - created).total_seconds()) if created else 0
        st = r.get("status")
        stalled = st == "pending" and age >= cutoff_seconds
        if st in summary:
            summary[st] += 1
        if stalled:
            summary["stalled"] += 1
        items.append({field: r.get(field) for field in _JOB_FIELDS} | {
            "age_seconds": age,
            "stalled": stalled,
        })

    return {"summary": summary, "stuck_minutes": stuck_minutes, "items": items}


@router.post("/admin/generations/reap-stuck")
async def reap_stuck_generations(
    background: BackgroundTasks,
    stuck_minutes: int = generate.STUCK_MINUTES_DEFAULT,
    limit: int = 50,
    ctx: AdminContext = Depends(require_admin_ctx),
) -> dict:
    """Cross-store self-heal sweep — super admin only."""
    require_super(ctx)
    return await generate.reap_stuck_generations(
        background=background, stuck_minutes=stuck_minutes, limit=limit
    )
