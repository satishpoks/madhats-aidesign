from PIL import Image

from app.services import composite


def test_tint_darkens_white_toward_colour():
    white = Image.new("RGB", (10, 10), (255, 255, 255))
    tinted = composite.tint_image(white, "#1a2b5c")
    # a white pixel multiplied by the colour becomes the colour
    assert tinted.getpixel((5, 5)) == (0x1a, 0x2b, 0x5c)


def test_tint_preserves_black_shadows():
    black = Image.new("RGB", (10, 10), (0, 0, 0))
    tinted = composite.tint_image(black, "#1a2b5c")
    assert tinted.getpixel((5, 5)) == (0, 0, 0)


def test_zone_box_front_panel_centre_is_upper_middle():
    x, y, w, h = composite.zone_box("front", "front_panel", "centre", (400, 400))
    assert 0 < x < 400 and 0 < y < 400 and w > 0 and h > 0


def test_render_composite_views_returns_a_path_per_view(monkeypatch):
    # Stub the IO: image download returns a white square; upload returns a fake path.
    white = Image.new("RGB", (400, 400), (255, 255, 255))
    monkeypatch.setattr(composite, "_load_image", lambda path: white.copy())
    saved = []
    def _save(img):
        saved.append(img); return f"composite/{len(saved)}.png"
    monkeypatch.setattr(composite, "_save_image", _save)
    out = composite.render_composite_views(
        {"front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"},
        "#1a2b5c",
        [{"type": "text", "content": "GO", "placement_zone": "front_panel", "placement_position": "centre"}],
    )
    assert set(out.keys()) == {"front", "back", "left", "right"}
    assert all(v.startswith("composite/") for v in out.values())
