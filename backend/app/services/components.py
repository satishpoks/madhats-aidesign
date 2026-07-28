"""Enumerate the complete uploaded/derived component set for a session.

Used by the sales notification (attachments) and the admin quote-requests view
(download links). Returns storage PATHS only — external URLs (Shopify product
photos, stub placeholders) are excluded because they aren't ours to hand over and
can't be downloaded via storage.download_asset. PII-safe: paths carry no customer
identity.
"""
from __future__ import annotations

_FACES = ("front", "back", "left", "right")


def _is_storage_path(value) -> bool:
    return bool(value) and isinstance(value, str) and not value.startswith("http")


def _element_asset_path(el: dict):
    """`canvas_describe._element` writes camelCase `assetPath`; v1-shaped
    elements use `asset_path`. Reading only the snake form is why per-element
    canvas assets appeared in no admin component list and no sales attachment.
    """
    return el.get("assetPath") or el.get("asset_path")


def _element_label(index: int, el: dict) -> str:
    """Name the element and its face, and shout the background flag.

    Reads `remove_bg` — the field `prompt_builder` reads to instruct the render
    — never `collected["logos"][].bg`, which records the chip answer and is
    documented as able to diverge from the toggle.
    """
    kind = el.get("type") or "element"
    face = (el.get("canvas") or {}).get("face") or el.get("placement_zone")
    label = f"Element {index} — {kind}" + (f" ({face})" if face else "")
    if el.get("remove_bg"):
        label += " — BACKGROUND TO BE REMOVED"
    return label


def enumerate_components(collected: dict, generation: dict | None = None) -> list[dict]:
    """Every downloadable component for a session, as ``{"label", "path"}``.

    Sources, in a stable order: the uploaded asset, each face's flattened canvas
    preview, each face's layout guide, each element's own asset, and (when a
    render exists) the rendered generation image per view.
    """
    collected = collected or {}
    out: list[dict] = []

    up = collected.get("uploaded_asset_path")
    if _is_storage_path(up):
        out.append({"label": "Uploaded logo/artwork", "path": up})

    previews = collected.get("canvas_previews") or {}
    for face in _FACES:
        p = previews.get(face)
        if _is_storage_path(p):
            out.append({"label": f"Canvas preview — {face}", "path": p})

    layouts = collected.get("canvas_layouts") or {}
    for face in _FACES:
        p = layouts.get(face)
        if _is_storage_path(p):
            out.append({"label": f"Layout guide — {face}", "path": p})

    for i, el in enumerate(collected.get("elements") or [], start=1):
        p = _element_asset_path(el)
        if _is_storage_path(p):
            out.append({"label": _element_label(i, el), "path": p})

    if generation:
        views = generation.get("view_images") or {}
        for face in _FACES:
            entry = views.get(face) or {}
            p = entry.get("image_url") or entry.get("watermarked_url")
            if _is_storage_path(p):
                out.append({"label": f"Rendered — {face}", "path": p})

    return out
