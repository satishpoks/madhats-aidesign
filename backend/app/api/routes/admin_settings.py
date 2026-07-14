"""Global studio settings, editable from the admin panel. Gated by X-Admin-Secret."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.services import settings_service

router = APIRouter(tags=["admin-settings"], dependencies=[Depends(require_admin)])


class SettingsOut(BaseModel):
    regen_edits_per_session: int
    designs_per_customer_per_day: int
    faq_knowledge: str
    watermark_text: str


class SettingsPatch(BaseModel):
    regen_edits_per_session: int | None = Field(default=None, ge=0)
    designs_per_customer_per_day: int | None = Field(default=None, ge=0)
    faq_knowledge: str | None = None
    watermark_text: str | None = Field(default=None, max_length=60)


def _out(s: settings_service.StudioSettings) -> SettingsOut:
    return SettingsOut(
        regen_edits_per_session=s.regen_edits_per_session,
        designs_per_customer_per_day=s.designs_per_customer_per_day,
        faq_knowledge=s.faq_knowledge,
        watermark_text=s.watermark_text,
    )


@router.get("/admin/settings", response_model=SettingsOut)
async def get_settings() -> SettingsOut:
    return _out(settings_service.get_settings())


@router.patch("/admin/settings", response_model=SettingsOut)
async def patch_settings(body: SettingsPatch) -> SettingsOut:
    updated = settings_service.update_settings(**body.model_dump(exclude_none=True))
    return _out(updated)
