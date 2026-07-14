"""Convert the interactive canvas (CanvasDesign JSON) into the existing
collected["elements"] shape + a deterministic description.

Mapping the canvas into the SAME element shape the deep-dive produced means the
existing multi-view generator (prompt_builder.build_view_prompt / render_views)
renders the canvas design with no further change.
"""
from __future__ import annotations

# Face tab -> (placement_zone, placement_position). Mirrors prompt_builder.element_view:
# side splits into left/right by position; back -> back; front -> front_panel.
FACE_ZONE: dict[str, tuple[str, str | None]] = {
    "front": ("front_panel", "centre"),
    "back": ("back", "centre"),
    "left": ("side", "left"),
    "right": ("side", "right"),
}

_FACE_LABEL = {"front": "front panel", "back": "back", "left": "left side", "right": "right side"}

# Built-in vector-shape labels (the "Clipart" palette).
_SHAPE_LABEL = {
    "rect": "rectangle", "square": "square", "roundedRect": "rounded rectangle",
    "circle": "circle", "ellipse": "oval", "triangle": "triangle", "diamond": "diamond",
    "pentagon": "pentagon", "hexagon": "hexagon", "star": "star",
    "line": "line", "arrow": "arrow", "doubleArrow": "double-headed arrow",
}
_LINE_SHAPES = {"line", "arrow", "doubleArrow"}

# Text has no explicit colour until the customer picks one; the canvas renders an
# unset colour as WHITE (nodes.tsx: `el.colour ?? '#ffffff'`). Default to white
# here so the colour is always described AND flows to the image model — otherwise
# a white text element carried no colour at all and was dropped (the model can't
# see white on the flattened guide). Common hexes map to plain names for the model.
_TEXT_COLOUR_NAMES = {
    "#ffffff": "white", "#fff": "white", "white": "white",
    "#000000": "black", "#000": "black", "black": "black",
    "#ff0000": "red", "#00ff00": "green", "#0000ff": "blue",
    "#ffff00": "yellow", "#ffa500": "orange",
}


def _text_colour(value: str | None) -> str:
    """The text element's colour, defaulting to white, with common hexes named."""
    raw = value or "#ffffff"
    return _TEXT_COLOUR_NAMES.get(str(raw).strip().lower(), raw)


def _shape_phrase(el: dict) -> str:
    kind = el.get("shapeKind", "rect")
    label = _SHAPE_LABEL.get(kind, kind)
    colour = el.get("fill") or "coloured"
    if kind in _LINE_SHAPES:
        return f"{colour} {label}"
    mode = "filled" if el.get("filled", True) else "outlined"
    return f"{mode} {colour} {label}"


def _element(el: dict, face: str) -> dict:
    zone, position = FACE_ZONE[face]
    etype = el.get("type")
    out: dict = {
        "placement_zone": zone,
        "placement_position": position,
        "canvas": {
            "face": face,
            "x": el.get("x"), "y": el.get("y"),
            "width": el.get("width"), "height": el.get("height"),
            "rotation": el.get("rotation", 0), "z": el.get("zIndex", 0),
        },
    }
    if etype == "text":
        out["type"] = "text"
        out["content"] = el.get("content", "")
        if el.get("font"):
            out["font"] = el["font"]
        # Always set a colour (default white) so it's never dropped downstream.
        out["colour"] = _text_colour(el.get("colour"))
        # Curved text: surface a coarse style hint. Exact size/placement is
        # owned by the flattened layout-guide image, so raw pixel font sizes
        # are intentionally NOT emitted into the text description.
        if el.get("curve"):
            out["style"] = "curved"
    elif etype == "shape":
        # Vector shapes render as a described graphic; the flattened layout PNG
        # already carries the exact geometry/colour, this is the text hint.
        out["type"] = "graphic"
        out["content"] = _shape_phrase(el)
        if el.get("fill"):
            out["colour"] = el["fill"]
    elif etype == "drawing":
        # A freehand pen stroke. Describe it as a graphic; the flattened layout PNG
        # carries the exact geometry, this is just the text hint.
        out["type"] = "graphic"
        colour = el.get("stroke")
        out["content"] = f"a hand-drawn line in {colour}" if colour else "a hand-drawn line"
        if colour:
            out["colour"] = colour
    else:  # image / uploaded logo / company graphic
        out["type"] = "logo"
        out["content"] = "uploaded logo/artwork"
        out["assetUrl"] = el.get("assetUrl")
        out["remove_bg"] = bool(el.get("removeBg"))
    return out


def _describe(el: dict, face: str) -> str:
    where = f"on the {_FACE_LABEL.get(face, face)}"
    etype = el.get("type")
    if etype == "text":
        parts = [f'text reading "{el.get("content", "")}"']
        parts.append(f'in {_text_colour(el.get("colour"))}')
        if el.get("font"):
            parts.append(f'{el["font"]} font')
        return f"{', '.join(parts)} {where}"
    if etype == "drawing":
        colour = el.get("stroke")
        phrase = f"a hand-drawn line in {colour}" if colour else "a hand-drawn line"
        return f"{phrase} {where}"
    if etype == "shape":
        return f"a {_shape_phrase(el)} {where}"
    return f"uploaded logo/artwork {where}"


def canvas_to_elements(canvas_design: dict) -> tuple[list[dict], str]:
    faces = (canvas_design or {}).get("faces") or {}
    elements: list[dict] = []
    lines: list[str] = []
    for face in ("front", "back", "left", "right"):
        for el in sorted(faces.get(face) or [], key=lambda e: e.get("zIndex", 0)):
            elements.append(_element(el, face))
            lines.append(_describe(el, face))
    description = "; ".join(lines)
    return elements, description
