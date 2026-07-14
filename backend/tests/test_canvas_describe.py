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
    assert el["colour"] == "white"  # #ffffff mapped to a plain name for the model
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


def test_shape_maps_to_graphic_with_description():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "s1", "type": "shape", "shapeKind": "rect",
                "x": 0.3, "y": 0.3, "width": 0.3, "height": 0.2, "rotation": 0, "zIndex": 0,
                "fill": "#2563eb", "filled": True,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    el = elements[0]
    assert el["type"] == "graphic"
    assert "rectangle" in el["content"] and "filled" in el["content"]
    assert el["placement_zone"] == "front_panel"
    assert el["colour"] == "#2563eb"
    assert "rectangle" in description


def test_outlined_and_line_shapes_described():
    design = {
        "colourway": None,
        "faces": {
            "front": [
                {"id": "c1", "type": "shape", "shapeKind": "circle", "x": 0.1, "y": 0.1,
                 "width": 0.2, "height": 0.2, "rotation": 0, "zIndex": 0, "fill": "#ff0000", "filled": False},
                {"id": "a1", "type": "shape", "shapeKind": "doubleArrow", "x": 0.4, "y": 0.5,
                 "width": 0.3, "height": 0.06, "rotation": 0, "zIndex": 1, "fill": "#00ff00"},
            ],
            "back": [], "left": [], "right": [],
        },
    }
    elements, _ = canvas_to_elements(design)
    assert "outlined" in elements[0]["content"]  # filled=False
    assert "double-headed arrow" in elements[1]["content"]  # no filled/outlined prefix for lines
    assert "filled" not in elements[1]["content"] and "outlined" not in elements[1]["content"]


def test_curved_text_gets_style_hint():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "e1", "type": "text", "x": 0.4, "y": 0.3,
                "width": 0.2, "height": 0.1, "rotation": 0, "zIndex": 0,
                "content": "SURF CO", "font": "Impact", "colour": "#ffffff",
                "fontSize": 42, "curve": 60,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, _ = canvas_to_elements(design)
    assert elements[0]["style"] == "curved"


def test_text_description_carries_no_pixel_dimensions():
    design = {
        "colourway": None,
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
    # Raw pixel size must not leak into the element (layout guide owns size).
    assert "size" not in elements[0]
    assert "px" not in description
    assert "42" not in description


def test_text_without_colour_defaults_to_white():
    # The canvas renders an unset text colour as white; it must be captured so it
    # reaches the image model (an unset colour was previously dropped and the white
    # text vanished from the render — session 3zftLzunVKZQCPvS5eNUNw).
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "e1", "type": "text", "x": 0.4, "y": 0.3,
                "width": 0.2, "height": 0.1, "rotation": 0, "zIndex": 0,
                "content": "Satish", "font": "Arial",
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    assert elements[0]["colour"] == "white"
    assert "in white" in description


def test_drawing_maps_to_graphic_with_stroke_colour():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "d1", "type": "drawing", "x": 0, "y": 0, "width": 0, "height": 0,
                "rotation": 0, "zIndex": 0, "points": [0.1, 0.1, 0.5, 0.5],
                "stroke": "#ff0000", "strokeWidth": 0.01,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    el = elements[0]
    assert el["type"] == "graphic"
    assert "hand-drawn line" in el["content"]
    assert el["colour"] == "#ff0000"
    assert el["placement_zone"] == "front_panel"
    assert "hand-drawn line" in description
    assert "0.1" not in description  # no pixel/normalised coords leak into the text
