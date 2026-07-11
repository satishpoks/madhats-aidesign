"""prompt_builder.build_prompt() — fidelity-locked image prompt assembly.

The prompt must hard-lock every attribute of the base cap to the reference photo
and describe only the decoration to add. See
docs/superpowers/specs/2026-07-01-fidelity-locked-image-prompt-design.md.
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
    prompt = _build({"design_description": {"summary": "a star"}})
    assert "REPRODUCE THE CAP EXACTLY" in prompt
    # a representative sample of the locked attributes
    assert "strap" in prompt.lower()
    assert "silhouette" in prompt.lower()
    assert "colour" in prompt.lower()


def test_missing_reference_image_raises():
    with pytest.raises(PromptBuildError):
        prompt_builder.build_prompt(
            {"design_description": {"summary": "x"}},
            {"style": "cap"},  # no reference_image_url
            _params({}),
        )


# --- Flow B: uploaded logo --------------------------------------------------

def test_uploaded_asset_references_second_image():
    collected = {"uploaded_asset_path": "uploads/logo.png"}
    prompt = _build(collected)
    assert "SECOND image" in prompt
    # must not fabricate a described-design placeholder
    assert "supplied logo/artwork" not in prompt


def test_uploaded_asset_forbids_standalone_logo_reproduction():
    """Flow B regression: Gemini was echoing the uploaded logo as its own panel
    beside the cap (a two-panel collage). The prompt must direct the model to
    apply the artwork ONTO the cap and never reproduce it as a separate copy."""
    collected = {"uploaded_asset_path": "uploads/logo.png"}
    prompt = _build(collected).lower()
    assert "onto the cap" in prompt
    assert "separate" in prompt


# --- single-subject output (no collage) -------------------------------------

def test_output_forbids_collage_and_locks_framing():
    """Every prompt must pin the output to one cap framed like the reference —
    no side-by-side/split-screen panels."""
    prompt = _build({"design_description": {"summary": "a star"}}).lower()
    assert "collage" in prompt
    assert "side-by-side" in prompt
    assert "aspect ratio" in prompt


# --- Flow A: described design intent ----------------------------------------

def test_described_design_weaves_all_structured_fields():
    collected = {
        "design_description": {
            "summary": "bold mountain crest",
            "text_elements": ["SUMMIT CO", "EST 2020"],
            "colours": ["white", "gold"],
            "imagery": ["mountain peak", "compass"],
            "style": "vintage",
        }
    }
    prompt = _build(collected)
    assert "bold mountain crest" in prompt
    assert "SUMMIT CO" in prompt and "EST 2020" in prompt
    assert "white" in prompt and "gold" in prompt
    assert "mountain peak" in prompt and "compass" in prompt
    assert "vintage" in prompt


def test_described_design_omits_empty_fields():
    collected = {
        "design_description": {
            "summary": "simple text logo",
            "text_elements": [],
            "colours": [],
            "imagery": [],
            "style": "",
        }
    }
    prompt = _build(collected)
    assert "simple text logo" in prompt
    # empty structured fields must not leave dangling labels
    assert "Text to include" not in prompt
    assert "Graphics/icons" not in prompt


# --- decoration style -------------------------------------------------------

def test_embroidery_selects_stitched_kind_and_modifier():
    collected = {"decoration_type": "embroidery", "design_description": {"summary": "x"}}
    prompt = _build(collected)
    assert "stitched embroidery" in prompt.lower()
    assert "EMBROIDERY" in prompt


def test_print_selects_printed_kind_and_modifier():
    collected = {"decoration_type": "print", "design_description": {"summary": "x"}}
    prompt = _build(collected)
    assert "printed graphic" in prompt.lower()
    assert "PRINT" in prompt


# --- placement + pins -------------------------------------------------------

def test_placement_zone_and_position_present():
    collected = {
        "design_description": {"summary": "x"},
        "placement_zone": "side_panel",
        "placement_position": "left",
    }
    prompt = _build(collected)
    assert "side panel" in prompt
    assert "left" in prompt


def test_pins_appended_when_present():
    collected = {
        "design_description": {"summary": "x"},
        "pin_annotations": [
            {"view": "front", "x_pct": 40, "y_pct": 55, "comment": "a bit higher"}
        ],
    }
    prompt = _build(collected)
    assert "a bit higher" in prompt


def test_no_pin_block_when_absent():
    prompt = _build({"design_description": {"summary": "x"}})
    assert "placement note" not in prompt.lower()


def test_uploaded_asset_includes_gathered_elements():
    collected = {
        "uploaded_asset_path": "uploads/logo.png",
        "design_description": {
            "text_elements": ["TEAM SPIRIT"],
            "colours": ["gold"],
            "imagery": ["star"],
        },
    }
    prompt = _build(collected)
    assert "SECOND image" in prompt          # logo still composited
    assert "TEAM SPIRIT" in prompt           # gathered text reaches the model
    assert "gold" in prompt
    assert "star" in prompt


def test_uploaded_asset_without_extras_has_no_dangling_labels():
    collected = {"uploaded_asset_path": "uploads/logo.png"}
    prompt = _build(collected)
    assert "SECOND image" in prompt
    assert "Text to include" not in prompt
    assert "Graphics/icons" not in prompt
