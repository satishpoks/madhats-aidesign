from app.services import colours


def test_name_to_hex_basic_css_names():
    assert colours.name_to_hex("blue") == "#0000ff"
    assert colours.name_to_hex("navy") == "#000080"


def test_name_to_hex_handles_spaces_and_case():
    assert colours.name_to_hex("Forest Green") == "#228b22"


def test_name_to_hex_unknown_returns_none():
    assert colours.name_to_hex("definitely-not-a-colour") is None
    assert colours.name_to_hex("") is None


def test_resolve_hex_prefers_explicit_hex():
    assert colours.resolve_hex({"name": "blue", "hex": "#123456"}) == "#123456"


def test_resolve_hex_from_name_when_no_hex():
    # This is the "blue overlays with grey" fix: a typed name resolves to blue.
    assert colours.resolve_hex({"name": "blue", "hex": ""}) == "#0000ff"


def test_resolve_hex_falls_back_to_grey_for_unknown():
    assert colours.resolve_hex({"name": "xyzzy", "hex": ""}) == "#808080"


def test_resolve_hex_accepts_bare_string():
    assert colours.resolve_hex("red") == "#ff0000"
