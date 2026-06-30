"""Stub adapter — returns a placeholder image immediately.

Used in tests and local dev when no model API key is configured. Still honours the
ImageProvider contract (reference image required).
"""
from __future__ import annotations

from urllib.parse import quote

from app.services.image.image_provider import (
    GenerationParams,
    GenerationResult,
    ImageProvider,
)


class StubAdapter(ImageProvider):
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,
        uploaded_asset_url: str | None,
        params: GenerationParams,
    ) -> GenerationResult:
        if not reference_image_url:
            raise ValueError("reference_image_url is required")
        label = quote(f"{params.decoration_type} @ {params.placement_zone}")
        url = f"https://placehold.co/800x600/1f2937/ffffff?text={label}"
        return GenerationResult(
            image_url=url,
            cost_usd=0.0,
            latency_ms=50,
            model="stub",
        )
