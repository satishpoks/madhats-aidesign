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


def _element(el: dict, face: str) -> dict:
    zone, position = FACE_ZONE[face]
    is_text = el.get("type") == "text"
    out: dict = {
        "type": "text" if is_text else "logo",
        "placement_zone": zone,
        "placement_position": position,
        "canvas": {
            "face": face,
            "x": el.get("x"), "y": el.get("y"),
            "width": el.get("width"), "height": el.get("height"),
            "rotation": el.get("rotation", 0), "z": el.get("zIndex", 0),
        },
    }
    if is_text:
        out["content"] = el.get("content", "")
        if el.get("font"):
            out["font"] = el["font"]
        if el.get("colour"):
            out["colour"] = el["colour"]
        if el.get("fontSize"):
            out["size"] = f'{el["fontSize"]}px'
    else:
        out["content"] = "uploaded logo/artwork"
        out["assetUrl"] = el.get("assetUrl")
        out["remove_bg"] = bool(el.get("removeBg"))
    return out


def _describe(el: dict, face: str) -> str:
    where = f"on the {_FACE_LABEL.get(face, face)}"
    if el.get("type") == "text":
        parts = [f'text reading "{el.get("content", "")}"']
        if el.get("colour"):
            parts.append(f'in {el["colour"]}')
        if el.get("font"):
            parts.append(f'{el["font"]} font')
        return f"{', '.join(parts)} {where}"
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
