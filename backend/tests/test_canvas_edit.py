"""Op resolution is a pure function of (raw ops, canvas_design) — plain dicts,
no LLM, no Supabase. The model picks intent; this module does the arithmetic."""
import pytest

from app.services.conversation import canvas_edit as ce


def _design():
    return {
        "colourway": None,
        "faces": {
            "front": [
                {"id": "logo1", "type": "image", "x": 0.4, "y": 0.4,
                 "width": 0.2, "height": 0.2, "rotation": 0, "zIndex": 0,
                 "assetUrl": "u.png"},
                {"id": "txt1", "type": "text", "x": 0.1, "y": 0.8,
                 "width": 0.3, "height": 0.1, "rotation": 0, "zIndex": 1,
                 "content": "MadHats", "colour": "#ffffff"},
            ],
            "back": [], "left": [], "right": [],
        },
    }


def test_inventory_lists_every_element_with_its_face():
    inv = ce.inventory(_design())
    assert [(e["id"], e["face"], e["type"]) for e in inv] == [
        ("logo1", "front", "image"), ("txt1", "front", "text")]
    assert "MadHats" in inv[1]["description"]


def test_move_up_subtracts_from_y_and_targets_the_right_face():
    ops = ce.resolve_ops(
        [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "small"}],
        _design())
    assert ops == [{"target": {"kind": "element", "id": "logo1", "face": "front"},
                    "patch": {"y": pytest.approx(0.35)}}]


def test_move_clamps_to_the_stage_and_never_goes_off_canvas():
    ops = ce.resolve_ops(
        [{"op": "move", "element_id": "txt1", "direction": "down", "amount": "large"}],
        _design())
    # y 0.8 + 0.20 = 1.0, but height 0.1 -> clamped to 0.9
    assert ops[0]["patch"]["y"] == pytest.approx(0.9)


def test_resize_bigger_scales_around_the_centre():
    ops = ce.resolve_ops(
        [{"op": "resize", "element_id": "logo1", "direction": "bigger", "amount": "small"}],
        _design())
    p = ops[0]["patch"]
    assert p["width"] == pytest.approx(0.23)      # 0.2 * 1.15
    assert p["x"] == pytest.approx(0.385)         # centre 0.5 held
    assert p["y"] == pytest.approx(0.385)


def test_rotate_accumulates_onto_the_current_rotation():
    ops = ce.resolve_ops(
        [{"op": "rotate", "element_id": "logo1", "direction": "clockwise", "amount": "medium"}],
        _design())
    assert ops[0]["patch"]["rotation"] == pytest.approx(15.0)


def test_recolour_writes_the_field_that_matches_the_element_type():
    ops = ce.resolve_ops(
        [{"op": "recolour", "element_id": "txt1", "colour": "red"}], _design())
    assert ops[0]["patch"] == {"colour": "#dc2626"}


def test_recolour_accepts_a_raw_hex():
    ops = ce.resolve_ops(
        [{"op": "recolour", "element_id": "txt1", "colour": "#123abc"}], _design())
    assert ops[0]["patch"] == {"colour": "#123abc"}


def test_set_text_and_font_and_curve():
    d = _design()
    assert ce.resolve_ops([{"op": "set_text", "element_id": "txt1", "text": "Hi"}], d)[0]["patch"] == {"content": "Hi"}
    assert ce.resolve_ops([{"op": "font", "element_id": "txt1", "font": "Bebas Neue"}], d)[0]["patch"] == {"font": "Bebas Neue"}
    assert ce.resolve_ops([{"op": "curve", "element_id": "txt1", "direction": "up"}], d)[0]["patch"] == {"curve": 40}


def test_delete_emits_a_remove_op():
    ops = ce.resolve_ops([{"op": "delete", "element_id": "txt1"}], _design())
    assert ops == [{"target": {"kind": "element", "id": "txt1", "face": "front"},
                    "remove": True}]


def test_a_hallucinated_element_id_is_dropped():
    # Ids are a closed set we own, so validation is an identity lookup.
    assert ce.resolve_ops(
        [{"op": "move", "element_id": "nope", "direction": "up", "amount": "small"}],
        _design()) == []


def test_an_unknown_op_or_amount_is_dropped_not_guessed():
    d = _design()
    assert ce.resolve_ops([{"op": "explode", "element_id": "logo1"}], d) == []
    assert ce.resolve_ops(
        [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "heaps"}], d) == []


def test_text_ops_are_dropped_for_a_non_text_element():
    assert ce.resolve_ops(
        [{"op": "set_text", "element_id": "logo1", "text": "no"}], _design()) == []


def test_resolve_ops_never_mutates_the_design_it_is_given():
    d = _design()
    ce.resolve_ops([{"op": "move", "element_id": "logo1", "direction": "up", "amount": "large"}], d)
    assert d["faces"]["front"][0]["y"] == 0.4
