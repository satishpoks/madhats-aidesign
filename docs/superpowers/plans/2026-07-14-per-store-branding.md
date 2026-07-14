# Per-Store Branding & Themed Emails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each store (tenant) present the customer-facing Design Studio and its outbound emails in that store's own branding — logo, primary colour, header colours, and a small configurable main menu of external links — configured through the existing global admin console.

**Architecture:** Branding lives in the pre-existing `stores.brand` jsonb (no new table). A pure `branding` service validates + serializes it. A new customer `GET /storefront` endpoint feeds a frontend Zustand `brandStore` that sets CSS variables (promoted Tailwind tokens) and drives a shared `StoreHeader`. Admin edits via extended `/admin/stores/{id}` routes and a new Branding view. Customer emails are themed by threading brand into the email service.

**Tech Stack:** Python 3.12 / FastAPI / supabase-py (backend); React 18 / Vite / Tailwind 3 / Zustand / react-router (frontend); pytest + vitest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-14-per-store-branding-design.md` — every task implicitly serves it.
- **No new auth.** Branding is edited through the existing global admin console (single `X-Admin-Secret`). Admin store routes use `require_admin` + store **id** in the path (mirror `/admin/stores/{id}/sync`) — NOT `require_store`.
- **Menu items:** max **5**; each `label` non-empty, trimmed, ≤ 40 chars; each `url` must parse as `http`/`https` only (reject `javascript:`, `data:`, relative). Menu items live **inside** `brand` as `brand.menu_items`.
- **Colours:** `primary_colour`, `header_bg`, `header_text` must match `^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$`.
- **Backward compatible:** every brand field is optional; unset → current MadHats defaults (`#FF5C00`, `MAD HATS`, etc.). Unconfigured stores look identical to today.
- **No secrets/PII in logs.** `/storefront` returns only the public subset (no `allowed_origins`, `sales_notification_email`, `watermark_asset_url`, secrets).
- **Logos** are stored in the private bucket and returned as `/media` proxy URLs (never raw signed URLs) to clients; inlined as CID attachments in the preview email.
- **DB access:** supabase-py only. No raw SQL in app code (migrations excepted).
- **Commit** after each task.

---

## File Structure

**Backend**
- Create `backend/app/services/branding.py` — pure validate + serialize helpers.
- Create `backend/app/api/routes/storefront.py` — customer `GET /storefront`.
- Modify `backend/app/api/routes/admin_stores.py` — add `GET /admin/stores/{id}`, `PATCH /admin/stores/{id}`, `POST /admin/stores/{id}/logo`.
- Modify `backend/app/models/store.py` — add `UpdateStoreRequest`.
- Modify `backend/app/storage.py` — add `download_asset`.
- Modify `backend/app/prompts.py` — parametrize preview email; add verification/resume branded templates.
- Modify `backend/app/services/email.py` — thread brand into senders.
- Modify `backend/app/services/delivery.py` + `backend/app/services/leads.py` — pass store brand to senders.
- Modify `backend/app/main.py` — register `storefront.router`.
- Create migration `backend/supabase/migrations/20260714000002_store_brand_menu.sql` — comment-only doc.

**Frontend**
- Modify `frontend/tailwind.config.js` — `accent`/`accentHover` → CSS vars.
- Create `frontend/src/store/brandStore.ts` — Zustand brand store + `applyBrandVars`.
- Create `frontend/src/components/StoreHeader.tsx` — logo/name + menu header.
- Modify `frontend/src/lib/api.ts` — `getStorefront()` + `Storefront` type.
- Modify `frontend/src/lib/types.ts` — `Brand`, `Storefront`, `MenuItem`.
- Modify `frontend/src/App.tsx` — init brand on mount (customer path).
- Modify `frontend/src/components/CustomiseStudio/index.tsx` — use `StoreHeader`.
- Create `frontend/src/admin/views/BrandingView.tsx` — admin editor.
- Modify `frontend/src/admin/adminApi.ts` — `getStore`, `updateStoreBrand`, `uploadStoreLogo`.
- Modify `frontend/src/admin/AdminApp.tsx` + `frontend/src/admin/AdminLayout.tsx` — route + nav.

---

## Task 1: `branding` service — validation + public serializer

**Files:**
- Create: `backend/app/services/branding.py`
- Test: `backend/tests/test_branding.py`

**Interfaces:**
- Produces:
  - `validate_brand(brand: dict) -> dict` — returns a cleaned copy; raises `ValueError` on invalid colour/menu.
  - `public_brand(brand: dict | None, base_url: str) -> dict` — safe subset with proxied `logo_url`.
  - Constants `MAX_MENU_ITEMS = 5`, `MAX_LABEL_LEN = 40`, `HEX_RE`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_branding.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_branding.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.branding`).

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/branding.py
"""Pure per-store branding helpers: validation for admin writes and a public
serializer for the customer storefront. No DB, no network — trivially testable.

Brand shape (all keys optional) stored in stores.brand jsonb:
    { logo_url, primary_colour, header_bg, header_text,
      watermark_asset_url (internal), menu_items: [{label, url}] }
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.storage import media_url

HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
MAX_MENU_ITEMS = 5
MAX_LABEL_LEN = 40
_COLOUR_KEYS = ("primary_colour", "header_bg", "header_text")
# Fields exposed to the public storefront (watermark_asset_url is internal).
_PUBLIC_KEYS = ("logo_url", "primary_colour", "header_bg", "header_text")


def _validate_menu_items(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError("menu_items must be a list")
    if len(raw) > MAX_MENU_ITEMS:
        raise ValueError(f"at most {MAX_MENU_ITEMS} menu items allowed")
    cleaned: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("each menu item must be an object")
        label = str(item.get("label") or "").strip()
        url = str(item.get("url") or "").strip()
        if not label:
            raise ValueError("menu item label is required")
        if len(label) > MAX_LABEL_LEN:
            raise ValueError(f"menu item label exceeds {MAX_LABEL_LEN} chars")
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("menu item url must be an http(s) URL")
        cleaned.append({"label": label, "url": url})
    return cleaned


def validate_brand(brand: dict) -> dict:
    """Return a cleaned copy of ``brand``. Raise ValueError on invalid input.
    Unknown keys are preserved (e.g. watermark_asset_url set by other flows)."""
    if not isinstance(brand, dict):
        raise ValueError("brand must be an object")
    cleaned = dict(brand)
    for key in _COLOUR_KEYS:
        val = cleaned.get(key)
        if val in (None, ""):
            cleaned.pop(key, None)
            continue
        if not isinstance(val, str) or not HEX_RE.match(val):
            raise ValueError(f"{key} must be a hex colour like #FF5C00")
    if "menu_items" in cleaned:
        cleaned["menu_items"] = _validate_menu_items(cleaned["menu_items"])
    return cleaned


def public_brand(brand: dict | None, base_url: str) -> dict:
    """The safe subset a customer widget may see. Logo becomes a /media URL."""
    if not brand:
        return {}
    out: dict = {}
    for key in _PUBLIC_KEYS:
        val = brand.get(key)
        if not val:
            continue
        out[key] = media_url(val, base_url) if key == "logo_url" else val
    items = brand.get("menu_items")
    if isinstance(items, list) and items:
        out["menu_items"] = [
            {"label": i.get("label", ""), "url": i.get("url", "")}
            for i in items if isinstance(i, dict)
        ]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_branding.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/branding.py backend/tests/test_branding.py
git commit -m "feat(branding): brand validation + public serializer service"
```

---

## Task 2: Customer `GET /storefront` endpoint

**Files:**
- Create: `backend/app/api/routes/storefront.py`
- Modify: `backend/app/main.py` (register router)
- Modify: `backend/supabase/migrations/20260714000002_store_brand_menu.sql` (create)
- Test: `backend/tests/test_storefront.py`

**Interfaces:**
- Consumes: `branding.public_brand`, `app.api.deps.require_store`.
- Produces: `GET /storefront` → `{ "name": str, "persona_name": str, "brand": {...} }`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_storefront.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_store
from app.main import app

_STORE = {
    "id": "s1", "name": "Acme Caps", "persona_name": "Rex",
    "sales_notification_email": "secret@acme.example",  # must NOT leak
    "brand": {
        "primary_colour": "#123456",
        "logo_url": "uploads/logo.png",
        "menu_items": [{"label": "Shop", "url": "https://acme.example/shop"}],
    },
}


@pytest.fixture
def client():
    app.dependency_overrides[require_store] = lambda: _STORE
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_storefront_returns_public_brand(client, monkeypatch):
    # public_brand (in app.services.branding) binds media_url at import, so patch
    # it THERE, not on the route module.
    monkeypatch.setattr(
        "app.services.branding.media_url", lambda p, base: f"http://api/media/{p}"
    )
    r = client.get("/storefront", headers={"X-Store-Key": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Acme Caps"
    assert body["persona_name"] == "Rex"
    assert body["brand"]["primary_colour"] == "#123456"
    assert body["brand"]["logo_url"] == "http://api/media/uploads/logo.png"
    assert body["brand"]["menu_items"][0]["label"] == "Shop"
    # secrets never surface
    assert "sales_notification_email" not in str(body)


def test_storefront_requires_store_key():
    # No override -> require_store enforces the header.
    r = TestClient(app).get("/storefront")
    assert r.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_storefront.py -q`
Expected: FAIL (404 — route not registered).

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/routes/storefront.py`:
```python
"""Public storefront config for the customer widget. Resolved via X-Store-Key.
Returns ONLY the public branding subset — never secrets or internal fields."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import require_store
from app.config import settings
from app.services.branding import public_brand

router = APIRouter(tags=["storefront"])


@router.get("/storefront")
async def get_storefront(request: Request, store: dict = Depends(require_store)) -> dict:
    return {
        "name": store.get("name") or "",
        "persona_name": store.get("persona_name") or settings.chatbot_persona_name,
        "brand": public_brand(store.get("brand"), str(request.base_url)),
    }
```

> Note: `public_brand` (in `app.services.branding`) builds the proxied logo URL
> via `media_url`. The test patches `app.services.branding.media_url` accordingly.

Register in `backend/app/main.py`: add `storefront,` to the routes import block (near `products,`) and add `storefront.router,` to the `include_router` tuple (after `products.router,`).

Create `backend/supabase/migrations/20260714000002_store_brand_menu.sql`:
```sql
-- Per-store branding is stored in the existing stores.brand jsonb (no structural
-- change). This migration only documents the widened shape:
--   brand = {
--     logo_url text (storage path, served via /media proxy),
--     primary_colour text (#hex), header_bg text (#hex), header_text text (#hex),
--     watermark_asset_url text (internal),
--     menu_items jsonb: [{label text, url text}]  -- max 5, http(s) only
--   }
comment on column stores.brand is
  'Per-store branding: logo_url, primary_colour, header_bg, header_text, watermark_asset_url, menu_items[{label,url}]';
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_storefront.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/storefront.py backend/app/main.py backend/supabase/migrations/20260714000002_store_brand_menu.sql backend/tests/test_storefront.py
git commit -m "feat(storefront): public GET /storefront brand+menu endpoint"
```

---

## Task 3: Admin store read + branding update

**Files:**
- Modify: `backend/app/models/store.py` (add `UpdateStoreRequest`)
- Modify: `backend/app/api/routes/admin_stores.py` (add GET-one + PATCH)
- Test: `backend/tests/test_admin_store_branding.py`

**Interfaces:**
- Consumes: `branding.validate_brand`, `require_admin`.
- Produces:
  - `GET /admin/stores/{store_id}` → full store row (incl. `brand`).
  - `PATCH /admin/stores/{store_id}` body `{ "brand": {...} }` → updated full row; 400 on invalid brand; 404 if missing.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_store_branding.py
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_admin
from app.main import app

_ROW = {"id": "s1", "slug": "acme", "name": "Acme", "brand": {"primary_colour": "#111111"}}


class _FakeTable:
    def __init__(self, row): self._row = row; self._filter = None
    def select(self, *a, **k): return self
    def update(self, patch): self._row = {**self._row, **patch}; return self
    def eq(self, col, val): self._filter = (col, val); return self
    def limit(self, n): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [self._row]; return r


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: None
    fake = _FakeTable(dict(_ROW))
    monkeypatch.setattr("app.api.routes.admin_stores.get_supabase", lambda: type("SB", (), {"table": lambda self, name: fake})())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_get_one_returns_full_store(client):
    r = client.get("/admin/stores/s1", headers={"X-Admin-Secret": "z"})
    assert r.status_code == 200
    assert r.json()["brand"]["primary_colour"] == "#111111"


def test_patch_updates_valid_brand(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"primary_colour": "#00FF00", "menu_items": [{"label": "Shop", "url": "https://x.example"}]}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 200
    assert r.json()["brand"]["primary_colour"] == "#00FF00"


def test_patch_rejects_invalid_brand(client):
    r = client.patch(
        "/admin/stores/s1",
        json={"brand": {"primary_colour": "notacolour"}},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_admin_store_branding.py -q`
Expected: FAIL (405/404 — routes not present).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/models/store.py` add:
```python
class UpdateStoreRequest(BaseModel):
    brand: dict | None = None
```

In `backend/app/api/routes/admin_stores.py`:
- Add imports at top: `from fastapi import Body` is not needed; add `from app.models.store import UpdateStoreRequest` to the existing model import line, and `from app.services.branding import validate_brand`.
- Append these routes:
```python
@router.get("/admin/stores/{store_id}")
async def get_store_admin(store_id: str) -> dict:
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    return res.data[0]


@router.patch("/admin/stores/{store_id}")
async def update_store(store_id: str, body: UpdateStoreRequest) -> dict:
    sb = get_supabase()
    patch: dict = {}
    if body.brand is not None:
        try:
            patch["brand"] = validate_brand(body.brand)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not patch:
        raise HTTPException(status_code=400, detail="Nothing to update")
    res = sb.table("stores").update(patch).eq("id", store_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    log.info("store_branding_updated", store_id=store_id)  # no PII
    return res.data[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_admin_store_branding.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/store.py backend/app/api/routes/admin_stores.py backend/tests/test_admin_store_branding.py
git commit -m "feat(admin): GET one store + PATCH store branding"
```

---

## Task 4: Admin store logo upload

**Files:**
- Modify: `backend/app/api/routes/admin_stores.py` (add logo upload route)
- Test: `backend/tests/test_admin_store_logo.py`

**Interfaces:**
- Consumes: `sniff_image_mime`, `upload_asset`, `media_url`, `MAX_UPLOAD_BYTES`, `validate_brand` (reused for merge), `require_admin`.
- Produces: `POST /admin/stores/{store_id}/logo` (multipart `file`) → `{ "logo_url": "<proxy url>" }`, persisting the storage path into `brand.logo_url`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_admin_store_logo.py
from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.api.deps import require_admin
from app.main import app


class _FakeTable:
    def __init__(self, row): self._row = row
    def select(self, *a, **k): return self
    def update(self, patch): self._row = {**self._row, **patch}; return self
    def eq(self, *a): return self
    def limit(self, n): return self
    def execute(self):
        class R: pass
        r = R(); r.data = [self._row]; return r


@pytest.fixture
def client(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: None
    fake = _FakeTable({"id": "s1", "brand": {"primary_colour": "#111111"}})
    monkeypatch.setattr("app.api.routes.admin_stores.get_supabase", lambda: type("SB", (), {"table": lambda self, n: fake})())
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_logo_rejects_non_image(client):
    r = client.post(
        "/admin/stores/s1/logo",
        files={"file": ("x.txt", b"not an image", "text/plain")},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 415


def test_logo_happy_path(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.admin_stores.sniff_image_mime", lambda d: "image/png")
    monkeypatch.setattr("app.api.routes.admin_stores.upload_asset", lambda d, n, m: "uploads/logo.png")
    monkeypatch.setattr("app.api.routes.admin_stores.media_url", lambda p, base: f"http://api/media/{p}")
    r = client.post(
        "/admin/stores/s1/logo",
        files={"file": ("logo.png", io.BytesIO(b"anybytes"), "image/png")},
        headers={"X-Admin-Secret": "z"},
    )
    assert r.status_code == 200
    assert r.json()["logo_url"] == "http://api/media/uploads/logo.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_admin_store_logo.py -q`
Expected: FAIL (404 — route missing).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/api/routes/admin_stores.py`:
- Extend imports:
```python
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from app.services.upload_validation import MAX_UPLOAD_BYTES, sniff_image_mime
from app.storage import media_url, upload_asset
```
- Append route:
```python
@router.post("/admin/stores/{store_id}/logo")
async def upload_store_logo(
    store_id: str, request: Request, file: UploadFile = File(...)
) -> dict:
    sb = get_supabase()
    res = sb.table("stores").select("*").eq("id", store_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Store not found")
    store = res.data[0]
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "logo", mime)
    brand = dict(store.get("brand") or {})
    brand["logo_url"] = path
    sb.table("stores").update({"brand": brand}).eq("id", store_id).execute()
    log.info("store_logo_uploaded", store_id=store_id)  # no PII
    return {"logo_url": media_url(path, str(request.base_url))}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_admin_store_logo.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/admin_stores.py backend/tests/test_admin_store_logo.py
git commit -m "feat(admin): store logo upload endpoint"
```

---

## Task 5: Theme the preview (delivery) email

**Files:**
- Modify: `backend/app/prompts.py` (parametrize `PREVIEW_EMAIL_HTML`)
- Modify: `backend/app/services/email.py` (`send_preview_email` brand params + logo CID)
- Modify: `backend/app/storage.py` (add `download_asset`)
- Modify: `backend/app/services/delivery.py` (pass store brand + logo bytes)
- Test: `backend/tests/test_email_branding.py`

**Interfaces:**
- Consumes: `branding` (not required — brand dict passed directly), `storage.download_asset`.
- Produces: `send_preview_email(..., brand: dict | None = None, store_name: str = "MadHats", logo_bytes: bytes | None = None)`.
  - `storage.download_asset(path: str) -> bytes | None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_email_branding.py
from __future__ import annotations

from app.services import email


def _capture(monkeypatch):
    sent = {}
    def fake_dispatch(to, subject, html, attachments=None):
        sent["html"] = html; sent["attachments"] = attachments or []
        return True
    monkeypatch.setattr(email, "_dispatch", fake_dispatch)
    return sent


def test_preview_email_uses_brand_colour_and_name(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(
        to="c@x.example", name="Sam", image_url="http://img", brief="b",
        brand={"primary_colour": "#0055AA"}, store_name="Acme Caps",
    )
    assert "#0055AA" in sent["html"]
    assert "Acme Caps" in sent["html"]


def test_preview_email_inlines_logo_as_cid(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(
        to="c@x.example", name="Sam", image_url="http://img",
        brand={"primary_colour": "#0055AA"}, store_name="Acme",
        logo_bytes=b"PNGBYTES",
    )
    cids = [a["content_id"] for a in sent["attachments"]]
    assert any("logo" in c for c in cids)
    assert 'src="cid:' in sent["html"]


def test_preview_email_defaults_without_brand(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_preview_email(to="c@x.example", name="Sam", image_url="http://img")
    assert "#ff5c00" in sent["html"].lower()
    assert "MAD HATS" in sent["html"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_email_branding.py -q`
Expected: FAIL (`send_preview_email() got an unexpected keyword argument 'brand'`).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/prompts.py`, change the header row and button colours of `PREVIEW_EMAIL_HTML` to use `$primary_colour` and the header block to `$header_html`. Replace the header `<tr>` (currently the `#ff5c00` bar with `MAD HATS`) with:
```html
        <tr><td style="background:$primary_colour;padding:14px 24px;">
          $header_html
        </td></tr>
```
And change the three hard-coded `#ff5c00` in the CTA/border styles (the primary button `background:#ff5c00`, the secondary button `border:1.5px solid #ff5c00`) to `$primary_colour`. Leave the subtle box-shadow rgba and the image-block border as-is (cosmetic). Leave the footer text but change `MadHats` reference to `$store_name`:
```html
          <div style="font-size:12px;color:#9e9eab;">— Ricardo, $store_name AI Design Studio</div>
```

In `backend/app/storage.py` add:
```python
def download_asset(path: str) -> bytes | None:
    """Download raw bytes of a stored object, or None on any failure."""
    if not path or path.startswith("http"):
        return None
    try:
        return _bucket().download(path)
    except Exception as exc:  # noqa: BLE001
        log.warning("asset_download_failed", error=str(exc))
        return None
```

In `backend/app/services/email.py`, update `send_preview_email`:
- Add params `brand: dict | None = None, store_name: str = "MadHats", logo_bytes: bytes | None = None` to the signature.
- Before building `html`, compute the header + colour:
```python
    b = brand or {}
    primary = b.get("primary_colour") or "#ff5c00"
    if logo_bytes:
        logo_cid = f"{_PREVIEW_CID}-logo"
        attachments.append({
            "filename": "logo.png",
            "content": base64.b64encode(logo_bytes).decode("ascii"),
            "content_type": "image/png",
            "content_id": logo_cid,
        })
        header_html = (
            f'<img src="cid:{logo_cid}" alt="{html_lib.escape(store_name)}" '
            'style="max-height:36px;display:block;" />'
        )
    else:
        header_html = (
            f'<div style="font-size:22px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">'
            f'{html_lib.escape(store_name.upper())}</div>'
            '<div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>'
        )
```
> Move the `attachments: list[dict] = []` initialization ABOVE this block if it
> isn't already (it is created before the image loop — keep the logo append after
> that list exists; simplest: append the logo attachment right after the existing
> image loop, before `html = Template(...)`).
- Add to the `.substitute(...)` call:
```python
        primary_colour=primary,
        header_html=header_html,
        store_name=html_lib.escape(store_name),
```

In `backend/app/services/delivery.py`, at both send sites (`_deliver` ~line 224 and `_deliver_final` ~line 301): load the store (already loaded in `_deliver` for the sales email — reuse it; in `_deliver_final` load via `get_store(session["store_id"])`), then:
```python
    brand = (store or {}).get("brand") or {}
    store_name = (store or {}).get("name") or "MadHats"
    logo_bytes = storage.download_asset(brand.get("logo_url")) if brand.get("logo_url") else None
```
and pass `brand=brand, store_name=store_name, logo_bytes=logo_bytes` into the `send_preview_email(...)` call. (Import `from app import storage` if not present, or add `download_asset` to the existing storage import.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_email_branding.py tests/test_email.py tests/test_delivery.py -q`
Expected: PASS (new tests pass; existing email/delivery tests still pass).

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/app/services/email.py backend/app/storage.py backend/app/services/delivery.py backend/tests/test_email_branding.py
git commit -m "feat(email): theme preview email with store brand (colour, name, logo CID)"
```

---

## Task 6: Theme the verification + resume emails

**Files:**
- Modify: `backend/app/prompts.py` (add branded HTML wrapper template)
- Modify: `backend/app/services/email.py` (`send_verification_email` / `send_resume_email` brand params)
- Modify: `backend/app/services/leads.py` (thread store into `send_verification`)
- Test: `backend/tests/test_email_transactional_branding.py`

**Interfaces:**
- Produces:
  - `send_verification_email(to, name, verify_url, store_name="MadHats", primary_colour="#ff5c00")`.
  - `send_resume_email(to, name, resume_url, store_name="MadHats", primary_colour="#ff5c00")`.
  - `send_verification(lead, store=None)` in leads.py.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_email_transactional_branding.py
from __future__ import annotations

from app.services import email


def _capture(monkeypatch):
    sent = {}
    monkeypatch.setattr(email, "_dispatch", lambda to, subject, html, attachments=None: sent.update(html=html, subject=subject) or True)
    return sent


def test_verification_email_branded(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify", store_name="Acme Caps", primary_colour="#0055AA")
    assert "Acme Caps" in sent["html"]
    assert "#0055AA" in sent["html"]
    assert "http://verify" in sent["html"]


def test_verification_email_default(monkeypatch):
    sent = _capture(monkeypatch)
    email.send_verification_email("c@x.example", "Sam", "http://verify")
    assert "http://verify" in sent["html"]
    # Must not crash and must contain the link; default branding tolerated.
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_email_transactional_branding.py -q`
Expected: FAIL (`unexpected keyword argument 'store_name'`).

- [ ] **Step 3: Write minimal implementation**

In `backend/app/prompts.py` add a reusable wrapper (uses `string.Template`):
```python
# Branded shell for short transactional emails (verification / resume). Inline
# styles only. $store_name and $primary_colour are HTML-escaped by the caller;
# $body_html is pre-rendered safe HTML.
BRANDED_EMAIL_HTML = """\
<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:24px 0;">
    <tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:8px;overflow:hidden;">
        <tr><td style="background:$primary_colour;padding:14px 24px;">
          <div style="font-size:20px;font-weight:bold;color:#ffffff;">$store_name</div>
        </td></tr>
        <tr><td style="padding:24px 28px;color:#1a1a2e;font-size:14px;line-height:22px;">
          $body_html
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""
```

In `backend/app/services/email.py`:
- Add a helper:
```python
def _branded(store_name: str, primary_colour: str, body_html: str) -> str:
    return Template(prompts.BRANDED_EMAIL_HTML).substitute(
        store_name=html_lib.escape(store_name or "MadHats"),
        primary_colour=primary_colour or "#ff5c00",
        body_html=body_html,
    )
```
- Rewrite the two senders (the plain-text bodies from prompts become the escaped body, with the link rendered as an anchor in the store's colour):
```python
def send_verification_email(
    to: str, name: str, verify_url: str,
    store_name: str = "MadHats", primary_colour: str = "#ff5c00",
) -> bool:
    text = prompts.VERIFICATION_EMAIL_BODY.format(name=name, verify_url=verify_url)
    esc = html_lib.escape(text).replace(html_lib.escape(verify_url), "")
    body = (
        f"<p style='white-space:pre-wrap'>{esc}</p>"
        f"<p><a href='{html_lib.escape(verify_url, quote=True)}' "
        f"style='display:inline-block;background:{primary_colour or '#ff5c00'};color:#fff;"
        f"text-decoration:none;font-weight:bold;padding:12px 20px;border-radius:8px;'>Verify my email</a></p>"
    )
    return _dispatch(to, prompts.VERIFICATION_EMAIL_SUBJECT, _branded(store_name, primary_colour, body))


def send_resume_email(
    to: str, name: str, resume_url: str,
    store_name: str = "MadHats", primary_colour: str = "#ff5c00",
) -> bool:
    text = prompts.RESUME_EMAIL_BODY.format(name=name, resume_url=resume_url)
    esc = html_lib.escape(text).replace(html_lib.escape(resume_url), "")
    body = (
        f"<p style='white-space:pre-wrap'>{esc}</p>"
        f"<p><a href='{html_lib.escape(resume_url, quote=True)}' "
        f"style='display:inline-block;background:{primary_colour or '#ff5c00'};color:#fff;"
        f"text-decoration:none;font-weight:bold;padding:12px 20px;border-radius:8px;'>Pick up where I left off</a></p>"
    )
    return _dispatch(to, prompts.RESUME_EMAIL_SUBJECT, _branded(store_name, primary_colour, body))
```

In `backend/app/services/leads.py`, thread the store through `send_verification`:
```python
def send_verification(lead: dict, store: dict | None = None) -> bool:
    ...
    brand = (store or {}).get("brand") or {}
    sent = email_service.send_verification_email(
        lead["email"], lead["name"], verify_url,
        store_name=(store or {}).get("name") or "MadHats",
        primary_colour=brand.get("primary_colour") or "#ff5c00",
    )
    ...
```
And in `capture_lead_and_verify(session, ...)` load the store once and pass it:
```python
    from app.services.stores import get_store
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    ...
        sent = send_verification(lead, store)
```
> Any other caller of `send_verification(lead)` stays valid (store defaults to
> None → MadHats defaults). Grep `send_verification(` to confirm; update the
> resume-email caller similarly if it has store in scope, otherwise leave default.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_email_transactional_branding.py tests/test_email.py tests/test_leads*.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/app/services/email.py backend/app/services/leads.py backend/tests/test_email_transactional_branding.py
git commit -m "feat(email): theme verification + resume emails per store"
```

---

## Task 7: Frontend theme plumbing (CSS vars + brandStore + init)

**Files:**
- Modify: `frontend/tailwind.config.js`
- Create: `frontend/src/store/brandStore.ts`
- Modify: `frontend/src/lib/types.ts` (add `Brand`, `MenuItem`, `Storefront`)
- Modify: `frontend/src/lib/api.ts` (add `getStorefront`)
- Modify: `frontend/src/App.tsx` (init on mount)
- Test: `frontend/src/store/brandStore.test.ts`

**Interfaces:**
- Produces:
  - `useBrandStore` with `{ brand: Brand, storeName: string, personaName: string, loaded: boolean, init(): Promise<void> }`.
  - `applyBrandVars(brand: Brand): void` (exported for tests).
  - `getStorefront(): Promise<Storefront>` in api.ts.
  - Types: `MenuItem { label; url }`, `Brand { logo_url?; primary_colour?; header_bg?; header_text?; menu_items? }`, `Storefront { name; persona_name; brand }`.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/store/brandStore.test.ts
import { describe, it, expect, beforeEach } from 'vitest'
import { applyBrandVars } from './brandStore'

describe('applyBrandVars', () => {
  beforeEach(() => {
    document.documentElement.removeAttribute('style')
  })

  it('sets primary + derived hover + header vars', () => {
    applyBrandVars({ primary_colour: '#0055AA', header_bg: '#ffffff', header_text: '#111111' })
    const s = document.documentElement.style
    expect(s.getPropertyValue('--brand-primary')).toBe('#0055AA')
    expect(s.getPropertyValue('--brand-header-bg')).toBe('#ffffff')
    expect(s.getPropertyValue('--brand-header-text')).toBe('#111111')
    // hover is derived (darker) — just assert it was set to a hex
    expect(s.getPropertyValue('--brand-primary-hover')).toMatch(/^#[0-9a-fA-F]{6}$/)
  })

  it('no-ops for unset fields (keeps Tailwind fallbacks)', () => {
    applyBrandVars({})
    expect(document.documentElement.style.getPropertyValue('--brand-primary')).toBe('')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/store/brandStore.test.ts`
Expected: FAIL (cannot resolve `./brandStore`).

- [ ] **Step 3: Write minimal implementation**

Add types to `frontend/src/lib/types.ts`:
```ts
export interface MenuItem { label: string; url: string }
export interface Brand {
  logo_url?: string
  primary_colour?: string
  header_bg?: string
  header_text?: string
  menu_items?: MenuItem[]
}
export interface Storefront { name: string; persona_name: string; brand: Brand }
```

Add to `frontend/src/lib/api.ts`:
```ts
import type { /* existing… */ Storefront } from './types'

export function getStorefront(): Promise<Storefront> {
  return request<Storefront>('/storefront')
}
```

Create `frontend/src/store/brandStore.ts`:
```ts
import { create } from 'zustand'
import type { Brand } from '../lib/types'
import { getStorefront } from '../lib/api'

/** Darken a #rrggbb (or #rgb) hex by `amt` (0..1). Used to derive a hover shade. */
function darken(hex: string, amt = 0.12): string {
  let h = hex.replace('#', '')
  if (h.length === 3) h = h.split('').map(c => c + c).join('')
  const n = parseInt(h, 16)
  const r = Math.max(0, Math.round(((n >> 16) & 255) * (1 - amt)))
  const g = Math.max(0, Math.round(((n >> 8) & 255) * (1 - amt)))
  const b = Math.max(0, Math.round((n & 255) * (1 - amt)))
  return '#' + [r, g, b].map(v => v.toString(16).padStart(2, '0')).join('')
}

/** Set CSS custom properties from a brand. Unset fields are left untouched so the
 *  Tailwind fallbacks (current MadHats look) apply. */
export function applyBrandVars(brand: Brand): void {
  const root = document.documentElement
  if (brand.primary_colour) {
    root.style.setProperty('--brand-primary', brand.primary_colour)
    root.style.setProperty('--brand-primary-hover', darken(brand.primary_colour))
  }
  if (brand.header_bg) root.style.setProperty('--brand-header-bg', brand.header_bg)
  if (brand.header_text) root.style.setProperty('--brand-header-text', brand.header_text)
}

interface BrandState {
  brand: Brand
  storeName: string
  personaName: string
  loaded: boolean
  init: () => Promise<void>
}

export const useBrandStore = create<BrandState>((set, get) => ({
  brand: {},
  storeName: '',
  personaName: '',
  loaded: false,
  init: async () => {
    if (get().loaded) return
    try {
      const sf = await getStorefront()
      applyBrandVars(sf.brand || {})
      set({ brand: sf.brand || {}, storeName: sf.name, personaName: sf.persona_name, loaded: true })
    } catch {
      // Storefront unreachable — keep Tailwind fallbacks; studio still works.
      set({ loaded: true })
    }
  },
}))
```

Update `frontend/tailwind.config.js` colours:
```js
        accent: 'var(--brand-primary, #FF5C00)',
        accentHover: 'var(--brand-primary-hover, #E64F00)',
```

Wire init in `frontend/src/App.tsx` — add near the existing bootstrap effect (customer path only, after the `/admin` early return):
```tsx
import { useBrandStore } from './store/brandStore'
// …inside App(), with the other hooks:
  const initBrand = useBrandStore(s => s.init)
  useEffect(() => { void initBrand() }, [initBrand])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/store/brandStore.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/tailwind.config.js frontend/src/store/brandStore.ts frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/App.tsx
git commit -m "feat(theme): CSS-var brand tokens + brandStore + storefront fetch"
```

---

## Task 8: `StoreHeader` — logo + menu, wired into the studio

**Files:**
- Create: `frontend/src/components/StoreHeader.tsx`
- Modify: `frontend/src/components/CustomiseStudio/index.tsx`
- Test: `frontend/src/components/StoreHeader.test.tsx`

**Interfaces:**
- Consumes: `useBrandStore`.
- Produces: `StoreHeader({ subtitle }: { subtitle?: string })` React component.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/StoreHeader.test.tsx
import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StoreHeader } from './StoreHeader'
import { useBrandStore } from '../store/brandStore'

describe('StoreHeader', () => {
  beforeEach(() => {
    useBrandStore.setState({ brand: {}, storeName: '', personaName: '', loaded: true })
  })

  it('renders the store name when no logo', () => {
    useBrandStore.setState({ storeName: 'Acme Caps', brand: {} })
    render(<StoreHeader />)
    expect(screen.getByText('Acme Caps')).toBeInTheDocument()
  })

  it('renders a logo img when logo_url set', () => {
    useBrandStore.setState({ storeName: 'Acme', brand: { logo_url: 'http://x/logo.png' } })
    render(<StoreHeader />)
    expect(screen.getByRole('img', { name: /acme/i })).toHaveAttribute('src', 'http://x/logo.png')
  })

  it('renders menu links with target=_blank + rel', () => {
    useBrandStore.setState({ storeName: 'Acme', brand: { menu_items: [{ label: 'Shop', url: 'https://acme.example/shop' }] } })
    render(<StoreHeader />)
    const link = screen.getByRole('link', { name: 'Shop' })
    expect(link).toHaveAttribute('href', 'https://acme.example/shop')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('falls back to MAD HATS when nothing set', () => {
    render(<StoreHeader />)
    expect(screen.getByText('MAD HATS')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/StoreHeader.test.tsx`
Expected: FAIL (cannot resolve `./StoreHeader`).

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/components/StoreHeader.tsx`:
```tsx
import { useBrandStore } from '../store/brandStore'

/**
 * Branded studio header: store logo (or name), optional subtitle, and up to 5
 * external main-menu links. Colours come from CSS vars (with MadHats fallbacks)
 * set by brandStore.applyBrandVars.
 */
export function StoreHeader({ subtitle }: { subtitle?: string }) {
  const { brand, storeName } = useBrandStore()
  const menu = (brand.menu_items ?? []).slice(0, 5)
  const headerStyle = {
    background: 'var(--brand-header-bg, #ffffff)',
    color: 'var(--brand-header-text, #1A1D29)',
  }

  return (
    <header
      className="border-b border-border px-6 py-3.5 flex items-center gap-3 flex-shrink-0"
      style={headerStyle}
    >
      {brand.logo_url ? (
        <img src={brand.logo_url} alt={storeName || 'MAD HATS'} className="h-8 w-auto object-contain" />
      ) : (
        <span className="text-accent font-extrabold text-lg tracking-wide">
          {storeName || 'MAD HATS'}
        </span>
      )}
      {subtitle && <span className="text-sm text-textMuted truncate">{subtitle}</span>}
      {menu.length > 0 && (
        <nav className="ml-auto flex items-center gap-4 overflow-x-auto">
          {menu.map((m, i) => (
            <a
              key={i}
              href={m.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm font-medium hover:text-accent whitespace-nowrap"
            >
              {m.label}
            </a>
          ))}
        </nav>
      )}
    </header>
  )
}
```

Replace the inline `<header>…</header>` in `frontend/src/components/CustomiseStudio/index.tsx` with:
```tsx
import { StoreHeader } from '../StoreHeader'
// …in the JSX, replacing the existing <header> block:
      <StoreHeader subtitle={productRef ? `${productRef.name} › Design` : undefined} />
```
(Remove the now-unused hardcoded header markup.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/StoreHeader.test.tsx`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/StoreHeader.tsx frontend/src/components/CustomiseStudio/index.tsx frontend/src/components/StoreHeader.test.tsx
git commit -m "feat(theme): branded StoreHeader with logo + external menu"
```

---

## Task 9: Admin Branding view + API + route/nav

**Files:**
- Modify: `frontend/src/admin/adminApi.ts` (add `getStore`, `updateStoreBrand`, `uploadStoreLogo`, `FullStore`)
- Create: `frontend/src/admin/views/BrandingView.tsx`
- Modify: `frontend/src/admin/AdminApp.tsx` (route)
- Modify: `frontend/src/admin/AdminLayout.tsx` (nav item)
- Test: `frontend/src/admin/views/BrandingView.test.tsx`

**Interfaces:**
- Consumes: `useStores` (from `./hatTypes/shared`), `ErrorBanner`.
- Produces:
  - `getStore(id: string): Promise<FullStore>` where `FullStore` includes `brand: Brand`.
  - `updateStoreBrand(id: string, brand: Brand): Promise<FullStore>`.
  - `uploadStoreLogo(id: string, file: File): Promise<{ logo_url: string }>`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/admin/views/BrandingView.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BrandingView } from './BrandingView'
import * as api from '../adminApi'

vi.mock('../adminApi', async (orig) => {
  const actual = await orig<typeof api>()
  return {
    ...actual,
    listStores: vi.fn(async () => [{ id: 's1', slug: 'acme', name: 'Acme', public_key: 'k', shopify_domain: null, status: 'active' }]),
    getStore: vi.fn(async () => ({ id: 's1', slug: 'acme', name: 'Acme', brand: { primary_colour: '#123456', menu_items: [] } })),
    updateStoreBrand: vi.fn(async (_id: string, brand) => ({ id: 's1', slug: 'acme', name: 'Acme', brand })),
    uploadStoreLogo: vi.fn(async () => ({ logo_url: 'http://x/logo.png' })),
  }
})

function renderView() {
  return render(<MemoryRouter initialEntries={['/admin/branding?store=s1']}><BrandingView /></MemoryRouter>)
}

describe('BrandingView', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads and shows the store primary colour', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalledWith('s1'))
    expect(await screen.findByDisplayValue('#123456')).toBeInTheDocument()
  })

  it('blocks a 6th menu item', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    // add 5 rows -> the "Add menu item" control disables at 5
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    expect(screen.getByRole('button', { name: /add menu item/i })).toBeDisabled()
  })

  it('rejects a non-http url on save', async () => {
    renderView()
    await waitFor(() => expect(api.getStore).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: /add menu item/i }))
    fireEvent.change(screen.getByPlaceholderText(/label/i), { target: { value: 'Bad' } })
    fireEvent.change(screen.getByPlaceholderText(/https/i), { target: { value: 'javascript:alert(1)' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))
    expect(await screen.findByText(/http\(s\)/i)).toBeInTheDocument()
    expect(api.updateStoreBrand).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/BrandingView.test.tsx`
Expected: FAIL (cannot resolve `./BrandingView`).

- [ ] **Step 3: Write minimal implementation**

Add to `frontend/src/admin/adminApi.ts`:
```ts
import type { Brand } from '../lib/types'

export interface FullStore {
  id: string; slug: string; name: string; brand: Brand
}

export function getStore(id: string): Promise<FullStore> {
  return request<FullStore>(`/admin/stores/${id}`)
}

export function updateStoreBrand(id: string, brand: Brand): Promise<FullStore> {
  return request<FullStore>(`/admin/stores/${id}`, { method: 'PATCH', body: JSON.stringify({ brand }) })
}

export async function uploadStoreLogo(id: string, file: File): Promise<{ logo_url: string }> {
  const secret = getSecret()
  if (secret === null) { logout(); throw new ApiError(401, 'Not authenticated') }
  const form = new FormData()
  form.append('file', file)
  const res = await fetch(`${BASE_URL}/admin/stores/${id}/logo`, {
    method: 'POST', headers: { 'X-Admin-Secret': secret }, body: form,
  })
  if (!res.ok) {
    if (res.status === 401 || res.status === 403) logout()
    let detail = res.statusText
    try { const j = (await res.json()) as { detail?: string }; detail = j.detail ?? detail } catch { /* keep */ }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<{ logo_url: string }>
}
```

Create `frontend/src/admin/views/BrandingView.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { getStore, updateStoreBrand, uploadStoreLogo, type FullStore } from '../adminApi'
import type { Brand, MenuItem } from '../../lib/types'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores } from './hatTypes/shared'

const HEX = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/
const MAX_MENU = 5

function validate(brand: Brand): string | null {
  for (const [k, v] of Object.entries(brand)) {
    if (k.endsWith('_colour') || k === 'header_bg' || k === 'header_text') {
      if (v && !HEX.test(v as string)) return `${k} must be a hex colour`
    }
  }
  for (const m of brand.menu_items ?? []) {
    if (!m.label.trim()) return 'Every menu item needs a label'
    if (!/^https?:\/\//i.test(m.url)) return 'Menu links must be full http(s) URLs'
  }
  return null
}

export function BrandingView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [brand, setBrand] = useState<Brand>({})
  const [logoUrl, setLogoUrl] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (stores.length > 0 && !stores.some(s => s.id === storeId)) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  useEffect(() => {
    if (!storeId) return
    getStore(storeId)
      .then((s: FullStore) => { setBrand(s.brand ?? {}); setLogoUrl(s.brand?.logo_url ?? '') })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load store'))
  }, [storeId])

  function setField(k: keyof Brand, v: string) { setBrand(b => ({ ...b, [k]: v })); setSaved(false) }
  function setMenu(items: MenuItem[]) { setBrand(b => ({ ...b, menu_items: items })); setSaved(false) }
  const menu = brand.menu_items ?? []

  async function onLogo(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file || !storeId) return
    setBusy(true); setError(null)
    try {
      const { logo_url } = await uploadStoreLogo(storeId, file)
      setLogoUrl(logo_url); setBrand(b => ({ ...b, logo_url }))
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Logo upload failed')
    } finally { setBusy(false); e.target.value = '' }
  }

  async function onSave() {
    const msg = validate(brand)
    if (msg) { setError(msg); return }
    setBusy(true); setError(null)
    try {
      // logo_url stored via upload already; strip the proxied absolute URL so we
      // don't overwrite the storage path with a signed URL. Backend keeps it.
      const { logo_url: _omit, ...rest } = brand
      await updateStoreBrand(storeId, rest)
      setSaved(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally { setBusy(false) }
  }

  return (
    <div className="flex flex-col gap-5 max-w-[720px]">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-[20px] font-semibold">Branding</h1>
        <select
          value={storeId}
          onChange={e => setParams({ store: e.target.value }, { replace: true })}
          className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-1.5 text-[13px]"
          aria-label="Store"
        >
          {stores.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      {(storesError || error) && <ErrorBanner message={storesError || error || ''} />}

      {/* Live preview */}
      <div className="rounded-xl border border-[#e0e1ea] overflow-hidden">
        <div className="px-4 py-3 flex items-center gap-3"
             style={{ background: brand.header_bg || '#fff', color: brand.header_text || '#1a1a2e' }}>
          {logoUrl ? <img src={logoUrl} alt="logo" className="h-7" /> : <strong>{stores.find(s => s.id === storeId)?.name}</strong>}
          <span className="ml-auto flex gap-3 text-[13px]">
            {menu.map((m, i) => <span key={i}>{m.label || '—'}</span>)}
          </span>
        </div>
        <div className="p-4 bg-white">
          <button className="rounded-lg px-4 py-2 text-white text-[13px] font-medium"
                  style={{ background: brand.primary_colour || '#ff5c00' }}>Sample button</button>
        </div>
      </div>

      {/* Logo */}
      <div className="flex items-center gap-3 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <label className={`cursor-pointer rounded-lg bg-[#ff5c00] px-4 py-1.5 text-[13px] font-medium text-white ${busy ? 'opacity-50' : ''}`}>
          {busy ? 'Uploading…' : 'Upload logo'}
          <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" onChange={onLogo} disabled={busy} className="sr-only" />
        </label>
        <span className="text-[12px] text-[#9a9ab0]">PNG/JPG/GIF/WebP · max 10 MB</span>
      </div>

      {/* Colours */}
      <div className="grid grid-cols-3 gap-4 rounded-xl border border-[#e0e1ea] bg-white p-4">
        {(['primary_colour', 'header_bg', 'header_text'] as const).map(k => (
          <label key={k} className="flex flex-col gap-1 text-[12px] text-[#6b6b80]">
            {k.replace('_', ' ')}
            <span className="flex items-center gap-2">
              <input type="color" value={(brand[k] as string) || '#ffffff'} onChange={e => setField(k, e.target.value)} className="h-8 w-10 p-0" aria-label={k} />
              <input type="text" value={(brand[k] as string) || ''} onChange={e => setField(k, e.target.value)}
                     placeholder="#RRGGBB" className="w-24 rounded border border-[#e0e1ea] px-2 py-1 text-[12px]" />
            </span>
          </label>
        ))}
      </div>

      {/* Menu */}
      <div className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <div className="flex items-center justify-between">
          <span className="text-[13px] font-medium">Main menu ({menu.length}/{MAX_MENU})</span>
          <button
            onClick={() => setMenu([...menu, { label: '', url: '' }])}
            disabled={menu.length >= MAX_MENU}
            className="rounded-lg border border-[#e0e1ea] px-3 py-1 text-[12px] disabled:opacity-40"
          >Add menu item</button>
        </div>
        {menu.map((m, i) => (
          <div key={i} className="flex gap-2">
            <input value={m.label} placeholder="Label"
                   onChange={e => setMenu(menu.map((x, j) => j === i ? { ...x, label: e.target.value } : x))}
                   className="w-40 rounded border border-[#e0e1ea] px-2 py-1 text-[13px]" />
            <input value={m.url} placeholder="https://…"
                   onChange={e => setMenu(menu.map((x, j) => j === i ? { ...x, url: e.target.value } : x))}
                   className="flex-1 rounded border border-[#e0e1ea] px-2 py-1 text-[13px]" />
            <button onClick={() => setMenu(menu.filter((_, j) => j !== i))}
                    className="rounded border border-[#e0e1ea] px-2 text-[12px] text-red-600">Remove</button>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button onClick={onSave} disabled={busy}
                className="rounded-lg bg-[#ff5c00] px-5 py-2 text-[13px] font-medium text-white disabled:opacity-50">Save</button>
        {saved && <span className="text-[13px] text-green-600">Saved ✓</span>}
      </div>
    </div>
  )
}
```

Register the route in `frontend/src/admin/AdminApp.tsx`:
```tsx
import { BrandingView } from './views/BrandingView'
// …inside <Route path="/admin"> children:
          <Route path="branding" element={<BrandingView />} />
```

Add the nav item in `frontend/src/admin/AdminLayout.tsx` `NAV` array (after Stores):
```ts
  { to: '/admin/branding', label: 'Branding' },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/BrandingView.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/adminApi.ts frontend/src/admin/views/BrandingView.tsx frontend/src/admin/AdminApp.tsx frontend/src/admin/AdminLayout.tsx frontend/src/admin/views/BrandingView.test.tsx
git commit -m "feat(admin): Branding view (logo, colours, menu) with live preview"
```

---

## Task 10: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Backend suite**

Run: `cd backend && pytest -q`
Expected: PASS (existing 441 + new branding/storefront/admin/email tests; no regressions).

- [ ] **Step 2: Frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS (existing 204 + new brandStore/StoreHeader/BrandingView; 2 pre-existing `adminQuotes` failures unrelated — Router context — are expected).

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npm run build`
Expected: TypeScript compiles; Vite build succeeds (confirms CSS-var tokens + new imports).

- [ ] **Step 4: Manual smoke (documented, run in the dev stack)**

1. `docker compose up -d` (frontend container needs no new deps for this feature).
2. Admin → **Branding**: pick the local store, upload a logo, set a primary colour, add a menu item, Save.
3. Customer studio (`?product_id=…`): header shows the logo + menu link (new tab); primary buttons use the new colour.
4. Complete a design to trigger the preview email; confirm the emailed header uses the store colour/logo (Mailpit: `http://localhost:54324`).

- [ ] **Step 5: Commit (if any doc/fixups)**

```bash
git add -A
git commit -m "test: verify per-store branding across backend + frontend"
```

---

## Spec Coverage Check

| Spec section | Task(s) |
|---|---|
| §3 Data model (`brand` jsonb + menu_items) | 1 (validate/serialize), 2 (migration doc) |
| §4.1 `GET /storefront` | 2 |
| §4.2 Logo upload | 4 |
| §4.3 `PATCH` validation | 1 (rules), 3 (endpoint) |
| §5 CSS-var theming + ThemeProvider | 7 |
| §5.3 Header + menu | 8 |
| §6 Admin Branding editor | 9 |
| §7 Emails (preview + verification + resume) | 5, 6 |
| §8 Testing | every task (TDD) + 10 |
| §9 Backward compatibility | fallbacks in 1/5/6/7/8; verified in 10 |

**Deferred (spec §10, separate thread):** canvas "remove background" bug.
