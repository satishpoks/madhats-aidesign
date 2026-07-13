from __future__ import annotations

from pydantic import BaseModel

# Allowed graphic categories (mirrors the DB check constraint).
GRAPHIC_CATEGORIES = ("clipart", "company")


class GraphicPublic(BaseModel):
    id: str
    category: str
    name: str
    url: str  # /media proxy URL (taint-safe for the canvas)


class GraphicAdmin(BaseModel):
    id: str
    category: str
    name: str
    active: bool
    sort_order: int
    url: str
