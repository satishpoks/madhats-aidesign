"""Public storefront config for the customer widget. Resolved via X-Store-Key.
Returns ONLY the public branding subset — never secrets or internal fields."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.config import settings
from app.services import settings_service
from app.services.branding import public_brand

router = APIRouter(tags=["storefront"])


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
        "watermark_text": settings_service.get_settings().watermark_text,
    }
