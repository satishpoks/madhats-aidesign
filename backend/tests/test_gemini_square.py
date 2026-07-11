"""_to_square — pad the reference photo to 1:1 so Gemini returns a square,
single-cap image (these models follow the input aspect ratio)."""
from __future__ import annotations

import io

from PIL import Image

from app.services.image.adapters.gemini_base import _to_square


def _png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


def test_landscape_padded_to_square():
    out = _to_square(_png(300, 150))
    assert Image.open(io.BytesIO(out)).size == (300, 300)


def test_portrait_padded_to_square():
    out = _to_square(_png(120, 400))
    assert Image.open(io.BytesIO(out)).size == (400, 400)


def test_already_square_returned_unchanged():
    src = _png(200, 200)
    assert _to_square(src) is src  # no re-encode when already 1:1


def test_undecodable_bytes_returned_unchanged():
    # never break generation on a decode hiccup
    assert _to_square(b"not an image") == b"not an image"
