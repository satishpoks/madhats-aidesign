from __future__ import annotations

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str
    # The frontend's live canvas (a CanvasDesign blob). Canvas sessions only;
    # ignored on every other flow. As of the checkpoint work (Task 6), v2
    # canvas turns send this on EVERY turn — it feeds the checkpoint snapshot
    # (`checkpoints.capture`), which needs the canvas as it stood at the
    # moment a checkpoint-opening step is entered, not just at the two turns
    # below. That is a widening of what is SENT, not of what is PERSISTED:
    # the set of turns whose blob may be written to
    # `design_sessions.canvas_design` is unchanged and still enforced by
    # `chat.py::_persist_live_canvas_design` —
    #   - DESCRIBE_CHANGES (and REWORK_CANVAS): an edit resolves against the
    #     live canvas, and the blob is persisted as the new base.
    #   - LOGO_ADJUST: the "Done" turn closing logo placement — read (never
    #     persisted) for a self-ticked "Remove background", which lives only in
    #     the frontend store until finalize (canvas_steps.observe_canvas).
    canvas_design: dict | None = None


class BackRequest(BaseModel):
    """Which checkpoint to restore. The seq comes from `data.back_targets`,
    which every v2 canvas turn ships."""
    seq: int


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
