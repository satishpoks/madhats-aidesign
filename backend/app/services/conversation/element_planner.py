"""Per-element attribute sequencing for the deep-dive.

Pure functions of one element dict. The deterministic state machine asks for
`next_attribute`; the customer may defer any non-content attribute.
"""
from __future__ import annotations

ATTRIBUTE_ORDER: dict[str, list[str]] = {
    "text": ["content", "font", "size", "colour", "style",
             "placement_zone", "placement_position"],
    "graphic": ["content", "style", "size", "colour",
                "placement_zone", "placement_position"],
    "logo": ["remove_bg", "size", "placement_zone", "placement_position"],
    "note": ["content"],
}

# The only attribute that can never be deferred.
_REQUIRED = "content"


def _unset(element: dict, attr: str) -> bool:
    val = element.get(attr)
    return val is None or val == ""


def next_attribute(element: dict) -> str | None:
    order = ATTRIBUTE_ORDER.get(element.get("type"), [])
    deferred = set(element.get("deferred") or [])
    for attr in order:
        if attr in deferred:
            continue
        if _unset(element, attr):
            return attr
    return None


def is_complete(element: dict) -> bool:
    return next_attribute(element) is None


def defer_remaining(element: dict) -> None:
    """Mark every still-unset, non-content attribute as designer's-choice."""
    deferred = element.setdefault("deferred", [])
    for attr in ATTRIBUTE_ORDER.get(element.get("type"), []):
        if attr == _REQUIRED:
            continue
        if _unset(element, attr) and attr not in deferred:
            deferred.append(attr)
