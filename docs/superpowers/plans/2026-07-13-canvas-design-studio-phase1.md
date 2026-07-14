# Canvas Design Studio — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the chat Q&A deep-dive with an interactive multi-face react-konva canvas whose flattened per-face PNGs + auto-built description feed the existing generation + gated-delivery pipeline.

**Architecture:** A new frontend `DesignStudio` (react-konva) is the design surface for both the customise (`?product_id`) and blank (`?mode=blank`) flows. The customer places text/logos on four face tabs, then "See it rendered" flattens each decorated face, uploads them as **layout-guide** images, and posts a `canvas_design` JSON. The backend converts `canvas_design` into the **existing** `collected["elements"]` shape — so the existing multi-view generator, delivery, viewer, and email all work unchanged. The front hero is AI-rendered (real photo + layout guide + description); non-front decorated faces reuse the uploaded flattened PNG. After finalize, the frontend hands off to the **existing ChatPanel** (hydrated to `generating`) for verify → deliver → refine.

**Tech Stack:** Python 3.12 / FastAPI / supabase-py; React 18 / Vite / Zustand / Tailwind; **react-konva + konva** (new frontend dep); Gemini image models via `ImageProvider`.

## Global Constraints

- **Composite onto the real product photo** — every generation call passes the real product `reference_image_url` as conditioning; the flattened canvas is an *additional* layout-guide image, never a from-scratch cap. (Verbatim hard constraint.)
- **No secrets in code** — all keys via env / `settings`.
- **No PII in logs** — never log customer name/email; log `session_id` only.
- **Uploaded files validated** — MIME + magic bytes + size before any processing (reuse the existing `/uploads/logo` validation).
- **Signed URLs only** — bucket `madhats-assets` stays private; TTL = `SIGNED_URL_TTL`.
- **ORM/table client only** — supabase-py table calls; no raw SQL in app code. Schema changes are SQL migrations in `backend/supabase/migrations/`.
- **InkyBay untouched.** Existing customise/blank chat Q&A code and states are **retained** (bypassed for canvas sessions), never deleted.
- **Backend tests:** `cd backend && pytest -q`. **Frontend tests:** `cd frontend && npx vitest run` (never `npm test` — it watches).
- **New frontend deps** must be installed inside the container: `docker compose exec frontend npm install` then `docker compose restart frontend`. Host `npx vitest run` uses host `node_modules`, so also `npm install` on the host for tests to resolve.

---

## File Structure

**Backend (create):**
- `backend/supabase/migrations/20260713000001_canvas_design.sql` — `canvas_design jsonb` column.
- `backend/app/services/canvas_describe.py` — `canvas_to_elements()` (CanvasDesign → elements + description).
- `backend/app/models/canvas.py` — pydantic request models for canvas routes.
- `backend/tests/test_canvas_describe.py`, `test_canvas_routes.py`, `test_canvas_generation.py`.

**Backend (modify):**
- `backend/app/services/image/image_provider.py` — add `layout_guide_url` to `generate()`.
- `backend/app/services/image/gemini.py` (real adapter) — pass layout guide as an extra image.
- `backend/app/api/routes/generate.py` — canvas branch in `_run_generation` + `_render_view` layout param.
- `backend/app/api/routes/sessions.py` — `POST /sessions/canvas`, `POST /sessions/{id}/canvas-layouts`, `POST /sessions/{id}/canvas-finalize`.
- `backend/app/services/conversation/state_machine.py` — add `CANVAS_DESIGN` enum value.

**Frontend (create):**
- `frontend/src/store/canvasStore.ts` — element state + reducers + `toCanvasDesign()`.
- `frontend/src/components/DesignStudio/index.tsx` — page shell (face tabs + stage + rail).
- `frontend/src/components/DesignStudio/CanvasStage.tsx` — react-konva stage.
- `frontend/src/components/DesignStudio/nodes.tsx` — `TextNode`, `ImageNode`.
- `frontend/src/components/DesignStudio/ToolRail.tsx`, `SelectedToolbar.tsx`.
- `frontend/src/lib/canvasFlatten.ts` — `flattenFace()` + `dataUrlToFile()`.
- `frontend/src/store/canvasStore.test.ts`, `frontend/src/lib/canvasFlatten.test.ts`.

**Frontend (modify):**
- `frontend/src/lib/api.ts` — `createCanvasSession`, `uploadCanvasLayouts`, `finalizeCanvas`.
- `frontend/src/lib/types.ts` — canvas DTO types.
- `frontend/src/store/sessionStore.ts` — `'canvas'` view + `startCanvasSession` / `startCanvasBlankSession` + bootstrap routing.
- `frontend/src/App.tsx` — render `DesignStudio` for the `'canvas'` view.
- `frontend/src/components/BlankHatPicker/index.tsx` — on select, start a **canvas** blank session.

---

## Task 1: DB migration — `canvas_design` column

**Files:**
- Create: `backend/supabase/migrations/20260713000001_canvas_design.sql`

**Interfaces:**
- Produces: `design_sessions.canvas_design jsonb` (nullable) — the persisted canvas state.

- [ ] **Step 1: Write the migration**

```sql
-- Canvas Design Studio: persist the customer's interactive canvas state.
-- Additive + nullable; customise/blank chat sessions leave it NULL.
alter table public.design_sessions
  add column if not exists canvas_design jsonb;

comment on column public.design_sessions.canvas_design is
  'Interactive canvas state (faces -> elements, colourway) for flow_mode=canvas sessions.';
```

- [ ] **Step 2: Apply it locally**

Run: `cd backend && npx supabase db reset`
Expected: reset completes; migration `20260713000001_canvas_design` listed with no error.

- [ ] **Step 3: Verify the column exists**

Run: `cd backend && npx supabase db reset && echo OK` then in Studio (http://localhost:54323) confirm `design_sessions.canvas_design` is present, or run a quick psql check if available.
Expected: column present, type `jsonb`, nullable.

- [ ] **Step 4: Commit**

```bash
git add backend/supabase/migrations/20260713000001_canvas_design.sql
git commit -m "feat(canvas): add canvas_design jsonb column to design_sessions"
```

---

## Task 2: Canvas → elements/description builder

Pure function: converts the frontend `CanvasDesign` JSON into the existing
`collected["elements"]` shape (so the current generator works unchanged) plus a
deterministic text description.

**Files:**
- Create: `backend/app/services/canvas_describe.py`
- Test: `backend/tests/test_canvas_describe.py`

**Interfaces:**
- Produces:
  - `FACE_ZONE: dict[str, tuple[str, str | None]]` — face → (placement_zone, placement_position).
  - `canvas_to_elements(canvas_design: dict) -> tuple[list[dict], str]` — returns `(elements, description)`. Each element dict uses the existing generator keys: `type` (`"text"`|`"logo"`), `content`, `font`, `colour`, `size`, `placement_zone`, `placement_position`, `remove_bg`, and a `canvas` sub-dict with normalised geometry `{x,y,width,height,rotation,face,z}` for audit.
- Consumes (canvas_design shape, produced by Task 8 `toCanvasDesign()`):
  ```json
  {"colourway": {"name": "Navy", "hex": "#1e3a8a"},
   "faces": {"front": [ {"id","type":"text|image","x","y","width","height","rotation","zIndex","content","font","colour","fontSize","assetUrl","removeBg"} ], "back": [], "left": [], "right": []}}
  ```

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_canvas_describe.py
from app.services.canvas_describe import canvas_to_elements, FACE_ZONE


def test_text_on_front_maps_to_front_panel_element():
    design = {
        "colourway": {"name": "Navy", "hex": "#1e3a8a"},
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
    assert len(elements) == 1
    el = elements[0]
    assert el["type"] == "text"
    assert el["content"] == "SURF CO"
    assert el["placement_zone"] == "front_panel"
    assert el["colour"] == "#ffffff"
    assert el["font"] == "Impact"
    assert el["canvas"]["face"] == "front"
    assert "SURF CO" in description and "front panel" in description


def test_image_on_left_maps_to_side_left_logo():
    design = {
        "colourway": None,
        "faces": {
            "front": [], "back": [],
            "left": [{
                "id": "e2", "type": "image", "x": 0.5, "y": 0.5,
                "width": 0.3, "height": 0.3, "rotation": 0, "zIndex": 0,
                "assetUrl": "uploads/logo.png", "removeBg": True,
            }],
            "right": [],
        },
    }
    elements, _ = canvas_to_elements(design)
    assert elements[0]["type"] == "logo"
    assert elements[0]["placement_zone"] == "side"
    assert elements[0]["placement_position"] == "left"
    assert elements[0]["remove_bg"] is True


def test_face_zone_map_covers_all_four_faces():
    assert set(FACE_ZONE) == {"front", "back", "left", "right"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_describe.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.canvas_describe`.

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/canvas_describe.py
"""Convert the interactive canvas (CanvasDesign JSON) into the existing
collected["elements"] shape + a deterministic description.

Mapping the canvas into the SAME element shape the deep-dive produced means the
existing multi-view generator (prompt_builder.build_view_prompt / render_views)
renders the canvas design with no further change.
"""
from __future__ import annotations

# Face tab -> (placement_zone, placement_position). Mirrors prompt_builder.element_view:
# side splits into left/right by position; back -> back; front -> front_panel.
FACE_ZONE: dict[str, tuple[str, str | None]] = {
    "front": ("front_panel", "centre"),
    "back": ("back", "centre"),
    "left": ("side", "left"),
    "right": ("side", "right"),
}

_FACE_LABEL = {"front": "front panel", "back": "back", "left": "left side", "right": "right side"}


def _element(el: dict, face: str) -> dict:
    zone, position = FACE_ZONE[face]
    is_text = el.get("type") == "text"
    out: dict = {
        "type": "text" if is_text else "logo",
        "placement_zone": zone,
        "placement_position": position,
        "canvas": {
            "face": face,
            "x": el.get("x"), "y": el.get("y"),
            "width": el.get("width"), "height": el.get("height"),
            "rotation": el.get("rotation", 0), "z": el.get("zIndex", 0),
        },
    }
    if is_text:
        out["content"] = el.get("content", "")
        if el.get("font"):
            out["font"] = el["font"]
        if el.get("colour"):
            out["colour"] = el["colour"]
        if el.get("fontSize"):
            out["size"] = f'{el["fontSize"]}px'
    else:
        out["content"] = "uploaded logo/artwork"
        out["assetUrl"] = el.get("assetUrl")
        out["remove_bg"] = bool(el.get("removeBg"))
    return out


def _describe(el: dict, face: str) -> str:
    where = f"on the {_FACE_LABEL.get(face, face)}"
    if el.get("type") == "text":
        parts = [f'text reading "{el.get("content", "")}"']
        if el.get("colour"):
            parts.append(f'in {el["colour"]}')
        if el.get("font"):
            parts.append(f'{el["font"]} font')
        return f"{', '.join(parts)} {where}"
    return f"uploaded logo/artwork {where}"


def canvas_to_elements(canvas_design: dict) -> tuple[list[dict], str]:
    faces = (canvas_design or {}).get("faces") or {}
    elements: list[dict] = []
    lines: list[str] = []
    for face in ("front", "back", "left", "right"):
        for el in sorted(faces.get(face) or [], key=lambda e: e.get("zIndex", 0)):
            elements.append(_element(el, face))
            lines.append(_describe(el, face))
    description = "; ".join(lines)
    return elements, description
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_describe.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/canvas_describe.py backend/tests/test_canvas_describe.py
git commit -m "feat(canvas): canvas_design -> elements/description builder"
```

---

## Task 3: `layout_guide_url` on the ImageProvider

Add an optional second conditioning image (the flattened canvas) to the provider
interface. The stub ignores it; the real Gemini adapter appends it as an extra
image part.

**Files:**
- Modify: `backend/app/services/image/image_provider.py:37-45`
- Modify: `backend/app/services/image/gemini.py` (the real adapter's `generate`)
- Modify: `backend/app/services/image/stub.py` (signature only) — if a stub adapter exists at that path; otherwise the stub is in `router.py`. Grep first.
- Test: `backend/tests/test_canvas_generation.py` (created here, extended in Task 6)

**Interfaces:**
- Produces: `ImageProvider.generate(prompt, reference_image_url, uploaded_asset_url, params, prior_design_url=None, layout_guide_url=None)`.

- [ ] **Step 1: Locate the adapters**

Run: `cd backend && grep -rn "async def generate" app/services/image`
Expected: lists `image_provider.py` (abstract) and each concrete adapter (stub + gemini). Note their exact file paths and signatures.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_canvas_generation.py
import inspect
from app.services.image.image_provider import ImageProvider


def test_generate_accepts_layout_guide_url():
    sig = inspect.signature(ImageProvider.generate)
    assert "layout_guide_url" in sig.parameters
    assert sig.parameters["layout_guide_url"].default is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_generation.py -q`
Expected: FAIL — `assert 'layout_guide_url' in ...` KeyError/AssertionError.

- [ ] **Step 4: Add the parameter to the interface**

In `backend/app/services/image/image_provider.py`, change the abstract signature:

```python
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,  # real product photo — always required
        uploaded_asset_url: str | None,  # customer logo/artwork, if any
        params: GenerationParams,
        prior_design_url: str | None = None,  # previous render to REFINE (edits only)
        layout_guide_url: str | None = None,  # flattened canvas — layout guide (canvas flow)
    ) -> GenerationResult:
        ...
```

Add the same `layout_guide_url: str | None = None` parameter to every concrete
adapter's `generate` (stub + gemini) found in Step 1. In the **stub**, ignore it.
In the **gemini** adapter, after the block that appends the reference image (and
the uploaded asset, if any), append the layout guide as another image part:

```python
        # Layout guide (canvas flow): the flattened canvas showing where the
        # customer placed each decoration. Conditioning is still the real photo;
        # this only guides placement. Fetch + attach like the other image inputs.
        if layout_guide_url:
            parts.append(_image_part_from_url(layout_guide_url))
```

Use whatever the adapter's existing image-part helper is (mirror how
`reference_image_url` / `uploaded_asset_url` are attached in that file — reuse the
same fetch/encode function, do not invent a new one).

- [ ] **Step 5: Run test + full image tests**

Run: `cd backend && pytest tests/test_canvas_generation.py -q && pytest -q -k "image or provider or generation"`
Expected: PASS; no regressions in existing generation/provider tests.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/image backend/tests/test_canvas_generation.py
git commit -m "feat(canvas): layout_guide_url conditioning image on ImageProvider"
```

---

## Task 4: Generation — front AI-render with layout guide; non-front reuse flattened PNG

For canvas sessions (`collected["flow_mode"] == "canvas"`), `_run_generation`
renders only the **front** hero through the model (adding the front layout guide),
and fills every other decorated face from its uploaded flattened PNG
(`collected["canvas_layouts"][view]`) instead of a model call.

**Files:**
- Modify: `backend/app/api/routes/generate.py` — `_render_view` (add `layout_guide_url`), `_run_generation` (canvas branch)
- Test: `backend/tests/test_canvas_generation.py` (extend)

**Interfaces:**
- Consumes: `canvas_describe` element shape (Task 2); `collected["canvas_layouts"]: dict[str,str]` (storage paths, set by Task 5 upload route); `layout_guide_url` param (Task 3).
- Produces: a completed `generations` row whose `view_images` has an AI-rendered `front` and flattened-PNG entries for decorated `back`/`left`/`right`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_canvas_generation.py
import asyncio
from unittest.mock import patch
from app.api.routes import generate as gen


def test_canvas_run_renders_front_and_reuses_flattened_for_back(monkeypatch):
    """Canvas: front is AI-rendered; a decorated back reuses its flattened PNG
    (no provider call for back)."""
    calls = {"views": []}

    async def fake_render_view(**kw):
        calls["views"].append(kw["view"])
        return {"ok": True, "view": kw["view"], "clean_path": "gen/front.png",
                "watermarked_path": "gen/front_wm.png", "model": "stub",
                "cost_usd": 0, "latency_ms": 1, "key": "k", "attempts": 1, "from_cache": False}

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

    assert calls["views"] == ["front"]  # only the front went to the model
    assert captured["status"] == "complete"
    assert set(captured["view_images"]) == {"front", "back"}
    assert captured["view_images"]["back"]["image_url"] == "uploads/back.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_generation.py::test_canvas_run_renders_front_and_reuses_flattened_for_back -q`
Expected: FAIL — front+back both rendered (or a signature error on `layout_guide_url`).

- [ ] **Step 3: Add `layout_guide_url` passthrough in `_render_view`**

In `_render_view` (backend/app/api/routes/generate.py), add the parameter and
forward it to the provider call:

```python
async def _render_view(
    *, view, provider, job_id, generation_id, session_id, tier,
    prompt, ref_url, uploaded_url, params, params_dict, key,
    prior_design_url=None, layout_guide_url=None,
) -> dict:
```

and in the `provider.generate(...)` call inside it:

```python
            result = await provider.generate(
                prompt=prompt, reference_image_url=ref_url,
                uploaded_asset_url=uploaded_url, params=params,
                prior_design_url=prior_design_url,
                layout_guide_url=layout_guide_url,
            )
```

- [ ] **Step 4: Add the canvas branch to `_run_generation`**

At the top of `_run_generation`, after `params_dict = asdict(params)`, add:

```python
    is_canvas = collected.get("flow_mode") == "canvas"
    canvas_layouts = collected.get("canvas_layouts") or {}
```

Replace the view-set selection so a canvas fresh render only AI-renders the front:

```python
    is_edit = tier == "edit"
    if is_edit:
        views = prompt_builder.affected_render_views(collected)
        prev_gen = _latest_complete_generation(session_id)
        prev_views = _prev_view_map(prev_gen)
    elif is_canvas:
        views = [prompt_builder.PRIMARY_VIEW]  # only the front hero is AI-rendered
        prev_views = {}
    else:
        views = prompt_builder.render_views(collected)
        prev_views = {}
```

Inside `_one(view)`, pass the front layout guide to the render (signed):

```python
                layout_guide = None
                if is_canvas:
                    lg = canvas_layouts.get(view)
                    if lg:
                        layout_guide = lg if lg.startswith("http") else generate_signed_url(lg)
                return await _render_view(
                    view=view, provider=provider, job_id=job_id, generation_id=generation_id,
                    session_id=session_id, tier=tier, prompt=view_prompt, ref_url=ref,
                    uploaded_url=uploaded, params=params, params_dict={**params_dict, "view": view},
                    key=key, prior_design_url=prior, layout_guide_url=layout_guide,
                )
```

After `new_views` is built from `results` (and before `view_images = {**prev_views, **new_views}`), splice in the flattened non-front faces for canvas sessions:

```python
        if is_canvas:
            # Non-front decorated faces reuse the customer's flattened canvas PNG
            # directly (it IS their composite) — no extra model call.
            for face, path in canvas_layouts.items():
                if face == prompt_builder.PRIMARY_VIEW:
                    continue
                new_views[face] = {"image_url": path, "watermarked_url": _make_watermarked(path)}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_generation.py -q`
Expected: PASS (all canvas generation tests).

- [ ] **Step 6: Run the full generation suite for regressions**

Run: `cd backend && pytest -q -k "generation or generate or multiview"`
Expected: PASS — existing customise/blank multi-view behaviour unchanged.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/generate.py backend/tests/test_canvas_generation.py
git commit -m "feat(canvas): front AI-render with layout guide; non-front reuse flattened PNG"
```

---

## Task 5: Canvas session routes (create / layouts / finalize)

**Files:**
- Create: `backend/app/models/canvas.py`
- Modify: `backend/app/api/routes/sessions.py`
- Modify: `backend/app/services/conversation/state_machine.py` (add enum value)
- Test: `backend/tests/test_canvas_routes.py`

**Interfaces:**
- Produces:
  - `POST /sessions/canvas` → `SessionResponse` (state `"canvas_design"`, flow_mode `"canvas"`). Body: `{product_id?: str, hat_type_id?: str, colour?: dict|str, channel?, entry_path?}`.
  - `POST /sessions/{id}/canvas-layouts` (multipart: repeated `face` + `file`) → `{views: {face: signed_url}}`; stores paths in `collected["canvas_layouts"]`.
  - `POST /sessions/{id}/canvas-finalize` (JSON `{canvas_design, email?, name?}`) → `{reply, state, data}` chat-shaped; persists `canvas_design`, writes `collected` (elements, description, flow_mode, email_captured), creates+verifies lead, sets state `"generating"`.
- Consumes: `canvas_describe.canvas_to_elements` (Task 2); existing `require_store`, `get_product`, `hat_types_service`, upload validation, leads service.

- [ ] **Step 1: Add the `CANVAS_DESIGN` enum value**

In `backend/app/services/conversation/state_machine.py`, add to `ConversationState`:

```python
    CANVAS_DESIGN = "canvas_design"
```

(No transition wiring needed — finalize jumps straight to `generating`; the value
must exist so `ConversationState(session["state"])` in `get_session` accepts it.)

- [ ] **Step 2: Write the failing tests**

```python
# backend/tests/test_canvas_routes.py
from app.services.canvas_describe import canvas_to_elements


def test_finalize_writes_elements_and_moves_to_generating(client, seeded_store_headers, canvas_session_id):
    design = {"colourway": {"name": "Navy", "hex": "#1e3a8a"},
              "faces": {"front": [{"id": "e1", "type": "text", "content": "HI",
                                    "x": 0.5, "y": 0.4, "width": 0.2, "height": 0.1,
                                    "rotation": 0, "zIndex": 0}],
                        "back": [], "left": [], "right": []}}
    r = client.post(f"/sessions/{canvas_session_id}/canvas-finalize",
                    json={"canvas_design": design, "email": "a@b.com", "name": "Al"},
                    headers=seeded_store_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "generating"
    elements, _ = canvas_to_elements(design)
    assert elements[0]["content"] == "HI"
```

> Follow the existing test fixtures in `backend/tests/` (look at `test_blank_session.py`
> for how a session + store headers are set up). Add a `canvas_session_id` fixture
> that POSTs `/sessions/canvas` with a seeded `product_id`.

- [ ] **Step 3: Run to verify it fails**

Run: `cd backend && pytest tests/test_canvas_routes.py -q`
Expected: FAIL — routes/fixtures not defined (404 / fixture error).

- [ ] **Step 4: Add the request models**

```python
# backend/app/models/canvas.py
from __future__ import annotations
from pydantic import BaseModel


class CreateCanvasSessionRequest(BaseModel):
    product_id: str | None = None
    hat_type_id: str | None = None
    colour: dict | str | None = None
    channel: str = "web"
    entry_path: str | None = None


class CanvasFinalizeRequest(BaseModel):
    canvas_design: dict
    email: str | None = None
    name: str | None = None
```

- [ ] **Step 5: Implement the three routes in `sessions.py`**

Add imports at the top of `backend/app/api/routes/sessions.py`:

```python
from fastapi import UploadFile, File, Form
from app.models.canvas import CreateCanvasSessionRequest, CanvasFinalizeRequest
from app.services import canvas_describe
```

Add the create route (build `product_ref` from a product OR a hat type, mirroring
the existing `create_session` / `create_blank_session` bodies above):

```python
@router.post("/sessions/canvas", response_model=SessionResponse)
async def create_canvas_session(
    body: CreateCanvasSessionRequest, store: dict = Depends(require_store)
) -> SessionResponse:
    collected: dict = {"flow_mode": "canvas"}
    if body.product_id:
        product = get_product(body.product_id, store_id=store["id"])
        if not product:
            raise HTTPException(status_code=404, detail="Unknown product_id for this store")
        product_ref = {
            "product_id": product["id"], "style": product["style"], "colour": product["colour"],
            "name": product["name"], "reference_image_url": product["reference_image_url"],
            "view_images": product.get("view_images") or {},
        }
    elif body.hat_type_id:
        hat = hat_types_service.get_hat_type(body.hat_type_id, store_id=store["id"])
        if not hat:
            raise HTTPException(status_code=404, detail="Unknown hat_type_id for this store")
        colour = None
        if body.colour:
            colour = body.colour if isinstance(body.colour, dict) else {"name": body.colour, "hex": body.colour}
        blanks = hat.get("blank_view_images") or {}
        product_ref = {
            "product_id": hat["id"], "style": hat.get("style", ""),
            "colour": (colour.get("name") or colour.get("hex")) if colour else "",
            "name": hat["name"], "reference_image_url": blanks.get("front", ""),
            "view_images": blanks,
        }
        collected["hat_type_id"] = hat["id"]
        if colour:
            collected["hat_colour"] = colour
    else:
        raise HTTPException(status_code=400, detail="product_id or hat_type_id required")

    share_token = secrets.token_urlsafe(16)
    sb = get_supabase()
    res = sb.table("design_sessions").insert({
        "store_id": store["id"], "share_token": share_token, "state": "canvas_design",
        "channel": body.channel, "entry_path": body.entry_path, "flow_mode": "canvas",
        "product_ref": product_ref, "collected": collected, "status": "draft",
    }).execute()
    row = res.data[0]
    return SessionResponse(session_id=row["id"], share_token=share_token, state=row["state"])
```

Add the layout-upload route. Reuse the SAME validation + storage primitives the
logo route (`app/api/routes/uploads.py:upload_logo`) uses:
`sniff_image_mime` + `MAX_UPLOAD_BYTES` from `app.services.upload_validation`, and
`upload_asset` from `app.storage`. Do NOT re-implement magic-byte checks.

Add these imports at the top of `sessions.py`:

```python
import uuid
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import upload_asset  # generate_signed_url already imported
```

```python
@router.post("/sessions/{session_id}/canvas-layouts")
async def upload_canvas_layouts(
    session_id: str,
    faces: list[str] = Form(...),
    files: list[UploadFile] = File(...),
    store: dict = Depends(require_store),
) -> dict:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("id, collected").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    layouts: dict[str, str] = {}
    signed: dict[str, str] = {}
    for face, upload in zip(faces, files):
        data = await upload.read()
        if not data:
            raise HTTPException(status_code=400, detail=f"Empty file for {face}")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
        mime = sniff_image_mime(data)
        if mime is None:
            raise HTTPException(status_code=415, detail="Unsupported file type")
        path = upload_asset(data, f"canvas_{face}_{uuid.uuid4().hex}.png", mime)
        layouts[face] = path
        signed[face] = generate_signed_url(path)
    collected = (sess.data[0].get("collected") or {})
    collected["canvas_layouts"] = {**(collected.get("canvas_layouts") or {}), **layouts}
    sb.table("design_sessions").update({"collected": collected}).eq("id", session_id).execute()
    return {"views": signed}
```

Add the finalize route:

```python
@router.post("/sessions/{session_id}/canvas-finalize")
async def finalize_canvas(
    session_id: str, body: CanvasFinalizeRequest, store: dict = Depends(require_store)
) -> dict:
    sb = get_supabase()
    sess = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not sess.data:
        raise HTTPException(status_code=404, detail="Session not found")
    session = sess.data[0]
    collected = session.get("collected") or {}

    elements, description = canvas_describe.canvas_to_elements(body.canvas_design)
    collected["elements"] = elements
    collected["design_description"] = {"summary": description} if description else None
    collected["flow_mode"] = "canvas"
    if body.name:
        collected["name"] = body.name

    # Capture the lead + fire the verification email. Reuse the exact helper the
    # chat flow uses at save_progress_email:
    #   leads.capture_lead_and_verify(session: dict, collected: dict, email: str) -> str | None
    # (name is read from collected["name"]; sending is best-effort). email_captured
    # must be set so advance_state(GENERATING) routes to verify_email.
    if body.email:
        from app.services import leads as leads_service
        leads_service.capture_lead_and_verify(session, collected, body.email)
        collected["email_captured"] = True

    sb.table("design_sessions").update(
        {"canvas_design": body.canvas_design, "collected": collected, "state": "generating"}
    ).eq("id", session_id).execute()

    return {"reply": "Your design is on its way — generating your preview now.",
            "state": "generating", "data": {}}
```

> `capture_lead_and_verify` takes the full `session` dict (it reads `session["id"]`)
> and the `collected` dict (it reads `collected["name"]`) — pass them as shown, not
> the store or kwargs.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && pytest tests/test_canvas_routes.py -q`
Expected: PASS.

- [ ] **Step 7: Run the sessions + leads suites for regressions**

Run: `cd backend && pytest -q -k "session or lead or blank"`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/canvas.py backend/app/api/routes/sessions.py backend/app/services/conversation/state_machine.py backend/tests/test_canvas_routes.py
git commit -m "feat(canvas): create/layouts/finalize session routes"
```

---

## Task 6: Frontend deps + `canvasStore`

**Files:**
- Modify: `frontend/package.json` (add `konva`, `react-konva`)
- Create: `frontend/src/store/canvasStore.ts`
- Test: `frontend/src/store/canvasStore.test.ts`

**Interfaces:**
- Produces (`canvasStore`):
  - Types `Face = 'front'|'back'|'left'|'right'`, `CanvasElement` (per spec §6), `Colourway = {name:string; hex:string}`.
  - State: `faces: Record<Face, CanvasElement[]>`, `activeFace: Face`, `selectedId: string|null`, `colourway: Colourway|null`, `faceImages: Record<Face,string>`.
  - Actions: `setFaceImages(imgs)`, `setActiveFace(f)`, `addText(text)`, `addImage(assetUrl)`, `updateElement(id, patch)`, `removeElement(id)`, `reorder(id, dir)`, `select(id|null)`, `setColourway(c)`, `reset()`, `toCanvasDesign(): CanvasDesign`.

- [ ] **Step 1: Add the dependency**

Run (host, for tests to resolve) then inside the container (for Vite):
```bash
cd frontend && npm install konva react-konva
# then, if the dev container is running:
# docker compose exec frontend npm install && docker compose restart frontend
```
Expected: `konva` + `react-konva` in `package.json` dependencies.

- [ ] **Step 2: Write the failing test**

```ts
// frontend/src/store/canvasStore.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useCanvasStore } from './canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

describe('canvasStore', () => {
  it('adds a text element to the active face', () => {
    const s = useCanvasStore.getState()
    s.setActiveFace('front')
    s.addText('SURF')
    const el = useCanvasStore.getState().faces.front[0]
    expect(el.type).toBe('text')
    expect(el.content).toBe('SURF')
  })

  it('updateElement patches only the target', () => {
    const s = useCanvasStore.getState()
    s.addText('A'); s.addText('B')
    const id = useCanvasStore.getState().faces.front[0].id
    s.updateElement(id, { colour: '#ff0000' })
    expect(useCanvasStore.getState().faces.front[0].colour).toBe('#ff0000')
    expect(useCanvasStore.getState().faces.front[1].colour).toBeUndefined()
  })

  it('removeElement drops it and clears selection', () => {
    const s = useCanvasStore.getState()
    s.addText('A')
    const id = useCanvasStore.getState().faces.front[0].id
    s.select(id); s.removeElement(id)
    expect(useCanvasStore.getState().faces.front).toHaveLength(0)
    expect(useCanvasStore.getState().selectedId).toBeNull()
  })

  it('toCanvasDesign serialises faces + colourway', () => {
    const s = useCanvasStore.getState()
    s.setColourway({ name: 'Navy', hex: '#1e3a8a' })
    s.addText('HI')
    const d = s.toCanvasDesign()
    expect(d.colourway?.name).toBe('Navy')
    expect(d.faces.front[0].content).toBe('HI')
    expect(Object.keys(d.faces)).toEqual(['front', 'back', 'left', 'right'])
  })
})
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/store/canvasStore.test.ts`
Expected: FAIL — cannot resolve `./canvasStore`.

- [ ] **Step 4: Implement the store**

```ts
// frontend/src/store/canvasStore.ts
import { create } from 'zustand'

export type Face = 'front' | 'back' | 'left' | 'right'
export const FACES: Face[] = ['front', 'back', 'left', 'right']

export interface CanvasElement {
  id: string
  type: 'text' | 'image'
  x: number; y: number; width: number; height: number; rotation: number
  zIndex: number
  content?: string; font?: string; colour?: string; fontSize?: number
  assetUrl?: string; removeBg?: boolean
}

export interface Colourway { name: string; hex: string }

export interface CanvasDesign {
  colourway: Colourway | null
  faces: Record<Face, CanvasElement[]>
}

interface CanvasState {
  faces: Record<Face, CanvasElement[]>
  activeFace: Face
  selectedId: string | null
  colourway: Colourway | null
  faceImages: Record<Face, string>

  setFaceImages: (imgs: Partial<Record<Face, string>>) => void
  setActiveFace: (f: Face) => void
  addText: (text: string) => void
  addImage: (assetUrl: string) => void
  updateElement: (id: string, patch: Partial<CanvasElement>) => void
  removeElement: (id: string) => void
  reorder: (id: string, dir: 'up' | 'down') => void
  select: (id: string | null) => void
  setColourway: (c: Colourway | null) => void
  reset: () => void
  toCanvasDesign: () => CanvasDesign
}

const emptyFaces = (): Record<Face, CanvasElement[]> => ({ front: [], back: [], left: [], right: [] })
const uid = () => Math.random().toString(36).slice(2, 10)

export const useCanvasStore = create<CanvasState>((set, get) => ({
  faces: emptyFaces(),
  activeFace: 'front',
  selectedId: null,
  colourway: null,
  faceImages: { front: '', back: '', left: '', right: '' },

  setFaceImages: imgs => set(s => ({ faceImages: { ...s.faceImages, ...imgs } })),
  setActiveFace: f => set({ activeFace: f, selectedId: null }),

  addText: text => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'text', x: 0.5, y: 0.4, width: 0.3, height: 0.12,
      rotation: 0, zIndex: s.faces[s.activeFace].length,
      content: text, font: 'Arial', colour: '#ffffff', fontSize: 36,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  addImage: assetUrl => set(s => {
    const el: CanvasElement = {
      id: uid(), type: 'image', x: 0.5, y: 0.5, width: 0.35, height: 0.35,
      rotation: 0, zIndex: s.faces[s.activeFace].length, assetUrl, removeBg: false,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),

  updateElement: (id, patch) => set(s => ({
    faces: {
      ...s.faces,
      [s.activeFace]: s.faces[s.activeFace].map(e => (e.id === id ? { ...e, ...patch } : e)),
    },
  })),

  removeElement: id => set(s => ({
    faces: { ...s.faces, [s.activeFace]: s.faces[s.activeFace].filter(e => e.id !== id) },
    selectedId: s.selectedId === id ? null : s.selectedId,
  })),

  reorder: (id, dir) => set(s => {
    const arr = [...s.faces[s.activeFace]]
    const i = arr.findIndex(e => e.id === id)
    const j = dir === 'up' ? i + 1 : i - 1
    if (i < 0 || j < 0 || j >= arr.length) return s
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
    arr.forEach((e, k) => (e.zIndex = k))
    return { faces: { ...s.faces, [s.activeFace]: arr } }
  }),

  select: id => set({ selectedId: id }),
  setColourway: c => set({ colourway: c }),
  reset: () => set({ faces: emptyFaces(), activeFace: 'front', selectedId: null, colourway: null,
    faceImages: { front: '', back: '', left: '', right: '' } }),

  toCanvasDesign: () => {
    const { faces, colourway } = get()
    return { colourway, faces }
  },
}))
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npx vitest run src/store/canvasStore.test.ts`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/store/canvasStore.ts frontend/src/store/canvasStore.test.ts
git commit -m "feat(canvas): react-konva dep + canvasStore"
```

---

## Task 7: Flatten helper (`canvasFlatten.ts`)

**Files:**
- Create: `frontend/src/lib/canvasFlatten.ts`
- Test: `frontend/src/lib/canvasFlatten.test.ts`

**Interfaces:**
- Produces:
  - `dataUrlToFile(dataUrl: string, name: string): File` — decode a `data:image/png;base64,...` URL to a `File`.
  - `flattenStage(stage: Konva.Stage, pixelRatio?: number): string` — `stage.toDataURL()` wrapper (thin; kept for a single seam to mock in components).

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/lib/canvasFlatten.test.ts
import { describe, it, expect } from 'vitest'
import { dataUrlToFile } from './canvasFlatten'

// 1x1 transparent PNG
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='

describe('dataUrlToFile', () => {
  it('decodes a data URL into a PNG File', () => {
    const f = dataUrlToFile(PNG, 'front.png')
    expect(f).toBeInstanceOf(File)
    expect(f.type).toBe('image/png')
    expect(f.name).toBe('front.png')
    expect(f.size).toBeGreaterThan(0)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/lib/canvasFlatten.test.ts`
Expected: FAIL — cannot resolve `./canvasFlatten`.

- [ ] **Step 3: Implement**

```ts
// frontend/src/lib/canvasFlatten.ts
import type Konva from 'konva'

/** Decode a base64 data URL (image/png) into a File for multipart upload. */
export function dataUrlToFile(dataUrl: string, name: string): File {
  const [meta, b64] = dataUrl.split(',')
  const mime = /:(.*?);/.exec(meta)?.[1] ?? 'image/png'
  const bin = atob(b64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return new File([bytes], name, { type: mime })
}

/** Flatten a Konva stage to a PNG data URL. Thin wrapper = one mockable seam. */
export function flattenStage(stage: Konva.Stage, pixelRatio = 2): string {
  return stage.toDataURL({ pixelRatio, mimeType: 'image/png' })
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/lib/canvasFlatten.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/canvasFlatten.ts frontend/src/lib/canvasFlatten.test.ts
git commit -m "feat(canvas): stage flatten + dataUrl->File helper"
```

---

## Task 8: API client + types for the canvas flow

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces (in `api.ts`):
  - `createCanvasSession(opts: {productId?: string; hatTypeId?: string; colour?: HatColour}): Promise<CreateSessionResponse>`
  - `uploadCanvasLayouts(sessionId: string, layouts: {face: string; file: File}[]): Promise<{views: Record<string,string>}>`
  - `finalizeCanvas(sessionId: string, body: {canvas_design: unknown; email?: string; name?: string}): Promise<ChatResponse>`

- [ ] **Step 1: Add the types**

In `frontend/src/lib/types.ts` append:

```ts
export interface CanvasLayoutsResponse { views: Record<string, string> }
```

- [ ] **Step 2: Add the API functions**

In `frontend/src/lib/api.ts` (reuse the existing `request`/`ChatResponse`/`CreateSessionResponse`/`HatColour`):

```ts
export function createCanvasSession(
  opts: { productId?: string; hatTypeId?: string; colour?: HatColour },
): Promise<CreateSessionResponse> {
  const body: Record<string, unknown> = {}
  if (opts.productId) body.product_id = opts.productId
  if (opts.hatTypeId) body.hat_type_id = opts.hatTypeId
  if (opts.colour) body.colour = opts.colour
  return request<CreateSessionResponse>('/sessions/canvas', {
    method: 'POST', body: JSON.stringify(body),
  })
}

export function uploadCanvasLayouts(
  sessionId: string, layouts: { face: string; file: File }[],
): Promise<{ views: Record<string, string> }> {
  const fd = new FormData()
  for (const { face, file } of layouts) {
    fd.append('faces', face)
    fd.append('files', file)
  }
  return request<{ views: Record<string, string> }>(`/sessions/${sessionId}/canvas-layouts`, {
    method: 'POST', body: fd,
  })
}

export function finalizeCanvas(
  sessionId: string, body: { canvas_design: unknown; email?: string; name?: string },
): Promise<ChatResponse> {
  return request<ChatResponse>(`/sessions/${sessionId}/canvas-finalize`, {
    method: 'POST', body: JSON.stringify(body),
  })
}
```

Add `import type { CreateSessionResponse, ChatResponse } from './types'` if not
already imported, and ensure `HatColour` is exported (it already is, from api.ts).

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors from these additions.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/types.ts
git commit -m "feat(canvas): api client + types for canvas session flow"
```

---

## Task 9: Konva element nodes (`nodes.tsx`)

**Files:**
- Create: `frontend/src/components/DesignStudio/nodes.tsx`

**Interfaces:**
- Produces: `TextNode`, `ImageNode` React components. Each takes
  `{ el: CanvasElement; stageW: number; stageH: number; isSelected: boolean; onSelect(): void; onChange(patch: Partial<CanvasElement>): void }`
  and converts normalised geometry ↔ pixels, committing drag/transform back via `onChange`.

> No unit test for the Konva nodes (rendering canvas nodes under jsdom has no
> stable assertions). They're exercised via the store tests (Task 6) and the
> manual verify (Task 12). Keep them thin — geometry math only.

- [ ] **Step 1: Implement the nodes**

```tsx
// frontend/src/components/DesignStudio/nodes.tsx
import { useRef, useEffect } from 'react'
import { Text, Image as KonvaImage, Transformer, Group } from 'react-konva'
import type Konva from 'konva'
import type { CanvasElement } from '../../store/canvasStore'

interface NodeProps {
  el: CanvasElement
  stageW: number
  stageH: number
  isSelected: boolean
  onSelect: () => void
  onChange: (patch: Partial<CanvasElement>) => void
}

function useTransformer(isSelected: boolean) {
  const shapeRef = useRef<Konva.Node>(null)
  const trRef = useRef<Konva.Transformer>(null)
  useEffect(() => {
    if (isSelected && trRef.current && shapeRef.current) {
      trRef.current.nodes([shapeRef.current])
      trRef.current.getLayer()?.batchDraw()
    }
  }, [isSelected])
  return { shapeRef, trRef }
}

export function TextNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  return (
    <Group>
      <Text
        ref={shapeRef as never}
        text={el.content ?? ''}
        x={el.x * stageW}
        y={el.y * stageH}
        rotation={el.rotation}
        fontSize={el.fontSize ?? 36}
        fontFamily={el.font ?? 'Arial'}
        fill={el.colour ?? '#ffffff'}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          const node = e.target as Konva.Text
          onChange({
            rotation: node.rotation(),
            fontSize: Math.max(8, (el.fontSize ?? 36) * node.scaleX()),
          })
          node.scaleX(1); node.scaleY(1)
        }}
      />
      {isSelected && <Transformer ref={trRef as never} enabledAnchors={['top-left','top-right','bottom-left','bottom-right']} rotateEnabled />}
    </Group>
  )
}

export function ImageNode({ el, stageW, stageH, isSelected, onSelect, onChange }: NodeProps) {
  const { shapeRef, trRef } = useTransformer(isSelected)
  const imgRef = useRef<HTMLImageElement | null>(null)
  const forceRef = useRef(0)
  if (!imgRef.current && el.assetUrl) {
    const img = new window.Image()
    img.crossOrigin = 'anonymous' // required so stage.toDataURL() isn't tainted
    img.src = el.assetUrl
    img.onload = () => { forceRef.current++; shapeRef.current?.getLayer()?.batchDraw() }
    imgRef.current = img
  }
  return (
    <Group>
      <KonvaImage
        ref={shapeRef as never}
        image={imgRef.current ?? undefined}
        x={el.x * stageW}
        y={el.y * stageH}
        width={el.width * stageW}
        height={el.height * stageH}
        rotation={el.rotation}
        draggable
        onClick={onSelect}
        onTap={onSelect}
        onDragEnd={e => onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH })}
        onTransformEnd={e => {
          const node = e.target as Konva.Image
          onChange({
            rotation: node.rotation(),
            width: (node.width() * node.scaleX()) / stageW,
            height: (node.height() * node.scaleY()) / stageH,
          })
          node.scaleX(1); node.scaleY(1)
        }}
      />
      {isSelected && <Transformer ref={trRef as never} rotateEnabled />}
    </Group>
  )
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/DesignStudio/nodes.tsx
git commit -m "feat(canvas): konva text + image nodes with normalised geometry"
```

---

## Task 10: CanvasStage, ToolRail, SelectedToolbar

**Files:**
- Create: `frontend/src/components/DesignStudio/CanvasStage.tsx`
- Create: `frontend/src/components/DesignStudio/ToolRail.tsx`
- Create: `frontend/src/components/DesignStudio/SelectedToolbar.tsx`

**Interfaces:**
- Produces:
  - `CanvasStage` — takes `{ stageRef: RefObject<Konva.Stage> }`; renders the active face's product image as a background `KonvaImage` + all elements for the active face + deselect-on-empty-click. Fixed logical size (e.g. 480×480); the parent scales it responsively.
  - `ToolRail` — `{ onAddText(): void; onUploadClick(): void; colourways: Colourway[]; onRender(): void; rendering: boolean }`.
  - `SelectedToolbar` — reads the selected element from the store; edits font/colour/fontSize, delete, layer up/down.

- [ ] **Step 1: Implement CanvasStage**

```tsx
// frontend/src/components/DesignStudio/CanvasStage.tsx
import { useRef, useEffect, useState, type RefObject } from 'react'
import { Stage, Layer, Image as KonvaImage } from 'react-konva'
import type Konva from 'konva'
import { useCanvasStore } from '../../store/canvasStore'
import { TextNode, ImageNode } from './nodes'

export const STAGE_W = 480
export const STAGE_H = 480

export function CanvasStage({ stageRef }: { stageRef: RefObject<Konva.Stage> }) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const faceImages = useCanvasStore(s => s.faceImages)
  const selectedId = useCanvasStore(s => s.selectedId)
  const select = useCanvasStore(s => s.select)
  const updateElement = useCanvasStore(s => s.updateElement)

  const [bg, setBg] = useState<HTMLImageElement | null>(null)
  const bgUrl = faceImages[activeFace]
  useEffect(() => {
    if (!bgUrl) { setBg(null); return }
    const img = new window.Image()
    img.crossOrigin = 'anonymous' // avoid tainting the canvas for toDataURL()
    img.src = bgUrl
    img.onload = () => setBg(img)
  }, [bgUrl])

  const els = [...faces[activeFace]].sort((a, b) => a.zIndex - b.zIndex)

  return (
    <Stage
      ref={stageRef as never}
      width={STAGE_W}
      height={STAGE_H}
      onMouseDown={e => { if (e.target === e.target.getStage()) select(null) }}
      onTouchStart={e => { if (e.target === e.target.getStage()) select(null) }}
      className="rounded-2xl bg-surface"
    >
      <Layer>
        {bg && <KonvaImage image={bg} width={STAGE_W} height={STAGE_H} listening={false} />}
        {els.map(el =>
          el.type === 'text' ? (
            <TextNode key={el.id} el={el} stageW={STAGE_W} stageH={STAGE_H}
              isSelected={el.id === selectedId} onSelect={() => select(el.id)}
              onChange={p => updateElement(el.id, p)} />
          ) : (
            <ImageNode key={el.id} el={el} stageW={STAGE_W} stageH={STAGE_H}
              isSelected={el.id === selectedId} onSelect={() => select(el.id)}
              onChange={p => updateElement(el.id, p)} />
          ),
        )}
      </Layer>
    </Stage>
  )
}
```

- [ ] **Step 2: Implement ToolRail**

```tsx
// frontend/src/components/DesignStudio/ToolRail.tsx
import type { Colourway } from '../../store/canvasStore'
import { useCanvasStore } from '../../store/canvasStore'

interface ToolRailProps {
  onAddText: () => void
  onUploadClick: () => void
  colourways: Colourway[]
  onRender: () => void
  rendering: boolean
}

export function ToolRail({ onAddText, onUploadClick, colourways, onRender, rendering }: ToolRailProps) {
  const colourway = useCanvasStore(s => s.colourway)
  const setColourway = useCanvasStore(s => s.setColourway)
  return (
    <div className="flex flex-col gap-3 p-4 w-full md:w-64">
      <button onClick={onAddText} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors">+ Add text</button>
      <button onClick={onUploadClick} className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors">↑ Upload logo</button>
      <button disabled className="px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textMuted opacity-60 cursor-not-allowed" title="Coming soon">◈ Clipart (soon)</button>

      {colourways.length > 0 && (
        <div>
          <p className="text-xs text-textMuted mb-1.5">Cap colour</p>
          <div className="flex flex-wrap gap-2">
            {colourways.map(c => (
              <button key={`${c.hex}-${c.name}`} onClick={() => setColourway(c)} aria-label={c.name}
                className={`w-7 h-7 rounded-full border-2 ${colourway?.hex === c.hex ? 'border-accent' : 'border-border'}`}
                style={{ background: c.hex }} title={c.name} />
            ))}
          </div>
        </div>
      )}

      <button onClick={onRender} disabled={rendering}
        className="mt-auto px-4 py-3 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold disabled:opacity-50 transition-colors">
        {rendering ? 'Rendering…' : 'See it rendered'}
      </button>
    </div>
  )
}
```

- [ ] **Step 3: Implement SelectedToolbar**

```tsx
// frontend/src/components/DesignStudio/SelectedToolbar.tsx
import { useCanvasStore } from '../../store/canvasStore'

const FONTS = ['Arial', 'Impact', 'Georgia', 'Courier New', 'Verdana']

export function SelectedToolbar() {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)
  if (!el) return null

  return (
    <div className="flex flex-wrap items-center gap-2 p-3 bg-surface border border-border rounded-xl">
      {el.type === 'text' && (
        <>
          <input value={el.content ?? ''} onChange={e => update(el.id, { content: e.target.value })}
            className="bg-base border border-border rounded px-2 py-1 text-sm text-textPrimary" aria-label="Text content" />
          <select value={el.font ?? 'Arial'} onChange={e => update(el.id, { font: e.target.value })}
            className="bg-base border border-border rounded px-2 py-1 text-sm" aria-label="Font">
            {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
          <input type="color" value={el.colour ?? '#ffffff'} onChange={e => update(el.id, { colour: e.target.value })}
            className="w-8 h-8 p-0 border-0 bg-transparent" aria-label="Text colour" />
          <input type="range" min={12} max={96} value={el.fontSize ?? 36}
            onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
        </>
      )}
      {el.type === 'image' && (
        <label className="flex items-center gap-1.5 text-sm text-textPrimary">
          <input type="checkbox" checked={!!el.removeBg} onChange={e => update(el.id, { removeBg: e.target.checked })} />
          Remove background
        </label>
      )}
      <button onClick={() => reorder(el.id, 'up')} className="px-2 py-1 text-sm border border-border rounded" title="Bring forward">↑</button>
      <button onClick={() => reorder(el.id, 'down')} className="px-2 py-1 text-sm border border-border rounded" title="Send back">↓</button>
      <button onClick={() => remove(el.id)} className="px-2 py-1 text-sm text-red-600 border border-red-200 rounded" title="Delete">Delete</button>
    </div>
  )
}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DesignStudio/CanvasStage.tsx frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/components/DesignStudio/SelectedToolbar.tsx
git commit -m "feat(canvas): CanvasStage + ToolRail + SelectedToolbar"
```

---

## Task 11: DesignStudio shell + face tabs + "See it rendered" flow

**Files:**
- Create: `frontend/src/components/DesignStudio/index.tsx`

**Interfaces:**
- Consumes: `canvasStore`, `sessionStore` (`sessionId`, `productRef`), `api` (`uploadCanvasLayouts`, `finalizeCanvas`, `uploadLogo`), `canvasFlatten`, `chatStore.hydrate`, `sessionStore` view switch.
- Produces: the full design page. On "See it rendered": collect email inline → flatten each decorated face → `uploadCanvasLayouts` → `finalizeCanvas` → hydrate `chatStore` to the finalize response → set session view to `'session'` (hand off to ChatPanel for verify/deliver).

- [ ] **Step 1: Implement the shell**

```tsx
// frontend/src/components/DesignStudio/index.tsx
import { useEffect, useRef, useState } from 'react'
import type Konva from 'konva'
import { useSessionStore } from '../../store/sessionStore'
import { useCanvasStore, FACES, type Face, type Colourway } from '../../store/canvasStore'
import { useChatStore } from '../../store/chatStore'
import { CanvasStage } from './CanvasStage'
import { ToolRail } from './ToolRail'
import { SelectedToolbar } from './SelectedToolbar'
import { Modal } from '../Modal'
import { flattenStage, dataUrlToFile } from '../../lib/canvasFlatten'
import { uploadLogo, uploadCanvasLayouts, finalizeCanvas } from '../../lib/api'

export function DesignStudio() {
  const sessionId = useSessionStore(s => s.sessionId)
  const productRef = useSessionStore(s => s.productRef)
  const setView = useSessionStore.setState

  const activeFace = useCanvasStore(s => s.activeFace)
  const setActiveFace = useCanvasStore(s => s.setActiveFace)
  const faces = useCanvasStore(s => s.faces)
  const addText = useCanvasStore(s => s.addText)
  const addImage = useCanvasStore(s => s.addImage)
  const setFaceImages = useCanvasStore(s => s.setFaceImages)
  const toCanvasDesign = useCanvasStore(s => s.toCanvasDesign)

  const stageRef = useRef<Konva.Stage>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const [rendering, setRendering] = useState(false)
  const [emailOpen, setEmailOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)

  // Seed the four face backgrounds from the product reference.
  useEffect(() => {
    if (productRef) {
      const v = productRef.view_images || {}
      setFaceImages({
        front: v.front || productRef.reference_image_url,
        back: v.back || '', left: v.left || '', right: v.right || '',
      })
    }
  }, [productRef, setFaceImages])

  const colourways: Colourway[] = [] // Phase 1: seeded from hat type when available (blank flow)

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !sessionId) return
    try {
      const { asset_url } = await uploadLogo(sessionId, file)
      addImage(asset_url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
  }

  async function doRender() {
    if (!sessionId) return
    setRendering(true); setError(null)
    try {
      // Flatten the CURRENT active face, then each other decorated face. Konva
      // renders one stage; switch faces, let it paint, flatten. Simplest: flatten
      // the active face now; for other decorated faces, re-render via activeFace.
      const design = toCanvasDesign()
      const layouts: { face: string; file: File }[] = []
      for (const face of FACES as Face[]) {
        if (design.faces[face].length === 0) continue
        setActiveFace(face)
        await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))
        const stage = stageRef.current
        if (!stage) continue
        const url = flattenStage(stage)
        layouts.push({ face, file: dataUrlToFile(url, `${face}.png`) })
      }
      if (layouts.length) await uploadCanvasLayouts(sessionId, layouts)
      const res = await finalizeCanvas(sessionId, { canvas_design: design, email: email || undefined })
      // Hand off to the existing ChatPanel for verify -> deliver -> refine.
      useChatStore.getState().hydrate([], res.state, res.data)
      setView({ view: 'session' })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
      setRendering(false)
    }
  }

  function onRenderClick() {
    if (email) void doRender()
    else setEmailOpen(true)
  }

  return (
    <div className="h-screen bg-base flex flex-col">
      <header className="bg-surface border-b border-border px-6 py-3.5 flex items-center gap-3">
        <span className="text-accent font-extrabold text-lg tracking-wide">MAD HATS</span>
        {productRef && <span className="text-sm text-textMuted truncate">{productRef.name} › Design</span>}
      </header>

      {error && <div role="alert" className="mx-6 mt-3 rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>}

      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto">
          <div className="flex gap-2">
            {(FACES as Face[]).map(f => (
              <button key={f} onClick={() => setActiveFace(f)}
                className={`px-3 py-1 rounded-full text-xs capitalize ${activeFace === f ? 'bg-accent text-white' : 'bg-surface border border-border text-textMuted'} ${faces[f].length ? 'font-semibold' : ''}`}>
                {f}{faces[f].length ? ` (${faces[f].length})` : ''}
              </button>
            ))}
          </div>
          <CanvasStage stageRef={stageRef} />
          <SelectedToolbar />
        </div>

        <div className="md:border-l border-border">
          <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
            colourways={colourways} onRender={onRenderClick} rendering={rendering} />
        </div>
      </div>

      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" onChange={handleUpload} className="sr-only" aria-label="Upload logo" />

      <Modal open={emailOpen} title="Where should we send it?" onClose={() => setEmailOpen(false)}>
        <div className="flex flex-col gap-3 p-2">
          <p className="text-sm text-textSub">Pop in your email — it saves your progress and we'll send your rendered design there.</p>
          <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com"
            className="bg-base border border-border rounded-xl px-3 py-2 text-sm" />
          <button onClick={() => { setEmailOpen(false); void doRender() }} disabled={!email.includes('@')}
            className="px-4 py-2 bg-accent text-white rounded-full text-sm font-semibold disabled:opacity-50">
            See it rendered
          </button>
        </div>
      </Modal>
    </div>
  )
}
```

> **Known risk — canvas taint:** `stage.toDataURL()` throws a SecurityError if any
> image on the stage was loaded cross-origin without CORS. All images set
> `crossOrigin = 'anonymous'` (Tasks 9 & 10). The product/logo images come from
> the backend `/media` proxy and signed storage URLs; confirm those respond with
> `Access-Control-Allow-Origin` during the Task 12 verify. If a face is tainted,
> `doRender` surfaces the error — the documented contingency (not built in P1) is
> server-side compositing from `canvas_design` via `services/composite.py`.

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/DesignStudio/index.tsx
git commit -m "feat(canvas): DesignStudio shell + face tabs + see-it-rendered flow"
```

---

## Task 12: Route entry points to the canvas + verify end-to-end

**Files:**
- Modify: `frontend/src/store/sessionStore.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/BlankHatPicker/index.tsx`
- Test: `frontend/src/__tests__/sessionStore.test.ts` (extend)

**Interfaces:**
- Produces: `SessionView` gains `'canvas'`; `startCanvasSession(productId)` and `startCanvasBlankSession(hatType, colour?)` create a canvas session and set `view: 'canvas'`; `bootstrapFromUrl` routes `?product_id` → `startCanvasSession`, `?mode=blank` → BlankHatPicker → `startCanvasBlankSession`.
- Consumes: `createCanvasSession` (Task 8).

- [ ] **Step 1: Write the failing test**

```ts
// add to frontend/src/__tests__/sessionStore.test.ts
import { vi } from 'vitest'

it('bootstrapFromUrl with ?product_id starts a canvas session', async () => {
  const api = await import('../lib/api')
  vi.spyOn(api, 'fetchProduct').mockResolvedValue({
    id: 'p1', style: 's', colour: 'navy', name: 'Cap', reference_image_url: 'http://x/f.png',
    view_images: { front: 'http://x/f.png' }, placement_zones: [], decoration_types: [],
  } as never)
  vi.spyOn(api, 'createCanvasSession').mockResolvedValue({ session_id: 's1', share_token: 't', state: 'canvas_design' } as never)
  window.history.pushState({}, '', '/?product_id=p1')
  const { useSessionStore } = await import('../store/sessionStore')
  await useSessionStore.getState().bootstrapFromUrl()
  expect(useSessionStore.getState().view).toBe('canvas')
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/sessionStore.test.ts`
Expected: FAIL — `view` is `'session'` (old chat path) or `createCanvasSession` unused.

- [ ] **Step 3: Update `sessionStore`**

- Change the view type: `export type SessionView = 'picker' | 'session' | 'blank' | 'canvas'`.
- Import `createCanvasSession` from `../lib/api`.
- Add:

```ts
  startCanvasSession: async (product: Product) => {
    const response = await createCanvasSession({ productId: product.id })
    set({
      sessionId: response.session_id, shareToken: response.share_token, state: response.state,
      productRef: {
        id: product.id, name: product.name, colour: product.colour, style: product.style,
        reference_image_url: product.reference_image_url, view_images: product.view_images,
      },
      view: 'canvas',
    })
  },

  startCanvasBlankSession: async (hatType: HatType, colour?: { name: string; hex: string }) => {
    const response = await createCanvasSession({ hatTypeId: hatType.id, colour })
    set({
      sessionId: response.session_id, shareToken: response.share_token, state: response.state,
      productRef: {
        id: hatType.id, name: hatType.name, colour: colour?.name ?? '', style: hatType.style,
        reference_image_url: hatType.view_images.front ?? '', view_images: hatType.view_images,
      },
      view: 'canvas',
    })
  },
```

Add both to the `SessionState` interface. In `bootstrapFromUrl`, replace the
`?product_id` branch's `await get().startSession(product)` with
`await get().startCanvasSession(product)`. (The `?mode=blank` branch still sets
`view: 'blank'` → BlankHatPicker handles the next step in Step 5.)

- [ ] **Step 4: Render the canvas view in App.tsx**

In `frontend/src/App.tsx`, add an import and a branch before the `'session'` check:

```tsx
import { DesignStudio } from './components/DesignStudio'
// ...
  if (sessionView === 'canvas') {
    return <DesignStudio />
  }
```

- [ ] **Step 5: BlankHatPicker → canvas blank session**

In `frontend/src/components/BlankHatPicker/index.tsx`, wherever it currently calls
`startBlankSession(hatType, colour)` on selection, call
`startCanvasBlankSession(hatType, colour)` instead (grep the file for
`startBlankSession`). Keep the picker UI unchanged.

- [ ] **Step 6: Run the store test + full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: the new test PASSES; pre-existing suite green apart from the two known
`adminQuotes` Router-context failures noted in CLAUDE.md.

- [ ] **Step 7: Manual end-to-end verify (real app)**

Run the stack (`docker compose up`), open `http://localhost:5173/?product_id=<seeded>`:
- Add text on Front; switch to Back, add text; upload a logo on Left.
- Click **See it rendered**, enter an email.
- Confirm: no `SecurityError` in the console (canvas not tainted); network shows
  `POST /sessions/{id}/canvas-layouts` (200) then `POST /sessions/{id}/canvas-finalize` (200, `state: "generating"`); the app hands off to the chat status ("generating…"); after the emailed verification link is clicked, the design reveals in the ProductViewer with front (AI-rendered) + the flattened back/left faces.

Fix any issue found before committing (if the canvas is tainted, that's the CORS
risk from Task 11 — verify the `/media` + signed-URL responses include
`Access-Control-Allow-Origin`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/store/sessionStore.ts frontend/src/App.tsx frontend/src/components/BlankHatPicker/index.tsx frontend/src/__tests__/sessionStore.test.ts
git commit -m "feat(canvas): route product_id + blank entry to the canvas studio"
```

---

## Task 13: Full-suite regression + docs

**Files:**
- Modify: `CLAUDE.md` (implementation-state note)

- [ ] **Step 1: Backend full suite**

Run: `cd backend && pytest -q`
Expected: all green (prior 387 + the new canvas tests).

- [ ] **Step 2: Frontend full suite**

Run: `cd frontend && npx vitest run`
Expected: green apart from the two known `adminQuotes` failures.

- [ ] **Step 3: Update CLAUDE.md**

Add a bullet under "Current implementation state" summarising the canvas flow:
entry (`?product_id` / `?mode=blank`) now lands on the react-konva **Design
Studio** (multi-face canvas), which replaces the Q&A deep-dive; "See it rendered"
flattens each decorated face → layout-guide PNGs + auto-built description →
existing generation/delivery; front is AI-rendered, non-front faces reuse the
flattened PNG; post-design handoff reuses ChatPanel for verify/deliver/refine.
Note Phase 2 (clipart) and Phase 3 (AI chat helper + smart suggestions) are pending.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(canvas): record Phase 1 canvas studio in project memory"
```

---

## Self-Review Notes (author)

- **Spec coverage:** §4 UX → Tasks 10–12; §5 frontend arch → Tasks 6–11; §6 data model + persistence → Tasks 1, 5, 6; §7 flatten/upload/describe → Tasks 2, 5, 7, 11; §8 generation wiring (layout guide, front-AI/others-flattened) → Tasks 3, 4; §9 state path → Task 5 (`CANVAS_DESIGN` + finalize→generating) + ChatPanel handoff (Task 11); §10 testing → each task's tests + Task 13.
- **Deferred (per spec §11):** clipart (disabled button placeholder only), AI chat helper, smart suggestions, AI-render-every-face.
- **Known risk carried forward:** canvas taint / CORS on `toDataURL()` — mitigated by `crossOrigin='anonymous'`, verified in Task 12 Step 7, with the server-composite contingency documented.
- **Type consistency:** `canvas_to_elements` element keys match `prompt_builder` consumers (`type`,`content`,`placement_zone`,`placement_position`,`colour`,`font`,`size`,`remove_bg`); `CanvasElement`/`CanvasDesign`/`Face` shared across store, nodes, flatten, api.
