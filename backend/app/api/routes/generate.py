from __future__ import annotations

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.deps import limiter
from app.config import settings
from app.db import get_supabase
from app.models.generation import GenerateRequest, GenerationStatus, JobResponse
from app.services import generation_cache, prompt_builder
from app.services.image.router import get_provider
from app.services.moderation import ModerationError, check_text
from app.services.watermark import apply_watermark
from app.storage import generate_signed_url, write_watermarked

router = APIRouter(tags=["generate"])
log = structlog.get_logger()


@router.post("/generate/preview/{session_id}", response_model=JobResponse)
@limiter.limit(settings.rate_limit_str)
async def generate_preview(
    session_id: str, body: GenerateRequest, request: Request, background: BackgroundTasks
) -> JobResponse:
    return await _start_generation(session_id, "preview", background)


@router.post("/generate/final/{session_id}", response_model=JobResponse)
@limiter.limit(settings.rate_limit_str)
async def generate_final(
    session_id: str, body: GenerateRequest, request: Request, background: BackgroundTasks
) -> JobResponse:
    return await _start_generation(session_id, "final", background)


async def _start_generation(session_id: str, tier: str, background: BackgroundTasks) -> JobResponse:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sess.data[0]

    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}

    if not product_ref.get("reference_image_url"):
        raise HTTPException(status_code=400, detail="Session has no product reference image")

    params = prompt_builder.build_params(collected, tier)
    try:
        prompt = prompt_builder.build_prompt(collected, product_ref, params)
    except prompt_builder.PromptBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # moderation on the assembled design intent before any model call
    try:
        await check_text(prompt)
    except ModerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = (
        sb.table("generations")
        .insert(
            {
                "session_id": session_id,
                "tier": tier,
                "model": "pending",
                "status": "pending",
            }
        )
        .execute()
    )
    job_id = job.data[0]["job_id"]

    background.add_task(
        _run_generation,
        job_id=job_id,
        tier=tier,
        prompt=prompt,
        product_ref=product_ref,
        collected=collected,
        params=params,
    )
    return JobResponse(job_id=job_id)


async def _run_generation(*, job_id, tier, prompt, product_ref, collected, params) -> None:
    """Background worker: cache-check → provider → watermark → store → update row."""
    sb = get_supabase()
    p_hash = prompt_builder.prompt_hash(prompt)
    asset_hash = collected.get("asset_hash", "none")
    key = generation_cache.cache_key(
        product_ref.get("product_id", ""), product_ref.get("colour", ""), p_hash, asset_hash
    )

    try:
        cached = generation_cache.lookup(key)
        if cached:
            sb.table("generations").update(
                {
                    "status": "complete",
                    "model": cached["model"],
                    "image_url": cached["image_url"],
                    "watermarked_url": cached["watermarked_url"],
                    "prompt_hash": key,
                    "cost_usd": 0,
                    "latency_ms": 0,
                }
            ).eq("job_id", job_id).execute()
            return

        provider = get_provider(tier)
        uploaded_path = collected.get("uploaded_asset_path")
        uploaded_url = generate_signed_url(uploaded_path) if uploaded_path else None

        result = await provider.generate(
            prompt=prompt,
            reference_image_url=product_ref["reference_image_url"],
            uploaded_asset_url=uploaded_url,
            params=params,
        )

        clean_path = result.image_url  # storage path (or external stub URL)
        watermarked_path = _make_watermarked(clean_path)

        sb.table("generations").update(
            {
                "status": "complete",
                "model": result.model,
                "image_url": clean_path,
                "watermarked_url": watermarked_path,
                "prompt_hash": key,
                "cost_usd": result.cost_usd,
                "latency_ms": result.latency_ms,
            }
        ).eq("job_id", job_id).execute()
        log.info("generation_complete", tier=tier, model=result.model, latency_ms=result.latency_ms)

    except Exception as exc:  # noqa: BLE001
        log.error("generation_failed", tier=tier, error=str(exc))
        sb.table("generations").update({"status": "failed"}).eq("job_id", job_id).execute()


def _make_watermarked(clean_path: str) -> str | None:
    """Fetch the clean image, watermark it, store it; return the watermarked storage path."""
    try:
        if clean_path.startswith("http"):
            resp = httpx.get(clean_path, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            image_bytes = resp.content
        else:
            signed = generate_signed_url(clean_path)
            resp = httpx.get(signed, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            image_bytes = resp.content
        stamped = apply_watermark(image_bytes)
        return write_watermarked(stamped)
    except Exception as exc:  # noqa: BLE001
        log.warning("watermark_failed", error=str(exc))
        return None


@router.get("/generate/status/{job_id}", response_model=GenerationStatus)
async def generation_status(job_id: str) -> GenerationStatus:
    sb = get_supabase()
    res = sb.table("generations").select("*").eq("job_id", job_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    row = res.data[0]

    image_url = _to_signed(row.get("image_url"))
    watermarked_url = _to_signed(row.get("watermarked_url"))

    return GenerationStatus(
        status=row["status"],
        image_url=image_url,
        watermarked_url=watermarked_url,
    )


def _to_signed(path: str | None) -> str | None:
    """Return a signed URL for a storage path; pass through external stub URLs."""
    if not path:
        return None
    if path.startswith("http"):
        return path
    return generate_signed_url(path)
