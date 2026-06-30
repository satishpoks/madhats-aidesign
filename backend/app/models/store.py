from __future__ import annotations

from pydantic import BaseModel, Field


class CreateStoreRequest(BaseModel):
    slug: str
    name: str
    shopify_domain: str | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    persona_name: str = "Ricardo"
    greeting_template: str | None = None
    sales_notification_email: str | None = None
    brand: dict = Field(default_factory=dict)


class StoreResponse(BaseModel):
    id: str
    slug: str
    name: str
    public_key: str
    shopify_domain: str | None = None
    status: str


class SyncResponse(BaseModel):
    fetched: int
    imported: int
    skipped: int
