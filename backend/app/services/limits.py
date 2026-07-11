"""AI-usage caps. Two dimensions:

- Per-session regeneration edits (`can_edit`): first design is free; then
  `regen_edits_per_session` modify-and-regenerate attempts.
- Per-customer/day designs (`can_start_design`): at most
  `designs_per_customer_per_day` NEW (non-edit) designs per verified email in a
  rolling 24h window. Edits do not count toward the daily cap.

PII safety: emails are used for lookups only, never logged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db import get_supabase
from app.services import settings_service


def edit_count(session_id: str) -> int:
    """Number of regeneration ('edit') generations recorded for this session."""
    res = (
        get_supabase()
        .table("generations")
        .select("id", count="exact")
        .eq("session_id", session_id)
        .eq("tier", "edit")
        .limit(1)
        .execute()
    )
    return res.count or 0


def can_edit(session_id: str) -> bool:
    return edit_count(session_id) < settings_service.get_settings().regen_edits_per_session


def _session_ids_for_email(email: str) -> list[str]:
    res = get_supabase().table("leads").select("session_id").eq("email", email).execute()
    return [r["session_id"] for r in (res.data or []) if r.get("session_id")]


def designs_today(email: str) -> int:
    """Count NEW (non-edit) generations across this email's sessions in 24h."""
    session_ids = _session_ids_for_email(email)
    if not session_ids:
        return 0
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    res = (
        get_supabase()
        .table("generations")
        .select("id", count="exact")
        .in_("session_id", session_ids)
        .neq("tier", "edit")
        .gte("created_at", cutoff)
        .limit(1)
        .execute()
    )
    return res.count or 0


def can_start_design(email: str | None) -> bool:
    """True if a NEW design may be generated for this customer right now.

    No email yet (can't attribute) -> allowed; the next attributable attempt is
    counted then.
    """
    if not email:
        return True
    return designs_today(email) < settings_service.get_settings().designs_per_customer_per_day
