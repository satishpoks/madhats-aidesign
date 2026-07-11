"""merge_brief — lossless accumulation of design elements into one brief."""
from __future__ import annotations

from app.services.conversation.brief import merge_brief


def test_merge_appends_and_dedupes_lists():
    existing = {"text_elements": ["SUMMIT CO"], "imagery": ["mountain"]}
    incoming = {"text_elements": ["SUMMIT CO", "EST 2020"], "imagery": ["compass"]}
    out = merge_brief(existing, incoming)
    assert out["text_elements"] == ["SUMMIT CO", "EST 2020"]
    assert out["imagery"] == ["mountain", "compass"]


def test_merge_fills_empty_scalars_only():
    out = merge_brief({"summary": "first"}, {"summary": "second", "style": "bold"})
    assert out["summary"] == "first"      # first non-empty summary wins
    assert out["style"] == "bold"          # style was empty -> filled


def test_incoming_summary_becomes_text_element_when_summary_taken():
    # No-LLM path: a second freeform element arrives as {"summary": ...}. It must
    # not be dropped just because summary is already set.
    out = merge_brief({"summary": "our logo"}, {"summary": "team name in gold"})
    assert out["summary"] == "our logo"
    assert "team name in gold" in out["text_elements"]


def test_empty_fields_pruned():
    out = merge_brief({}, {"summary": "x", "text_elements": [], "colours": [""]})
    assert out == {"summary": "x"}
