from app.api.routes import generate as gen


def _collected():
    # Mirrors canvas_describe output: front logo (path A), back logo (path B).
    return {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel", "placement_position": "centre",
         "assetPath": "canvas_front_A.png", "assetUrl": "http://x/sign/madhats-assets/canvas_front_A.png?t=1"},
        {"type": "logo", "placement_zone": "back", "placement_position": "centre",
         "assetPath": "canvas_back_B.png", "assetUrl": "http://x/sign/madhats-assets/canvas_back_B.png?t=1"},
    ]}


def test_front_gets_front_logo_only(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    assert gen._canvas_view_images(_collected(), "front") == ["signed://canvas_front_A.png"]


def test_back_gets_back_logo_only(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    assert gen._canvas_view_images(_collected(), "back") == ["signed://canvas_back_B.png"]


def test_recovers_path_from_signed_url_when_no_assetpath(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    c = {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel",
         "assetUrl": "http://x/storage/v1/object/sign/madhats-assets/old_front.png?t=9"},
    ]}
    assert gen._canvas_view_images(c, "front") == ["signed://old_front.png"]


def test_company_graphic_media_url_passthrough(monkeypatch):
    c = {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel", "assetUrl": "http://api/media/tok123"},
    ]}
    assert gen._canvas_view_images(c, "front") == ["http://api/media/tok123"]
