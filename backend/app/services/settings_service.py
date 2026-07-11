"""Global studio settings, editable from the admin panel.

Backed by the single-row `app_settings` table. Values fall back to the env
defaults in `app.config.settings` when the row is missing a column. A short
in-process cache avoids a DB hit on every conversation turn / limit check;
`update_settings` and `invalidate_cache` clear it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.config import settings
from app.db import get_supabase

_TTL_SECONDS = 30.0
_cache: dict = {"value": None, "ts": 0.0}


@dataclass
class StudioSettings:
    regen_edits_per_session: int
    designs_per_customer_per_day: int
    faq_knowledge: str


def _read_row() -> dict:
    """Return the single app_settings row as a dict (empty dict if absent)."""
    res = get_supabase().table("app_settings").select("*").eq("id", 1).limit(1).execute()
    return res.data[0] if res.data else {}


def _from_row(row: dict) -> StudioSettings:
    return StudioSettings(
        regen_edits_per_session=int(
            row.get("regen_edits_per_session", settings.regen_edits_per_session)
        ),
        designs_per_customer_per_day=int(
            row.get("designs_per_customer_per_day", settings.designs_per_customer_per_day)
        ),
        faq_knowledge=row.get("faq_knowledge") or "",
    )


def invalidate_cache() -> None:
    _cache["value"] = None
    _cache["ts"] = 0.0


def get_settings() -> StudioSettings:
    now = time.monotonic()
    if _cache["value"] is not None and (now - _cache["ts"]) < _TTL_SECONDS:
        return _cache["value"]
    value = _from_row(_read_row())
    _cache["value"] = value
    _cache["ts"] = now
    return value


def update_settings(
    *,
    regen_edits_per_session: int | None = None,
    designs_per_customer_per_day: int | None = None,
    faq_knowledge: str | None = None,
) -> StudioSettings:
    """Patch the single row with the provided fields, then invalidate the cache."""
    patch: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if regen_edits_per_session is not None:
        patch["regen_edits_per_session"] = int(regen_edits_per_session)
    if designs_per_customer_per_day is not None:
        patch["designs_per_customer_per_day"] = int(designs_per_customer_per_day)
    if faq_knowledge is not None:
        patch["faq_knowledge"] = faq_knowledge
    get_supabase().table("app_settings").update(patch).eq("id", 1).execute()
    invalidate_cache()
    return get_settings()
