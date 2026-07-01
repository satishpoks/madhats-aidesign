"""gemini_base response serialisation — capture the raw provider response and a
compact response_meta for the audit log, defensively (no network)."""
from __future__ import annotations

from app.services.image.adapters import gemini_base


class _Inline:
    def __init__(self, data):
        self.data = data


class _Part:
    def __init__(self, inline_data=None):
        self.inline_data = inline_data


class _Content:
    def __init__(self, parts):
        self.parts = parts


class _Candidate:
    def __init__(self, parts, finish_reason="STOP", safety_ratings=None):
        self.content = _Content(parts)
        self.finish_reason = finish_reason
        self.safety_ratings = safety_ratings or []


class _Response:
    def __init__(self, candidates):
        self.candidates = candidates


def test_serialise_response_falls_back_to_repr_when_not_convertible():
    resp = _Response([_Candidate([_Part(_Inline(b"imgbytes"))])])
    out = gemini_base._serialise_response(resp)
    assert isinstance(out, dict)
    # our fake has no to_dict/_result, so the defensive fallback is used
    assert out.get("unserialisable") is True
    assert "repr" in out


def test_response_meta_reports_image_returned_and_finish():
    resp = _Response([_Candidate([_Part(_Inline(b"imgbytes"))], finish_reason="STOP")])
    meta = gemini_base._response_meta(resp)
    assert meta["image_returned"] is True
    assert meta["candidate_count"] == 1
    assert meta["finish_reason"] == "STOP"


def test_response_meta_image_returned_false_when_no_inline_data():
    resp = _Response([_Candidate([_Part(inline_data=None)])])
    meta = gemini_base._response_meta(resp)
    assert meta["image_returned"] is False
