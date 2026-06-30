"""Watermarking — stamps a 'MADHATS PREVIEW ONLY' overlay onto generated images.

The clean (unwatermarked) image is kept internally; only the watermarked version
is ever shown to or emailed to the customer.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

_TEXT = "MADHATS PREVIEW ONLY"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def apply_watermark(image_bytes: bytes) -> bytes:
    """Return PNG bytes of the image with a diagonal tiled watermark."""
    base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = base.size

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    font_size = max(18, w // 18)
    font = _load_font(font_size)

    # tile the text across a larger canvas, then rotate it diagonally
    tile = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tile)
    step_x = font_size * 12
    step_y = font_size * 4
    for y in range(0, h * 2, step_y):
        for x in range(0, w * 2, step_x):
            tdraw.text((x, y), _TEXT, font=font, fill=(255, 255, 255, 70))

    tile = tile.rotate(30, expand=False)
    # centre-crop the rotated tile back to the base size
    left = (tile.width - w) // 2
    top = (tile.height - h) // 2
    tile = tile.crop((left, top, left + w, top + h))
    overlay = Image.alpha_composite(overlay, tile)

    # corner badge for an unmistakable single mark
    badge_font = _load_font(max(14, w // 28))
    draw.text((12, h - max(14, w // 28) - 14), _TEXT, font=badge_font, fill=(255, 255, 255, 180))

    result = Image.alpha_composite(base, overlay).convert("RGB")
    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue()
