"""Flat 4-angle composite preview for the blank-hat flow (Pillow).

Deterministic, no model call: tint the white blank to the chosen colour and
overlay text/logo elements at approximate per-zone boxes. Used for the on-screen
COMPOSITE_PREVIEW confirmation before the real AI render.
"""
from __future__ import annotations

import io

import httpx
import structlog
from PIL import Image, ImageChops, ImageDraw, ImageFont

from app.storage import generate_signed_url, write_composite

log = structlog.get_logger()

_VIEWS = ("front", "back", "left", "right")


def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = (hex_colour or "#808080").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (128, 128, 128)


def tint_image(img: Image.Image, hex_colour: str) -> Image.Image:
    """Recolour the blank to ``hex_colour``, preserving shading AND transparency.

    Multiply-blends the target colour over the blank's RGB (so a light mockup
    takes the exact colour while its shadows/highlights survive) and keeps the
    ORIGINAL alpha channel — so a transparent background stays transparent and
    only the hat pixels are recoloured (no solid colour block). Returns RGBA.
    """
    r, g, b = _hex_to_rgb(hex_colour)
    base = img.convert("RGBA")
    alpha = base.getchannel("A")
    rgb = base.convert("RGB")
    solid = Image.new("RGB", rgb.size, (r, g, b))
    tinted = ImageChops.multiply(rgb, solid).convert("RGBA")
    tinted.putalpha(alpha)
    return tinted


# Approximate bounding boxes as fractions of the image, per (view, zone).
_ZONE_FRAC = {
    ("front", "front_panel"): (0.30, 0.32, 0.40, 0.22),
    ("front", "under_brim"): (0.30, 0.66, 0.40, 0.12),
    ("back", "back"): (0.30, 0.34, 0.40, 0.22),
    ("left", "side"): (0.28, 0.36, 0.44, 0.20),
    ("right", "side"): (0.28, 0.36, 0.44, 0.20),
}
_DEFAULT_FRAC = (0.30, 0.34, 0.40, 0.22)


def zone_box(view: str, zone: str, position: str, size: tuple[int, int]) -> tuple[int, int, int, int]:
    fx, fy, fw, fh = _ZONE_FRAC.get((view, zone), _DEFAULT_FRAC)
    w, h = size
    x, y, bw, bh = int(fx * w), int(fy * h), int(fw * w), int(fh * h)
    if position == "left":
        x -= int(0.12 * w)
    elif position == "right":
        x += int(0.12 * w)
    return (max(0, x), max(0, y), bw, bh)


def _element_view(el: dict) -> str:
    zone = el.get("placement_zone") or "front_panel"
    if zone == "side":
        return "right" if el.get("placement_position") == "right" else "left"
    return {"back": "back", "front_panel": "front", "under_brim": "front"}.get(zone, "front")


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _draw_element(img: Image.Image, el: dict, view: str) -> None:
    box = zone_box(view, el.get("placement_zone") or "front_panel",
                   el.get("placement_position") or "centre", img.size)
    x, y, w, h = box
    etype = el.get("type")
    if etype in ("text",):
        draw = ImageDraw.Draw(img)
        draw.text((x, y), (el.get("content") or "")[:40], fill=(255, 255, 255), font=_font(max(16, h // 2)))
    elif etype in ("logo", "graphic") and el.get("asset_path"):
        try:
            logo = _load_image(el["asset_path"]).convert("RGBA")
            logo.thumbnail((w, h))
            img.paste(logo, (x, y), logo)
        except Exception as exc:  # noqa: BLE001
            log.warning("composite_logo_skip", error=type(exc).__name__)
    else:  # graphic described in words -> label placeholder
        draw = ImageDraw.Draw(img)
        draw.rectangle([x, y, x + w, y + h], outline=(255, 255, 255), width=2)
        draw.text((x + 4, y + 4), (el.get("content") or "graphic")[:24], fill=(255, 255, 255), font=_font(14))


def _load_image(path: str) -> Image.Image:
    url = generate_signed_url(path) if not path.startswith("http") else path
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def _save_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    # Keep alpha so a transparent blank background survives to the preview
    # (RGB flattening would fill it with black).
    img.convert("RGBA").save(buf, format="PNG")
    return write_composite(buf.getvalue())


def render_composite_views(view_paths: dict[str, str], colour_hex: str, elements: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for view in _VIEWS:
        path = view_paths.get(view)
        if not path:
            continue
        base = tint_image(_load_image(path), colour_hex)
        for el in elements or []:
            if _element_view(el) == view:
                try:
                    _draw_element(base, el, view)
                except Exception as exc:  # noqa: BLE001
                    log.warning("element_draw_skip", error=type(exc).__name__)
        out[view] = _save_image(base)
    return out
