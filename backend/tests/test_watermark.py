"""Watermark applies cleanly to a generated image."""
from __future__ import annotations

import io

from PIL import Image

from app.services.watermark import apply_watermark


def _png_bytes(size=(200, 150), colour=(120, 80, 200)) -> bytes:
    img = Image.new("RGB", size, colour)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_watermark_returns_valid_png():
    stamped = apply_watermark(_png_bytes())
    assert stamped
    reopened = Image.open(io.BytesIO(stamped))
    assert reopened.size == (200, 150)
    assert reopened.format == "PNG"
