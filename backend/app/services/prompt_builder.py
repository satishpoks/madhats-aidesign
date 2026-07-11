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


def _design_block(collected: dict) -> str:
    """Describe ONLY the decoration to add — never the base cap.

    Flow B (uploaded logo): point the model at the second image. Flow A
    (described design): weave in every captured field (summary, text, colours,
    imagery, style), skipping empties so no dangling labels leak into the prompt.
    """
    if collected.get("uploaded_asset_path"):
        block = prompts.UPLOADED_ASSET_DESIGN_BLOCK
        design = collected.get("design_description") or {}
        summary = design.get("summary") if isinstance(design, dict) else str(design)
        if summary:
            block += f"\nExtra context from the customer: {summary}"
        return block

    design = collected.get("design_description") or {}
    if not isinstance(design, dict):
        return str(design) or prompts.FALLBACK_DESIGN_BLOCK

    lines: list[str] = []
    summary = design.get("summary") or collected.get("design_summary")
    if summary:
        lines.append(summary)
    text_elements = [t for t in (design.get("text_elements") or []) if t]
    if text_elements:
        quoted = ", ".join(f'"{t}"' for t in text_elements)
        lines.append(f"Text to include (render exactly as written): {quoted}")
    colours = [c for c in (design.get("colours") or []) if c]
    if colours:
        lines.append(f"Design colours (of the decoration, not the cap): {', '.join(colours)}")
    imagery = [i for i in (design.get("imagery") or []) if i]
    if imagery:
        lines.append(f"Graphics/icons: {', '.join(imagery)}")
    style = design.get("style")
    if style:
        lines.append(f"Design style: {style}")

    return "\n".join(lines) if lines else prompts.FALLBACK_DESIGN_BLOCK


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
        placement_zone=params.placement_zone.replace("_", " "),
        placement_position=params.placement_position,
        pin_block=pin_block,
    )


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
