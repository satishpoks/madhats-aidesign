"""Public storefront config for the customer widget. Resolved via X-Store-Key.
Returns ONLY the public branding subset — never secrets or internal fields."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.config import settings
from app.services import settings_service
from app.services.branding import public_brand
from app.services.watermark import _DEFAULT_TEXT as DEFAULT_WATERMARK_TEXT

router = APIRouter(tags=["storefront"])
log = structlog.get_logger()


def _watermark_text() -> str:
    """The canvas watermark string — best-effort, never fatal.

    `settings_service.get_settings()` reads the single `app_settings` row and
    does NOT catch, so a missing row or an unreachable database would 500 the
    customer widget's very first call — a hot path that previously needed only
    the `stores` read `require_store` already performs — for a decorative string
    that has a perfectly good default. `brandStore.init` swallows the failure,
    so the visible effect would be a studio with no branding at all.

    Falls back to the same literal `services/watermark.py` stamps into the
    emailed previews, so canvas and email still agree when settings are down.
    """
    try:
        return settings_service.get_settings().watermark_text
    except Exception as exc:  # noqa: BLE001 — branding must never break the widget
        log.warning("storefront_settings_unavailable", error=type(exc).__name__)
        return DEFAULT_WATERMARK_TEXT


@router.get("/storefront")
async def get_storefront(request: Request, store: dict = Depends(require_store)) -> dict:
    return {
        "name": store.get("name") or "",
        "persona_name": store.get("persona_name") or settings.chatbot_persona_name,
        "brand": public_brand(store.get("brand"), str(request.base_url)),
        # Global app setting (app_settings), not a per-store brand field — so it
        # is returned top-level rather than through public_brand's brand
        # allow-list. The canvas draws this over the design from the review
        # onward; delivery.py already burns the same string into the emailed
        # previews server-side, so both surfaces stay in step.
        "watermark_text": _watermark_text(),
    }
