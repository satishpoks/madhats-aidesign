from __future__ import annotations

from pydantic import BaseModel


class GenerateRequest(BaseModel):
    tier: str = "preview"


class JobResponse(BaseModel):
    job_id: str


class GenerationStatus(BaseModel):
    status: str
    image_url: str | None = None
    watermarked_url: str | None = None
    # Per-view signed watermarked URLs { view: url } for a multi-view design
    # (front hero + any decorated back/side view). Empty for single-view designs.
    view_images: dict[str, str] = {}
