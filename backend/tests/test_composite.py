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


def test_side_element_with_right_position_draws_on_right_view_only(monkeypatch):
    white = Image.new("RGB", (400, 400), (255, 255, 255))
    monkeypatch.setattr(composite, "_load_image", lambda path: white.copy())
    monkeypatch.setattr(composite, "_save_image", lambda img: "composite/x.png")

    drawn_views = []

    def _fake_draw_element(img, el, view):
        drawn_views.append(view)

    monkeypatch.setattr(composite, "_draw_element", _fake_draw_element)

    composite.render_composite_views(
        {"front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"},
        "#1a2b5c",
        [{"type": "text", "content": "GO", "placement_zone": "side", "placement_position": "right"}],
    )

    assert drawn_views == ["right"]
    assert "left" not in drawn_views


def test_side_element_with_left_or_default_position_draws_on_left_view():
    assert composite._element_view({"placement_zone": "side", "placement_position": "left"}) == "left"
    assert composite._element_view({"placement_zone": "side"}) == "left"
    assert composite._element_view({"placement_zone": "side", "placement_position": "centre"}) == "left"


def test_malformed_element_does_not_abort_render(monkeypatch):
    white = Image.new("RGB", (400, 400), (255, 255, 255))
    monkeypatch.setattr(composite, "_load_image", lambda path: white.copy())
    saved = []

    def _save(img):
        saved.append(img)
        return f"composite/{len(saved)}.png"

    monkeypatch.setattr(composite, "_save_image", _save)

    out = composite.render_composite_views(
        {"front": "b/f", "back": "b/b", "left": "b/l", "right": "b/r"},
        "#1a2b5c",
        [{"type": "text", "content": None, "placement_zone": "front_panel"}],
    )

    assert set(out.keys()) == {"front", "back", "left", "right"}


def test_draw_element_handles_none_content_for_text_and_graphic(monkeypatch):
    img = Image.new("RGB", (400, 400), (255, 255, 255))
    # Should not raise for text with None content.
    composite._draw_element(img, {"type": "text", "content": None, "placement_zone": "front_panel"}, "front")
    # Should not raise for a described-graphic placeholder with None content.
    composite._draw_element(img, {"type": "graphic", "content": None, "placement_zone": "front_panel"}, "front")


def test_composite_logo_skip_log_does_not_leak_signed_url(monkeypatch):
    img = Image.new("RGB", (400, 400), (255, 255, 255))

    def _boom(path):
        raise RuntimeError("https://signed.example/secret-token?sig=abc123")

    monkeypatch.setattr(composite, "_load_image", _boom)

    import structlog
    from structlog.testing import LogCapture

    log_output = LogCapture()
    structlog.configure(processors=[log_output], logger_factory=structlog.ReturnLoggerFactory())
    try:
        composite._draw_element(
            img,
            {"type": "logo", "asset_path": "some/path.png", "placement_zone": "front_panel"},
            "front",
        )
    finally:
        structlog.reset_defaults()

    skip_logs = [entry for entry in log_output.entries if entry.get("event") == "composite_logo_skip"]
    assert skip_logs, "expected a composite_logo_skip log entry"
    for entry in skip_logs:
        assert entry.get("error") == "RuntimeError"
        assert "signed.example" not in str(entry)
        assert "secret-token" not in str(entry)
