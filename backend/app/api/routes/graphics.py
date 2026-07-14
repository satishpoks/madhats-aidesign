"""Customer-facing graphics library (tenant-scoped via X-Store-Key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.models.graphics import GRAPHIC_CATEGORIES, GraphicPublic
from app.services import graphics as svc
from app.storage import media_url

router = APIRouter(tags=["graphics"])


@router.get("/graphics", response_model=list[GraphicPublic])
async def list_graphics(
    request: Request, category: str | None = None, store: dict = Depends(require_store)
) -> list[dict]:
    cat = category if category in GRAPHIC_CATEGORIES else None
    base = str(request.base_url)
    out = []
    for row in svc.list_graphics(store["id"], category=cat, active_only=True):
        url = media_url(row["storage_path"], base)
        if not url:
            continue
        out.append({"id": row["id"], "category": row["category"], "name": row.get("name") or "", "url": url})
    return out
