"""Enumerate the uploaded/derived component set for a quote request (C5)."""
from __future__ import annotations

from app.services import components


def test_enumerate_components_covers_every_source():
    collected = {
        "uploaded_asset_path": "uploads/logo.png",
        "canvas_previews": {"front": "composite/f.png", "back": "composite/b.png"},
        "canvas_layouts": {"front": "uploads/lay_f.png"},
        "elements": [
            {"type": "logo", "asset_path": "uploads/el1.png"},
            {"type": "text", "content": "hi"},                       # no path — skipped
            {"type": "logo", "assetUrl": "https://cdn/x.png"},       # external — skipped
        ],
    }
    gen = {"view_images": {"front": {"image_url": "generated/preview/hero.png",
                                     "watermarked_url": "watermarked/hero.png"}}}
    out = components.enumerate_components(collected, gen)
    labels = {c["label"] for c in out}
    paths = {c["path"] for c in out}

    assert "uploads/logo.png" in paths
    assert "composite/f.png" in paths and "composite/b.png" in paths
    assert "uploads/lay_f.png" in paths
    assert "uploads/el1.png" in paths
    assert "generated/preview/hero.png" in paths      # rendered image included when present
    assert "https://cdn/x.png" not in paths           # external element skipped
    assert all("path" in c and "label" in c for c in out)
    assert any("Uploaded" in lbl for lbl in labels)


def test_enumerate_components_empty_without_render():
    assert components.enumerate_components({}, None) == []
