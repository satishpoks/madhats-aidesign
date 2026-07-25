from app.services.branding import canvas_intro_text, validate_brand
from app import prompts
from app.services import branding

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


def test_colour_disclaimer_uses_store_links_when_set():
    store = {"brand": {
        "colour_ref_embroidery_url": "https://acme.test/embroidery",
        "colour_ref_print_url": "https://acme.test/print",
    }}
    out = branding.colour_disclaimer_text(store, "Sam")
    assert "https://acme.test/embroidery" in out
    assert "https://acme.test/print" in out
    assert "Sam" in out
    assert "{" not in out and "}" not in out  # fully rendered, single-pass safe


def test_colour_disclaimer_falls_back_to_dummy_defaults():
    out = branding.colour_disclaimer_text(None, "there")
    assert prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL in out
    assert prompts.V2_DEFAULT_COLOUR_PRINT_URL in out


def test_validate_brand_accepts_colour_ref_links():
    cleaned = branding.validate_brand({
        "colour_ref_embroidery_url": "https://acme.test/e",
        "colour_ref_print_url": "http://acme.test/p",
    })
    assert cleaned["colour_ref_embroidery_url"] == "https://acme.test/e"
    assert cleaned["colour_ref_print_url"] == "http://acme.test/p"


def test_validate_brand_rejects_non_http_colour_ref_link():
    with pytest.raises(ValueError):
        branding.validate_brand({"colour_ref_embroidery_url": "ftp://acme.test/e"})


def test_validate_brand_drops_empty_colour_ref_link():
    cleaned = branding.validate_brand({"colour_ref_embroidery_url": ""})
    assert "colour_ref_embroidery_url" not in cleaned
