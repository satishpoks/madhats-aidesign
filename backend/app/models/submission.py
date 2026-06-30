from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSubmissionRequest(BaseModel):
    session_id: str
    product_ref: dict
    final_image_urls: list[str] = Field(default_factory=list)
    source_ref: dict | None = None
    customer: dict | None = None


class SubmissionResponse(BaseModel):
    submission_id: str


class UpdateSubmissionRequest(BaseModel):
    review_status: str
    reviewer_notes: str | None = None
