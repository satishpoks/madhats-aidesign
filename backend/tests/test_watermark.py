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


def test_watermark_accepts_custom_text_and_marks_image():
    clean = _png_bytes()
    stamped = apply_watermark(clean, text="ACME PREVIEW")
    assert stamped
    reopened = Image.open(io.BytesIO(stamped))
    assert reopened.size == (200, 150)
    # The watermark actually changed pixels (a solid clean image would be
    # unchanged if nothing were drawn).
    assert stamped != clean


def test_watermark_text_runs_diagonally_bottom_left_to_top_right():
    # A single diagonal line of text should leave marks near the bottom-left and
    # top-right of the image, and comparatively little in the opposite corners.
    from PIL import Image as _Image

    base = _Image.new("RGB", (300, 300), (0, 0, 0))  # black canvas
    out = io.BytesIO(); base.save(out, format="PNG")
    stamped = _Image.open(io.BytesIO(apply_watermark(out.getvalue(), text="PREVIEW MARK"))).convert("L")

    def brightness(box):
        return sum(stamped.crop(box).getdata()) / (box[2] - box[0]) / (box[3] - box[1])

    bottom_left = brightness((0, 200, 100, 300))
    top_right = brightness((200, 0, 300, 100))
    top_left = brightness((0, 0, 100, 100))
    bottom_right = brightness((200, 200, 300, 300))
    # The diagonal (BL + TR) carries the text; the anti-diagonal corners are darker.
    assert (bottom_left + top_right) > (top_left + bottom_right)
