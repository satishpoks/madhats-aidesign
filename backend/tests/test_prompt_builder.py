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


# --- build_params reads per-element placement --------------------------------

def test_build_params_reads_first_element_placement():
    params = prompt_builder.build_params(
        {"elements": [{"type": "text", "content": "HI", "placement_zone": "back",
                       "placement_position": "left", "remove_bg": True}]}, "preview")
    assert params.placement_zone == "back"
    assert params.placement_position == "left"
    assert params.remove_bg is True


# --- cap fidelity lock ------------------------------------------------------

def test_cap_lock_directive_always_present():
    prompt = _build({"elements": [{"type": "text", "content": "a star", "deferred": []}]})
    assert "REPRODUCE THE CAP EXACTLY" in prompt
    # a representative sample of the locked attributes
    assert "strap" in prompt.lower()
    assert "silhouette" in prompt.lower()
    assert "colour" in prompt.lower()


def test_customer_content_excludes_system_scaffolding():
    """Moderation runs over customer_content(), NOT the full prompt.

    Regression: the LLM moderator flagged the assembled fidelity-lock prompt
    ("PRIMARY DIRECTIVE / MUST / Do NOT alter …") as a jailbreak ~83% of the
    time, returning 422 and stranding legitimate designs at generation. The
    moderated string must contain the customer's own words but none of the
    imperative system scaffolding.
    """
    collected = {
        "elements": [{"type": "text", "content": "Sharks FC 2026", "deferred": []}],
        "brief_notes": ["please make the text gold"],
    }
    content = prompt_builder.customer_content(collected)

    # Customer's own words are present…
    assert "Sharks FC 2026" in content
    assert "gold" in content
    # …but the jailbreak-triggering system scaffolding is not.
    assert "PRIMARY DIRECTIVE" not in content
    assert "REPRODUCE THE CAP EXACTLY" not in content
    assert "Do NOT" not in content


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


def test_logo_remove_bg_adds_knockout_instruction():
    prompt = _build({"elements": [{"type": "logo", "content": "uploaded logo",
        "asset_path": "uploads/logo.png", "placement_zone": "front_panel",
        "remove_bg": True, "deferred": []}],
        "uploaded_asset_path": "uploads/logo.png"})
    assert "knock out the background" in prompt.lower()


def test_logo_without_remove_bg_has_no_knockout_instruction():
    prompt = _build({"elements": [{"type": "logo", "content": "uploaded logo",
        "asset_path": "uploads/logo.png", "placement_zone": "front_panel",
        "remove_bg": False, "deferred": []}],
        "uploaded_asset_path": "uploads/logo.png"})
    assert "knock out the background" not in prompt.lower()


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


# --- rich brief context reaches the prompt (regression: dropped detail) ------

def test_brief_context_imagery_colours_style_included():
    """The rich design_description brief (imagery/colours/style/extra text) that
    Haiku accumulates across turns must reach the model — previously _design_block
    only enumerated `elements` and dropped the brief entirely."""
    collected = {
        "elements": [{"type": "graphic", "content": "a mountain range", "deferred": []}],
        "design_description": {
            "summary": "a mountain range at sunset",
            "imagery": ["snow-capped peaks", "a rising sun"],
            "colours": ["orange", "deep purple"],
            "style": "vintage outdoors badge",
            "text_elements": ["EST. 2024"],
        },
    }
    prompt = _build(collected)
    assert "snow-capped peaks" in prompt
    assert "rising sun" in prompt
    assert "orange" in prompt and "deep purple" in prompt
    assert "vintage outdoors badge" in prompt
    assert "EST. 2024" in prompt


def test_brief_only_no_elements_still_renders_detail():
    """A brief with no discrete elements must still describe the design rather
    than fall back to the generic placeholder."""
    collected = {"design_description": {"imagery": ["a soaring eagle"], "colours": ["gold"]}}
    prompt = _build(collected)
    assert "soaring eagle" in prompt and "gold" in prompt
    assert prompts_fallback() not in prompt


def prompts_fallback():
    from app import prompts
    return prompts.FALLBACK_DESIGN_BLOCK


def test_no_brief_no_dangling_context_labels():
    """When there is no brief, no empty context labels leak into the prompt."""
    prompt = _build({"elements": [{"type": "text", "content": "HI", "deferred": []}]})
    assert "Imagery" not in prompt
    assert "Overall colours" not in prompt


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


# --- output framing: square, single cap, no title panel --------------------

def test_output_demands_square_single_cap_and_forbids_titles():
    prompt = _build({"elements": [{"type": "text", "content": "HI", "deferred": []}]}).lower()
    assert "square" in prompt
    assert "70-75%" in prompt                       # explicit cap coverage
    assert "title" in prompt and "caption" in prompt  # forbids a title/caption card
    assert "design name" in prompt and "customer name" in prompt
    assert "side-by-side" in prompt                 # collage still forbidden


# --- reference selection by placement zone ---------------------------------

def test_reference_uses_back_view_for_back_placement():
    product_ref = {
        "reference_image_url": "https://cdn/front.png",
        "view_images": {"front": "https://cdn/front.png", "back": "https://cdn/back.png"},
    }
    collected = {"elements": [{"type": "text", "content": "HI", "placement_zone": "back"}]}
    assert prompt_builder.reference_image_for(product_ref, collected) == "https://cdn/back.png"


def test_reference_falls_back_to_front_when_view_missing():
    product_ref = {"reference_image_url": "https://cdn/front.png", "view_images": {}}
    collected = {"elements": [{"type": "text", "content": "HI", "placement_zone": "back"}]}
    assert prompt_builder.reference_image_for(product_ref, collected) == "https://cdn/front.png"


def test_reference_front_placement_uses_default():
    product_ref = {
        "reference_image_url": "https://cdn/front.png",
        "view_images": {"front": "https://cdn/front.png", "back": "https://cdn/back.png"},
    }
    collected = {"elements": [{"type": "text", "content": "HI", "placement_zone": "front_panel"}]}
    assert prompt_builder.reference_image_for(product_ref, collected) == "https://cdn/front.png"


# --- blank-mode recolour variant (flow_mode == "blank") ---------------------

def test_blank_mode_prompt_mentions_recolour():
    collected = {"flow_mode": "blank", "elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "b/front.png", "colour": "Navy"}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    assert "Navy" in prompt
    assert "recolour" in prompt.lower() or "colour the cap" in prompt.lower()


def test_colour_note_included_in_prompt():
    """Per-section colour details captured at the colour deep-dive reach the model."""
    collected = {"flow_mode": "blank", "hat_colour": {"name": "Navy", "hex": "#1a2b5c"},
                 "colour_note": "white stitching and a red brim",
                 "elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "b/front.png", "colour": ""}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    assert "white stitching and a red brim" in prompt


def test_blank_mode_uses_chat_chosen_colour():
    """Colour is picked in chat now (collected['hat_colour']); the recolour
    instruction must use it even when product_ref.colour is empty."""
    collected = {"flow_mode": "blank", "hat_colour": {"name": "Forest Green", "hex": "#0b3d0b"},
                 "elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "b/front.png", "colour": ""}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    assert "Forest Green" in prompt


def test_customise_mode_prompt_unchanged():
    collected = {"elements": [{"type": "text", "content": "GO"}]}
    ref = {"reference_image_url": "p/front.png", "colour": "Black"}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    # customise mode still forbids recolour (fidelity-locked base prompt)
    assert "Do NOT recolour" in prompt


# --- canvas-blank recolour variant (flow_mode == "canvas" + canvas_blank) ---

def test_canvas_blank_session_uses_blank_template_and_colour():
    """A canvas session created from a HAT TYPE (collected['canvas_blank'] is
    True) must use the same recolour-capable IMAGE_GEN_PROMPT_BLANK template as
    the chat blank flow — not the colour-locked customise template."""
    collected = {
        "flow_mode": "canvas",
        "canvas_blank": True,
        "hat_colour": {"name": "Navy", "hex": "#1e3a8a"},
        "elements": [{"type": "text", "content": "GO"}],
    }
    ref = {"reference_image_url": "b/front.png", "colour": ""}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    assert "KEEP THE CAP SHAPE EXACTLY, RECOLOUR THE BODY" in prompt
    assert "Navy" in prompt


def test_canvas_customise_session_keeps_colour_locked_template():
    """A canvas session created from a PRODUCT (no canvas_blank marker) must
    stay on the colour-locked customise template, unchanged."""
    collected = {
        "flow_mode": "canvas",
        "elements": [{"type": "text", "content": "GO"}],
    }
    ref = {"reference_image_url": "p/front.png", "colour": "Black"}
    prompt = prompt_builder.build_prompt(collected, ref, _params(collected))
    assert "KEEP THE CAP SHAPE EXACTLY, RECOLOUR THE BODY" not in prompt
    assert "Do NOT recolour" in prompt
