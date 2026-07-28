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


def _canvas_element(**over):
    """Shaped exactly as canvas_describe._element writes it (camelCase asset)."""
    el = {"type": "logo", "content": "uploaded logo/artwork",
          "assetPath": "uploads/logo.png", "remove_bg": False,
          "placement_zone": "front", "canvas": {"face": "front"}}
    el.update(over)
    return el


def test_camelcase_assetpath_is_found():
    """canvas_describe writes assetPath; reading only asset_path meant canvas
    elements appeared in no admin list and no sales attachment."""
    out = components.enumerate_components({"elements": [_canvas_element()]})
    assert any(c["path"] == "uploads/logo.png" for c in out)


def test_v1_snake_case_asset_path_still_works():
    out = components.enumerate_components({"elements": [
        {"type": "logo", "asset_path": "uploads/old.png"}]})
    assert any(c["path"] == "uploads/old.png" for c in out)


def test_flagged_element_label_says_the_background_must_be_removed():
    out = components.enumerate_components({"elements": [_canvas_element(remove_bg=True)]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "BACKGROUND TO BE REMOVED" in label


def test_unflagged_element_label_does_not():
    out = components.enumerate_components({"elements": [_canvas_element(remove_bg=False)]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "BACKGROUND" not in label.upper()


def test_label_names_the_face():
    out = components.enumerate_components({"elements": [_canvas_element()]})
    label = next(c["label"] for c in out if c["path"] == "uploads/logo.png")
    assert "front" in label.lower()


def test_the_same_path_is_never_emitted_twice():
    """`uploaded_asset_path` is overwritten by every /uploads/logo call, so it
    ends up equal to the LAST element's assetPath — which emitted a duplicate
    sales-email attachment with an identical filename (the filename is derived
    from the path). First occurrence wins, so the stable ordering is kept."""
    collected = {"uploaded_asset_path": "uploads/logo.png",
                 "elements": [_canvas_element()]}
    out = components.enumerate_components(collected)
    paths = [c["path"] for c in out]
    assert paths.count("uploads/logo.png") == 1
    assert "Uploaded" in out[0]["label"]        # first occurrence retained


def test_external_urls_are_still_excluded():
    out = components.enumerate_components({"elements": [
        _canvas_element(assetPath="https://cdn.example.com/x.png")]})
    assert not any("example.com" in c["path"] for c in out)


def test_dedupe_never_drops_the_background_removal_marker():
    """The collision above is the COMMON case on a single-logo canvas design:
    `uploaded_asset_path` equals the last element's `assetPath`, and the generic
    "Uploaded logo/artwork" entry sorts first — so keeping the first occurrence
    silently discarded the element label's `— BACKGROUND TO BE REMOVED`, which
    is the entire signal the print team acts on.
    """
    collected = {"uploaded_asset_path": "uploads/logo.png",
                 "elements": [_canvas_element(remove_bg=True)]}
    out = components.enumerate_components(collected)
    paths = [c["path"] for c in out]

    assert paths.count("uploads/logo.png") == 1        # still deduped
    assert "Uploaded" in out[0]["label"]               # ordering unchanged
    assert "BACKGROUND TO BE REMOVED" in out[0]["label"]


def test_dedupe_does_not_invent_the_marker_when_no_element_is_flagged():
    collected = {"uploaded_asset_path": "uploads/logo.png",
                 "elements": [_canvas_element(remove_bg=False)]}
    out = components.enumerate_components(collected)
    assert "BACKGROUND" not in out[0]["label"].upper()


def test_the_marker_is_merged_only_onto_the_colliding_entry():
    """A second, unrelated component must not pick the marker up."""
    collected = {"uploaded_asset_path": "uploads/logo.png",
                 "canvas_layouts": {"front": "uploads/lay_f.png"},
                 "elements": [_canvas_element(remove_bg=True)]}
    out = components.enumerate_components(collected)
    lay = next(c for c in out if c["path"] == "uploads/lay_f.png")
    assert "BACKGROUND" not in lay["label"].upper()
