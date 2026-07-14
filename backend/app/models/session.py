from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    product_id: str
    channel: str = "web"
    entry_path: str = "pick_first"


class CreateBlankSessionRequest(BaseModel):
    hat_type_id: str
    # Colour is optional: the landing picker now selects only the hat TYPE and
    # the customer chooses the colour in chat (after quantity). Kept for
    # back-compat with any caller that still sends it.
    colour: dict | str | None = None
    channel: str = "web"
    entry_path: str = "blank_first"


class SessionResponse(BaseModel):
    session_id: str
    share_token: str
    state: str


class ChatMessageOut(BaseModel):
    role: str
    content: str
    state_before: str
    state_after: str
    created_at: str


class SessionDetail(BaseModel):
    session_id: str
    share_token: str
    state: str
    channel: str
    entry_path: str
    product_ref: dict | None = None
    collected: dict = Field(default_factory=dict)
    status: str
    messages: list[ChatMessageOut] = Field(default_factory=list)
    # UI affordances for the current state (chips / continue / trigger), so a
    # resumed session can rebuild the right controls without re-deriving them
    # client-side. Mirrors the ChatResponse.data shape.
    data: dict = Field(default_factory=dict)
    # Signed (watermarked) design URLs for the latest completed generation, in
    # front→back→left→right order — so a resumed session shows the already-made
    # design immediately. Only populated once the email is verified (same gate as
    # the on-screen reveal); empty otherwise.
    designs: list[str] = Field(default_factory=list)
    # The persisted canvas design (placed text/logos/shapes per face + colourway)
    # so a resumed canvas session can rehydrate the interactive studio and let the
    # customer re-edit their actual layout. None for non-canvas / legacy sessions.
    canvas_design: dict | None = None
