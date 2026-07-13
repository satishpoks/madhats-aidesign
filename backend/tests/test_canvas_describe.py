from app.services.canvas_describe import canvas_to_elements, FACE_ZONE


def test_text_on_front_maps_to_front_panel_element():
    design = {
        "colourway": {"name": "Navy", "hex": "#1e3a8a"},
        "faces": {
            "front": [{
                "id": "e1", "type": "text", "x": 0.4, "y": 0.3,
                "width": 0.2, "height": 0.1, "rotation": 0, "zIndex": 0,
                "content": "SURF CO", "font": "Impact", "colour": "#ffffff", "fontSize": 42,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    assert len(elements) == 1
    el = elements[0]
    assert el["type"] == "text"
    assert el["content"] == "SURF CO"
    assert el["placement_zone"] == "front_panel"
    assert el["colour"] == "#ffffff"
    assert el["font"] == "Impact"
    assert el["canvas"]["face"] == "front"
    assert "SURF CO" in description and "front panel" in description


def test_image_on_left_maps_to_side_left_logo():
    design = {
        "colourway": None,
        "faces": {
            "front": [], "back": [],
            "left": [{
                "id": "e2", "type": "image", "x": 0.5, "y": 0.5,
                "width": 0.3, "height": 0.3, "rotation": 0, "zIndex": 0,
                "assetUrl": "uploads/logo.png", "removeBg": True,
            }],
            "right": [],
        },
    }
    elements, _ = canvas_to_elements(design)
    assert elements[0]["type"] == "logo"
    assert elements[0]["placement_zone"] == "side"
    assert elements[0]["placement_position"] == "left"
    assert elements[0]["remove_bg"] is True


def test_face_zone_map_covers_all_four_faces():
    assert set(FACE_ZONE) == {"front", "back", "left", "right"}
