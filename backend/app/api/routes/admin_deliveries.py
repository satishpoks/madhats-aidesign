"""Delivery backfill/retry sweep — admin-triggered self-heal.

`delivery.maybe_send_preview` is invoked by both async tracks (generation
completion and email verification), but if the send itself failed on both
occasions (e.g. a Resend outage at that moment), nothing else re-triggers
delivery. This route re-sweeps verified-but-undelivered leads and retries.

Intended to be invoked by an external scheduler (e.g. a Railway cron hitting
this endpoint periodically) or manually by ops. Gated by X-Admin-Secret like
the rest of `/admin/*`.
"""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from app.api.deps import require_admin
from app.services import delivery

router = APIRouter(tags=["admin-deliveries"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


@router.post("/admin/deliveries/backfill")
async def backfill_deliveries(limit: int = 100, max_age_hours: int = 72) -> dict:
    return delivery.backfill_pending(limit=limit, max_age_hours=max_age_hours)
