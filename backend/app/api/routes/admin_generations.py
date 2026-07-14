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

from fastapi import APIRouter, BackgroundTasks, Depends

from app.api.deps import require_admin
from app.api.routes import generate

router = APIRouter(tags=["admin-generations"], dependencies=[Depends(require_admin)])


@router.post("/admin/generations/reap-stuck")
async def reap_stuck_generations(
    background: BackgroundTasks,
    stuck_minutes: int = generate.STUCK_MINUTES_DEFAULT,
    limit: int = 50,
) -> dict:
    return await generate.reap_stuck_generations(
        background=background, stuck_minutes=stuck_minutes, limit=limit
    )
