"""Admin decoration-type management. Gated by X-Admin-Secret + X-Store-Key."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_admin, require_store
from app.models.decoration_type import DecorationTypeAdmin
from app.services import decoration_types as svc

router = APIRouter(tags=["admin-decoration-types"], dependencies=[Depends(require_admin)])
log = structlog.get_logger()


class CreateDecorationTypeBody(BaseModel):
    name: str


def _to_admin(row: dict) -> dict:
    return {
        "id": row["id"],
        "name": row.get("name") or "",
        "active": bool(row.get("active", True)),
        "sort_order": row.get("sort_order", 0),
    }


@router.get("/admin/decoration-types", response_model=list[DecorationTypeAdmin])
async def list_decoration_types(store: dict = Depends(require_store)) -> list[dict]:
    return [_to_admin(r) for r in svc.list_types(store["id"])]


@router.post("/admin/decoration-types", response_model=DecorationTypeAdmin)
async def create_decoration_type(
    body: CreateDecorationTypeBody, store: dict = Depends(require_store)
) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    row = svc.create_type(store["id"], name)
    log.info("decoration_type_created", store_id=store["id"])  # no PII
    return _to_admin(row)


@router.delete("/admin/decoration-types/{type_id}")
async def delete_decoration_type(
    type_id: str, store: dict = Depends(require_store)
) -> dict:
    svc.delete_type(type_id)
    return {"deleted": True}
