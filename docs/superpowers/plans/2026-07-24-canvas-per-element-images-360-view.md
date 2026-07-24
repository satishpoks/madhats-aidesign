# Canvas per-element images + admin 360° view — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve every canvas-uploaded image per element so generation conditions each face on its own artwork (no missing/duplicate images) and the admin 360° view can show + download the customer's real design.

**Architecture:** Uploaded images gain a re-signable storage `assetPath` on each canvas element (upload endpoint → frontend store → `canvas_design` → described element). Generation's canvas branch resolves each view's own logo images from `elements_for_view` instead of a single global scalar, and the provider accepts a list of artworks. The admin session endpoint derives a per-face `canvas_faces` payload (preview, layout guide, individual images re-proxied via `/media`, element text) that a new `SessionDetailView` section renders with per-image download. A pure `path_from_signed_url` helper recovers individual images from existing sessions' expired signed URLs.

**Tech Stack:** Python 3.12 / FastAPI, supabase-py, Pillow, Gemini image models; React 18 / Vite / Zustand / Tailwind; pytest, vitest.

## Global Constraints

- Backend tests run with `CANVAS_ORCHESTRATOR_V2=false` (repo `.env` defaults it to `true`, which flips 3 unrelated tests): `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`.
- Frontend targeted tests only (full `vitest run` stalls on this Windows host): `cd frontend && npx vitest run <file>`.
- No SQL migration — `canvas_design` and `collected` are JSONB; all new keys are additive.
- Private bucket is `madhats-assets`; images reach the admin browser only via the `/media/{token}` proxy (`media_url(path, base_url)`), never raw signed URLs.
- All generation changes are gated inside the existing `is_canvas` branch or on the new `uploaded_asset_urls` kwarg — v1 customise/blank single-logo rendering must stay byte-identical.
- No PII in logs.
- Commit after each task. Work on branch `feat/canvas-per-element-images-360-view` (spec already committed there).

---

### Task 1: `path_from_signed_url` storage helper

Recovers a bucket-relative storage path from a Supabase signed/public URL so
existing sessions' individual uploads (stored as now-expired signed URLs in
`canvas_design`) can be re-proxied.

**Files:**
- Modify: `backend/app/storage.py` (add function near `media_url`, ~line 148)
- Test: `backend/tests/test_storage_path_from_signed_url.py` (create)

**Interfaces:**
- Produces: `path_from_signed_url(url: str | None) -> str | None`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_storage_path_from_signed_url.py
from app.storage import path_from_signed_url


def test_extracts_path_from_signed_url():
    url = (
        "http://host.docker.internal:54321/storage/v1/object/sign/"
        "madhats-assets/canvas_front_ab12cd.png?token=eyJhbGciOi.abc.def"
    )
    assert path_from_signed_url(url) == "canvas_front_ab12cd.png"


def test_extracts_nested_path_and_ignores_query():
    url = (
        "https://proj.supabase.co/storage/v1/object/public/"
        "madhats-assets/sub/dir/logo.png?download=1"
    )
    assert path_from_signed_url(url) == "sub/dir/logo.png"


def test_returns_none_for_non_storage_url():
    assert path_from_signed_url("https://cdn.shopify.com/x/cap.jpg") is None
    assert path_from_signed_url("/media/abc") is None


def test_returns_none_for_empty():
    assert path_from_signed_url(None) is None
    assert path_from_signed_url("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_storage_path_from_signed_url.py -q`
Expected: FAIL with `ImportError: cannot import name 'path_from_signed_url'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/storage.py — add after media_url()
_BUCKET_MARKERS = ("/object/sign/madhats-assets/", "/object/public/madhats-assets/")


def path_from_signed_url(url: str | None) -> str | None:
    """Extract the bucket-relative storage path from a Supabase signed/public URL.

    Existing canvas sessions persisted expiring signed URLs on their image
    elements; the storage object still exists, so recovering the path lets us
    re-sign / re-proxy it. Returns None for anything that isn't a
    madhats-assets storage URL (external product images, /media proxies)."""
    if not url:
        return None
    for marker in _BUCKET_MARKERS:
        idx = url.find(marker)
        if idx != -1:
            rest = url[idx + len(marker):]
            return rest.split("?", 1)[0] or None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_storage_path_from_signed_url.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/storage.py backend/tests/test_storage_path_from_signed_url.py
git commit -m "feat(storage): path_from_signed_url to recover storage paths"
```

---

### Task 2: `/uploads/logo` returns `asset_path`

**Files:**
- Modify: `backend/app/api/routes/uploads.py:51` (return dict)
- Test: `backend/tests/test_uploads_asset_path.py` (create)

**Interfaces:**
- Produces: `POST /uploads/logo/{session_id}` response includes `asset_path: str` (the private-bucket storage path), plus the existing `asset_url`, `asset_hash`.

- [ ] **Step 1: Write the failing test**

Check existing upload tests for the fixture pattern first: `grep -rl "uploads/logo" backend/tests`. Mirror their client + session-seeding + storage-monkeypatch setup. The assertion:

```python
# backend/tests/test_uploads_asset_path.py
# (Reuse the app TestClient + seeded session + upload_asset/generate_signed_url
#  monkeypatch pattern from the existing uploads test.)

def test_upload_logo_returns_asset_path(client, seeded_session, patched_storage):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64  # sniff_image_mime must accept; use a real tiny PNG fixture
    res = client.post(
        f"/uploads/logo/{seeded_session}",
        files={"file": ("logo.png", png, "image/png")},
    )
    assert res.status_code == 200
    body = res.json()
    assert "asset_path" in body
    assert body["asset_path"]  # non-empty storage path
    assert "asset_url" in body and "asset_hash" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_uploads_asset_path.py -q`
Expected: FAIL with `KeyError`/assert on `asset_path` missing.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/routes/uploads.py — replace the return in upload_logo()
    return {
        "asset_url": generate_signed_url(path),
        "asset_path": path,
        "asset_hash": asset_hash,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_uploads_asset_path.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/uploads.py backend/tests/test_uploads_asset_path.py
git commit -m "feat(uploads): return asset_path from /uploads/logo"
```

---

### Task 3: `canvas_describe` — shared element label + carry `assetPath`

Extract one source of truth for element text (used by both the prompt
description and the admin view), and copy `assetPath` onto described logo
elements so generation can re-sign per element.

**Files:**
- Modify: `backend/app/services/canvas_describe.py`
- Test: `backend/tests/test_canvas_describe_assetpath.py` (create)
- Existing tests to keep green: `grep -rl canvas_describe backend/tests`

**Interfaces:**
- Produces: `element_label(el: dict, face: str | None = None) -> str` (human phrase, e.g. `text reading "SATISH", in white, Arial font` / `filled blue rectangle` / `a hand-drawn line in #111827` / `uploaded logo/artwork`).
- Produces: described logo element now includes `assetPath` (from `el.get("assetPath")`) alongside `assetUrl`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_canvas_describe_assetpath.py
from app.services import canvas_describe as cd


def test_logo_element_carries_asset_path():
    design = {"faces": {"front": [
        {"type": "image", "assetUrl": "http://x/sign/y?t=1",
         "assetPath": "canvas_front_ab.png", "x": 0.1, "y": 0.1,
         "width": 0.2, "height": 0.2, "zIndex": 0},
    ], "back": [], "left": [], "right": []}}
    elements, _ = cd.canvas_to_elements(design)
    logo = elements[0]
    assert logo["type"] == "logo"
    assert logo["assetPath"] == "canvas_front_ab.png"
    assert logo["assetUrl"] == "http://x/sign/y?t=1"


def test_element_label_covers_kinds():
    assert 'SATISH' in cd.element_label(
        {"type": "text", "content": "SATISH", "colour": "#ffffff", "font": "Arial"})
    assert cd.element_label(
        {"type": "shape", "shapeKind": "rect", "fill": "blue", "filled": True}
    ) == "filled blue rectangle"
    assert cd.element_label(
        {"type": "drawing", "stroke": "#111827"}) == "a hand-drawn line in #111827"
    assert cd.element_label({"type": "image"}) == "uploaded logo/artwork"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_describe_assetpath.py -q`
Expected: FAIL (`AttributeError: module ... has no attribute 'element_label'` and missing `assetPath`).

- [ ] **Step 3: Write minimal implementation**

In `canvas_describe.py`:

1. Add `assetPath` to the image branch of `_element` (after the existing `assetUrl` line, ~line 102):

```python
        out["assetUrl"] = el.get("assetUrl")
        out["assetPath"] = el.get("assetPath")
        out["remove_bg"] = bool(el.get("removeBg"))
```

2. Add a public `element_label` that reuses the existing phrase helpers, and make `_describe` delegate to it for the non-position part. Add near `_describe`:

```python
def element_label(el: dict, face: str | None = None) -> str:
    """Human phrase for one element (no placement). Single source of truth for
    both the prompt description and the admin 360 view."""
    etype = el.get("type")
    if etype == "text":
        parts = [f'text reading "{el.get("content", "")}"', f"in {_text_colour(el.get('colour'))}"]
        if el.get("font"):
            parts.append(f'{el["font"]} font')
        label = ", ".join(parts)
    elif etype == "drawing":
        colour = el.get("stroke")
        label = f"a hand-drawn line in {colour}" if colour else "a hand-drawn line"
    elif etype == "shape":
        label = _shape_phrase(el)
    else:
        label = "uploaded logo/artwork"
    if face:
        return f"{label} on the {_FACE_LABEL.get(face, face)}"
    return label
```

3. Refactor `_describe` to delegate (keeps existing output shape — text keeps its comma format, shape keeps the leading "a "):

```python
def _describe(el: dict, face: str) -> str:
    etype = el.get("type")
    if etype == "shape":
        return f"a {_shape_phrase(el)} on the {_FACE_LABEL.get(face, face)}"
    return element_label(el, face)
```

- [ ] **Step 4: Run tests to verify they pass (and existing canvas_describe tests stay green)**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_describe_assetpath.py $(grep -rl canvas_describe backend/tests | tr '\n' ' ') -q`
Expected: PASS (new + all pre-existing canvas_describe tests). If a pre-existing test asserts the exact `_describe` string, keep its wording identical — adjust `element_label` so outputs match verbatim.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/canvas_describe.py backend/tests/test_canvas_describe_assetpath.py
git commit -m "feat(canvas_describe): shared element_label + carry assetPath"
```

---

### Task 4: Provider accepts a list of uploaded artworks

**Files:**
- Modify: `backend/app/services/image/image_provider.py:41-50` (abstract signature)
- Modify: `backend/app/services/image/adapters/stub.py:18-26`
- Modify: `backend/app/services/image/adapters/gemini_base.py:210-291`
- Test: `backend/tests/test_provider_uploaded_list.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `ImageProvider.generate(..., uploaded_asset_urls: list[str] | None = None)`. When provided (non-empty), each URL is attached as an artwork image part. Single `uploaded_asset_url` still supported; the adapter normalises to a list internally: `urls = uploaded_asset_urls or ([uploaded_asset_url] if uploaded_asset_url else [])`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_provider_uploaded_list.py
import inspect
from app.services.image.image_provider import ImageProvider
from app.services.image.adapters.stub import StubAdapter


def test_generate_signature_has_uploaded_asset_urls():
    sig = inspect.signature(ImageProvider.generate)
    assert "uploaded_asset_urls" in sig.parameters
    assert inspect.signature(StubAdapter.generate).parameters["uploaded_asset_urls"]


async def test_stub_accepts_list(anyio_backend="asyncio"):
    from app.services.image.image_provider import GenerationParams
    res = await StubAdapter().generate(
        prompt="p", reference_image_url="http://x/ref.png",
        uploaded_asset_url=None, params=GenerationParams(tier="preview"),
        uploaded_asset_urls=["http://x/a.png", "http://x/b.png"],
    )
    assert res.image_url
```

(Match the async-test style used elsewhere in `backend/tests` — e.g. `@pytest.mark.anyio` or the project's async fixture. Check a neighbouring provider/gemini test.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_provider_uploaded_list.py -q`
Expected: FAIL (`uploaded_asset_urls` not in signature).

- [ ] **Step 3: Write minimal implementation**

`image_provider.py` — add the kwarg to the abstract method:

```python
    async def generate(
        self,
        prompt: str,
        reference_image_url: str,
        uploaded_asset_url: str | None,
        params: GenerationParams,
        prior_design_url: str | None = None,
        layout_guide_url: str | None = None,
        uploaded_asset_urls: list[str] | None = None,
    ) -> GenerationResult:
        ...
```

`stub.py` — add the kwarg (ignored):

```python
        layout_guide_url: str | None = None,
        uploaded_asset_urls: list[str] | None = None,
    ) -> GenerationResult:
```

`gemini_base.py` `generate()` — add the kwarg and replace the single-logo block (lines ~257-272) with a loop over the normalised list:

```python
        layout_guide_url: str | None = None,
        uploaded_asset_urls: list[str] | None = None,
    ) -> GenerationResult:
        ...
        # (after the prior_design block, replacing the `if uploaded_asset_url:` block)
        urls = uploaded_asset_urls or ([uploaded_asset_url] if uploaded_asset_url else [])
        multi = len(urls) > 1
        for i, art_url in enumerate(urls):
            try:
                logo_bytes, logo_mime = await _fetch_bytes(art_url)
                squared_logo = _to_square_logo(logo_bytes)
                if squared_logo is not logo_bytes:
                    logo_bytes, logo_mime = squared_logo, "image/png"
                label = _artwork_label(i) if multi else _SECOND_IMAGE_LABEL
                contents.append(label)
                contents.append({"mime_type": logo_mime, "data": logo_bytes})
                payload_parts.append({"type": "text", "text": label})
                payload_parts.append(
                    _image_part(logo_mime, logo_bytes, role="uploaded_asset", source_url=art_url)
                )
            except httpx.HTTPError:
                log.warning("logo_fetch_failed", tier=self.tier)
```

Add a module-level helper near the labels (~line 66):

```python
def _artwork_label(i: int) -> str:
    """Per-artwork label when a face carries multiple uploaded images. Ordinal-free
    so each reads correctly; same intent as _SECOND_IMAGE_LABEL."""
    return (
        f"ARTWORK {i + 1} — one of the customer's uploaded artworks to apply onto "
        "the cap as decoration ONLY, at the position shown in the layout guide. Use "
        "it as a reference; never reproduce it as a separate panel. It does NOT set "
        "the output shape, size or aspect ratio — those come only from the FIRST image."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_provider_uploaded_list.py -q`
Expected: PASS. Also run the existing gemini/provider tests: `pytest $(grep -rl gemini_base backend/tests | tr '\n' ' ') -q` — expected still green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/image/image_provider.py backend/app/services/image/adapters/stub.py backend/app/services/image/adapters/gemini_base.py backend/tests/test_provider_uploaded_list.py
git commit -m "feat(image): providers accept uploaded_asset_urls list"
```

---

### Task 5: Generation maps each canvas view to its own images (the bug fix)

**Files:**
- Modify: `backend/app/api/routes/generate.py` (`_render_view` signature ~258; `_run_generation` `_one` ~427-467; add `_canvas_view_images` helper)
- Test: `backend/tests/test_canvas_view_images.py` (create)

**Interfaces:**
- Consumes: `path_from_signed_url` (Task 1); `elements_for_view`, `view_has_logo` (existing `prompt_builder`); `generate_signed_url` (existing).
- Produces: `_canvas_view_images(collected: dict, view: str) -> list[str]` — ordered fetchable URLs for the given view's logo elements.

- [ ] **Step 1: Write the failing test** (this is the regression for the reported bug)

```python
# backend/tests/test_canvas_view_images.py
from app.api.routes import generate as gen


def _collected():
    # Mirrors canvas_describe output: front logo (path A), back logo (path B).
    return {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel", "placement_position": "centre",
         "assetPath": "canvas_front_A.png", "assetUrl": "http://x/sign/madhats-assets/canvas_front_A.png?t=1"},
        {"type": "logo", "placement_zone": "back", "placement_position": "centre",
         "assetPath": "canvas_back_B.png", "assetUrl": "http://x/sign/madhats-assets/canvas_back_B.png?t=1"},
    ]}


def test_front_gets_front_logo_only(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    assert gen._canvas_view_images(_collected(), "front") == ["signed://canvas_front_A.png"]


def test_back_gets_back_logo_only(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    assert gen._canvas_view_images(_collected(), "back") == ["signed://canvas_back_B.png"]


def test_recovers_path_from_signed_url_when_no_assetpath(monkeypatch):
    monkeypatch.setattr(gen, "generate_signed_url", lambda p: f"signed://{p}")
    c = {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel",
         "assetUrl": "http://x/storage/v1/object/sign/madhats-assets/old_front.png?t=9"},
    ]}
    assert gen._canvas_view_images(c, "front") == ["signed://old_front.png"]


def test_company_graphic_media_url_passthrough(monkeypatch):
    c = {"flow_mode": "canvas", "elements": [
        {"type": "logo", "placement_zone": "front_panel", "assetUrl": "http://api/media/tok123"},
    ]}
    assert gen._canvas_view_images(c, "front") == ["http://api/media/tok123"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_view_images.py -q`
Expected: FAIL (`_canvas_view_images` undefined).

- [ ] **Step 3: Write minimal implementation**

Add the helper (import `path_from_signed_url` from `app.storage` at top of `generate.py` — `generate_signed_url` is already imported there):

```python
def _canvas_view_images(collected: dict, view: str) -> list[str]:
    """Fetchable URLs for the logo elements on one canvas view, in order.

    Resolution per element: re-sign assetPath; else recover the path from an
    (expired) signed assetUrl and re-sign; else pass a /media or external http
    URL through as-is; else skip. Fixes the missing-first / duplicate-across-
    views bug where every logo view got the single global uploaded_asset_path."""
    urls: list[str] = []
    for el in prompt_builder.elements_for_view(collected, view):
        if el.get("type") != "logo":
            continue
        path = el.get("assetPath") or path_from_signed_url(el.get("assetUrl"))
        if path:
            urls.append(generate_signed_url(path))
            continue
        asset_url = el.get("assetUrl")
        if asset_url and asset_url.startswith("http"):
            urls.append(asset_url)
    return urls
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_view_images.py -q`
Expected: PASS.

- [ ] **Step 5: Wire it into `_run_generation` + `_render_view`**

In `_render_view` (signature ~258), add `uploaded_urls: list[str] | None = None` and pass it through to the provider call (~301):

```python
async def _render_view(
    *, view, provider, job_id, generation_id, session_id, tier,
    prompt, ref_url, uploaded_url, params, key, prior_design_url=None,
    layout_guide_url=None, uploaded_urls=None,
) -> dict:
    ...
            result = await asyncio.wait_for(
                provider.generate(
                    prompt=prompt, reference_image_url=ref_url,
                    uploaded_asset_url=uploaded_url, params=params,
                    prior_design_url=prior_design_url,
                    layout_guide_url=layout_guide_url,
                    uploaded_asset_urls=uploaded_urls,
                ),
                timeout=GENERATION_CALL_TIMEOUT_SECONDS,
            )
```

In `_one(view)` (~435), compute per-view images for canvas; keep v1 path unchanged:

```python
                # Canvas: each view gets ITS OWN uploaded image(s). v1 flows keep
                # the single global uploaded asset gated by view_has_logo.
                if is_canvas:
                    view_uploads = _canvas_view_images(collected, view)
                    uploaded = view_uploads[0] if view_uploads else None
                else:
                    view_uploads = None
                    uploaded = uploaded_url_full if prompt_builder.view_has_logo(collected, view) else None
```

And pass `uploaded_urls=view_uploads` into the `_render_view(...)` call (~462):

```python
                return await _render_view(
                    view=view, provider=provider, job_id=job_id, generation_id=generation_id,
                    session_id=session_id, tier=tier, prompt=view_prompt, ref_url=ref,
                    uploaded_url=uploaded, params=params,
                    key=key, prior_design_url=prior, layout_guide_url=layout_guide,
                    uploaded_urls=view_uploads,
                )
```

Note: `uploaded` (single) is still passed for the audit log + cache-key `asset_hash if uploaded else "none"` branch; leave that line as-is. The provider prefers `uploaded_asset_urls` when non-empty.

- [ ] **Step 6: Run the generation test suite to confirm no regression**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_view_images.py $(grep -rl "_run_generation\|render_view\|generate import" backend/tests | tr '\n' ' ') -q`
Expected: PASS (new test + existing generation tests green).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/generate.py backend/tests/test_canvas_view_images.py
git commit -m "fix(generate): canvas views condition on their own uploaded images"
```

---

### Task 6: Admin session endpoint returns `canvas_faces`

**Files:**
- Modify: `backend/app/api/routes/admin_diagnostics.py` (`get_session_detail` ~124-192; add `_resolve_element_media` + `_build_canvas_faces` helpers)
- Test: `backend/tests/test_admin_session_canvas_faces.py` (create)

**Interfaces:**
- Consumes: `path_from_signed_url` (Task 1), `media_url` (existing), `canvas_describe.element_label` (Task 3), `prompt_builder.RENDER_VIEW_ORDER` (existing).
- Produces: `GET /admin/sessions/{id}` response gains `canvas_design` (or null) and `canvas_faces: list[CanvasFace]` where each face is `{face, preview_url, layout_url, elements: [{kind, url?, download_name?, text?}]}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_session_canvas_faces.py
# Reuse the admin TestClient + X-Admin-Secret + seeded-session pattern from the
# existing admin diagnostics test (grep -rl "admin/sessions" backend/tests).

def test_canvas_session_returns_faces(admin_client, seed_canvas_session):
    sid = seed_canvas_session(
        canvas_design={"colourway": None, "faces": {
            "front": [{"type": "image", "assetPath": "canvas_front_A.png",
                       "assetUrl": "http://x/sign/madhats-assets/canvas_front_A.png?t=1",
                       "x": 0.1, "y": 0.1, "width": 0.2, "height": 0.2, "zIndex": 0},
                      {"type": "text", "content": "SATISH", "colour": "#ffffff",
                       "font": "Arial", "x": 0.3, "y": 0.5, "width": 0.3, "height": 0.1, "zIndex": 1}],
            "back": [{"type": "image", "assetPath": "canvas_back_B.png",
                      "assetUrl": "http://x/sign/madhats-assets/canvas_back_B.png?t=1",
                      "x": 0.2, "y": 0.2, "width": 0.2, "height": 0.2, "zIndex": 0}],
            "left": [], "right": []}},
        collected={"flow_mode": "canvas",
                   "canvas_previews": {"front": "prev_front.png", "back": "prev_back.png"},
                   "canvas_layouts": {"front": "lay_front.png", "back": "lay_back.png"}},
    )
    res = admin_client.get(f"/admin/sessions/{sid}")
    assert res.status_code == 200
    faces = {f["face"]: f for f in res.json()["canvas_faces"]}
    assert set(faces) == {"front", "back"}
    front = faces["front"]
    assert "/media/" in front["preview_url"] and "/media/" in front["layout_url"]
    kinds = [e["kind"] for e in front["elements"]]
    assert kinds.count("image") == 1
    img = next(e for e in front["elements"] if e["kind"] == "image")
    assert "/media/" in img["url"] and img["download_name"].endswith(".png")
    text = next(e for e in front["elements"] if e["kind"] == "text")
    assert "SATISH" in text["text"]


def test_non_canvas_session_has_no_faces(admin_client, seed_session):
    sid = seed_session(collected={"flow_mode": "session"})
    body = admin_client.get(f"/admin/sessions/{sid}").json()
    assert body.get("canvas_design") is None
    assert body.get("canvas_faces") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_session_canvas_faces.py -q`
Expected: FAIL (`canvas_faces` missing).

- [ ] **Step 3: Write minimal implementation**

Add imports at top of `admin_diagnostics.py`:

```python
from app.services import canvas_describe
from app.services import prompt_builder
from app.storage import media_url, path_from_signed_url
```

Add helpers above `get_session_detail`:

```python
def _resolve_element_media(el: dict, request: Request) -> str | None:
    """A canvas image element -> a /media proxy URL (or external passthrough).
    assetPath -> proxy; else recover path from an expired signed assetUrl; else
    pass through an http/media URL; else None."""
    path = el.get("assetPath") or path_from_signed_url(el.get("assetUrl"))
    if path:
        return media_url(path, str(request.base_url))
    url = el.get("assetUrl")
    return url if url and url.startswith("http") else None


def _build_canvas_faces(session: dict, request: Request) -> list[dict]:
    design = session.get("canvas_design") or {}
    faces_src = design.get("faces") or {}
    collected = session.get("collected") or {}
    previews = collected.get("canvas_previews") or {}
    layouts = collected.get("canvas_layouts") or {}
    out: list[dict] = []
    for face in prompt_builder.RENDER_VIEW_ORDER:
        els_src = sorted(faces_src.get(face) or [], key=lambda e: e.get("zIndex", 0))
        has_preview = bool(previews.get(face) or layouts.get(face))
        if not els_src and not has_preview:
            continue
        elements: list[dict] = []
        img_n = 0
        for el in els_src:
            if el.get("type") == "image":
                img_n += 1
                url = _resolve_element_media(el, request)
                elements.append({
                    "kind": "image",
                    "url": url,
                    "download_name": f"{face}-upload-{img_n}.png",
                    "text": canvas_describe.element_label(el),
                })
            else:
                kind = {"text": "text", "shape": "graphic", "drawing": "drawing"}.get(el.get("type"), "other")
                elements.append({"kind": kind, "text": canvas_describe.element_label(el)})
        out.append({
            "face": face,
            "preview_url": media_url(previews.get(face), str(request.base_url)),
            "layout_url": media_url(layouts.get(face), str(request.base_url)),
            "elements": elements,
        })
    return out
```

In `get_session_detail`'s return dict, add:

```python
        "canvas_design": session.get("canvas_design"),
        "canvas_faces": _build_canvas_faces(session, request),
```

(`canvas_design` is naturally `None` for non-canvas sessions; `_build_canvas_faces` returns `[]` when there are no faces.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_admin_session_canvas_faces.py -q`
Expected: PASS. Also run existing admin diagnostics tests: `pytest $(grep -rl "admin/sessions" backend/tests | tr '\n' ' ') -q` — expected green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/admin_diagnostics.py backend/tests/test_admin_session_canvas_faces.py
git commit -m "feat(admin): session detail returns per-face canvas design"
```

---

### Task 7: Frontend `canvasStore` stores `assetPath`

**Files:**
- Modify: `frontend/src/store/canvasStore.ts` (`CanvasElement` ~24; `addImage` ~118-131)
- Test: `frontend/src/__tests__/canvasStore.test.ts` (add cases; file exists)

**Interfaces:**
- Produces: `addImage(assetUrl: string, aspect?: number, assetPath?: string)` stores `assetPath` on the element; `toCanvasDesign` round-trips it.

- [ ] **Step 1: Write the failing test** (append to existing `canvasStore.test.ts`)

```ts
it('stores assetPath on uploaded images and round-trips it', () => {
  const s = useCanvasStore.getState()
  s.reset()
  s.addImage('http://x/sign/a.png?t=1', 1, 'canvas_front_A.png')
  const el = useCanvasStore.getState().faces.front[0]
  expect(el.assetPath).toBe('canvas_front_A.png')
  expect(useCanvasStore.getState().toCanvasDesign().faces.front[0].assetPath).toBe('canvas_front_A.png')
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/canvasStore.test.ts`
Expected: FAIL (`assetPath` is undefined).

- [ ] **Step 3: Write minimal implementation**

`CanvasElement` already allows extra fields? No — it's a typed interface. Add the field (~line 24, near `assetUrl`):

```ts
  assetUrl?: string; assetPath?: string; removeBg?: boolean
```

Update `addImage`:

```ts
  addImage: (assetUrl, aspect = 1, assetPath) => set(s => {
    const a = aspect && isFinite(aspect) && aspect > 0 ? aspect : 1
    const maxN = 0.4
    const width = a >= 1 ? maxN : maxN * a
    const height = a >= 1 ? maxN / a : maxN
    const el: CanvasElement = {
      id: uid(), type: 'image', x: 0.5 - width / 2, y: 0.5 - height / 2, width, height,
      rotation: 0, zIndex: s.faces[s.activeFace].length, assetUrl, assetPath, removeBg: false,
    }
    return { faces: { ...s.faces, [s.activeFace]: [...s.faces[s.activeFace], el] }, selectedId: el.id }
  }),
```

And the interface method type (~line 60):

```ts
  addImage: (assetUrl: string, aspect?: number, assetPath?: string) => void
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/canvasStore.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/__tests__/canvasStore.test.ts
git commit -m "feat(canvas): store assetPath on uploaded image elements"
```

---

### Task 8: Frontend threads `asset_path` through upload

**Files:**
- Modify: `frontend/src/lib/api.ts:132-142` (`uploadLogo` return type)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:169-187` (`handleUpload`)

**Interfaces:**
- Consumes: `addImage(url, aspect, assetPath)` (Task 7).
- Produces: nothing new (wiring only).

- [ ] **Step 1: Update `uploadLogo` return type**

```ts
export function uploadLogo(
  sessionId: string,
  file: File,
): Promise<{ asset_url: string; asset_path: string; asset_hash: string }> {
  const formData = new FormData()
  formData.append('file', file)
  return request<{ asset_url: string; asset_path: string; asset_hash: string }>(`/uploads/logo/${sessionId}`, {
    method: 'POST',
    body: formData,
  })
}
```

- [ ] **Step 2: Thread the path in `handleUpload`**

```ts
      const { asset_url, asset_path } = await uploadLogo(sessionId, file)
      let aspect = 1
      try {
        const img = await loadImage(asset_url)
        if (img.naturalWidth && img.naturalHeight) aspect = img.naturalWidth / img.naturalHeight
      } catch { /* keep square default */ }
      addImage(asset_url, aspect, asset_path)
```

(`addGraphic` for library graphics stays `addImage(url, aspect)` — no path.)

- [ ] **Step 3: Typecheck / build**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Run the DesignStudio-touching tests**

Run: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx src/__tests__/canvasStore.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/components/DesignStudio/Surface.tsx
git commit -m "feat(canvas): thread asset_path from upload into the element"
```

---

### Task 9: Admin 360° view — "Customer's design" section + download

**Files:**
- Modify: `frontend/src/admin/adminApi.ts` (`SessionDetail` ~312-329; add `CanvasFace`/`CanvasFaceElement`)
- Create: `frontend/src/admin/downloadImage.ts` (blob-download util)
- Modify: `frontend/src/admin/views/SessionDetailView.tsx` (add the section)
- Test: `frontend/src/admin/views/SessionDetailView.test.tsx` (create)

**Interfaces:**
- Consumes: `SessionDetail.canvas_faces` (Task 6 shape).
- Produces: nothing downstream.

- [ ] **Step 1: Add API types** (`adminApi.ts`)

```ts
export interface CanvasFaceElement {
  kind: 'image' | 'text' | 'graphic' | 'drawing' | 'other'
  url?: string | null
  download_name?: string
  text?: string
}
export interface CanvasFace {
  face: string
  preview_url: string | null
  layout_url: string | null
  elements: CanvasFaceElement[]
}
```

Add to `SessionDetail`:

```ts
  canvas_design: Record<string, unknown> | null
  canvas_faces: CanvasFace[]
```

- [ ] **Step 2: Create the download util** (`frontend/src/admin/downloadImage.ts`)

```ts
/** Fetch a (CORS-enabled) /media image as a blob and trigger a browser download.
 *  Cross-origin <a download> is ignored by browsers, so we go via a blob URL. */
export async function downloadImage(url: string, filename: string): Promise<void> {
  const res = await fetch(url)
  const blob = await res.blob()
  const objUrl = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = objUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(objUrl)
}
```

- [ ] **Step 3: Write the failing test** (`SessionDetailView.test.tsx`)

```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi } from 'vitest'
import { SessionDetailView } from './SessionDetailView'
import * as api from '../adminApi'

const baseDetail = {
  id: 's1', store_id: null, share_token: null, state: 'complete', status: null,
  channel: 'web', entry_path: null, product: 'Cap', product_ref: null,
  reference_image_url: null, view_images: {}, collected: {}, created_at: null,
  messages: [], generations: [], leads: [],
  canvas_design: {},
  canvas_faces: [{
    face: 'front', preview_url: 'http://api/media/p', layout_url: 'http://api/media/l',
    elements: [
      { kind: 'image', url: 'http://api/media/i', download_name: 'front-upload-1.png', text: 'uploaded logo/artwork' },
      { kind: 'text', text: 'text reading "SATISH", in white, Arial font' },
    ],
  }],
}

function renderAt() {
  return render(
    <MemoryRouter initialEntries={['/admin/sessions/s1']}>
      <Routes><Route path="/admin/sessions/:id" element={<SessionDetailView />} /></Routes>
    </MemoryRouter>,
  )
}

it('renders the customer design section with images and element text', async () => {
  vi.spyOn(api, 'getSessionDetail').mockResolvedValue(baseDetail as unknown as api.SessionDetail)
  renderAt()
  expect(await screen.findByText(/Customer's design/i)).toBeInTheDocument()
  expect(await screen.findByText(/SATISH/)).toBeInTheDocument()
  expect(screen.getAllByRole('button', { name: /download/i }).length).toBeGreaterThan(0)
})

it('omits the section when there are no canvas faces', async () => {
  vi.spyOn(api, 'getSessionDetail').mockResolvedValue({ ...baseDetail, canvas_faces: [] } as unknown as api.SessionDetail)
  renderAt()
  await screen.findByText('Cap')
  expect(screen.queryByText(/Customer's design/i)).not.toBeInTheDocument()
})
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/SessionDetailView.test.tsx`
Expected: FAIL (section not rendered).

- [ ] **Step 5: Implement the section**

In `SessionDetailView.tsx`, import the util and add the card inside the left column (after the AI-mockups `Card`, before the "Selected cap — 360°" card). Only render when `detail.canvas_faces?.length`:

```tsx
import { downloadImage } from '../downloadImage'
// ...
const FACE_LABEL: Record<string, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }

function Thumb({ url, label, download }: { url: string | null; label: string; download?: string }) {
  if (!url) return null
  return (
    <figure className="text-center">
      <img src={url} alt={label} className="size-28 rounded-lg border border-[#e0e1ea] bg-[#f8f9fa] object-contain" />
      <figcaption className="mt-1 text-[11px] text-[#6b6b80]">{label}</figcaption>
      {download && (
        <button
          onClick={() => void downloadImage(url, download)}
          className="mt-1 text-[11px] font-medium text-[#ff5c00] hover:underline"
        >
          Download
        </button>
      )}
    </figure>
  )
}
```

Then the card (inside `return`, left column):

```tsx
          {detail.canvas_faces?.length > 0 && (
            <Card title="Customer's design">
              <div className="space-y-5">
                {detail.canvas_faces.map((f) => {
                  const images = f.elements.filter((e) => e.kind === 'image' && e.url)
                  const notes = f.elements.filter((e) => e.kind !== 'image' && e.text)
                  return (
                    <div key={f.face} className="rounded-lg border border-[#f0f1f5] p-3">
                      <h3 className="mb-2 text-[12px] font-semibold text-[#1a1a2e]">{FACE_LABEL[f.face] ?? f.face}</h3>
                      <div className="flex flex-wrap gap-3">
                        <Thumb url={f.preview_url} label="Preview" download={`${f.face}-preview.png`} />
                        <Thumb url={f.layout_url} label="Layout guide" download={`${f.face}-layout.png`} />
                        {images.map((e, i) => (
                          <Thumb key={i} url={e.url ?? null} label={`Upload ${i + 1}`} download={e.download_name ?? `${f.face}-upload-${i + 1}.png`} />
                        ))}
                      </div>
                      {notes.length > 0 && (
                        <ul className="mt-3 space-y-1">
                          {notes.map((e, i) => (
                            <li key={i} className="text-[12px] text-[#6b6b80]">
                              <span className="capitalize text-[#1a1a2e]">{e.kind}:</span> {e.text}
                            </li>
                          ))}
                        </ul>
                      )}
                      {images.length === 0 && !f.preview_url && !f.layout_url && (
                        <p className="text-[12px] text-[#6b6b80]">No recoverable images for this face.</p>
                      )}
                    </div>
                  )
                })}
              </div>
            </Card>
          )}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/SessionDetailView.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 7: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/admin/adminApi.ts frontend/src/admin/downloadImage.ts frontend/src/admin/views/SessionDetailView.tsx frontend/src/admin/views/SessionDetailView.test.tsx
git commit -m "feat(admin): 360 view shows + downloads the customer's canvas design"
```

---

### Task 10: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: all green (baseline was 954 passing; +new tests).

- [ ] **Step 2: Frontend targeted suites**

Run: `cd frontend && npx vitest run src/__tests__/canvasStore.test.ts src/admin/views/SessionDetailView.test.tsx src/store/canvasStore.test.ts src/__tests__/surfaceDirective.test.tsx`
Expected: all green.

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: no errors.

- [ ] **Step 4: Manual smoke (optional, if stack is up)**

Create a canvas session, upload a front image and a back image, finish, generate. Confirm in the admin 360° view both uploads appear per-face with working Download buttons, and (once rendered) the front render uses the front logo and the back render uses the back logo — not duplicated.

- [ ] **Step 5: Commit any final doc/CLAUDE.md note** (if you update project memory)

```bash
git add -A && git commit -m "chore: verify canvas per-element images + 360 view"
```

---

## Self-Review notes

- **Spec §3–§9 coverage:** persistence (Tasks 2,3,7,8), generation fix (Tasks 4,5), admin view (Tasks 6,9), path recovery (Task 1, used in 5+6), shared label helper (Task 3). All mapped.
- **Type consistency:** `_canvas_view_images` (Task 5) matches spec §5b; `element_label` (Task 3) consumed in Task 6; `addImage(url, aspect, assetPath)` defined in Task 7, consumed in Task 8; `canvas_faces`/`CanvasFace` shape identical between Task 6 (backend) and Task 9 (frontend).
- **No fal adapter exists** — only `stub` + `gemini_base` (used by `gemini_flash`/`gemini_pro`); Task 4 covers exactly those (spec's fal reference was superfluous).
- **v1 safety:** Task 5 keeps the non-canvas branch (`view_has_logo` + single `uploaded_url_full`) untouched; provider prefers the list only when passed.
