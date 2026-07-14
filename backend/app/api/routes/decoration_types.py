"""Customer-facing decoration-type list (tenant-scoped via X-Store-Key)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import require_store
from app.models.decoration_type import DecorationTypePublic
from app.services import decoration_types as svc

router = APIRouter(tags=["decoration-types"])


@router.get("/decoration-types", response_model=list[DecorationTypePublic])
async def list_decoration_types(store: dict = Depends(require_store)) -> list[dict]:
    return [
        {"id": r["id"], "name": r.get("name") or ""}
        for r in svc.list_types(store["id"], active_only=True)
    ]
