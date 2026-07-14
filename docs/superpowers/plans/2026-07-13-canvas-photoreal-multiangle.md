# Canvas Photorealistic Multi-Angle Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every decorated face of a canvas design come back as a photorealistic Gemini render (front + back + left + right as applicable), instead of only the front, with the other faces reusing their flat canvas PNGs.

**Architecture:** The per-view rendering machinery (`render_views`, `build_view_prompt`, `reference_image_url_for_view`, and the layout-guide/cache-key handling inside `_run_generation._one`) already exists and is used by the non-canvas flow — it is merely bypassed for canvas sessions. The change flips the canvas branch to render the full decorated view set and removes the flat-PNG reuse splice; each face then renders with its real product-angle photo (conditioning) + its flattened canvas PNG (layout guide) + its extracted per-face component description. A small enrichment to `canvas_describe` keeps that description complete but coarse (no pixel coordinates).

**Tech Stack:** Python 3.12 / FastAPI, pytest, google-generativeai (Gemini), Pillow.

## Global Constraints

- **Composite onto the real product reference photo** — every generation call passes the real product angle photo as the conditioning FIRST image; never generate a cap from scratch.
- **No pixel coordinates in the text description** — exact placement is owned by the flattened canvas layout-guide image; the text description gives identity + styling + coarse zone words only. This preserves the property the cache-key test relies on (identical elements + different layouts → same `view_prompt`, differentiated only by the layout path folded into the key).
- **No secrets in code / no PII in logs** — unchanged; do not add customer name/email to any log line.
- Backend tests run with: `cd backend && python -m pytest -q` (or a focused `pytest path::test -v`).

---

### Task 1: Complete the extracted per-face description (`canvas_describe`)

Tighten `canvas_to_elements` so every captured attribute survives into the
element shape that `build_view_prompt` enumerates, keeping it coarse: map the
canvas `curve` prop to a `style` hint, and stop emitting raw pixel font sizes
(the layout guide owns exact size). No pixel x/y is ever written into a
description.

**Files:**
- Modify: `backend/app/services/canvas_describe.py:54-62` (the `text` branch of `_element`)
- Test: `backend/tests/test_canvas_describe.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `canvas_to_elements(canvas_design: dict) -> tuple[list[dict], str]` (unchanged signature). Text elements now carry `style: "curved"` when the canvas element has a truthy `curve`, and NO longer carry a `size` key.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_canvas_describe.py`:

```python
def test_curved_text_gets_style_hint():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "e1", "type": "text", "x": 0.4, "y": 0.3,
                "width": 0.2, "height": 0.1, "rotation": 0, "zIndex": 0,
                "content": "SURF CO", "font": "Impact", "colour": "#ffffff",
                "fontSize": 42, "curve": 60,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, _ = canvas_to_elements(design)
    assert elements[0]["style"] == "curved"


def test_text_description_carries_no_pixel_dimensions():
    design = {
        "colourway": None,
        "faces": {
            "front": [{
                "id": "e1", "type": "text", "x": 0.4, "y": 0.3,
                "width": 0.2, "height": 0.1, "rotation": 0, "zIndex": 0,
                "content": "SURF CO", "font": "Impact", "colour": "#ffffff", "fontSize": 42,
            }],
            "back": [], "left": [], "right": [],
        },
    }
    elements, description = canvas_to_elements(design)
    # Raw pixel size must not leak into the element (layout guide owns size).
    assert "size" not in elements[0]
    assert "px" not in description
    assert "42" not in description
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_canvas_describe.py::test_curved_text_gets_style_hint tests/test_canvas_describe.py::test_text_description_carries_no_pixel_dimensions -v`
Expected: FAIL — `test_curved_text_gets_style_hint` KeyError/assert on missing `style`; `test_text_description_carries_no_pixel_dimensions` fails because `elements[0]` still has `size: "42px"`.

- [ ] **Step 3: Update the `text` branch of `_element`**

In `backend/app/services/canvas_describe.py`, replace the `text` branch (currently lines 54-62):

```python
    if etype == "text":
        out["type"] = "text"
        out["content"] = el.get("content", "")
        if el.get("font"):
            out["font"] = el["font"]
        if el.get("colour"):
            out["colour"] = el["colour"]
        if el.get("fontSize"):
            out["size"] = f'{el["fontSize"]}px'
```

with:

```python
    if etype == "text":
        out["type"] = "text"
        out["content"] = el.get("content", "")
        if el.get("font"):
            out["font"] = el["font"]
        if el.get("colour"):
            out["colour"] = el["colour"]
        # Curved text: surface a coarse style hint. Exact size/placement is
        # owned by the flattened layout-guide image, so raw pixel font sizes
        # are intentionally NOT emitted into the text description.
        if el.get("curve"):
            out["style"] = "curved"
```

- [ ] **Step 4: Run the full `canvas_describe` suite to verify pass + no regression**

Run: `cd backend && python -m pytest tests/test_canvas_describe.py -v`
Expected: PASS — the two new tests plus all pre-existing ones (none assert on `size`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/canvas_describe.py backend/tests/test_canvas_describe.py
git commit -m "feat(canvas): coarse-but-complete element description (curve->style, drop px size)"
```

---

### Task 2: Render every decorated canvas face (`generate._run_generation`)

Flip the canvas branch to render the full decorated view set and remove the
flat-PNG reuse splice. No change is needed inside `_one(view)` — it already
attaches the per-view reference angle, the per-view layout guide, the
layout-sensitive cache key, and the per-view scoped prompt.

**Files:**
- Modify: `backend/app/api/routes/generate.py:299-301` (canvas branch — `views` selection)
- Modify: `backend/app/api/routes/generate.py:371-377` (remove the flat-PNG reuse splice)
- Modify: `backend/app/api/routes/generate.py:284-305` and `262-278` (refresh the docstring + inline canvas comments)
- Test: `backend/tests/test_canvas_generation.py`

**Interfaces:**
- Consumes: `prompt_builder.render_views(collected) -> list[str]` (front + every face carrying a decoration element, in canonical order `front, back, left, right`); `prompt_builder.PRIMARY_VIEW == "front"`.
- Produces: no signature change to `_run_generation`. Behavioural contract: for a canvas session, `generations.view_images` contains one entry per decorated face and every entry's `image_url` is a real render output (never a raw `canvas_layouts` `uploads/*.png` path).

- [ ] **Step 1: Rewrite the pinned-behaviour test + add the multi-face assertions**

In `backend/tests/test_canvas_generation.py`, DELETE the existing
`test_canvas_run_renders_front_and_reuses_flattened_for_back` (lines 15-69) and
replace it with:

```python
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
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `cd backend && python -m pytest tests/test_canvas_generation.py::test_canvas_run_renders_every_decorated_face -v`
Expected: FAIL — with the current code `seen["views"] == ["front"]` only, and `view_images["back"]["image_url"]` is the raw `uploads/back.png` (from the splice), so the `set(seen["views"]) == {"front", "back"}` / `gen/back.png` assertions fail.

- [ ] **Step 3: Flip the canvas branch to render all decorated faces**

In `backend/app/api/routes/generate.py`, replace the canvas branch (currently lines 299-301):

```python
    elif is_canvas:
        views = [prompt_builder.PRIMARY_VIEW]  # only the front hero is AI-rendered
        prev_views = {}
```

with:

```python
    elif is_canvas:
        # Every decorated face is AI-rendered: the front hero PLUS any back/side
        # face carrying decoration (prompt_builder.render_views). Each face's
        # _one() attaches its own reference angle, its flattened canvas PNG as the
        # layout guide, and its per-view scoped description.
        views = prompt_builder.render_views(collected)
        prev_views = {}
```

- [ ] **Step 4: Remove the flat-PNG reuse splice**

In `backend/app/api/routes/generate.py`, DELETE this block (currently lines 371-377):

```python
        if is_canvas:
            # Non-front decorated faces reuse the customer's flattened canvas PNG
            # directly (it IS their composite) — no extra model call.
            for face, path in canvas_layouts.items():
                if face == prompt_builder.PRIMARY_VIEW:
                    continue
                new_views[face] = {"image_url": path, "watermarked_url": _make_watermarked(path)}
```

Note: `canvas_layouts = collected.get("canvas_layouts") or {}` (near line 286) is
still read by `_one(view)` for the layout guide, so leave that assignment in place.

- [ ] **Step 5: Refresh the `_run_generation` docstring + canvas comment**

In `backend/app/api/routes/generate.py`, update the multi-line comment above the
`is_edit / elif is_canvas / else` block (currently around lines 288-294) so it
reads:

```python
    # An edit re-renders ONLY the affected views and REFINES from the previous
    # design; a fresh design renders every decorated view. Carry forward the
    # previous render's unaffected views so the delivered set stays complete.
    # A canvas session AI-renders EVERY decorated face (front hero + any
    # decorated back/side), each with its real product-angle photo as the
    # conditioning image and its flattened canvas PNG as the layout guide.
```

And in the `_run_generation` docstring (around lines 266-277), replace the
sentence describing the old canvas reuse behaviour ("A canvas session AI-renders
ONLY the front hero…") with:

```python
    Multi-view: the design AI-renders the front hero PLUS any back/side view
    that carries decoration (prompt_builder.render_views), each as its own model
    call, fired CONCURRENTLY — including canvas sessions, where each decorated
    face renders with its real product-angle photo (conditioning) plus its
    flattened canvas PNG as a layout guide.
```

- [ ] **Step 6: Run the rewritten test + the cache-key regression tests**

Run: `cd backend && python -m pytest tests/test_canvas_generation.py -v`
Expected: PASS — `test_canvas_run_renders_every_decorated_face`,
`test_canvas_cache_key_differs_by_layout_guide_path`,
`test_non_canvas_cache_key_unaffected_by_fix`, and
`test_generate_accepts_layout_guide_url` all pass.

- [ ] **Step 7: Run the broader generation + prompt-builder suites for regressions**

Run: `cd backend && python -m pytest tests/test_canvas_generation.py tests/test_canvas_routes.py tests/test_prompt_builder.py tests/test_multiview.py -q`
Expected: PASS (no regression in the non-canvas multi-view path or the canvas routes).

- [ ] **Step 8: Commit**

```bash
git add backend/app/api/routes/generate.py backend/tests/test_canvas_generation.py
git commit -m "feat(canvas): AI-render every decorated face photorealistically (not just front)"
```

---

### Task 3: Full backend suite verification

**Files:**
- Test: whole `backend/tests/` suite.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS — the full suite green (prior baseline was 413 passing; this plan
adds 3 tests and removes 1, so ~415). If an unrelated Windows tinypool
"Worker exited" flake appears, rerun the focused canvas suites from Task 2 to
confirm they pass in isolation.

- [ ] **Step 2: (Optional) Inspect a real per-view prompt**

If a live session is available, hit `GET /admin/prompt-preview/{session_id}`
(with `X-Admin-Secret`) to eyeball that the assembled per-face prompt enumerates
that face's components with coarse zone words and no pixel coordinates.

---

## Self-Review notes

- **Spec coverage:** "render every decorated angle" → Task 2. "extract components at their locations → coarse description" → Task 1 (attribute completeness) + Task 2 (each face's components now reach the model via `build_view_prompt`). "real product photo as main reference + flattened canvas as layout guide" → already wired in `_one`, exercised by Task 2's assertions on `refs`/`layout_guides`. Test changes (rewrite pinned test, keep cache-key tests, add describe case) → Tasks 1-2. Full-suite check → Task 3.
- **No pixel coordinates** constraint enforced in Task 1 (drop px size, no x/y in description) and asserted by `test_text_description_carries_no_pixel_dimensions`.
- **Type consistency:** `render_views`, `PRIMARY_VIEW`, `build_params`, `_run_generation` kwargs, and the `_render_view` result dict keys all match their existing definitions in `generate.py` / `prompt_builder.py`.
