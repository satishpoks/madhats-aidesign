"""element_planner — per-element attribute sequencing (pure functions)."""
from __future__ import annotations

from app.services.conversation import element_planner as ep


def test_text_asks_content_first_then_font():
    assert ep.next_attribute({"type": "text", "deferred": []}) == "content"
    assert ep.next_attribute({"type": "text", "content": "TEAM", "deferred": []}) == "font"


def test_deferred_attribute_is_skipped():
    el = {"type": "text", "content": "TEAM", "deferred": ["font"]}
    assert ep.next_attribute(el) == "size"


def test_set_attribute_is_skipped_bool_false_counts_as_set():
    el = {"type": "logo", "remove_bg": False, "deferred": []}
    assert ep.next_attribute(el) == "size"  # remove_bg=False is a real answer


def test_complete_when_all_set_or_deferred():
    el = {"type": "note", "content": "leave room on the back", "deferred": []}
    assert ep.next_attribute(el) is None
    assert ep.is_complete(el) is True


def test_defer_remaining_defers_non_content_only():
    el = {"type": "text", "content": "TEAM", "deferred": []}
    ep.defer_remaining(el)
    assert "content" not in el["deferred"]
    assert set(el["deferred"]) == {"font", "size", "colour", "style",
                                   "placement_zone", "placement_position"}
    assert ep.is_complete(el) is True
