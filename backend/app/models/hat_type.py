from __future__ import annotations

from pydantic import BaseModel, Field


class HatColour(BaseModel):
    name: str
    hex: str


class CreateHatTypeRequest(BaseModel):
    name: str
    slug: str
    style: str = ""
    description: str | None = None
    colours: list[HatColour] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
    pricing_slabs: list[dict] = Field(default_factory=list)


class UpdateHatTypeRequest(BaseModel):
    name: str | None = None
    style: str | None = None
    description: str | None = None
    colours: list[HatColour] | None = None
    placement_zones: list[str] | None = None
    decoration_types: list[str] | None = None
    pricing_slabs: list[dict] | None = None
    active: bool | None = None


class HatTypeAdmin(BaseModel):
    id: str
    store_id: str | None = None
    slug: str
    name: str
    style: str = ""
    description: str | None = None
    blank_view_images: dict[str, str] = Field(default_factory=dict)
    view_images: dict[str, str] = Field(default_factory=dict)  # browser-loadable proxy URLs
    colours: list[dict] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
    pricing_slabs: list[dict] = Field(default_factory=list)
    active: bool = False


class HatTypePublic(BaseModel):
    id: str
    slug: str
    name: str
    style: str = ""
    view_images: dict[str, str] = Field(default_factory=dict)  # browser-loadable URLs
    colours: list[dict] = Field(default_factory=list)
    placement_zones: list[str] = Field(default_factory=list)
    decoration_types: list[str] = Field(default_factory=list)
