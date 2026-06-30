"""Selects the active ImageProvider per tier from env vars — zero code change to swap models."""
from __future__ import annotations

import structlog

from app.config import settings
from app.services.image.adapters.stub import StubAdapter
from app.services.image.image_provider import ImageProvider

log = structlog.get_logger()


def _build(adapter_key: str) -> ImageProvider:
    key = (adapter_key or "stub").lower()
    if key == "stub":
        return StubAdapter()
    if key == "gemini_flash":
        from app.services.image.adapters.gemini_flash import GeminiFlashAdapter

        return GeminiFlashAdapter()
    if key == "gemini_pro":
        from app.services.image.adapters.gemini_pro import GeminiProAdapter

        return GeminiProAdapter()
    log.warning("unknown_adapter_falling_back_to_stub", adapter=adapter_key)
    return StubAdapter()


def get_provider(tier: str) -> ImageProvider:
    """Return the configured provider for 'preview' or 'final'."""
    if tier == "final":
        return _build(settings.image_provider_final)
    return _build(settings.image_provider_preview)
