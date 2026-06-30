from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    product_id: str
    channel: str = "web"
    entry_path: str = "pick_first"


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
