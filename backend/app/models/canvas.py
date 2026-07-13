from __future__ import annotations

from pydantic import BaseModel


class CreateCanvasSessionRequest(BaseModel):
    product_id: str | None = None
    hat_type_id: str | None = None
    colour: dict | str | None = None
    channel: str = "web"
    entry_path: str | None = None


class CanvasFinalizeRequest(BaseModel):
    canvas_design: dict
    email: str | None = None
    name: str | None = None
