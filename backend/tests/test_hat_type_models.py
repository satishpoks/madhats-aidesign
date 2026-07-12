from app.models.hat_type import CreateHatTypeRequest, HatTypePublic


def test_create_defaults():
    req = CreateHatTypeRequest(name="5-Panel", slug="five-panel")
    assert req.style == ""
    assert req.colours == []
    assert req.placement_zones == []


def test_public_shape_has_signed_view_urls():
    pub = HatTypePublic(
        id="h1", name="5-Panel", style="", slug="five-panel",
        view_images={"front": "https://x/front"}, colours=[{"name": "Black", "hex": "#000000"}],
        placement_zones=["front_panel"], decoration_types=["print"],
    )
    assert pub.view_images["front"].startswith("https://")
