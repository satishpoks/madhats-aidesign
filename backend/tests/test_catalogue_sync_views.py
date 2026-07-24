"""_map_views records only genuine angles + front — no fabricated aliases (C6.1)."""
from __future__ import annotations

from app.services.catalogue_sync import _map_views


def test_no_genuine_angles_records_only_front():
    srcs = ["https://x/cap-1.jpg", "https://x/cap-2.jpg", "https://x/cap-3.jpg"]
    views = _map_views(srcs)
    assert views == {"front": "https://x/cap-1.jpg"}
    assert "back" not in views and "left" not in views and "right" not in views


def test_keyword_matched_angles_are_kept():
    srcs = [
        "https://x/cap-front.jpg",
        "https://x/cap-back.jpg",
        "https://x/cap-left-side.jpg",
    ]
    views = _map_views(srcs)
    assert views["front"] == "https://x/cap-front.jpg"
    assert views["back"] == "https://x/cap-back.jpg"
    assert views["left"] == "https://x/cap-left-side.jpg"
    assert "right" not in views      # no genuine right angle -> absent


def test_empty_srcs_is_empty():
    assert _map_views([]) == {}
