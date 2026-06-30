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
