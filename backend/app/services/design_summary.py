"""Human-readable design summaries derived from ``collected["elements"]``.

The per-element deep-dive (docs/superpowers/specs/2026-07-11-per-element-
deepdive-design.md) replaced the flat ``placement_zone`` / ``placement_position``
/ ``design_description`` fields with a structured ``elements`` list. A handful
of business-critical, human-facing surfaces (sales emails, ops failure alerts,
the quote page's placement default) still need a single "where does this go"
answer and a short plain-English brief of the design — this module is the one
place that derives both from the element model, with legacy fallbacks for any
session that predates it.

No PII: these helpers only ever touch design content (text/colours/placement),
never name/email/phone.
"""
from __future__ import annotations

# Mirrors app.services.prompt_builder._ZONE_LABEL — kept as a separate copy so
# this module has no import-time dependency on prompt_builder.
_ZONE_LABEL = {
    "front_panel": "front panel",
    "side": "side",
    "back": "back",
    "under_brim": "under the brim",
}


def _zone_label(zone: str | None) -> str | None:
    if not zone:
        return None
    return _ZONE_LABEL.get(zone, zone.replace("_", " "))


def primary_placement(collected: dict) -> tuple[str, str]:
    """Return (zone_label, position) for the design's primary placement.

    Reads the FIRST element in ``collected["elements"]`` that has a
    ``placement_zone`` set. Falls back to the legacy top-level
    ``placement_zone`` / ``placement_position`` fields, then to
    ``("front panel", "centre")``.
    """
    for el in collected.get("elements") or []:
        zone = el.get("placement_zone")
        if zone:
            return _zone_label(zone), el.get("placement_position") or "centre"

    legacy_zone = collected.get("placement_zone")
    if legacy_zone:
        return _zone_label(legacy_zone), collected.get("placement_position") or "centre"

    return "front panel", "centre"


def _placement_phrase(el: dict) -> str:
    """'on the <zone> (<position>)', or '' if no zone is set."""
    zone = el.get("placement_zone")
    if not zone:
        return ""
    label = _zone_label(zone)
    pos = el.get("placement_position")
    return f"on the {label}" + (f" ({pos})" if pos else "")


def _element_brief_line(el: dict) -> str:
    """One human-readable line for a single element, or '' if there's nothing
    to say (e.g. a text/graphic element whose content was never captured)."""
    etype = el.get("type")
    deferred = set(el.get("deferred") or [])

    def _attr(name: str):
        if name in deferred:
            return None
        val = el.get(name)
        return val if val not in (None, "") else None

    if etype == "note":
        content = _attr("content")
        return f"Note to team: {content}" if content else ""

    if etype == "logo":
        label = "Uploaded logo"
        bits: list[str] = []
    else:
        content = _attr("content")
        if not content:
            return ""
        label = f'Text "{content}"' if etype == "text" else f"Graphic: {content}"
        bits = [v for v in (_attr("style"), _attr("colour")) if v]

    place = _placement_phrase(el)
    if place:
        bits.append(place)

    return f"{label} — {', '.join(bits)}" if bits else label


def summarise_elements(collected: dict) -> str:
    """Short human-readable brief of the design, one line per element.

    Falls back to ``design_description.summary`` if there are no elements
    (legacy sessions / no-key flat-brief path), else "".
    """
    elements = collected.get("elements") or []
    lines = [ln for ln in (_element_brief_line(el) for el in elements) if ln]
    if lines:
        return "\n".join(lines)

    design = collected.get("design_description")
    if isinstance(design, dict) and design.get("summary"):
        return design["summary"]
    return ""
