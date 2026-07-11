"""prompt_builder.build_prompt() — fidelity-locked image prompt assembly.

The prompt must hard-lock every attribute of the base cap to the reference photo
and describe only the decoration to add, one block per element with its own
placement. See docs/superpowers/specs/2026-07-01-fidelity-locked-image-prompt-design.md.
"""
from __future__ import annotations

import pytest

from app.services import prompt_builder
from app.services.prompt_builder import PromptBuildError


def _params(collected, tier="preview"):
    return prompt_builder.build_params(collected, tier)


def _ref(**overrides):
    ref = {
        "reference_image_url": "https://cdn/ref.png",
        "style": "6-panel snapback",
        "colour": "black",
    }
    ref.update(overrides)
    return ref


def _build(collected, ref=None):
    ref = ref or _ref()
    return prompt_builder.build_prompt(collected, ref, _params(collected))


# --- cap fidelity lock ------------------------------------------------------

def test_cap_lock_directive_always_present():
    prompt = _build({"elements": [{"type": "text", "content": "a star", "deferred": []}]})
    assert "REPRODUCE THE CAP EXACTLY" in prompt
    # a representative sample of the locked attributes
    assert "strap" in prompt.lower()
    assert "silhouette" in prompt.lower()
    assert "colour" in prompt.lower()


def test_missing_reference_image_raises():
    with pytest.raises(PromptBuildError):
        prompt_builder.build_prompt(
            {"elements": [{"type": "text", "content": "x", "deferred": []}]},
            {"style": "cap"},  # no reference_image_url
            _params({}),
        )


# --- element enumeration + per-element placement ----------------------------

def test_elements_enumerated_with_per_element_placement():
    collected = {"elements": [
        {"type": "text", "content": "TEAM SPIRIT", "font": "bold", "size": "large", "colour": "gold",
         "placement_zone": "front_panel", "placement_position": "centre", "deferred": []},
        {"type": "graphic", "content": "a star", "style": "minimalist", "colour": "navy",
         "placement_zone": "side", "deferred": ["size"]},
    ]}
    prompt = _build(collected)
    assert "TEAM SPIRIT" in prompt and "gold" in prompt and "front panel" in prompt
    assert "star" in prompt and "navy" in prompt and "side" in prompt


def test_note_element_is_team_context_not_render():
    prompt = _build({"elements": [{"type": "note", "content": "match our jersey blue", "deferred": []}]})
    assert "note to the team" in prompt.lower()
    assert "match our jersey blue" in prompt


def test_logo_element_keeps_second_image_directive():
    prompt = _build({"elements": [{"type": "logo", "content": "uploaded logo",
        "asset_path": "uploads/logo.png", "placement_zone": "front_panel", "deferred": []}],
        "uploaded_asset_path": "uploads/logo.png"})
    assert "SECOND image" in prompt
    assert "onto the cap" in prompt.lower()


def test_deferred_and_empty_attributes_skipped():
    prompt = _build({"elements": [{"type": "text", "content": "HI", "deferred": ["colour", "font"]}]})
    assert "Design colours" not in prompt and "font" not in prompt.lower()


def test_cap_lock_and_no_collage_still_present():
    prompt = _build({"elements": [{"type": "text", "content": "HI", "deferred": []}]}).lower()
    assert "reproduce the cap exactly" in prompt
    assert "collage" in prompt and "side-by-side" in prompt


# --- Flow B: uploaded logo --------------------------------------------------

def test_uploaded_asset_references_second_image():
    collected = {"uploaded_asset_path": "uploads/logo.png", "elements": [
        {"type": "logo", "content": "uploaded logo", "asset_path": "uploads/logo.png", "deferred": []},
    ]}
    prompt = _build(collected)
    assert "SECOND image" in prompt
    # must not fabricate a described-design placeholder
    assert "supplied logo/artwork" not in prompt


def test_uploaded_asset_forbids_standalone_logo_reproduction():
    """Flow B regression: Gemini was echoing the uploaded logo as its own panel
    beside the cap (a two-panel collage). The prompt must direct the model to
    apply the artwork ONTO the cap and never reproduce it as a separate copy."""
    collected = {"uploaded_asset_path": "uploads/logo.png", "elements": [
        {"type": "logo", "content": "uploaded logo", "asset_path": "uploads/logo.png", "deferred": []},
    ]}
    prompt = _build(collected).lower()
    assert "onto the cap" in prompt
    assert "separate" in prompt


# --- single-subject output (no collage) -------------------------------------

def test_output_forbids_collage_and_locks_framing():
    """Every prompt must pin the output to one cap framed like the reference —
    no side-by-side/split-screen panels."""
    prompt = _build({"elements": [{"type": "text", "content": "a star", "deferred": []}]}).lower()
    assert "collage" in prompt
    assert "side-by-side" in prompt
    assert "aspect ratio" in prompt


# --- decoration style -------------------------------------------------------

def test_embroidery_selects_stitched_kind_and_modifier():
    collected = {"decoration_type": "embroidery", "elements": [{"type": "text", "content": "x", "deferred": []}]}
    prompt = _build(collected)
    assert "stitched embroidery" in prompt.lower()
    assert "EMBROIDERY" in prompt


def test_print_selects_printed_kind_and_modifier():
    collected = {"decoration_type": "print", "elements": [{"type": "text", "content": "x", "deferred": []}]}
    prompt = _build(collected)
    assert "printed graphic" in prompt.lower()
    assert "PRINT" in prompt


# --- pins --------------------------------------------------------------------

def test_pins_appended_when_present():
    collected = {
        "elements": [{"type": "text", "content": "x", "deferred": []}],
        "pin_annotations": [
            {"view": "front", "x_pct": 40, "y_pct": 55, "comment": "a bit higher"}
        ],
    }
    prompt = _build(collected)
    assert "a bit higher" in prompt


def test_no_pin_block_when_absent():
    prompt = _build({"elements": [{"type": "text", "content": "x", "deferred": []}]})
    assert "placement note" not in prompt.lower()


def test_prompt_keeps_physical_realism_instruction():
    prompt = _build({"elements": [{"type": "text", "content": "HI", "deferred": []}]}).lower()
    assert "physically applied" in prompt
    assert "curvature" in prompt
