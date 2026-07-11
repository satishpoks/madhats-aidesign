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


def build_params(collected: dict, tier: str) -> GenerationParams:
    return GenerationParams(
        tier=tier,
        placement_zone=collected.get("placement_zone", "front_panel"),
        placement_position=collected.get("placement_position", "centre"),
        decoration_type=collected.get("decoration_type", "print"),
        remove_bg=bool(collected.get("remove_bg", False)),
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


def _design_block(collected: dict) -> str:
    """Describe ONLY the decoration to add — never the base cap.

    Enumerates ``collected["elements"]`` — one line/block per element, each
    carrying its own placement. Falls back to the legacy flat shape only if
    ``elements`` is absent (back-compat for any un-migrated caller).
    """
    elements = collected.get("elements")
    if not elements:
        if collected.get("uploaded_asset_path"):
            return prompts.UPLOADED_ASSET_DESIGN_BLOCK
        return prompts.FALLBACK_DESIGN_BLOCK
    lines = [_element_line(el) for el in elements if el.get("type") != "logo"]
    logo_lines = [_element_line(el) for el in elements if el.get("type") == "logo"]
    all_lines = logo_lines + [f"- {ln}" for ln in lines]
    return "\n".join(all_lines) if all_lines else prompts.FALLBACK_DESIGN_BLOCK


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

    return prompts.IMAGE_GEN_PROMPT.format(
        decoration_kind=decoration_kind,
        design_block=design_block,
        decoration_style=decoration_style,
        pin_block=pin_block,
    )


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
