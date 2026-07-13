from __future__ import annotations

from pydantic import BaseModel


class DecorationTypePublic(BaseModel):
    id: str
    name: str


class DecorationTypeAdmin(BaseModel):
    id: str
    name: str
    active: bool
    sort_order: int
