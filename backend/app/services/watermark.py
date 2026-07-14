"""Watermarking — stamps a single diagonal text line onto generated images.

One line of configurable text runs bottom-left → top-right across the image,
semi-transparent with a subtle contrasting outline so it stays readable on both
light and dark artwork. Cleaner and more legible than a tiled repeat. The text
is configurable from the admin panel (``watermark_text`` app setting); callers
pass it in.

The clean (unwatermarked) image is kept internally; only the watermarked version
is ever shown to or emailed to the customer.
"""
from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw, ImageFont

_DEFAULT_TEXT = "MADHATS PREVIEW"


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    # No system TrueType font (e.g. the slim prod container has none installed).
    # Pillow's bundled default IS scalable when given a size (>=10.1) — pass the
    # size so the watermark still scales to the full diagonal instead of being
    # stuck at the fixed ~10px bitmap fallback.
    try:
        return ImageFont.load_default(size)
    except TypeError:  # very old Pillow — no size arg; returns fixed bitmap font
        return ImageFont.load_default()


def _text_width(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, stroke: int) -> int:
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    left, _t, right, _b = probe.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return max(1, right - left)


def apply_watermark(image_bytes: bytes, text: str | None = None) -> bytes:
    """Return PNG bytes of the image with a single diagonal text watermark.

    ``text`` is the configurable watermark string (falls back to a default when
    empty/None). The line runs bottom-left → top-right corner-to-corner (spanning
    the full diagonal) as plain semi-transparent text — no outline/background.
    """
    text = (text or "").strip() or _DEFAULT_TEXT
    base = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
    w, h = base.size
    diagonal = math.hypot(w, h)

    # Size the font so the text spans the full diagonal (~98%, corner to corner):
    # measure at a probe size, then scale. Cap the height so a short string
    # doesn't become huge. Plain text, no stroke.
    probe_size = 100
    probe_w = _text_width(text, _load_font(probe_size), 0)
    size = int(probe_size * (diagonal * 0.98) / probe_w)
    size = max(14, min(size, int(min(w, h) * 0.6)))
    font = _load_font(size)

    # Render the text once onto its own tightly-cropped tile — text only, fully
    # transparent background, no stroke/outline.
    left, top, right, bottom = ImageDraw.Draw(Image.new("RGBA", (10, 10))).textbbox(
        (0, 0), text, font=font, stroke_width=0
    )
    tw, th = right - left, bottom - top
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    # Mid-grey (not pure white) so the watermark stays lightly visible on light
    # artwork too — pure white vanished on white backgrounds. Grey reads on both
    # dark and light: it lightens over dark art and darkens over white.
    ImageDraw.Draw(tile).text(
        (-left, -top), text, font=font, fill=(128, 128, 128, 95),
    )

    # Rotate to run bottom-left → top-right (PIL rotates counter-clockwise).
    angle = math.degrees(math.atan2(h, w))
    rotated = tile.rotate(angle, expand=True, resample=Image.BICUBIC)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    overlay.alpha_composite(rotated, ((w - rotated.width) // 2, (h - rotated.height) // 2))

    result = Image.alpha_composite(base, overlay).convert("RGB")
    out = io.BytesIO()
    result.save(out, format="PNG")
    return out.getvalue()
