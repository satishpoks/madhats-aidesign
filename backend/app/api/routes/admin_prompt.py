"""Prompt-preview debug endpoint — returns the exact image-generation prompt for
a session WITHOUT calling the model or incurring cost.

Makes tuning the fidelity-locked prompt fast: edit templates in `app.prompts`,
hit this route, and read the exact string that would be sent to Gemini. Gated by
X-Admin-Secret like the rest of `/admin/*`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import require_admin
from app.config import settings
from app.db import get_supabase
from app.services import prompt_builder
from app.services.image.router import get_provider

router = APIRouter(tags=["admin-prompt"], dependencies=[Depends(require_admin)])

# Best-effort model label per tier when the provider doesn't expose model_name
# (e.g. the stub adapter).
_MODEL_BY_TIER = {
    "preview": settings.gemini_preview_model,
    "final": settings.gemini_final_model,
}


@router.get("/admin/prompt-preview/{session_id}")
async def prompt_preview(session_id: str, tier: str = "preview") -> dict:
    if tier not in ("preview", "final"):
        raise HTTPException(status_code=400, detail="tier must be 'preview' or 'final'")

    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = res.data[0]

    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}
    if not product_ref.get("reference_image_url"):
        raise HTTPException(status_code=400, detail="Session has no product reference image")

    params = prompt_builder.build_params(collected, tier)
    try:
        prompt = prompt_builder.build_prompt(collected, product_ref, params)
    except prompt_builder.PromptBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    provider = get_provider(tier)
    model = getattr(provider, "model_name", None) or _MODEL_BY_TIER.get(tier)

    return {
        "session_id": session_id,
        "tier": tier,
        "provider": type(provider).__name__,
        "model": model,
        "reference_image_url": product_ref.get("reference_image_url"),
        "has_uploaded_asset": bool(collected.get("uploaded_asset_path")),
        "prompt": prompt,
    }
