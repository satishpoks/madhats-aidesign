from app.services.branding import canvas_intro_text, validate_brand
from app import prompts

import pytest


def test_default_when_unset():
    assert canvas_intro_text(None) == prompts.V2_DEFAULT_INTRO
    assert canvas_intro_text({"brand": {}}) == prompts.V2_DEFAULT_INTRO


def test_returns_admin_text():
    store = {"brand": {"canvas_intro": "Custom welcome!"}}
    assert canvas_intro_text(store) == "Custom welcome!"


def test_validate_keeps_intro():
    out = validate_brand({"canvas_intro": "Hello team"})
    assert out["canvas_intro"] == "Hello team"


def test_validate_rejects_overlong_intro():
    with pytest.raises(ValueError):
        validate_brand({"canvas_intro": "x" * 601})
