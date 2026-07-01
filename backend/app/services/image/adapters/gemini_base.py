"""Shared Gemini compositing logic for the Flash (preview) and Pro (final) tiers.

Always sends the real product reference photo as the first image part so the model
composites onto it rather than inventing a cap shape.
"""
from __future__ import annotations

import time

import google.generativeai as genai
import httpx
import structlog

from app.config import settings
from app.services.image.image_provider import (
    GenerationParams,
    GenerationResult,
    ImageProvider,
)
from app.storage import write_generated

log = structlog.get_logger()

# Rough per-image cost estimates (USD) — real figures come from billing later.
_COST_BY_TIER = {"preview": 0.002, "final": 0.01}


async def _fetch_bytes(url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "image/png")


class _GeminiAdapter(ImageProvider):
    tier: str = "preview"

    def __init__(self, model_name: str):
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        genai.configure(api_key=settings.gemini_api_key)
        self.model_name = model_name

    async def generate(
        self,
        prompt: str,
        reference_image_url: str,
        uploaded_asset_url: str | None,
        params: GenerationParams,
    ) -> GenerationResult:
        if not reference_image_url:
            raise ValueError("reference_image_url is required — never generate a cap from scratch")

        started = time.monotonic()

        ref_bytes, ref_mime = await _fetch_bytes(reference_image_url)
        contents: list = [{"mime_type": ref_mime, "data": ref_bytes}]

        if uploaded_asset_url:
            try:
                logo_bytes, logo_mime = await _fetch_bytes(uploaded_asset_url)
                contents.append({"mime_type": logo_mime, "data": logo_bytes})
            except httpx.HTTPError:
                log.warning("logo_fetch_failed", tier=self.tier)

        contents.append(prompt)

        model = genai.GenerativeModel(self.model_name)
        response = await model.generate_content_async(contents)

        image_bytes = _extract_image(response)
        if image_bytes is None:
            raise RuntimeError("Gemini returned no image data")

        storage_path = write_generated(image_bytes, tier=self.tier)
        latency_ms = int((time.monotonic() - started) * 1000)

        meta = _response_meta(response)
        meta["model"] = self.model_name

        return GenerationResult(
            image_url=storage_path,
            cost_usd=_COST_BY_TIER.get(self.tier, 0.0),
            latency_ms=latency_ms,
            model=self.model_name,
            raw_response=_serialise_response(response),
            response_meta=meta,
        )


def _extract_image(response) -> bytes | None:
    """Pull inline image bytes out of a Gemini response."""
    try:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return inline.data
    except (AttributeError, IndexError):
        pass
    return None


def _serialise_response(response) -> dict:
    """Serialise a Gemini response to a JSON-safe dict for the audit log.

    Bytes fields (the generated image) become base64 automatically. Best-effort:
    tries the SDK's own conversion, then protobuf, then falls back to a repr so a
    quirky/mocked response can never break logging.
    """
    try:
        return type(response).to_dict(response)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    try:
        from google.protobuf.json_format import MessageToDict

        return MessageToDict(response._result)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return {"unserialisable": True, "repr": repr(response)[:2000]}


def _response_meta(response) -> dict:
    """Compact summary of a Gemini response for quick scanning in the log."""
    meta: dict = {
        "image_returned": _extract_image(response) is not None,
        "candidate_count": 0,
        "finish_reason": None,
        "safety_ratings": None,
    }
    try:
        candidates = list(response.candidates or [])
        meta["candidate_count"] = len(candidates)
        if candidates:
            first = candidates[0]
            fr = getattr(first, "finish_reason", None)
            meta["finish_reason"] = getattr(fr, "name", None) or (str(fr) if fr is not None else None)
            ratings = getattr(first, "safety_ratings", None)
            if ratings:
                meta["safety_ratings"] = [str(r) for r in ratings]
    except Exception:  # noqa: BLE001
        pass
    return meta
