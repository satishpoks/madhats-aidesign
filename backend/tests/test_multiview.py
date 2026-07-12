"""Multi-view generation: one AI render per decorated angle.

Covers the view-set computation + per-view prompt scoping (prompt_builder) and
the concurrent, all-or-nothing worker + stacked-image delivery.
"""
from __future__ import annotations

import asyncio

import httpx

from app.api.routes import generate as generate_routes
from app.services import prompt_builder
from app.services.image.image_provider import GenerationParams, GenerationResult

# --- view-set + per-view prompt scoping -------------------------------------


def test_render_views_front_only_when_no_back_side_elements():
    collected = {"elements": [{"type": "text", "content": "GO", "placement_zone": "front_panel"}]}
    assert prompt_builder.render_views(collected) == ["front"]


def test_render_views_adds_decorated_back_and_sides_in_order():
    collected = {
        "elements": [
            {"type": "text", "content": "GO", "placement_zone": "front_panel"},
            {"type": "graphic", "content": "logo", "placement_zone": "back"},
            {"type": "text", "content": "R", "placement_zone": "side", "placement_position": "right"},
        ]
    }
    # front always present; back + right added; canonical order.
    assert prompt_builder.render_views(collected) == ["front", "back", "right"]


def test_render_views_front_included_even_if_only_back_decorated():
    collected = {"elements": [{"type": "graphic", "content": "x", "placement_zone": "back"}]}
    assert prompt_builder.render_views(collected) == ["front", "back"]


def test_view_prompt_scopes_elements_to_the_view():
    product_ref = {"reference_image_url": "http://x/f.png", "view_images": {"front": "http://x/f.png", "back": "http://x/b.png"}}
    collected = {
        "elements": [
            {"type": "text", "content": "FRONTTEXT", "placement_zone": "front_panel"},
            {"type": "text", "content": "BACKTEXT", "placement_zone": "back"},
        ]
    }
    params = prompt_builder.build_params(collected, "preview")
    front = prompt_builder.build_view_prompt(collected, product_ref, params, "front")
    back = prompt_builder.build_view_prompt(collected, product_ref, params, "back")
    assert "FRONTTEXT" in front and "BACKTEXT" not in front
    assert "BACKTEXT" in back and "FRONTTEXT" not in back


def test_view_with_no_elements_renders_clean():
    product_ref = {"reference_image_url": "http://x/f.png", "view_images": {"front": "http://x/f.png", "back": "http://x/b.png"}}
    # Only the back is decorated; the front hero carries no element and no brief.
    collected = {"elements": [{"type": "text", "content": "BACKTEXT", "placement_zone": "back"}]}
    params = prompt_builder.build_params(collected, "preview")
    front = prompt_builder.build_view_prompt(collected, product_ref, params, "front")
    assert "No decoration is added on this view" in front


def test_reference_url_per_view_falls_back_to_front():
    product_ref = {"reference_image_url": "http://x/f.png", "view_images": {"front": "http://x/f.png"}}
    assert prompt_builder.reference_image_url_for_view(product_ref, "back") == "http://x/f.png"
    assert prompt_builder.reference_image_url_for_view(product_ref, "front") == "http://x/f.png"


def test_view_has_logo_only_for_logo_view():
    collected = {"elements": [
        {"type": "logo", "asset_path": "u/l.png", "placement_zone": "back"},
        {"type": "text", "content": "x", "placement_zone": "front_panel"},
    ]}
    assert prompt_builder.view_has_logo(collected, "back") is True
    assert prompt_builder.view_has_logo(collected, "front") is False


# --- concurrent, all-or-nothing worker --------------------------------------


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, rows, sink):
        self._table, self._rows, self._sink, self._u = table, rows, sink, None

    def select(self, *a, **k):
        return self

    def eq(self, f, v):
        self._rows = [r for r in self._rows if r.get(f) == v]
        return self

    def order(self, f, desc=False, **k):
        self._rows = sorted(self._rows, key=lambda r: r.get(f) or "", reverse=desc)
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def update(self, payload):
        self._u = payload
        return self

    def execute(self):
        if self._u is not None:
            self._sink.setdefault(self._table, []).append(self._u)
            for r in self._rows:
                r.update(self._u)
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, tables):
        self._t = tables
        self.sink = {}

    def table(self, name):
        return _Query(name, list(self._t.get(name, [])), self.sink)


def _ok(model="m"):
    return GenerationResult(
        image_url="generations/clean.png", cost_usd=0.01, latency_ms=100,
        model=model, raw_response={}, response_meta={"image_returned": True},
    )


class _PerViewProvider:
    """Returns a distinct image per call; optionally fails on a chosen call index."""

    def __init__(self, fail_on=None):
        self.calls = 0
        self._fail_on = fail_on

    async def generate(self, **kwargs):
        self.calls += 1
        if self._fail_on and self.calls == self._fail_on:
            raise httpx.TimeoutException("boom")
        return GenerationResult(
            image_url=f"generations/clean-{self.calls}.png", cost_usd=0.01, latency_ms=100,
            model="m", raw_response={}, response_meta={"image_returned": True},
        )


def _patch(monkeypatch, fake, provider, *, previews=None, alerts=None, sleeps=None):
    monkeypatch.setattr(generate_routes, "get_supabase", lambda: fake)
    monkeypatch.setattr(generate_routes.generation_cache, "lookup", lambda key: None)
    monkeypatch.setattr(generate_routes, "get_provider", lambda tier: provider)
    monkeypatch.setattr(generate_routes, "generate_signed_url", lambda p: f"signed:{p}")
    monkeypatch.setattr(generate_routes, "_make_watermarked", lambda p: f"wm:{p}")
    monkeypatch.setattr(generate_routes, "get_store", lambda s: None)
    monkeypatch.setattr(generate_routes.generation_logger, "log_request", lambda **k: "log")
    monkeypatch.setattr(generate_routes.generation_logger, "log_response", lambda *a, **k: None)
    monkeypatch.setattr(generate_routes.generation_logger, "log_cache_hit", lambda **k: None)

    async def _sleep(s):
        (sleeps if sleeps is not None else []).append(s)

    monkeypatch.setattr(generate_routes.asyncio, "sleep", _sleep)
    monkeypatch.setattr(
        generate_routes.delivery, "maybe_send_preview",
        lambda sid: (previews if previews is not None else []).append(sid) or True,
    )
    monkeypatch.setattr(
        generate_routes.email_service, "send_generation_alert",
        lambda *a, **k: (alerts if alerts is not None else []).append(a) or True,
    )


def _kwargs(**over):
    kw = dict(
        job_id="job-1", session_id="sess-1", store_id="s1", tier="preview",
        prompt="ignored — rebuilt per view",
        product_ref={"product_id": "p1", "colour": "black", "reference_image_url": "http://x/f.png",
                     "view_images": {"front": "http://x/f.png", "back": "http://x/b.png"}},
        collected={"elements": [
            {"type": "text", "content": "FRONT", "placement_zone": "front_panel"},
            {"type": "text", "content": "BACK", "placement_zone": "back"},
        ]},
        params=GenerationParams(tier="preview"),
    )
    kw.update(over)
    return kw


def test_two_views_render_and_store_view_images(monkeypatch):
    row = {"job_id": "job-1", "session_id": "sess-1", "status": "pending"}
    fake = _FakeSB({"generations": [row]})
    provider = _PerViewProvider()
    previews: list = []
    _patch(monkeypatch, fake, provider, previews=previews)

    asyncio.run(generate_routes._run_generation(**_kwargs()))

    assert provider.calls == 2  # front + back, one model call each
    assert row["status"] == "complete"
    assert set(row["view_images"].keys()) == {"front", "back"}
    # hero (front) is mirrored into image_url for backward compatibility
    assert row["image_url"] == row["view_images"]["front"]["image_url"]
    assert previews == ["sess-1"]


def test_all_or_nothing_one_view_fails_fails_whole_design(monkeypatch):
    row = {"job_id": "job-1", "session_id": "sess-1", "status": "pending"}
    fake = _FakeSB({"generations": [row]})

    # The back view fails all attempts (its prompt contains "BACK"); the front
    # view succeeds. All-or-nothing must fail the whole design.
    class _BackAlwaysFails(_PerViewProvider):
        async def generate(self, **kwargs):
            self.calls += 1
            # front call(s) succeed; any back-view prompt (contains "BACK") fails.
            if "BACK" in kwargs.get("prompt", ""):
                raise httpx.TimeoutException("back boom")
            return _ok()

    provider = _BackAlwaysFails()
    previews: list = []
    alerts: list = []
    _patch(monkeypatch, fake, provider, previews=previews, alerts=alerts)

    asyncio.run(generate_routes._run_generation(**_kwargs()))

    assert row["status"] == "failed"
    assert "back boom" in row["error"]
    assert previews == []       # nothing delivered
    assert len(alerts) == 1     # ops alerted


def test_edit_rerenders_only_affected_view_and_refines_from_prior(monkeypatch):
    # A back-only change re-renders ONLY the back, feeds the previous back design
    # as prior_design_url, and carries the front forward unchanged.
    prev_gen = {
        "id": "g0", "session_id": "sess-1", "status": "complete",
        "image_url": "gen/front0.png", "watermarked_url": "gen/front0w.png",
        "view_images": {
            "front": {"image_url": "gen/front0.png", "watermarked_url": "gen/front0w.png"},
            "back": {"image_url": "gen/back0.png", "watermarked_url": "gen/back0w.png"},
        },
        "created_at": "2026-07-12T00:00:00Z",
    }
    row = {"job_id": "job-1", "session_id": "sess-1", "status": "pending"}
    fake = _FakeSB({"generations": [row, prev_gen]})

    priors: list = []

    class _Prov:
        async def generate(self, **kwargs):
            priors.append(kwargs.get("prior_design_url"))
            return GenerationResult(
                image_url="gen/back1.png", cost_usd=0.01, latency_ms=10,
                model="m", raw_response={}, response_meta={},
            )

    _patch(monkeypatch, fake, _Prov(), previews=[])
    # Make _latest_complete_generation see the previous row (skip the pending one).
    monkeypatch.setattr(
        generate_routes, "_latest_complete_generation", lambda sid: prev_gen
    )

    collected = {
        "elements": [
            {"type": "text", "content": "FRONT", "placement_zone": "front_panel"},
            {"type": "text", "content": "BACK", "placement_zone": "back"},
        ],
        "refine_mode": True,
        "refine_views": ["back"],
        "change_request": "make the back text bigger",
    }
    asyncio.run(generate_routes._run_generation(
        job_id="job-1", session_id="sess-1", store_id="s1", tier="edit",
        prompt="ignored", provider_tier="preview",
        product_ref={"product_id": "p1", "colour": "black", "reference_image_url": "http://x/f.png",
                     "view_images": {"front": "http://x/f.png", "back": "http://x/b.png"}},
        collected=collected, params=GenerationParams(tier="edit"),
    ))

    assert row["status"] == "complete"
    # only the back re-rendered; front carried forward from the previous gen
    assert row["view_images"]["front"]["image_url"] == "gen/front0.png"
    assert row["view_images"]["back"]["image_url"] == "gen/back1.png"
    # exactly one render (back), refined from the previous back design
    assert priors == ["signed:gen/back0.png"]


def test_resume_designs_gated_on_verification(monkeypatch):
    """GET /sessions returns the completed design only once the email is
    verified (same reveal gate as the chat + email); never before."""
    from app.api.routes import sessions as sessions_routes

    gen = {
        "id": "g1", "session_id": "sess-1", "status": "complete",
        "image_url": "generations/f.png", "watermarked_url": "generations/fw.png",
        "view_images": {
            "front": {"image_url": "generations/f.png", "watermarked_url": "generations/fw.png"},
            "back": {"image_url": "generations/b.png", "watermarked_url": "generations/bw.png"},
        },
        "created_at": "2026-07-12T00:00:00Z",
    }

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *a, **k):
            return self

        def eq(self, f, v):
            self._rows = [r for r in self._rows if r.get(f) == v]
            return self

        def order(self, *a, **k):
            return self

        def limit(self, n):
            self._rows = self._rows[:n]
            return self

        def execute(self):
            return type("R", (), {"data": self._rows})()

    class _SB:
        def table(self, name):
            return _Q([gen] if name == "generations" else [])

    monkeypatch.setattr(sessions_routes, "generate_signed_url", lambda p: f"signed:{p}")
    sb = _SB()

    # Not verified -> no design leaked.
    assert sessions_routes._released_designs(sb, "sess-1", {"email_verified": False}) == []
    # Verified -> both views, front→back, signed watermarked.
    out = sessions_routes._released_designs(sb, "sess-1", {"email_verified": True})
    assert out == ["signed:generations/fw.png", "signed:generations/bw.png"]


def test_delivery_sends_all_views_stacked(monkeypatch):
    from app.services import delivery

    sent: dict = {}

    class _Q:
        def __init__(self, rows):
            self._rows = rows

        def select(self, *a, **k):
            return self

        def eq(self, f, v):
            self._rows = [r for r in self._rows if r.get(f) == v]
            return self

        def order(self, *a, **k):
            return self

        def limit(self, n):
            self._rows = self._rows[:n]
            return self

        def update(self, p):
            for r in self._rows:
                r.update(p)
            return self

        def execute(self):
            return type("R", (), {"data": self._rows})()

    lead = {"id": "l1", "session_id": "sess-1", "name": "Ann", "email": "a@x.com",
            "email_verified": True, "preview_email_sent": False, "quote_request_sent": True}
    gen = {"id": "g1", "session_id": "sess-1", "status": "complete",
           "image_url": "generations/f.png", "watermarked_url": "generations/fw.png",
           "view_images": {
               "front": {"image_url": "generations/f.png", "watermarked_url": "generations/fw.png"},
               "back": {"image_url": "generations/b.png", "watermarked_url": "generations/bw.png"},
           }}
    session = {"id": "sess-1", "collected": {"quantity": 10}, "product_ref": {"product_id": "p1"},
               "store_id": None, "share_token": "tok"}
    tables = {"leads": [lead], "generations": [gen], "design_sessions": [session]}

    class _SB:
        def table(self, name):
            return _Q(list(tables.get(name, [])))

    monkeypatch.setattr(delivery, "get_supabase", lambda: _SB())
    monkeypatch.setattr(delivery, "get_product", lambda *a, **k: {"name": "Cap"})
    monkeypatch.setattr(delivery, "generate_signed_url", lambda p: f"signed:{p}")
    monkeypatch.setattr(delivery, "_fetch_image_bytes", lambda url: f"bytes:{url}".encode())
    import app.services.stores as stores_mod
    monkeypatch.setattr(stores_mod, "get_store", lambda _s: None)

    def _fake_preview(*args, **kwargs):
        sent["images"] = kwargs.get("images")
        return True

    monkeypatch.setattr(delivery.email_service, "send_preview_email", _fake_preview)
    monkeypatch.setattr(delivery.email_service, "send_quote_to_sales", lambda *a, **k: True)

    assert delivery.maybe_send_preview("sess-1") is True
    imgs = sent["images"]
    assert [i["label"] for i in imgs] == ["Front", "Back"]
    assert imgs[0]["url"] == "signed:generations/fw.png"
    assert imgs[1]["url"] == "signed:generations/bw.png"
    assert all(i["bytes"] for i in imgs)
