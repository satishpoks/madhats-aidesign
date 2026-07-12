"""_to_square — pad the reference photo to 1:1 so Gemini returns a square,
single-cap image (these models follow the input aspect ratio)."""
from __future__ import annotations

import io

from PIL import Image

from app.services.image.adapters.gemini_base import (
    _OUTPUT_SIZE,
    _normalise_output,
    _to_square,
    _to_square_logo,
)


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


# --- logo squaring: the output shape must follow the cap, not a long logo ---

def test_long_logo_padded_to_square_transparently():
    # A wide/long logo (the reported failure) is padded to a square so its
    # aspect ratio can't bias the output; padding is transparent (no white box).
    out = _to_square_logo(_png(600, 100))
    img = Image.open(io.BytesIO(out))
    assert img.size == (600, 600)
    assert img.mode == "RGBA"
    assert img.getpixel((0, 0))[3] == 0  # top-left corner is transparent padding


def test_square_logo_returned_unchanged():
    src = _png(200, 200)
    assert _to_square_logo(src) is src


def test_logo_undecodable_bytes_returned_unchanged():
    assert _to_square_logo(b"not an image") == b"not an image"


# --- output normalisation: exactly 1000x1000 every time ---

def test_output_normalised_to_1000_square():
    assert _OUTPUT_SIZE == 1000
    out = _normalise_output(_png(1600, 900))
    img = Image.open(io.BytesIO(out))
    assert img.size == (1000, 1000)
    assert img.mode == "RGB"
