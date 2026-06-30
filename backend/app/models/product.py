from __future__ import annotations

from pydantic import BaseModel, Field


class Product(BaseModel):
    id: str
    style: str
    colour: str
    name: str
    description: str | None = None
    store_url: str | None = None
    reference_image_url: str
    view_images: dict[str, str] = Field(default_factory=dict)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)


class ProductPage(BaseModel):
    """Paginated envelope for product listing responses."""

    items: list[Product]
    total: int
    limit: int
    offset: int
