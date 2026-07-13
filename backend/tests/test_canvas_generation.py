import inspect

from app.services.image.image_provider import ImageProvider


def test_generate_accepts_layout_guide_url():
    sig = inspect.signature(ImageProvider.generate)
    assert "layout_guide_url" in sig.parameters
    assert sig.parameters["layout_guide_url"].default is None
