"""Per-call audit trail for image generation.

Writes one row to `generation_logs` per actual provider call: the inputs
(reference image, uploaded logo, full prompt) are recorded BEFORE the call, the
outcome (the exact final request_payload sent to the image model, response
metadata, full raw response, output image) is recorded AFTER. Retries produce
one row each; cache hits produce a single `cache_hit` row.

Best-effort by design: a logging failure must NEVER break generation, so every
write is wrapped and only warns. No customer PII is stored — prompt/params are
design data only (CLAUDE.md §8.10).
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.db import get_supabase

log = structlog.get_logger()


def log_request(
    *,
    generation_id: str | None,
    job_id: str | None,
    session_id: str | None,
    attempt: int,
    tier: str | None,
    reference_image_url: str | None,
    uploaded_asset_url: str | None,
    full_prompt: str,
) -> str | None:
    """Insert the inputs row (status='requested') before a provider call.

    Returns the new log id, or None on any failure (never raises).
    """
    try:
        res = (
            get_supabase()
            .table("generation_logs")
            .insert(
                {
                    "generation_id": generation_id,
                    "job_id": job_id,
                    "session_id": session_id,
                    "attempt": attempt,
                    "tier": tier,
                    "reference_image_url": reference_image_url,
                    "uploaded_asset_url": uploaded_asset_url,
                    "full_prompt": full_prompt,
                    "status": "requested",
                }
            )
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    except Exception as exc:  # noqa: BLE001 — logging must never break generation
        log.warning("generation_log_request_failed", error_type=type(exc).__name__)
        return None


def log_response(
    log_id: str | None,
    *,
    status: str,
    model: str | None = None,
    output_image_url: str | None = None,
    request_payload: dict | None = None,
    response_meta: dict | None = None,
    raw_response: dict | None = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Update the request row with the provider outcome. No-op if log_id is None.

    ``request_payload`` is the exact final payload the adapter sent to the image
    model (model + ordered content parts); it's only known after the call, so
    it's patched in here alongside the response.
    """
    if not log_id:
        return
    try:
        (
            get_supabase()
            .table("generation_logs")
            .update(
                {
                    "status": status,
                    "model": model,
                    "output_image_url": output_image_url,
                    "request_payload": request_payload,
                    "response_meta": response_meta,
                    "raw_response": raw_response,
                    "error": error,
                    "latency_ms": latency_ms,
                    "response_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", log_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("generation_log_response_failed", error_type=type(exc).__name__)


def log_cache_hit(
    *,
    generation_id: str | None,
    job_id: str | None,
    session_id: str | None,
    tier: str | None,
    reference_image_url: str | None,
    uploaded_asset_url: str | None,
    full_prompt: str,
    model: str | None,
    output_image_url: str | None,
) -> None:
    """Write a single row recording that a cached result was served (no model call)."""
    try:
        (
            get_supabase()
            .table("generation_logs")
            .insert(
                {
                    "generation_id": generation_id,
                    "job_id": job_id,
                    "session_id": session_id,
                    "attempt": 0,
                    "tier": tier,
                    "reference_image_url": reference_image_url,
                    "uploaded_asset_url": uploaded_asset_url,
                    "full_prompt": full_prompt,
                    "status": "cache_hit",
                    "model": model,
                    "output_image_url": output_image_url,
                    "response_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("generation_log_cache_hit_failed", error_type=type(exc).__name__)
