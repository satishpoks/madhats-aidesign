import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

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

# Watchdog: a generation still 'pending' this long has stalled (a normal render
# is seconds; the provider call has no timeout, so a hung upstream connection can
# otherwise pin a job at 'pending' forever). Set comfortably above the slowest
# real render so a merely-slow job isn't reaped (reaping is non-destructive — the
# original can still complete and delivery dedupes — but a false reap wastes a
# render). Reaped jobs are re-enqueued up to MAX_STALL_RETRIES times per session,
# then ops is alerted. Configurable per-call via the ?stuck_minutes= query param.
STUCK_MINUTES_DEFAULT = 8
MAX_STALL_RETRIES = 2
_STALL_ERROR_PREFIX = "stalled:"


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

    if tier == "edit":
        # Layer the requested change onto the existing design intent so the edit
        # modifies rather than replaces the design. Compile every captured
        # refinement instruction (description + follow-up answers + "anything
        # else") into one change_request; fall back to the single last_change.
        details = [str(d).strip() for d in (collected.get("refine_details") or []) if str(d).strip()]
        change = " ; ".join(details) or collected.get("last_change")
        if change:
            collected = {**collected, "change_request": change}

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


async def _render_view(
    *, view, provider, job_id, generation_id, session_id, tier,
    prompt, ref_url, uploaded_url, params, params_dict, key, prior_design_url=None,
    layout_guide_url=None,
) -> dict:
    """Render ONE view: cache-check → provider (with retry) → watermark.

    Never raises — always returns a result dict:
      success: {"ok": True, view, clean_path, watermarked_path, model,
                cost_usd, latency_ms, key, attempts, from_cache}
      failure: {"ok": False, view, error, attempts}
    so the caller can enforce all-or-nothing across the whole view set.
    """
    cached = generation_cache.lookup(key)
    if cached:
        generation_logger.log_cache_hit(
            generation_id=generation_id, job_id=job_id, session_id=session_id,
            tier=tier, reference_image_url=ref_url, uploaded_asset_url=uploaded_url,
            full_prompt=prompt, params=params_dict, model=cached["model"],
            output_image_url=cached["image_url"],
        )
        return {
            "ok": True, "view": view, "clean_path": cached["image_url"],
            "watermarked_path": cached.get("watermarked_url"), "model": cached["model"],
            "cost_usd": 0, "latency_ms": 0, "key": key, "attempts": 0, "from_cache": True,
        }

    result = None
    last_exc: Exception | None = None
    attempts = 0
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempts = attempt
        # Record the inputs + full prompt BEFORE the call so a crash still
        # leaves a 'requested' row; the response is patched in afterwards.
        log_id = generation_logger.log_request(
            generation_id=generation_id, job_id=job_id, session_id=session_id,
            attempt=attempt, tier=tier, reference_image_url=ref_url,
            uploaded_asset_url=uploaded_url, full_prompt=prompt, params=params_dict,
        )
        try:
            result = await provider.generate(
                prompt=prompt, reference_image_url=ref_url,
                uploaded_asset_url=uploaded_url, params=params,
                prior_design_url=prior_design_url,
                layout_guide_url=layout_guide_url,
            )
            last_exc = None
            generation_logger.log_response(
                log_id, status="complete", model=result.model,
                output_image_url=result.image_url, response_meta=result.response_meta,
                raw_response=result.raw_response, latency_ms=result.latency_ms,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            generation_logger.log_response(log_id, status="failed", error=str(exc))
            if attempt >= MAX_GENERATION_ATTEMPTS or not _is_transient(exc):
                break
            backoff = _BACKOFF_SECONDS[min(attempt - 1, len(_BACKOFF_SECONDS) - 1)]
            log.warning(
                "generation_retrying", tier=tier, view=view, attempt=attempt,
                error_type=type(exc).__name__,
            )
            await asyncio.sleep(backoff)

    if last_exc is not None:
        return {"ok": False, "view": view, "error": str(last_exc), "attempts": attempts}

    clean_path = result.image_url  # storage path (or external stub URL)
    watermarked_path = _make_watermarked(clean_path)
    return {
        "ok": True, "view": view, "clean_path": clean_path,
        "watermarked_path": watermarked_path, "model": result.model,
        "cost_usd": result.cost_usd, "latency_ms": result.latency_ms,
        "key": key, "attempts": attempts, "from_cache": False,
    }


async def _run_generation(
    *, job_id, session_id, store_id, tier, prompt, product_ref, collected, params,
    generation_id=None, provider_tier=None,
) -> None:
    """Background worker: render every decorated view → store → update row.

    Multi-view: the design AI-renders the front hero PLUS any back/side view
    that carries decoration (prompt_builder.render_views), each as its own model
    call, fired CONCURRENTLY — including canvas sessions, where each decorated
    face renders with its real product-angle photo (conditioning) plus its
    flattened canvas PNG as a layout guide. Delivery is all-or-nothing — if any
    view fails all its retries, the whole row is marked failed and ops is
    alerted so a human can regenerate the set; the customer is never shown a
    failure. On full success the hero lands in image_url/watermarked_url
    (backward-compatible) and every view is recorded in view_images, then the
    gated delivery primitive fires.

    ``prompt`` (the pre-assembled full-design prompt) is used only for moderation
    upstream in _start_generation; the per-view prompts are built here.
    """
    provider_tier = provider_tier or tier
    sb = get_supabase()
    asset_hash = collected.get("asset_hash", "none")
    uploaded_path = collected.get("uploaded_asset_path")
    uploaded_url_full = generate_signed_url(uploaded_path) if uploaded_path else None
    params_dict = asdict(params)
    is_canvas = collected.get("flow_mode") == "canvas"
    canvas_layouts = collected.get("canvas_layouts") or {}

    # An edit re-renders ONLY the affected views and REFINES from the previous
    # design; a fresh design renders every decorated view. Carry forward the
    # previous render's unaffected views so the delivered set stays complete.
    # A canvas session AI-renders EVERY decorated face (front hero + any
    # decorated back/side), each with its real product-angle photo as the
    # conditioning image and its flattened canvas PNG as the layout guide.
    is_edit = tier == "edit"
    if is_edit:
        views = prompt_builder.affected_render_views(collected)
        prev_gen = _latest_complete_generation(session_id)
        prev_views = _prev_view_map(prev_gen)
    elif is_canvas:
        # Every decorated face is AI-rendered: the front hero PLUS any back/side
        # face carrying decoration (prompt_builder.render_views). Each face's
        # _one() attaches its own reference angle, its flattened canvas PNG as the
        # layout guide, and its per-view scoped description.
        views = prompt_builder.render_views(collected)
        prev_views = {}
    else:
        views = prompt_builder.render_views(collected)
        prev_views = {}

    try:
        provider = get_provider(provider_tier)

        async def _one(view: str) -> dict:
            try:
                view_prompt = prompt_builder.build_view_prompt(collected, product_ref, params, view)
                # Reference angle for this view (blank-hat refs are raw storage
                # paths → sign them; Shopify/stub refs are already http URLs).
                ref = prompt_builder.reference_image_url_for_view(product_ref, view)
                if ref and not ref.startswith("http"):
                    ref = generate_signed_url(ref)
                # Only the view carrying the uploaded logo gets it as a 2nd image.
                uploaded = uploaded_url_full if prompt_builder.view_has_logo(collected, view) else None
                # On an edit, feed this view's PREVIOUS render so the model
                # refines it rather than re-rendering from scratch.
                prior = None
                if is_edit:
                    prev_clean = (prev_views.get(view) or {}).get("image_url")
                    if prev_clean:
                        prior = prev_clean if prev_clean.startswith("http") else generate_signed_url(prev_clean)
                layout_guide = None
                if is_canvas:
                    lg = canvas_layouts.get(view)
                    if lg:
                        layout_guide = lg if lg.startswith("http") else generate_signed_url(lg)
                prompt_for_key = view_prompt
                if is_canvas and canvas_layouts.get(view):
                    # Canvas descriptions are placement-agnostic; without this,
                    # two designs with identical elements but different pixel
                    # layouts collide and one serves the other's render,
                    # discarding the layout guide. The flattened-layout path is
                    # unique per upload, so folding it in makes the key
                    # layout-sensitive.
                    prompt_for_key = f"{view_prompt}\n[layout:{canvas_layouts[view]}]"
                key = generation_cache.cache_key(
                    product_ref.get("product_id", ""), product_ref.get("colour", ""),
                    prompt_builder.prompt_hash(prompt_for_key), asset_hash if uploaded else "none",
                )
                return await _render_view(
                    view=view, provider=provider, job_id=job_id, generation_id=generation_id,
                    session_id=session_id, tier=tier, prompt=view_prompt, ref_url=ref,
                    uploaded_url=uploaded, params=params, params_dict={**params_dict, "view": view},
                    key=key, prior_design_url=prior, layout_guide_url=layout_guide,
                )
            except Exception as exc:  # noqa: BLE001 — never let a build error escape gather
                return {"ok": False, "view": view, "error": str(exc), "attempts": 0}

        results = await asyncio.gather(*[_one(v) for v in views])
        attempts = max((r.get("attempts", 0) for r in results), default=0)

        failures = [r for r in results if not r["ok"]]
        if failures:
            # All-or-nothing: any failed view fails the whole design.
            err = failures[0]["error"]
            log.error("generation_failed", tier=tier, views=len(views), failed=len(failures))
            sb.table("generations").update(
                {"status": "failed", "error": err, "attempts": attempts}
            ).eq("job_id", job_id).execute()
            _send_ops_alert(session_id, store_id, product_ref, collected, err)
            return

        new_views = {
            r["view"]: {"image_url": r["clean_path"], "watermarked_url": r["watermarked_path"]}
            for r in results
        }
        # Carry forward previously-rendered unaffected views (edit only), then
        # overwrite the ones we just re-rendered.
        view_images = {**prev_views, **new_views}
        by_view = {r["view"]: r for r in results}
        anchor = by_view.get(prompt_builder.PRIMARY_VIEW) or results[0]
        hero_entry = view_images.get(prompt_builder.PRIMARY_VIEW) or next(iter(view_images.values()))

        sb.table("generations").update(
            {
                "status": "complete",
                "model": anchor["model"],
                "image_url": hero_entry["image_url"],
                "watermarked_url": hero_entry["watermarked_url"],
                "view_images": view_images,
                "prompt_hash": anchor["key"],
                "cost_usd": sum(r.get("cost_usd") or 0 for r in results),
                "latency_ms": max((r.get("latency_ms") or 0 for r in results), default=0),
                "attempts": attempts,
            }
        ).eq("job_id", job_id).execute()
        log.info(
            "generation_complete", tier=tier, model=anchor["model"], views=len(results),
            total_views=len(view_images), attempts=attempts,
        )

        _safe_maybe_send_preview(session_id)

    except Exception as exc:  # noqa: BLE001
        log.error("generation_failed", tier=tier, error_type=type(exc).__name__)
        sb.table("generations").update(
            {"status": "failed", "error": str(exc)}
        ).eq("job_id", job_id).execute()
        _send_ops_alert(session_id, store_id, product_ref, collected, str(exc))


def _latest_complete_generation(session_id: str) -> dict | None:
    """Most recent completed generation for a session — the design an edit
    refines from and carries unaffected views forward from."""
    res = (
        get_supabase()
        .table("generations")
        .select("*")
        .eq("session_id", session_id)
        .eq("status", "complete")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def _prev_view_map(prev_gen: dict | None) -> dict:
    """The previous generation's per-view images, falling back to its single
    hero for a legacy/single-view row."""
    if not prev_gen:
        return {}
    views = prev_gen.get("view_images") or {}
    if views:
        return dict(views)
    if prev_gen.get("image_url"):
        return {
            "front": {
                "image_url": prev_gen.get("image_url"),
                "watermarked_url": prev_gen.get("watermarked_url"),
            }
        }
    return {}


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


# --- Watchdog: reap stalled generations ------------------------------------

def _count_stalled(session_id: str) -> int:
    """How many times this session's generations have been reaped as stalled."""
    res = (
        get_supabase()
        .table("generations")
        .select("job_id, status, error")
        .eq("session_id", session_id)
        .eq("status", "failed")
        .execute()
    )
    return sum(
        1 for r in (res.data or []) if str(r.get("error") or "").startswith(_STALL_ERROR_PREFIX)
    )


def _enqueue_generation(background: BackgroundTasks, session: dict, tier: str) -> None:
    """Insert a fresh 'pending' row for a session and launch the worker.

    A lean re-enqueue used by the watchdog only: it deliberately skips the
    per-customer caps and moderation `_start_generation` runs — this is a
    system-initiated retry of an already-validated design, not a new request.
    """
    sb = get_supabase()
    product_ref = session.get("product_ref") or {}
    collected = session.get("collected") or {}
    params = prompt_builder.build_params(collected, tier)
    prompt = prompt_builder.build_prompt(collected, product_ref, params)
    job = (
        sb.table("generations")
        .insert({"session_id": session["id"], "tier": tier, "model": "pending", "status": "pending"})
        .execute()
    )
    job_id = job.data[0]["job_id"]
    generation_id = job.data[0].get("id")
    provider_tier = "preview" if tier == "edit" else tier
    background.add_task(
        _run_generation,
        job_id=job_id,
        generation_id=generation_id,
        session_id=session["id"],
        store_id=session.get("store_id"),
        tier=tier,
        provider_tier=provider_tier,
        prompt=prompt,
        product_ref=product_ref,
        collected=collected,
        params=params,
    )


async def reap_stuck_generations(
    *, background: BackgroundTasks, stuck_minutes: int = STUCK_MINUTES_DEFAULT, limit: int = 50
) -> dict:
    """Find generations stuck at 'pending' past ``stuck_minutes`` and unblock them.

    Generation is decoupled and non-blocking (the request returns a job_id
    immediately; the worker renders in the background and the finished design is
    emailed via gated delivery). But the provider call has no timeout, so a hung
    upstream connection can leave a job pinned at 'pending' forever — the design
    is never produced, so it's never delivered and no notification ever fires.

    This watchdog closes that gap. Each stalled job is marked failed; a fresh
    generation is re-enqueued so the design still gets produced and delivered, up
    to ``MAX_STALL_RETRIES`` times per session, after which ops is alerted
    instead (so a persistently-hung provider can't loop). Matches the
    delivery-backfill pattern: an admin endpoint an external cron hits
    periodically; safe to run repeatedly.

    Returns ``{"reaped": int, "retried": int, "gave_up": int}``.
    """
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=stuck_minutes)).isoformat()
    stuck = (
        sb.table("generations")
        .select("*")
        .eq("status", "pending")
        .lt("created_at", cutoff)
        .order("created_at")
        .limit(limit)
        .execute()
    )
    tally = {"reaped": 0, "retried": 0, "gave_up": 0}
    for row in stuck.data or []:
        job_id = row.get("job_id")
        session_id = row.get("session_id")
        sb.table("generations").update(
            {"status": "failed", "error": f"{_STALL_ERROR_PREFIX} no response within {stuck_minutes} min"}
        ).eq("job_id", job_id).execute()
        tally["reaped"] += 1

        # Count stalls (incl. the one just reaped) so a persistently-hung
        # provider gives up rather than re-enqueueing forever.
        session = None
        try:
            sess = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
            session = sess.data[0] if sess.data else None
        except Exception:  # noqa: BLE001
            session = None

        if session is None or _count_stalled(session_id) > MAX_STALL_RETRIES:
            if session is not None:
                _send_ops_alert(
                    session_id, session.get("store_id"),
                    session.get("product_ref") or {}, session.get("collected") or {},
                    "generation stalled repeatedly — watchdog gave up after retries",
                )
            tally["gave_up"] += 1
            continue

        try:
            _enqueue_generation(background, session, tier=row.get("tier") or "preview")
            tally["retried"] += 1
        except Exception:  # noqa: BLE001 — one bad row must not abort the sweep
            log.warning("watchdog_retry_enqueue_failed", session_id=session_id)
            tally["gave_up"] += 1

    log.info("generation_watchdog_complete", **tally)
    return tally


@router.get("/generate/status/{job_id}", response_model=GenerationStatus)
async def generation_status(job_id: str) -> GenerationStatus:
    sb = get_supabase()
    res = sb.table("generations").select("*").eq("job_id", job_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Job not found")
    row = res.data[0]

    image_url = _to_signed(row.get("image_url"))
    watermarked_url = _to_signed(row.get("watermarked_url"))

    # Sign each view's watermarked image (fall back to its clean image) so a
    # multi-view design surfaces every angle on-screen. Ordered front→back→
    # left→right. Empty for single-view designs.
    view_images: dict[str, str] = {}
    raw_views = row.get("view_images") or {}
    for view in prompt_builder.RENDER_VIEW_ORDER:
        entry = raw_views.get(view)
        if not entry:
            continue
        signed = _to_signed(entry.get("watermarked_url") or entry.get("image_url"))
        if signed:
            view_images[view] = signed

    return GenerationStatus(
        status=row["status"],
        image_url=image_url,
        watermarked_url=watermarked_url,
        view_images=view_images,
    )


def _to_signed(path: str | None) -> str | None:
    """Return a signed URL for a storage path; pass through external stub URLs."""
    if not path:
        return None
    if path.startswith("http"):
        return path
    return generate_signed_url(path)
