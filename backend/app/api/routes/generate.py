import asyncio
from dataclasses import asdict

import httpx
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.deps import limiter
from app.config import settings
from app.db import get_supabase
from app.models.generation import GenerateRequest, GenerationStatus, JobResponse
from app.services import delivery
from app.services import design_summary
from app.services import email as email_service
from app.services import generation_cache, generation_logger, prompt_builder
from app.services.image.router import get_provider
from app.services.moderation import ModerationError, check_text
from app.services.stores import get_store
from app.services.watermark import apply_watermark
from app.storage import generate_signed_url, write_watermarked

router = APIRouter(tags=["generate"])
log = structlog.get_logger()

# Google's client libraries may not be installed in every environment (e.g. the
# stub-only local/test setup). Import defensively so exception classification
# below degrades gracefully instead of failing to import.
try:
    from google.api_core.exceptions import GoogleAPICallError, ResourceExhausted
except ImportError:  # pragma: no cover - google-api-core not installed
    GoogleAPICallError = None  # type: ignore[assignment,misc]
    ResourceExhausted = None  # type: ignore[assignment,misc]

MAX_GENERATION_ATTEMPTS = 3
# Backoff between attempts: ~2s after attempt 1, ~8s after attempt 2 (capped).
_BACKOFF_SECONDS = (2, 8)


def _is_transient(exc: Exception) -> bool:
    """Classify a provider exception as transient (retry) vs permanent (fail fast).

    Retryable: httpx timeouts, google ResourceExhausted (429), and any
    GoogleAPICallError carrying a 5xx status code. Everything else — ValueError,
    InvalidArgument/400, or any exception type we don't recognise — is treated
    as permanent and is NOT retried.
    """
    if isinstance(exc, httpx.TimeoutException):
        return True
    if ResourceExhausted is not None and isinstance(exc, ResourceExhausted):
        return True
    if GoogleAPICallError is not None and isinstance(exc, GoogleAPICallError):
        code = getattr(exc, "code", None)
        code_value = getattr(code, "value", code)
        return isinstance(code_value, int) and 500 <= code_value < 600
    # Fallback for plain exceptions carrying an HTTP-style status_code attribute.
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and 500 <= status < 600


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


@router.post("/generate/regenerate/{session_id}", response_model=JobResponse)
@limiter.limit(settings.rate_limit_str)
async def generate_regenerate(
    session_id: str, body: GenerateRequest, request: Request, background: BackgroundTasks
) -> JobResponse:
    """Regenerate the design with the customer's latest requested change.

    Same pipeline as preview, but tagged tier='edit' and the prompt includes
    collected['last_change']. Caps are enforced in _start_generation (Task 11).
    """
    return await _start_generation(session_id, "edit", background)


def _session_lead_email(session_id: str) -> str | None:
    res = (
        get_supabase()
        .table("leads")
        .select("email")
        .eq("session_id", session_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0]["email"] if res.data else None


async def _start_generation(session_id: str, tier: str, background: BackgroundTasks) -> JobResponse:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sess.data[0]

    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}

    if tier == "edit" and collected.get("last_change"):
        # Layer the requested change onto the existing design intent so the edit
        # modifies rather than replaces the design. build_params/build_prompt
        # already consume collected; surface the change as an extra instruction.
        collected = {**collected, "change_request": collected["last_change"]}

    if not product_ref.get("reference_image_url"):
        raise HTTPException(status_code=400, detail="Session has no product reference image")

    from app.services import limits  # noqa: PLC0415

    # Per-customer/day cap for NEW designs (not edits). Uses the session's lead
    # email if one exists yet.
    lead_email = _session_lead_email(session_id)
    if tier != "edit" and not limits.can_start_design(lead_email):
        raise HTTPException(status_code=429, detail="daily_design_limit")
    if tier == "edit" and not limits.can_edit(session_id):
        raise HTTPException(status_code=429, detail="edit_limit")

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
    generation_id = job.data[0].get("id")

    # get_provider() only knows the real adapter tiers (preview/final); an edit
    # reuses the preview adapter while the generations row still records
    # tier='edit' so downstream reporting (and Task 11's cap enforcement) can
    # distinguish edits from fresh previews.
    provider_tier = "preview" if tier == "edit" else tier

    background.add_task(
        _run_generation,
        job_id=job_id,
        generation_id=generation_id,
        session_id=session_id,
        store_id=session.get("store_id"),
        tier=tier,
        provider_tier=provider_tier,
        prompt=prompt,
        product_ref=product_ref,
        collected=collected,
        params=params,
    )
    return JobResponse(job_id=job_id)


async def _run_generation(
    *, job_id, session_id, store_id, tier, prompt, product_ref, collected, params,
    generation_id=None, provider_tier=None,
) -> None:
    """Background worker: cache-check → provider (with retry) → watermark → store → update row.

    Generation and email verification are independent async tracks (see
    docs/superpowers/specs/2026-07-01-decoupled-generation-gated-delivery-design.md
    §4.2-4.3). On success this calls `delivery.maybe_send_preview` so a design
    whose email was already verified is delivered immediately. On final failure
    (retries exhausted or a permanent error) it marks the row failed and alerts
    ops so a human can regenerate — the customer is never shown a failure.
    """
    provider_tier = provider_tier or tier
    sb = get_supabase()
    p_hash = prompt_builder.prompt_hash(prompt)
    asset_hash = collected.get("asset_hash", "none")
    key = generation_cache.cache_key(
        product_ref.get("product_id", ""), product_ref.get("colour", ""), p_hash, asset_hash
    )
    attempts = 0

    # Inputs recorded in every generation_logs row (references, not bytes).
    ref_url = product_ref.get("reference_image_url")
    uploaded_path = collected.get("uploaded_asset_path")
    uploaded_url = generate_signed_url(uploaded_path) if uploaded_path else None
    params_dict = asdict(params)

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
            generation_logger.log_cache_hit(
                generation_id=generation_id,
                job_id=job_id,
                session_id=session_id,
                tier=tier,
                reference_image_url=ref_url,
                uploaded_asset_url=uploaded_url,
                full_prompt=prompt,
                params=params_dict,
                model=cached["model"],
                output_image_url=cached["image_url"],
            )
            _safe_maybe_send_preview(session_id)
            return

        provider = get_provider(provider_tier)

        result = None
        last_exc: Exception | None = None
        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            attempts = attempt
            # Record the inputs + full prompt BEFORE the call so a crash still
            # leaves a 'requested' row; the response is patched in afterwards.
            log_id = generation_logger.log_request(
                generation_id=generation_id,
                job_id=job_id,
                session_id=session_id,
                attempt=attempt,
                tier=tier,
                reference_image_url=ref_url,
                uploaded_asset_url=uploaded_url,
                full_prompt=prompt,
                params=params_dict,
            )
            try:
                result = await provider.generate(
                    prompt=prompt,
                    reference_image_url=product_ref["reference_image_url"],
                    uploaded_asset_url=uploaded_url,
                    params=params,
                )
                last_exc = None
                generation_logger.log_response(
                    log_id,
                    status="complete",
                    model=result.model,
                    output_image_url=result.image_url,
                    response_meta=result.response_meta,
                    raw_response=result.raw_response,
                    latency_ms=result.latency_ms,
                )
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                generation_logger.log_response(log_id, status="failed", error=str(exc))
                if attempt >= MAX_GENERATION_ATTEMPTS or not _is_transient(exc):
                    break
                backoff = _BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)]
                log.warning(
                    "generation_retrying",
                    tier=tier,
                    attempt=attempt,
                    error_type=type(exc).__name__,
                )
                await asyncio.sleep(backoff)

        if last_exc is not None:
            raise last_exc

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
                "attempts": attempts,
            }
        ).eq("job_id", job_id).execute()
        log.info(
            "generation_complete",
            tier=tier,
            model=result.model,
            latency_ms=result.latency_ms,
            attempts=attempts,
        )

        _safe_maybe_send_preview(session_id)

    except Exception as exc:  # noqa: BLE001
        log.error(
            "generation_failed",
            tier=tier,
            error_type=type(exc).__name__,
            attempts=attempts,
        )
        sb.table("generations").update(
            {"status": "failed", "error": str(exc), "attempts": attempts}
        ).eq("job_id", job_id).execute()
        _send_ops_alert(session_id, store_id, product_ref, collected, str(exc))


def _safe_maybe_send_preview(session_id: str) -> None:
    """Trigger the gated delivery primitive after a successful generation.

    Wrapped in its own try/except: a delivery error (email provider outage,
    unexpected DB shape, etc.) must NEVER flip a just-completed generation row
    back to failed. The generation itself already succeeded; delivery is a
    best-effort side effect layered on top.
    """
    try:
        delivery.maybe_send_preview(session_id)
    except Exception as exc:  # noqa: BLE001
        log.error(
            "post_generation_delivery_failed", session_id=session_id, error_type=type(exc).__name__
        )


def _send_ops_alert(
    session_id: str, store_id: str | None, product_ref: dict, collected: dict, error_text: str
) -> None:
    """Notify the store's ops inbox that a design needs manual regeneration.

    Logs session_id only — never product/brief/customer details — even though
    the email body itself may reference business context for the ops team.
    """
    try:
        store = get_store(store_id) if store_id else None
        to = (store or {}).get("sales_notification_email") or settings.sales_notification_email
        product_name = product_ref.get("name") or "Custom cap"
        # Prefer the per-element brief (collected["elements"]) — the flat
        # design_description.summary is a fallback for legacy/no-key sessions
        # that never populated elements (design_summary.summarise_elements
        # already falls back to it internally).
        brief = (
            design_summary.summarise_elements(collected)
            or collected.get("design_summary")
            or "No description provided"
        )
        email_service.send_generation_alert(to, session_id, product_name, brief, error_text)
        log.info("generation_alert_sent", session_id=session_id)
    except Exception as exc:  # noqa: BLE001
        log.error("generation_alert_failed", session_id=session_id, error_type=type(exc).__name__)


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
