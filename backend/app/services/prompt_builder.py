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


# --- Multi-view rendering: one AI render per decorated angle -----------------

# Canonical order the views are rendered/shown/emailed in.
RENDER_VIEW_ORDER = ("front", "back", "left", "right")
PRIMARY_VIEW = "front"


def element_view(el: dict) -> str:
    """Which product angle best shows this element's placement.

    ``side`` splits into left/right by the element's position; ``back`` -> back;
    ``front_panel``/``under_brim`` -> front. Mirrors composite._element_view so
    the on-screen mock-up and the AI render agree on where each element lands.
    """
    zone = el.get("placement_zone") or "front_panel"
    if zone == "side":
        return "right" if el.get("placement_position") == "right" else "left"
    return _ZONE_TO_VIEW.get(zone, "front")


def render_views(collected: dict) -> list[str]:
    """Views to AI-render: always the front hero PLUS every other view that
    carries at least one decoration element, in canonical order."""
    views = {PRIMARY_VIEW}
    for el in collected.get("elements") or []:
        views.add(element_view(el))
    return [v for v in RENDER_VIEW_ORDER if v in views]


def elements_for_view(collected: dict, view: str) -> list[dict]:
    return [el for el in (collected.get("elements") or []) if element_view(el) == view]


def affected_render_views(collected: dict) -> list[str]:
    """For an EDIT: the decorated views the change actually touches.

    Uses ``collected["refine_views"]`` (accumulated during the refine sub-flow
    from the change text + any newly-added element's placement). When empty or
    unknown, re-renders every decorated view — the safe fallback."""
    all_views = render_views(collected)
    wanted = {v for v in (collected.get("refine_views") or []) if v in all_views}
    return [v for v in all_views if v in wanted] or all_views


def view_has_logo(collected: dict, view: str) -> bool:
    """True if this view carries an uploaded-logo element (so only that view's
    render should receive the uploaded artwork as a second image)."""
    return any(el.get("type") == "logo" for el in elements_for_view(collected, view))


def reference_image_url_for_view(product_ref: dict, view: str) -> str:
    """The product reference photo for a specific angle (falls back to front)."""
    views = product_ref.get("view_images") or {}
    return views.get(view) or product_ref.get("reference_image_url") or ""


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


_ZONE_LABEL = {"front_panel": "front panel", "side": "side", "back": "main back panel (not the strap)", "under_brim": "under the brim"}


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


def _has_discrete_decoration(collected: dict) -> bool:
    """True if the design captures at least one text/graphic element discretely —
    in which case the per-element enumeration owns the wording, not the flat brief."""
    return any(el.get("type") in ("text", "graphic") for el in (collected.get("elements") or []))


def _brief_without_owned_decorations(collected: dict) -> dict | None:
    """Drop the flat brief's decoration-describing fields (``summary`` +
    ``text_elements``) when discrete text/graphic elements already own the design.

    The legacy ``design_description`` accumulator is not kept in sync with the
    per-element deep-dive: it can hold a stale/incomplete shadow of an element's
    text (session VKV2NBdIYqgtQ_23J0uANA captured a back-panel text as
    "handwritten text (content not specified)" before its content — "Satish" —
    was known, then leaked that phantom text onto the FRONT hero). The enumerated
    elements are authoritative for wording; only overall imagery/colours/style
    survive here as supplementary context."""
    brief = collected.get("design_description")
    if not isinstance(brief, dict) or not _has_discrete_decoration(collected):
        return brief
    return {k: v for k, v in brief.items() if k not in ("summary", "text_elements")}


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


def _augment_design_block(design_block: str, collected: dict) -> str:
    """Append the requested-change and per-section colour notes (both global,
    so they apply to every view's render)."""
    change = collected.get("change_request")
    if change:
        design_block = (
            f"{design_block}\nRequested change from the customer: {change}."
            "\nStart from the CURRENT DESIGN image (the existing design on this cap) "
            "and change ONLY what is requested — keep every other detail identical."
        )
    # Per-section colour instructions / colour remarks captured at the colour
    # deep-dive (blank flow) — apply them to the cap and pass to the team.
    colour_note = (collected.get("colour_note") or "").strip()
    if colour_note:
        design_block = f"{design_block}\nCustomer's colour details (apply per section): {colour_note}."
    # Free-form notes the customer added at the pre-generation confirmation step.
    notes = [str(n).strip() for n in (collected.get("brief_notes") or []) if str(n).strip()]
    if notes:
        design_block = f"{design_block}\nCustomer's notes/requests: {'; '.join(notes)}."
    return design_block


def _render_template(
    collected: dict, product_ref: dict, params: GenerationParams, design_block: str
) -> str:
    """Assemble the final image prompt from a ready-made ``design_block``."""
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

    is_blank = collected.get("flow_mode") == "blank"
    template = prompts.IMAGE_GEN_PROMPT_BLANK if is_blank else prompts.IMAGE_GEN_PROMPT

    fmt = dict(
        decoration_kind=decoration_kind,
        design_block=design_block,
        decoration_style=decoration_style,
        pin_block=pin_block,
    )
    if is_blank:
        # The colour is chosen in chat now (collected["hat_colour"]); fall back
        # to the product ref colour for any legacy session that carried it there.
        hc = collected.get("hat_colour")
        name = hc.get("name") if isinstance(hc, dict) else (hc if isinstance(hc, str) else None)
        fmt["hat_colour"] = name or product_ref.get("colour") or "the customer's chosen colour"
    return template.format(**fmt)


def build_prompt(collected: dict, product_ref: dict, params: GenerationParams) -> str:
    if not product_ref or not product_ref.get("reference_image_url"):
        raise PromptBuildError("product reference_image_url missing — cannot composite")
    design_block = _augment_design_block(_design_block(collected), collected)
    return _render_template(collected, product_ref, params, design_block)


def build_view_prompt(
    collected: dict, product_ref: dict, params: GenerationParams, view: str
) -> str:
    """Build the image prompt for a SINGLE view, enumerating only that view's
    elements onto that view's reference photo.

    A view with no elements renders the clean cap (or, for the primary front
    view, whatever overall brief context exists). The global brief and the
    uploaded logo are scoped to the view that actually carries them so a
    back-panel render doesn't try to re-apply front decoration.
    """
    if not product_ref or not product_ref.get("reference_image_url"):
        raise PromptBuildError("product reference_image_url missing — cannot composite")

    view_elements = elements_for_view(collected, view)
    if view_elements:
        scoped = {**collected, "elements": view_elements}
        if view != PRIMARY_VIEW:
            # Overall brief / uploaded logo belong to the primary view only.
            scoped["design_description"] = None
            scoped["uploaded_asset_path"] = None
        else:
            # The per-element enumeration owns the wording; keep only the flat
            # brief's overall context so a stale text shadow can't leak onto the
            # hero (regression: session VKV2NBdIYqgtQ_23J0uANA).
            scoped["design_description"] = _brief_without_owned_decorations(collected)
        design_block = _design_block(scoped)
    else:
        brief = _brief_without_owned_decorations(collected)
        brief_ctx = _brief_context_block({"design_description": brief}) if view == PRIMARY_VIEW else ""
        design_block = brief_ctx or prompts.NO_DECORATION_DESIGN_BLOCK

    design_block = _augment_design_block(design_block, collected)
    return _render_template(collected, product_ref, params, design_block)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()
