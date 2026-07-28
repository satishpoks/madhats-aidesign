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


def customer_brief(collected: dict, product_ref: dict | None = None) -> str:
    """A short, customer-facing bullet summary of the WHOLE design, for the
    pre-generation confirmation step (cap, colour, decoration, every element,
    and any notes). One bullet per line; falls back to a generic phrase."""
    product_ref = product_ref or {}
    lines: list[str] = []
    if product_ref.get("name"):
        lines.append(f"• Cap: {product_ref['name']}")
    hc = collected.get("hat_colour")
    colour = (hc.get("name") or hc.get("hex")) if isinstance(hc, dict) else (hc if isinstance(hc, str) else None)
    colour = colour or product_ref.get("colour")
    if colour:
        lines.append(f"• Colour: {colour}")
    if collected.get("decoration_type"):
        lines.append(f"• Decoration: {collected['decoration_type']}")
    for el in collected.get("elements") or []:
        ln = _element_brief_line(el)
        if ln:
            lines.append(f"• {ln}")
    for note in collected.get("brief_notes") or []:
        lines.append(f"• Note: {note}")
    return "\n".join(lines) if lines else "• Your custom design"


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


def design_breakdown(collected: dict) -> str:
    """One line per design element for the INTERNAL sales notification.

    Separate from `customer_brief`, which is customer-facing and deliberately
    drops production detail. This one exists to carry that detail — above all
    the background-removal flag, which previously reached no admin surface at
    all and left sales quoting a job without knowing the artwork needed
    knocking out.

    Reads `remove_bg` (what the render acts on), never
    `collected["logos"][].bg` (the chip answer, documented as divergent).
    """
    lines: list[str] = []
    for i, el in enumerate(collected.get("elements") or [], start=1):
        etype = el.get("type") or "element"
        content = el.get("content") or ""
        face = (el.get("canvas") or {}).get("face") or el.get("placement_zone") or ""
        bits = [f"{i}. {etype}"]
        if content:
            bits.append(f'"{content}"' if etype == "text" else content)
        if face:
            bits.append(f"on the {face}")
        line = " — ".join([bits[0], ", ".join(bits[1:])]) if len(bits) > 1 else bits[0]
        if el.get("remove_bg"):
            line += "  ** BACKGROUND TO BE REMOVED **"
        lines.append(line)
    return "\n".join(lines) if lines else "—"
