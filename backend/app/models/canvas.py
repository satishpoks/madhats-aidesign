from __future__ import annotations

from pydantic import BaseModel


class CreateCanvasSessionRequest(BaseModel):
    product_id: str | None = None
    hat_type_id: str | None = None
    colour: dict | str | None = None
    channel: str = "web"
    # design_sessions.entry_path is NOT NULL — default to a non-null marker like
    # the customise/blank create requests ("pick_first"/"blank_first").
    entry_path: str = "canvas_first"


class CanvasFinalizeRequest(BaseModel):
    canvas_design: dict
    email: str | None = None
    name: str | None = None
