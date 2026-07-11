from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    state: str
    data: dict = {}


class VerificationPollResponse(BaseModel):
    # reply is None until the emailed link is clicked; then it carries Ricardo's
    # confirmation line and `state` advances past verify_email.
    reply: str | None = None
    state: str
    data: dict = {}


class RegenerationPollResponse(BaseModel):
    # reply is None if the session isn't (or is no longer) at regenerating;
    # then it carries Ricardo's reply and `state` advances to offer_refine.
    reply: str | None = None
    state: str
    data: dict = {}
