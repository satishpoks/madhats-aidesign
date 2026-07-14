"""Public storefront config for the customer widget. Resolved via X-Store-Key.
Returns ONLY the public branding subset — never secrets or internal fields."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.config import settings
from app.services.branding import public_brand

router = APIRouter(tags=["storefront"])


@router.get("/storefront")
async def get_storefront(request: Request, store: dict = Depends(require_store)) -> dict:
    return {
        "name": store.get("name") or "",
        "persona_name": store.get("persona_name") or settings.chatbot_persona_name,
        "brand": public_brand(store.get("brand"), str(request.base_url)),
    }
