"""Pure branding validation + public serialization (no DB, no network)."""
from __future__ import annotations

import pytest

from app.services import branding


def test_validate_brand_accepts_valid():
    cleaned = branding.validate_brand({
        "primary_colour": "#FF5C00",
        "header_bg": "#fff",
        "header_text": "#1A1D29",
        "menu_items": [{"label": "  Shop  ", "url": "https://x.example/s"}],
    })
    assert cleaned["primary_colour"] == "#FF5C00"
    assert cleaned["menu_items"] == [{"label": "Shop", "url": "https://x.example/s"}]


def test_validate_brand_rejects_bad_hex():
    with pytest.raises(ValueError):
        branding.validate_brand({"primary_colour": "orange"})


def test_validate_brand_rejects_too_many_menu_items():
    items = [{"label": f"L{i}", "url": "https://x.example"} for i in range(6)]
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": items})


def test_validate_brand_rejects_non_http_url():
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": [{"label": "x", "url": "javascript:alert(1)"}]})


def test_validate_brand_rejects_empty_label():
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": [{"label": "   ", "url": "https://x.example"}]})


def test_public_brand_proxies_logo_and_drops_internal(monkeypatch):
    monkeypatch.setattr(branding, "media_url", lambda p, base: f"{base}media/tok" if p else None)
    out = branding.public_brand(
        {
            "primary_colour": "#FF5C00",
            "header_bg": "#ffffff",
            "header_text": "#000000",
            "logo_url": "uploads/logo.png",
            "watermark_asset_url": "uploads/wm.png",  # internal — must be dropped
            "menu_items": [{"label": "Shop", "url": "https://x.example"}],
        },
        "http://api/",
    )
    assert out["logo_url"] == "http://api/media/tok"
    assert out["primary_colour"] == "#FF5C00"
    assert out["menu_items"] == [{"label": "Shop", "url": "https://x.example"}]
    assert "watermark_asset_url" not in out


def test_public_brand_handles_none():
    assert branding.public_brand(None, "http://api/") == {}
