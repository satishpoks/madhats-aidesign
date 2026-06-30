"""Preview-tier adapter — Gemini Flash. Model ID from GEMINI_PREVIEW_MODEL env var."""
from __future__ import annotations

from app.config import settings
from app.services.image.adapters.gemini_base import _GeminiAdapter


class GeminiFlashAdapter(_GeminiAdapter):
    tier = "preview"

    def __init__(self) -> None:
        super().__init__(settings.gemini_preview_model)
