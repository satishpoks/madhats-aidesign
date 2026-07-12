"""Assembles the image-generation prompt from session.collected + product ref.

Enforces that a reference_image_url is always present (hard constraint: composite
onto the real product photo, never generate a cap from scratch). Appends pin
annotations and the decoration-style modifier.
"""
from __future__ import annotations

import hashlib

from app import prompts
from app.services.image.image_provider import GenerationParams


class PromptBuildError(Exception):
    pass


def _first_with(elements: list, key: str, default):
    for el in elements or []:
        if el.get(key) not in (None, ""):
            return el[key]
    return default


# Placement zone -> the product `view_images` angle key that best shows it, so a
# design placed on the back composites onto the back-view photo, not the front.
_ZONE_TO_VIEW = {
    "front_panel": "front",
    "back": "back",
    "side": "left",
    "under_brim": "front",
}


def _primary_zone(collected: dict) -> str | None:
    """The placement zone of the first element that has one (falls back to the
    legacy top-level key)."""
    for el in collected.get("elements") or []:
        if el.get("placement_zone"):
            return el["placement_zone"]
    return collected.get("placement_zone")


def reference_image_for(product_ref: dict, collected: dict) -> str:
    """Pick the product reference photo whose angle matches the primary placement.

    Composite onto the real product photo (hard constraint). When the design goes
    on the back/side and the catalogue has that view, use it so the preview shows
    the decoration on the correct face; otherwise fall back to the front reference.
    """
    default = product_ref.get("reference_image_url")
    views = product_ref.get("view_images") or {}
    zone = _primary_zone(collected)
    view_key = _ZONE_TO_VIEW.get(zone) if zone else None
    if view_key and views.get(view_key):
        return views[view_key]
    return default


def build_params(collected: dict, tier: str) -> GenerationParams:
    elements = collected.get("elements") or []
    return GenerationParams(
        tier=tier,
        placement_zone=_first_with(elements, "placement_zone", collected.get("placement_zone", "front_panel")),
        placement_position=_first_with(elements, "placement_position", collected.get("placement_position", "centre")),
        decoration_type=collected.get("decoration_type", "print"),
        remove_bg=bool(_first_with(elements, "remove_bg", collected.get("remove_bg", False))),
        pin_annotations=collected.get("pin_annotations", []) or [],
        resolution="2k" if tier == "final" else "standard",
    )


_ZONE_LABEL = {"front_panel": "front panel", "side": "side", "back": "back", "under_brim": "under the brim"}


def _placement_phrase(el: dict) -> str:
    zone = el.get("placement_zone")
    if not zone:
        return ""
    label = _ZONE_LABEL.get(zone, zone.replace("_", " "))
    pos = el.get("placement_position")
    return f" on the {label}" + (f" ({pos})" if pos else "")


def _element_line(el: dict) -> str:
    """Render one element (with its own placement) as a prompt line/block.
    Empty/deferred attributes are skipped so no dangling labels leak in."""
    etype = el.get("type")
    if etype == "note":
        return f"Customer note to the team (do not render): {el.get('content', '')}"
    if etype == "logo":
        base = prompts.UPLOADED_ASSET_DESIGN_BLOCK
        place = _placement_phrase(el)
        return base + (f"\nPlace the artwork{place}." if place else "")
    # text / graphic
    bits = []
    content = el.get("content", "")
    if etype == "text":
        bits.append(f'Text reading "{content}" (render exactly as written)')
    else:
        bits.append(f"A graphic: {content}")
    if el.get("font"):
        bits.append(f"{el['font']} font")
    if el.get("style"):
        bits.append(f"{el['style']} style")
    if el.get("size"):
        bits.append(f"{el['size']} size")
    if el.get("colour"):
        bits.append(f"in {el['colour']}")
    return ", ".join(bits) + _placement_phrase(el) + "."


def _brief_context_block(collected: dict) -> str:
    """Render the rich, accumulated design brief (``collected["design_description"]``)
    as extra context for the model.

    The deep-dive captures discrete ``elements``, but Haiku also accumulates a
    fuller brief across turns — imagery/motifs, an overall colour palette, an
    overall style, and any extra text the customer named. That detail used to be
    dropped entirely (``_design_block`` only enumerated ``elements``). We now
    append it so nothing the customer described is lost. Empty fields are pruned
    so no dangling labels leak in.
    """
    brief = collected.get("design_description")
    if not isinstance(brief, dict):
        return ""
    imagery = [str(i).strip() for i in (brief.get("imagery") or []) if str(i).strip()]
    colours = [str(c).strip() for c in (brief.get("colours") or []) if str(c).strip()]
    texts = [str(t).strip() for t in (brief.get("text_elements") or []) if str(t).strip()]
    style = str(brief.get("style") or "").strip()
    summary = str(brief.get("summary") or "").strip()
    lines: list[str] = []
    if summary:
        lines.append(f"Overall design the customer described: {summary}.")
    if imagery:
        lines.append(f"Imagery / motifs to include: {', '.join(imagery)}.")
    if texts:
        lines.append("Text the customer wants included: " + "; ".join(f'"{t}"' for t in texts) + ".")
    if colours:
        lines.append(f"Overall colours to use: {', '.join(colours)}.")
    if style:
        lines.append(f"Overall style: {style}.")
    return "\n".join(lines)


def _design_block(collected: dict) -> str:
    """Describe ONLY the decoration to add — never the base cap.

    Enumerates ``collected["elements"]`` (one line/block per element, each with
    its own placement) AND appends the rich accumulated brief context so no
    detail the customer gave is dropped. Falls back to the legacy flat shape only
    if neither is present.
    """
    elements = collected.get("elements") or []
    lines = [_element_line(el) for el in elements if el.get("type") != "logo"]
    logo_lines = [_element_line(el) for el in elements if el.get("type") == "logo"]
    element_lines = logo_lines + [f"- {ln}" for ln in lines]

    parts: list[str] = []
    if element_lines:
        parts.append("\n".join(element_lines))
    context = _brief_context_block(collected)
    if context:
        parts.append(context)
    if parts:
        return "\n".join(parts)

    if collected.get("uploaded_asset_path"):
        return prompts.UPLOADED_ASSET_DESIGN_BLOCK
    return prompts.FALLBACK_DESIGN_BLOCK


def build_prompt(collected: dict, product_ref: dict, params: GenerationParams) -> str:
    if not product_ref or not product_ref.get("reference_image_url"):
        raise PromptBuildError("product reference_image_url missing — cannot composite")

    if params.decoration_type == "embroidery":
        decoration_kind = prompts.DECORATION_KIND_EMBROIDERY
        decoration_style = prompts.EMBROIDERY_STYLE_MODIFIER
    else:
        decoration_kind = prompts.DECORATION_KIND_PRINT
        decoration_style = prompts.PRINT_STYLE_MODIFIER

    pin_lines = [
        prompts.PIN_ANNOTATION_TEMPLATE.format(
            view=pin.get("view", "front"),
            x_pct=pin.get("x_pct", 50),
            y_pct=pin.get("y_pct", 50),
            comment=pin.get("comment", ""),
        )
        for pin in params.pin_annotations
    ]
    pin_block = ("\n" + "\n".join(pin_lines)) if pin_lines else ""

    design_block = _design_block(collected)
    change = collected.get("change_request")
    if change:
        design_block = f"{design_block}\nRequested change from the customer: {change}."

    is_blank = collected.get("flow_mode") == "blank"
    template = prompts.IMAGE_GEN_PROMPT_BLANK if is_blank else prompts.IMAGE_GEN_PROMPT

    fmt = dict(
        decoration_kind=decoration_kind,
        design_block=design_block,
        decoration_style=decoration_style,
        pin_block=pin_block,
    )
    if is_blank:
        fmt["hat_colour"] = product_ref.get("colour") or "the customer's chosen colour"
    return template.format(**fmt)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
