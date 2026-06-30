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


def build_prompt(collected: dict, product_ref: dict, params: GenerationParams) -> str:
    if not product_ref or not product_ref.get("reference_image_url"):
        raise PromptBuildError("product reference_image_url missing — cannot composite")

    design = collected.get("design_description") or {}
    design_summary = (
        design.get("summary")
        if isinstance(design, dict)
        else str(design)
    ) or collected.get("design_summary") or "the customer's supplied logo/artwork"

    sections = [
        prompts.IMAGE_GEN_BASE_TEMPLATE.format(
            style=product_ref.get("style", "cap"),
            colour=product_ref.get("colour", "as shown"),
            design_summary=design_summary,
        ),
        prompts.PLACEMENT_CONTEXT_TEMPLATE.format(
            placement_zone=params.placement_zone.replace("_", " "),
            placement_position=params.placement_position,
        ),
    ]

    if params.decoration_type == "embroidery":
        sections.append(prompts.EMBROIDERY_STYLE_MODIFIER)
    else:
        sections.append(prompts.PRINT_STYLE_MODIFIER)

    for pin in params.pin_annotations:
        sections.append(
            prompts.PIN_ANNOTATION_TEMPLATE.format(
                view=pin.get("view", "front"),
                x_pct=pin.get("x_pct", 50),
                y_pct=pin.get("y_pct", 50),
                comment=pin.get("comment", ""),
            )
        )

    return "\n\n".join(sections)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
