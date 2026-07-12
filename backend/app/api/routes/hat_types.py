"""Customer-facing blank-hat catalogue (tenant-scoped via X-Store-Key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.models.hat_type import HatTypePublic
from app.services import hat_types as svc
from app.storage import media_url

router = APIRouter(tags=["hat-types"])


@router.get("/hat-types", response_model=list[HatTypePublic])
async def list_hat_types(request: Request, store: dict = Depends(require_store)) -> list[dict]:
    base = str(request.base_url)
    out = []
    for row in svc.list_hat_types(store["id"], active_only=True):
        imgs = row.get("blank_view_images") or {}
        out.append({
            "id": row["id"], "slug": row["slug"], "name": row["name"], "style": row.get("style", ""),
            "view_images": {v: media_url(p, base) for v, p in imgs.items() if p},
            "colours": row.get("colours") or [],
            "placement_zones": row.get("placement_zones") or [],
            "decoration_types": row.get("decoration_types") or [],
        })
    return out
