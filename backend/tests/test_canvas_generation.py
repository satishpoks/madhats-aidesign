import asyncio
import inspect
from unittest.mock import patch

from app.api.routes import generate as gen
from app.services.image.image_provider import ImageProvider


def test_generate_accepts_layout_guide_url():
    sig = inspect.signature(ImageProvider.generate)
    assert "layout_guide_url" in sig.parameters
    assert sig.parameters["layout_guide_url"].default is None


def test_canvas_run_renders_every_decorated_face(monkeypatch):
    """Canvas: every decorated face is AI-rendered with its own reference angle
    + layout guide. No face reuses its flat canvas PNG (the old splice is gone)."""
    seen = {"views": [], "layout_guides": {}, "refs": {}}

    async def fake_render_view(**kw):
        view = kw["view"]
        seen["views"].append(view)
        seen["layout_guides"][view] = kw["layout_guide_url"]
        seen["refs"][view] = kw["ref_url"]
        return {"ok": True, "view": view, "clean_path": f"gen/{view}.png",
                "watermarked_path": f"gen/{view}_wm.png", "model": "stub",
                "cost_usd": 0, "latency_ms": 1, "key": f"k_{view}", "attempts": 1,
                "from_cache": False}

    captured = {}

    class FakeTable:
        def update(self, d): captured.update(d); return self
        def eq(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": [{}]})()
        def insert(self, d): return self
        def select(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
    class FakeSB:
        def table(self, *_): return FakeTable()

    monkeypatch.setattr(gen, "get_supabase", lambda: FakeSB())
    monkeypatch.setattr(gen, "_render_view", fake_render_view)
    monkeypatch.setattr(gen, "_make_watermarked", lambda p: p + "_wm")
    monkeypatch.setattr(gen, "_safe_maybe_send_preview", lambda s: None)
    monkeypatch.setattr(gen, "get_provider", lambda t: object())
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed:{p}")

    collected = {
        "flow_mode": "canvas",
        "canvas_layouts": {"front": "uploads/front.png", "back": "uploads/back.png"},
        "elements": [
            {"type": "text", "content": "HI", "placement_zone": "front_panel"},
            {"type": "text", "content": "BACK", "placement_zone": "back"},
        ],
    }
    product_ref = {"product_id": "p1", "colour": "navy",
                   "reference_image_url": "http://x/front.png",
                   "view_images": {"front": "http://x/front.png", "back": "http://x/back.png"}}
    params = gen.prompt_builder.build_params(collected, "preview")

    asyncio.run(gen._run_generation(
        job_id="j1", session_id="s1", store_id=None, tier="preview",
        prompt="p", product_ref=product_ref, collected=collected, params=params))

    # Both decorated faces went to the model (order-independent).
    assert set(seen["views"]) == {"front", "back"}
    assert captured["status"] == "complete"
    assert set(captured["view_images"]) == {"front", "back"}
    # No face reuses its raw flat PNG — every image_url is a real render output.
    assert captured["view_images"]["back"]["image_url"] == "gen/back.png"
    assert captured["view_images"]["front"]["image_url"] == "gen/front.png"
    # Each render received its own layout guide (signed) + correct reference angle.
    assert seen["layout_guides"]["front"] == "signed:uploads/front.png"
    assert seen["layout_guides"]["back"] == "signed:uploads/back.png"
    assert seen["refs"]["front"] == "http://x/front.png"
    assert seen["refs"]["back"] == "http://x/back.png"


def test_canvas_cache_key_differs_by_layout_guide_path(monkeypatch):
    """Canvas descriptions are placement-agnostic (never mention pixel x/y), so
    two designs with identical elements but DIFFERENT layouts produce the same
    view_prompt. Without folding the layout-guide path into the cache key,
    those two sessions collide on the same key and the second serves the
    first's cached render, discarding its own layout guide. The key must
    differ when canvas_layouts[view] differs, even though view_prompt is
    identical."""
    captured_keys: list[str] = []

    async def fake_render_view(**kw):
        captured_keys.append(kw["key"])
        return {"ok": True, "view": kw["view"], "clean_path": "gen/front.png",
                "watermarked_path": "gen/front_wm.png", "model": "stub",
                "cost_usd": 0, "latency_ms": 1, "key": kw["key"], "attempts": 1, "from_cache": False}

    class FakeTable:
        def update(self, d): return self
        def eq(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": [{}]})()
        def insert(self, d): return self
        def select(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
    class FakeSB:
        def table(self, *_): return FakeTable()

    monkeypatch.setattr(gen, "get_supabase", lambda: FakeSB())
    monkeypatch.setattr(gen, "_render_view", fake_render_view)
    monkeypatch.setattr(gen, "_make_watermarked", lambda p: p + "_wm")
    monkeypatch.setattr(gen, "_safe_maybe_send_preview", lambda s: None)
    monkeypatch.setattr(gen, "get_provider", lambda t: object())
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed:{p}")

    base_collected = {
        "flow_mode": "canvas",
        "canvas_layouts": {"front": "uploads/layoutA.png"},
        "elements": [
            {"type": "text", "content": "HI", "placement_zone": "front_panel"},
        ],
    }
    product_ref = {"product_id": "p1", "colour": "navy",
                   "reference_image_url": "http://x/front.png",
                   "view_images": {"front": "http://x/front.png"}}
    params = gen.prompt_builder.build_params(base_collected, "preview")

    asyncio.run(gen._run_generation(
        job_id="j1", session_id="s1", store_id=None, tier="preview",
        prompt="p", product_ref=product_ref, collected=base_collected, params=params))

    other_collected = {**base_collected, "canvas_layouts": {"front": "uploads/layoutB.png"}}
    asyncio.run(gen._run_generation(
        job_id="j2", session_id="s2", store_id=None, tier="preview",
        prompt="p", product_ref=product_ref, collected=other_collected, params=params))

    assert len(captured_keys) == 2
    assert captured_keys[0] != captured_keys[1], (
        "same view_prompt + different canvas layout must yield different cache keys"
    )


def test_non_canvas_cache_key_unaffected_by_fix(monkeypatch):
    """Regression guard: a non-canvas (customise flow) render's cache key must
    stay byte-identical to before this fix — no layout string is folded in."""
    captured_keys: list[str] = []

    async def fake_render_view(**kw):
        captured_keys.append(kw["key"])
        return {"ok": True, "view": kw["view"], "clean_path": "gen/front.png",
                "watermarked_path": "gen/front_wm.png", "model": "stub",
                "cost_usd": 0, "latency_ms": 1, "key": kw["key"], "attempts": 1, "from_cache": False}

    class FakeTable:
        def update(self, d): return self
        def eq(self, *a, **k): return self
        def execute(self): return type("R", (), {"data": [{}]})()
        def insert(self, d): return self
        def select(self, *a, **k): return self
        def order(self, *a, **k): return self
        def limit(self, *a, **k): return self
    class FakeSB:
        def table(self, *_): return FakeTable()

    monkeypatch.setattr(gen, "get_supabase", lambda: FakeSB())
    monkeypatch.setattr(gen, "_render_view", fake_render_view)
    monkeypatch.setattr(gen, "_make_watermarked", lambda p: p + "_wm")
    monkeypatch.setattr(gen, "_safe_maybe_send_preview", lambda s: None)
    monkeypatch.setattr(gen, "get_provider", lambda t: object())
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed:{p}")

    collected = {
        "elements": [
            {"type": "text", "content": "HI", "placement_zone": "front_panel"},
        ],
    }
    product_ref = {"product_id": "p1", "colour": "navy",
                   "reference_image_url": "http://x/front.png",
                   "view_images": {"front": "http://x/front.png"}}
    params = gen.prompt_builder.build_params(collected, "preview")
    view_prompt = gen.prompt_builder.build_view_prompt(
        collected, product_ref, params, gen.prompt_builder.PRIMARY_VIEW
    )
    expected_key = gen.generation_cache.cache_key(
        "p1", "navy", gen.prompt_builder.prompt_hash(view_prompt), "none"
    )

    asyncio.run(gen._run_generation(
        job_id="j1", session_id="s1", store_id=None, tier="preview",
        prompt="p", product_ref=product_ref, collected=collected, params=params))

    assert captured_keys == [expected_key]
