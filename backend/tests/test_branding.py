"""Pure branding validation + public serialization (no DB, no network)."""
from __future__ import annotations

import pytest

from app.services import branding


def test_validate_brand_accepts_valid():
    cleaned = branding.validate_brand({
        "primary_colour": "#FF5C00",
        "header_bg": "#fff",
        "header_text": "#1A1D29",
        "menu_items": [{"label": "  Shop  ", "url": "https://x.example/s"}],
    })
    assert cleaned["primary_colour"] == "#FF5C00"
    assert cleaned["menu_items"] == [{"label": "Shop", "url": "https://x.example/s"}]


def test_validate_brand_rejects_bad_hex():
    with pytest.raises(ValueError):
        branding.validate_brand({"primary_colour": "orange"})


def test_validate_brand_rejects_too_many_menu_items():
    items = [{"label": f"L{i}", "url": "https://x.example"} for i in range(6)]
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": items})


def test_validate_brand_rejects_non_http_url():
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": [{"label": "x", "url": "javascript:alert(1)"}]})


def test_validate_brand_rejects_empty_label():
    with pytest.raises(ValueError):
        branding.validate_brand({"menu_items": [{"label": "   ", "url": "https://x.example"}]})


def test_public_brand_proxies_logo_and_drops_internal(monkeypatch):
    monkeypatch.setattr(branding, "media_url", lambda p, base: f"{base}media/tok" if p else None)
    out = branding.public_brand(
        {
            "primary_colour": "#FF5C00",
            "header_bg": "#ffffff",
            "header_text": "#000000",
            "logo_url": "uploads/logo.png",
            "watermark_asset_url": "uploads/wm.png",  # internal — must be dropped
            "menu_items": [{"label": "Shop", "url": "https://x.example"}],
        },
        "http://api/",
    )
    assert out["logo_url"] == "http://api/media/tok"
    assert out["primary_colour"] == "#FF5C00"
    assert out["menu_items"] == [{"label": "Shop", "url": "https://x.example"}]
    assert "watermark_asset_url" not in out


def test_public_brand_handles_none():
    assert branding.public_brand(None, "http://api/") == {}


# --- Workstream D: canvas_flow (admin-configurable step order) ----------------
# The id allow-list IS the guard keeping admins away from every dependency-locked
# step, so these tests are the safety boundary, not just schema polish.

def test_validate_brand_accepts_valid_canvas_flow():
    cleaned = branding.validate_brand({
        "canvas_flow": {"steps": [
            {"id": "ask_purpose", "enabled": False},
            {"id": "ask_quantity", "enabled": True},
        ]}
    })
    assert cleaned["canvas_flow"]["steps"] == [
        {"id": "ask_purpose", "enabled": False},
        {"id": "ask_quantity", "enabled": True},
    ]


def test_configurable_ids_are_sourced_from_the_registry():
    """The safe subset is intersected with REGISTRY by id string, so a step
    Workstream B has not merged yet (`needed_by`) simply drops out instead of
    raising at import — and becomes configurable for free once B ships it.

    This is why the test above does not name `needed_by`: asserting it is
    accepted would fail until B merges, and asserting it is rejected would fail
    after. The invariant that holds either way is the one asserted here.
    """
    from app.services.conversation import canvas_steps as cs

    registry_ids = {s.id.value for s in cs.REGISTRY}
    assert cs.CONFIGURABLE_STEP_IDS <= registry_ids
    assert cs.CONFIGURABLE_STEP_IDS <= cs._CONFIGURABLE_STEP_NAMES
    # Present today regardless of B:
    assert {"ask_quantity", "ask_purpose"} <= cs.CONFIGURABLE_STEP_IDS
    # needed_by is configurable exactly when the registry carries it:
    assert ("needed_by" in cs.CONFIGURABLE_STEP_IDS) is ("needed_by" in registry_ids)


def test_validate_brand_defaults_enabled_when_omitted():
    cleaned = branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_quantity"}]}})
    assert cleaned["canvas_flow"]["steps"] == [{"id": "ask_quantity", "enabled": True}]


def test_validate_brand_rejects_a_locked_step_id():
    # The guard that stops an admin ever disabling/reordering a locked step:
    # ask_email must precede finalize, so it is not in the configurable set.
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_email"}]}})


def test_validate_brand_rejects_a_prepare_bearing_step_id():
    # ask_decoration carries `prepare` (the store-scoped chip load) and may
    # satisfy its own step, so the Complexity gate locks it.
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_decoration"}]}})


def test_validate_brand_rejects_a_loop_step_id():
    # ASK_ANYTHING_ELSE is position-coupled to the decor loop.
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "ask_anything_else"}]}})


def test_validate_brand_rejects_an_unknown_step_id():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [{"id": "not_a_step"}]}})


def test_validate_brand_rejects_duplicate_step_ids():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": [
            {"id": "ask_quantity"}, {"id": "ask_quantity"},
        ]}})


def test_validate_brand_rejects_non_bool_enabled():
    with pytest.raises(ValueError):
        branding.validate_brand(
            {"canvas_flow": {"steps": [{"id": "ask_quantity", "enabled": "yes"}]}})


def test_validate_brand_rejects_non_list_steps():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": "ask_quantity"}})


def test_validate_brand_rejects_non_dict_canvas_flow():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": ["ask_quantity"]})


def test_validate_brand_rejects_non_dict_flow_step():
    with pytest.raises(ValueError):
        branding.validate_brand({"canvas_flow": {"steps": ["ask_quantity"]}})


def test_validate_brand_without_canvas_flow_is_untouched():
    # Baseline invariant: a brand with no canvas_flow key comes back identical.
    cleaned = branding.validate_brand({"primary_colour": "#FF5C00"})
    assert "canvas_flow" not in cleaned
