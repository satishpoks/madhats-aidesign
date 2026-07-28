from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    # The frontend's live canvas (a CanvasDesign blob), sent on the two turns
    # that need to see what's on screen rather than the last saved design.
    # Canvas sessions only; ignored on every other state and flow:
    #   - DESCRIBE_CHANGES (and REWORK_CANVAS): an edit resolves against the
    #     live canvas, and the blob is persisted as the new base (chat.py
    #     `_persist_live_canvas_design`).
    #   - LOGO_ADJUST: the "Done" turn closing logo placement — read (never
    #     persisted) for a self-ticked "Remove background", which lives only in
    #     the frontend store until finalize (canvas_steps.observe_canvas).
    canvas_design: dict | None = None


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
