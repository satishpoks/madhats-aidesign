"""Final-tier adapter — Gemini Pro. Model ID from GEMINI_FINAL_MODEL env var."""
from __future__ import annotations

from app.config import settings
from app.services.image.adapters.gemini_base import _GeminiAdapter


class GeminiProAdapter(_GeminiAdapter):
    tier = "final"

    def __init__(self) -> None:
        super().__init__(settings.gemini_final_model)
