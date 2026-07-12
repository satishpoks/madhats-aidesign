"""Colour-name → hex resolution.

The customer may TAP a colourway swatch (which carries an explicit hex) or TYPE
a colour name ("blue", "navy", "forest green"). A typed name has no hex, which
made the composite tint fall back to neutral grey — so "blue" rendered grey.
Pillow's ImageColor understands CSS colour names, so we resolve typed names to a
real hex.
"""
from __future__ import annotations

from PIL import ImageColor

FALLBACK_HEX = "#808080"


def name_to_hex(name: str | None) -> str | None:
    """Resolve a colour NAME to a #rrggbb hex, or None if it isn't a known name.

    Tries the name as given, then with spaces removed and lowercased, so
    "Forest Green" → "forestgreen" resolves."""
    name = (name or "").strip()
    if not name:
        return None
    for candidate in (name, name.replace(" ", ""), name.replace(" ", "").lower()):
        try:
            r, g, b = ImageColor.getrgb(candidate)[:3]
            return f"#{r:02x}{g:02x}{b:02x}"
        except ValueError:
            continue
    return None


def resolve_hex(colour: dict | str | None, default: str = FALLBACK_HEX) -> str:
    """Best hex for a chosen colour: an explicit hex wins, else resolve the name,
    else the neutral default. Never returns an empty string."""
    if isinstance(colour, str):
        colour = {"name": colour}
    colour = colour or {}
    hex_ = (colour.get("hex") or "").strip()
    if hex_:
        return hex_ if hex_.startswith("#") else f"#{hex_}"
    return name_to_hex(colour.get("name")) or default
