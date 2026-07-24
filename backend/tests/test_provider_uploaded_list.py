from __future__ import annotations

import inspect
import io

from PIL import Image

from app.services.image.adapters import gemini_base
from app.services.image.adapters.stub import StubAdapter
from app.services.image.image_provider import GenerationParams, ImageProvider


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def test_generate_signature_has_uploaded_asset_urls():
    assert "uploaded_asset_urls" in inspect.signature(ImageProvider.generate).parameters
    assert "uploaded_asset_urls" in inspect.signature(StubAdapter.generate).parameters


async def test_stub_accepts_list():
    res = await StubAdapter().generate(
        prompt="p", reference_image_url="http://x/ref.png",
        uploaded_asset_url=None, params=GenerationParams(tier="preview"),
        uploaded_asset_urls=["http://x/a.png", "http://x/b.png"],
    )
    assert res.image_url


class _Inline:
    def __init__(self, data): self.data = data


class _Part:
    def __init__(self, data): self.inline_data = _Inline(data)


class _Content:
    def __init__(self, parts): self.parts = parts


class _Cand:
    def __init__(self, parts):
        self.content = _Content(parts)
        self.finish_reason = "STOP"
        self.safety_ratings = []


class _Resp:
    def __init__(self): self.candidates = [_Cand([_Part(_png())])]


class _FakeModel:
    def __init__(self, name): pass
    async def generate_content_async(self, contents): return _Resp()


async def test_gemini_attaches_one_artwork_part_per_url(monkeypatch):
    monkeypatch.setattr(gemini_base.settings, "gemini_api_key", "test-key")
    monkeypatch.setattr(gemini_base.genai, "configure", lambda **k: None)
    monkeypatch.setattr(gemini_base.genai, "GenerativeModel", _FakeModel)
    monkeypatch.setattr(gemini_base, "write_generated", lambda b, tier: "generated/x.png")

    async def _fake_fetch(url):
        return _png(), "image/png"

    monkeypatch.setattr(gemini_base, "_fetch_bytes", _fake_fetch)

    adapter = gemini_base._GeminiAdapter("test-model")
    res = await adapter.generate(
        prompt="p", reference_image_url="http://x/ref.png",
        uploaded_asset_url=None, params=GenerationParams(tier="preview"),
        uploaded_asset_urls=["http://x/a.png", "http://x/b.png"],
    )
    art = [p for p in res.request_payload["contents"] if p.get("role") == "uploaded_asset"]
    assert len(art) == 2
    assert [p["source_url"] for p in art] == ["http://x/a.png", "http://x/b.png"]
