from app.services import canvas_describe as cd


def test_logo_element_carries_asset_path():
    design = {"faces": {"front": [
        {"type": "image", "assetUrl": "http://x/sign/y?t=1",
         "assetPath": "canvas_front_ab.png", "x": 0.1, "y": 0.1,
         "width": 0.2, "height": 0.2, "zIndex": 0},
    ], "back": [], "left": [], "right": []}}
    elements, _ = cd.canvas_to_elements(design)
    logo = elements[0]
    assert logo["type"] == "logo"
    assert logo["assetPath"] == "canvas_front_ab.png"
    assert logo["assetUrl"] == "http://x/sign/y?t=1"


def test_element_label_covers_kinds():
    assert 'SATISH' in cd.element_label(
        {"type": "text", "content": "SATISH", "colour": "#ffffff", "font": "Arial"})
    assert cd.element_label(
        {"type": "shape", "shapeKind": "rect", "fill": "blue", "filled": True}
    ) == "filled blue rectangle"
    assert cd.element_label(
        {"type": "drawing", "stroke": "#111827"}) == "a hand-drawn line in #111827"
    assert cd.element_label({"type": "image"}) == "uploaded logo/artwork"
