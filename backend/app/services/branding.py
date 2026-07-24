"""Pure per-store branding helpers: validation for admin writes and a public
serializer for the customer storefront. No DB, no network — trivially testable.

Brand shape (all keys optional) stored in stores.brand jsonb:
    { logo_url, primary_colour, header_bg, header_text,
      watermark_asset_url (internal), menu_items: [{label, url}] }
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app import prompts
from app.storage import media_url

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_MENU_ITEMS = 5
MAX_LABEL_LEN = 40
_COLOUR_KEYS = ("primary_colour", "header_bg", "header_text")
# Fields exposed to the public storefront (watermark_asset_url is internal).
_PUBLIC_KEYS = ("logo_url", "primary_colour", "header_bg", "header_text")


def _validate_menu_items(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("menu_items must be a list")
    if len(raw) > MAX_MENU_ITEMS:
        raise ValueError(f"at most {MAX_MENU_ITEMS} menu items allowed")
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each menu item must be an object")
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not label:
            raise ValueError("menu item label is required")
        if len(label) > MAX_LABEL_LEN:
            raise ValueError(f"menu item label exceeds {MAX_LABEL_LEN} chars")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("menu item url must be an http(s) URL")
        cleaned.append({"label": label, "url": url})
    return cleaned


def _validate_canvas_flow(raw) -> dict:
    """Validate a per-store canvas flow config (V3 admin-configurable order).

    The id allow-list IS the guard that keeps admins away from every
    dependency-locked step: only the curated safe subset
    (`canvas_steps.CONFIGURABLE_STEP_IDS`) may be named, so a locked step can
    never be disabled or reordered through this door. The import is
    function-local to avoid a module-load cycle (canvas_steps pulls in
    leads/intent_extractor, which reach back into config/storage).
    """
    from app.services.conversation.canvas_steps import CONFIGURABLE_STEP_IDS

    if not isinstance(raw, dict):
        raise ValueError("canvas_flow must be an object")
    steps = raw.get("steps", [])
    if not isinstance(steps, list):
        raise ValueError("canvas_flow.steps must be a list")
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in steps:
        if not isinstance(item, dict):
            raise ValueError("each flow step must be an object")
        sid = item.get("id")
        if sid not in CONFIGURABLE_STEP_IDS:
            raise ValueError(f"step '{sid}' is not reorderable/optional")
        if sid in seen:
            raise ValueError(f"duplicate flow step '{sid}'")
        seen.add(sid)
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("flow step 'enabled' must be a boolean")
        cleaned.append({"id": sid, "enabled": enabled})
    return {"steps": cleaned}


def validate_brand(brand: dict) -> dict:
    """Return a cleaned copy of ``brand``. Raise ValueError on invalid input.
    Unknown keys are preserved (e.g. watermark_asset_url set by other flows)."""
    if not isinstance(brand, dict):
        raise ValueError("brand must be an object")
    cleaned = dict(brand)
    for key in _COLOUR_KEYS:
        val = cleaned.get(key)
        if val in (None, ""):
            cleaned.pop(key, None)
            continue
        if not isinstance(val, str) or not HEX_RE.match(val):
            raise ValueError(f"{key} must be a hex colour like #FF5C00")
    if "menu_items" in cleaned:
        cleaned["menu_items"] = _validate_menu_items(cleaned["menu_items"])
    if "canvas_flow" in cleaned:
        cleaned["canvas_flow"] = _validate_canvas_flow(cleaned["canvas_flow"])
    intro = cleaned.get("canvas_intro")
    if intro is not None and (not isinstance(intro, str) or len(intro) > 600):
        raise ValueError("canvas_intro must be a string of at most 600 characters")
    return cleaned


def canvas_intro_text(store: dict | None) -> str:
    """The admin-set step-2 intro for the v2 canvas flow, or the MadHats default."""
    brand = (store or {}).get("brand") or {}
    text = brand.get("canvas_intro")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return prompts.V2_DEFAULT_INTRO


def public_brand(brand: dict | None, base_url: str) -> dict:
    """The safe subset a customer widget may see. Logo becomes a /media URL."""
    if not brand:
        return {}
    out: dict = {}
    for key in _PUBLIC_KEYS:
        val = brand.get(key)
        if not val:
            continue
        out[key] = media_url(val, base_url) if key == "logo_url" else val
    items = brand.get("menu_items")
    if isinstance(items, list) and items:
        out["menu_items"] = [
            {"label": i.get("label", ""), "url": i.get("url", "")}
            for i in items if isinstance(i, dict)
        ]
    return out
