"""app.services.design_summary — placement + brief derived from collected["elements"].

Regression coverage for whole-branch review Finding 2: downstream summaries
(sales emails, ops alerts, the quote page) must read the element model, not
the retired flat placement_zone/placement_position/design_description fields.
"""
from __future__ import annotations

from app.services import design_summary as ds


def test_primary_placement_reads_first_elements_placement():
    collected = {
        "elements": [
            {"type": "text", "content": "TEAM", "placement_zone": "side", "placement_position": "left"},
            {"type": "graphic", "content": "star", "placement_zone": "back"},
        ]
    }
    assert ds.primary_placement(collected) == ("side", "left")


def test_primary_placement_skips_elements_with_no_zone():
    collected = {
        "elements": [
            {"type": "note", "content": "match jersey blue"},
            {"type": "text", "content": "TEAM", "placement_zone": "back"},
        ]
    }
    assert ds.primary_placement(collected) == ("back", "centre")


def test_primary_placement_falls_back_to_legacy_flat_fields():
    collected = {"placement_zone": "under_brim", "placement_position": "right"}
    assert ds.primary_placement(collected) == ("under the brim", "right")


def test_primary_placement_defaults_when_nothing_set():
    assert ds.primary_placement({}) == ("front panel", "centre")


def test_summarise_elements_multi_element_brief():
    collected = {
        "elements": [
            {
                "type": "text", "content": "TEAM SPIRIT", "style": "bold", "colour": "gold",
                "placement_zone": "front_panel", "placement_position": "centre",
            },
            {
                "type": "graphic", "content": "a star", "style": "minimalist", "colour": "navy",
                "placement_zone": "side",
            },
            {"type": "logo", "placement_zone": "front_panel"},
            {"type": "note", "content": "match jersey blue"},
        ]
    }
    brief = ds.summarise_elements(collected)
    assert 'Text "TEAM SPIRIT" — bold, gold, on the front panel (centre)' in brief
    assert "Graphic: a star — minimalist, navy, on the side" in brief
    assert "Uploaded logo — on the front panel" in brief
    assert "Note to team: match jersey blue" in brief


def test_summarise_elements_skips_deferred_attributes():
    collected = {
        "elements": [
            {"type": "text", "content": "TEAM", "colour": "gold", "style": "bold", "deferred": ["style"]},
        ]
    }
    brief = ds.summarise_elements(collected)
    assert "bold" not in brief
    assert "gold" in brief


def test_summarise_elements_skips_element_with_no_content():
    collected = {"elements": [{"type": "text", "placement_zone": "side"}]}
    assert ds.summarise_elements(collected) == ""


def test_summarise_elements_falls_back_to_flat_design_description():
    collected = {"design_description": {"summary": "a mountain crest"}}
    assert ds.summarise_elements(collected) == "a mountain crest"


def test_summarise_elements_empty_when_nothing_present():
    assert ds.summarise_elements({}) == ""
