# Hat Types Admin — CMS-style Management UX — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crammed single-screen `/admin/hat-types` page with a proper CMS flow — a searchable list with thumbnails + status, a guided 5-step create wizard, and a scrollable per-section edit page — so a non-technical admin can create, preview, and configure every applicable hat-type parameter.

**Architecture:** Three route-level views (list / wizard / edit) under `/admin/hat-types`, backed by four shared, self-contained field components (`BasicsFields`, `AngleUploader`, `ColourwayEditor`, `ChipListEditor`) and a small `shared.ts` helper module. One small backend change exposes browser-loadable proxy URLs (`view_images`) for the angle thumbnails. Store selection persists across the three views via a `?store=<id>` query param.

**Tech Stack:** Backend Python 3.12 / FastAPI (supabase-py, no ORM). Frontend React 18 / Vite / Tailwind 3 / react-router-dom / Zustand. Tests: backend `pytest`, frontend `vitest` + `@testing-library/react`.

## Global Constraints

- No secrets in code; all provider keys via env (unchanged here).
- Admin hat-type routes are store-scoped: every call needs **both** `X-Admin-Secret` **and** `X-Store-Key`.
- A hat type may only be activated once **all four** angle images (front/back/left/right) are present — enforced server-side (`svc.all_angles_present`), mirrored in UI.
- `slug` is auto-derived from the name and never shown to the admin.
- Out of scope: `pricing_slabs` editor, live-composite/customer-eye previews, any change to the customer-facing `BlankHatPicker`, the public `/hat-types` route, or the customise flow.
- Follow existing admin-view conventions (flat files in `frontend/src/admin/views/`, `#ff5c00` primary, `ErrorBanner` for errors).

---

## File Structure

**Backend (modify):**
- `backend/app/models/hat_type.py` — add `view_images` field to `HatTypeAdmin`.
- `backend/app/api/routes/admin_hat_types.py` — compute `view_images` proxy URLs on list + angle-upload responses.
- `backend/tests/test_admin_hat_types.py` — assert `view_images`.

**Frontend (create):**
- `frontend/src/admin/views/hatTypes/shared.ts` — `VIEWS`, `slugify`, `angleCount`, `allAngles`, `hatStatus`, `useStores`.
- `frontend/src/admin/views/hatTypes/shared.test.ts`
- `frontend/src/admin/views/hatTypes/ChipListEditor.tsx` (+ `.test.tsx`)
- `frontend/src/admin/views/hatTypes/ColourwayEditor.tsx` (+ `.test.tsx`)
- `frontend/src/admin/views/hatTypes/AngleUploader.tsx` (+ `.test.tsx`)
- `frontend/src/admin/views/hatTypes/BasicsFields.tsx` (+ `.test.tsx`)
- `frontend/src/admin/views/HatTypeWizard.tsx` (+ `.test.tsx`)
- `frontend/src/admin/views/HatTypeEditView.tsx` (+ `.test.tsx`)

**Frontend (modify):**
- `frontend/src/admin/adminApi.ts` — `HatType.view_images`; widen `createHatType`; `uploadHatAngle` return type.
- `frontend/src/admin/views/HatTypesView.tsx` — rewrite as the list view.
- `frontend/src/admin/views/HatTypesView.test.tsx` — rewrite for list behavior.
- `frontend/src/admin/AdminApp.tsx` — add `hat-types/new` and `hat-types/:id` routes.

---

### Task 1: Backend — expose `view_images` proxy URLs for admin

**Files:**
- Modify: `backend/app/models/hat_type.py`
- Modify: `backend/app/api/routes/admin_hat_types.py`
- Test: `backend/tests/test_admin_hat_types.py`

**Interfaces:**
- Consumes: `app.storage.media_url(path: str | None, base_url: str) -> str | None`; `svc.list_hat_types`, `svc.set_angle`.
- Produces: admin `GET /admin/hat-types` rows and `POST /admin/hat-types/{id}/angle/{view}` responses now include `view_images: dict[str, str]` (view → browser-loadable proxy URL). `HatTypeAdmin.view_images` field.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_admin_hat_types.py`:

```python
def test_list_includes_proxied_view_images(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]
    client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    rows = client.get("/admin/hat-types", headers=h).json()
    assert "/media/" in rows[0]["view_images"]["front"]


def test_angle_upload_returns_proxied_url(client):
    h = {"X-Admin-Secret": "s3cr3t", "X-Store-Key": "k"}
    created = client.post("/admin/hat-types", json={"name": "5P", "slug": "5p"}, headers=h)
    hat_id = created.json()["id"]
    r = client.post(
        f"/admin/hat-types/{hat_id}/angle/front",
        headers=h,
        files={"file": ("front.png", PNG_MAGIC, "image/png")},
    )
    assert "/media/" in r.json()["view_images"]["front"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_admin_hat_types.py::test_list_includes_proxied_view_images tests/test_admin_hat_types.py::test_angle_upload_returns_proxied_url -q`
Expected: FAIL — `KeyError: 'view_images'`.

- [ ] **Step 3: Add the `view_images` field to the model**

In `backend/app/models/hat_type.py`, in class `HatTypeAdmin`, add after the `blank_view_images` line:

```python
    view_images: dict[str, str] = Field(default_factory=dict)  # browser-loadable proxy URLs
```

- [ ] **Step 4: Compute proxy URLs in the routes**

In `backend/app/api/routes/admin_hat_types.py`, update the imports and the two routes.

Change the FastAPI import line to include `Request`:

```python
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
```

Add the storage import next to the existing `from app.storage import upload_asset`:

```python
from app.storage import media_url, upload_asset
```

Add this helper just below `_VIEWS = {"front", "back", "left", "right"}`:

```python
def _with_view_images(row: dict, base_url: str) -> dict:
    imgs = row.get("blank_view_images") or {}
    row["view_images"] = {v: media_url(p, base_url) for v, p in imgs.items() if p}
    return row
```

Replace the `list_hat_types` route body:

```python
@router.get("/admin/hat-types", response_model=list[HatTypeAdmin])
async def list_hat_types(request: Request, store: dict = Depends(require_store)) -> list[dict]:
    base = str(request.base_url)
    return [_with_view_images(row, base) for row in svc.list_hat_types(store["id"])]
```

Replace the `upload_angle` route signature + return. Add `request: Request` as the first parameter and change the final return:

```python
@router.post("/admin/hat-types/{hat_type_id}/angle/{view}")
async def upload_angle(
    request: Request,
    hat_type_id: str,
    view: str,
    file: UploadFile = File(...),
    store: dict = Depends(require_store),
) -> dict:
    row = svc.get_hat_type(hat_type_id, store_id=store["id"])
    if row is None:
        raise HTTPException(status_code=404, detail="Hat type not found")
    if view not in _VIEWS:
        raise HTTPException(status_code=400, detail="view must be front|back|left|right")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File exceeds 10 MB limit")
    mime = sniff_image_mime(data)
    if mime is None:
        raise HTTPException(status_code=415, detail="Unsupported file type (png/jpeg/gif/webp only)")
    path = upload_asset(data, file.filename or "blank", mime)
    updated = svc.set_angle(hat_type_id, view, path)
    imgs = updated["blank_view_images"]
    base = str(request.base_url)
    return {
        "blank_view_images": imgs,
        "view_images": {v: media_url(p, base) for v, p in imgs.items() if p},
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_admin_hat_types.py -q`
Expected: PASS (all, including the two new tests). The existing `test_angle_upload_success` still passes — it only asserts `blank_view_images`, which is still returned.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/hat_type.py backend/app/api/routes/admin_hat_types.py backend/tests/test_admin_hat_types.py
git commit -m "feat(be): expose proxied view_images on admin hat-types"
```

---

### Task 2: Frontend — API types + shared helpers

**Files:**
- Modify: `frontend/src/admin/adminApi.ts`
- Create: `frontend/src/admin/views/hatTypes/shared.ts`
- Test: `frontend/src/admin/views/hatTypes/shared.test.ts`

**Interfaces:**
- Consumes: `listStores(): Promise<Store[]>`, `type HatType`, `type Store` from `adminApi`.
- Produces:
  - `HatType.view_images: Record<string, string>`
  - `createHatType(body: { name: string; slug: string; style?: string; description?: string }, storeKey: string): Promise<HatType>`
  - `uploadHatAngle(...): Promise<{ blank_view_images: Record<string,string>; view_images: Record<string,string> }>`
  - `shared.ts`: `VIEWS: readonly ['front','back','left','right']`, `type View`, `slugify(name: string): string`, `angleCount(h): number`, `allAngles(h): boolean`, `type HatStatus = 'active'|'draft'|'needs_images'`, `hatStatus(h): HatStatus`, `useStores(): { stores: Store[]; loading: boolean; error: string | null }`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/hatTypes/shared.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { slugify, angleCount, allAngles, hatStatus, VIEWS } from './shared'

describe('hat-type shared helpers', () => {
  it('slugifies a display name', () => {
    expect(slugify('Trucker Cap!')).toBe('trucker-cap')
    expect(slugify('  5-Panel  ')).toBe('5-panel')
  })

  it('counts present angles', () => {
    expect(angleCount({ blank_view_images: { front: 'a', back: 'b' } })).toBe(2)
    expect(allAngles({ blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' } })).toBe(true)
  })

  it('derives status from angles + active flag', () => {
    expect(hatStatus({ blank_view_images: { front: 'a' }, active: false })).toBe('needs_images')
    const full = { front: 'a', back: 'b', left: 'c', right: 'd' }
    expect(hatStatus({ blank_view_images: full, active: false })).toBe('draft')
    expect(hatStatus({ blank_view_images: full, active: true })).toBe('active')
    expect(VIEWS).toHaveLength(4)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/shared.test.ts`
Expected: FAIL — cannot resolve `./shared`.

- [ ] **Step 3: Create the shared module**

Create `frontend/src/admin/views/hatTypes/shared.ts`:

```ts
import { useEffect, useState } from 'react'
import { listStores, type HatType, type Store } from '../../adminApi'

export const VIEWS = ['front', 'back', 'left', 'right'] as const
export type View = (typeof VIEWS)[number]

export function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

type AngleShape = Pick<HatType, 'blank_view_images'>

export function angleCount(h: AngleShape): number {
  return VIEWS.filter((v) => h.blank_view_images[v]).length
}

export function allAngles(h: AngleShape): boolean {
  return angleCount(h) === VIEWS.length
}

export type HatStatus = 'active' | 'draft' | 'needs_images'

export function hatStatus(h: Pick<HatType, 'blank_view_images' | 'active'>): HatStatus {
  if (!allAngles(h)) return 'needs_images'
  return h.active ? 'active' : 'draft'
}

export function useStores(): { stores: Store[]; loading: boolean; error: string | null } {
  const [stores, setStores] = useState<Store[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let active = true
    listStores()
      .then((data) => {
        if (active) {
          setStores(data)
          setError(null)
        }
      })
      .catch((e: unknown) => {
        if (active) setError(e instanceof Error ? e.message : 'Failed to load stores')
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])
  return { stores, loading, error }
}
```

- [ ] **Step 4: Extend the API types**

In `frontend/src/admin/adminApi.ts`:

Add to the `HatType` interface (after `blank_view_images`):

```ts
  view_images: Record<string, string>
```

Widen `createHatType`:

```ts
export function createHatType(
  body: { name: string; slug: string; style?: string; description?: string },
  storeKey: string,
): Promise<HatType> {
  return request<HatType>('/admin/hat-types', { method: 'POST', body: JSON.stringify(body) }, storeKey)
}
```

Change `uploadHatAngle`'s return type (signature line + its `Promise<...>`):

```ts
export async function uploadHatAngle(
  id: string,
  view: string,
  file: File,
  storeKey: string,
): Promise<{ blank_view_images: Record<string, string>; view_images: Record<string, string> }> {
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/shared.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/adminApi.ts frontend/src/admin/views/hatTypes/shared.ts frontend/src/admin/views/hatTypes/shared.test.ts
git commit -m "feat(fe): hat-type api types + shared helpers"
```

---

### Task 3: Frontend — `ChipListEditor` component

**Files:**
- Create: `frontend/src/admin/views/hatTypes/ChipListEditor.tsx`
- Test: `frontend/src/admin/views/hatTypes/ChipListEditor.test.tsx`

**Interfaces:**
- Produces: `ChipListEditor(props: { label: string; value: string[]; onChange: (next: string[]) => void; suggestions?: string[]; placeholder?: string }): JSX.Element`. Adds a chip on Enter or suggestion click (deduped, trimmed, non-empty); removes on ×.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/hatTypes/ChipListEditor.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ChipListEditor } from './ChipListEditor'

describe('ChipListEditor', () => {
  it('adds a chip on Enter', () => {
    const onChange = vi.fn()
    render(<ChipListEditor label="Zones" value={[]} onChange={onChange} />)
    const input = screen.getByLabelText('Zones')
    fireEvent.change(input, { target: { value: 'Front panel' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith(['Front panel'])
  })

  it('removes a chip via its × button', () => {
    const onChange = vi.fn()
    render(<ChipListEditor label="Zones" value={['Front panel', 'Back']} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove Front panel' }))
    expect(onChange).toHaveBeenCalledWith(['Back'])
  })

  it('adds a suggestion on click and skips duplicates', () => {
    const onChange = vi.fn()
    render(
      <ChipListEditor label="Zones" value={['Back']} onChange={onChange} suggestions={['Back', 'Front panel']} />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Add Front panel' }))
    expect(onChange).toHaveBeenCalledWith(['Back', 'Front panel'])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/ChipListEditor.test.tsx`
Expected: FAIL — cannot resolve `./ChipListEditor`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/admin/views/hatTypes/ChipListEditor.tsx`:

```tsx
import { useState } from 'react'

interface Props {
  label: string
  value: string[]
  onChange: (next: string[]) => void
  suggestions?: string[]
  placeholder?: string
}

export function ChipListEditor({ label, value, onChange, suggestions = [], placeholder }: Props) {
  const [draft, setDraft] = useState('')

  function add(raw: string) {
    const item = raw.trim()
    if (!item || value.includes(item)) return
    onChange([...value, item])
  }

  function remove(item: string) {
    onChange(value.filter((v) => v !== item))
  }

  const available = suggestions.filter((s) => !value.includes(s))

  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium">
        {label}
        <input
          value={draft}
          placeholder={placeholder ?? 'Type and press Enter'}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add(draft)
              setDraft('')
            }
          }}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      {value.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {value.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 rounded-full bg-[#fff2ea] px-2 py-0.5 text-xs text-[#ff5c00]"
            >
              {item}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                onClick={() => remove(item)}
                className="text-[#ff5c00] hover:text-[#e64f00]"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      {available.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {available.map((s) => (
            <button
              key={s}
              type="button"
              aria-label={`Add ${s}`}
              onClick={() => add(s)}
              className="rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-500 hover:border-[#ff5c00] hover:text-[#ff5c00]"
            >
              + {s}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/ChipListEditor.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/hatTypes/ChipListEditor.tsx frontend/src/admin/views/hatTypes/ChipListEditor.test.tsx
git commit -m "feat(fe): ChipListEditor for zones/decoration"
```

---

### Task 4: Frontend — `ColourwayEditor` component

**Files:**
- Create: `frontend/src/admin/views/hatTypes/ColourwayEditor.tsx`
- Test: `frontend/src/admin/views/hatTypes/ColourwayEditor.test.tsx`

**Interfaces:**
- Consumes: colour shape `{ name: string; hex: string }` (same as `HatType.colours`).
- Produces: `ColourwayEditor(props: { value: { name: string; hex: string }[]; onChange: (next: { name: string; hex: string }[]) => void }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/hatTypes/ColourwayEditor.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ColourwayEditor } from './ColourwayEditor'

describe('ColourwayEditor', () => {
  it('adds an empty colour row', () => {
    const onChange = vi.fn()
    render(<ColourwayEditor value={[]} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /add colour/i }))
    expect(onChange).toHaveBeenCalledWith([{ name: '', hex: '#000000' }])
  })

  it('edits a colour name', () => {
    const onChange = vi.fn()
    render(<ColourwayEditor value={[{ name: '', hex: '#000000' }]} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('Colour 1 name'), { target: { value: 'Black' } })
    expect(onChange).toHaveBeenCalledWith([{ name: 'Black', hex: '#000000' }])
  })

  it('removes a colour row', () => {
    const onChange = vi.fn()
    render(
      <ColourwayEditor
        value={[{ name: 'Black', hex: '#000000' }, { name: 'Red', hex: '#ff0000' }]}
        onChange={onChange}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Remove colour 1' }))
    expect(onChange).toHaveBeenCalledWith([{ name: 'Red', hex: '#ff0000' }])
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/ColourwayEditor.test.tsx`
Expected: FAIL — cannot resolve `./ColourwayEditor`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/admin/views/hatTypes/ColourwayEditor.tsx`:

```tsx
interface Colour {
  name: string
  hex: string
}

interface Props {
  value: Colour[]
  onChange: (next: Colour[]) => void
}

export function ColourwayEditor({ value, onChange }: Props) {
  function patch(i: number, next: Partial<Colour>) {
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...next } : c)))
  }
  function remove(i: number) {
    onChange(value.filter((_, idx) => idx !== i))
  }
  function add() {
    onChange([...value, { name: '', hex: '#000000' }])
  }

  return (
    <div className="space-y-2">
      {value.map((c, i) => (
        <div key={i} className="flex items-center gap-2">
          <input
            type="color"
            aria-label={`Colour ${i + 1} swatch`}
            value={c.hex}
            onChange={(e) => patch(i, { hex: e.target.value })}
            className="h-8 w-8 rounded border border-gray-300"
          />
          <input
            aria-label={`Colour ${i + 1} name`}
            value={c.name}
            placeholder="e.g. Black"
            onChange={(e) => patch(i, { name: e.target.value })}
            className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
          />
          <button
            type="button"
            aria-label={`Remove colour ${i + 1}`}
            onClick={() => remove(i)}
            className="rounded px-2 py-1 text-sm text-gray-400 hover:text-red-500"
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="rounded-lg border border-dashed border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:border-[#ff5c00] hover:text-[#ff5c00]"
      >
        + Add colour
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/ColourwayEditor.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/hatTypes/ColourwayEditor.tsx frontend/src/admin/views/hatTypes/ColourwayEditor.test.tsx
git commit -m "feat(fe): ColourwayEditor"
```

---

### Task 5: Frontend — `AngleUploader` component

**Files:**
- Create: `frontend/src/admin/views/hatTypes/AngleUploader.tsx`
- Test: `frontend/src/admin/views/hatTypes/AngleUploader.test.tsx`

**Interfaces:**
- Consumes: `uploadHatAngle(id, view, file, storeKey)` from `adminApi` (now returns `{ blank_view_images, view_images }`); `VIEWS` from `shared`.
- Produces: `AngleUploader(props: { hatId: string; storeKey: string; viewImages: Record<string, string>; onUploaded: (view: string, url: string) => void }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/hatTypes/AngleUploader.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AngleUploader } from './AngleUploader'
import * as api from '../../adminApi'

vi.mock('../../adminApi')

describe('AngleUploader', () => {
  beforeEach(() => vi.resetAllMocks())

  it('renders a thumbnail when a view image exists', () => {
    render(
      <AngleUploader hatId="h1" storeKey="k" viewImages={{ front: 'http://img/front.png' }} onUploaded={vi.fn()} />,
    )
    expect(screen.getByAltText('front')).toHaveAttribute('src', 'http://img/front.png')
  })

  it('uploads a file and reports the returned url', async () => {
    vi.mocked(api.uploadHatAngle).mockResolvedValue({
      blank_view_images: { front: 'p/front.png' },
      view_images: { front: 'http://img/front.png' },
    })
    const onUploaded = vi.fn()
    render(<AngleUploader hatId="h1" storeKey="k" viewImages={{}} onUploaded={onUploaded} />)
    const file = new File(['x'], 'front.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('Upload front'), { target: { files: [file] } })
    await waitFor(() => expect(onUploaded).toHaveBeenCalledWith('front', 'http://img/front.png'))
    expect(api.uploadHatAngle).toHaveBeenCalledWith('h1', 'front', file, 'k')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/AngleUploader.test.tsx`
Expected: FAIL — cannot resolve `./AngleUploader`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/admin/views/hatTypes/AngleUploader.tsx`:

```tsx
import { useState } from 'react'
import { uploadHatAngle } from '../../adminApi'
import { VIEWS } from './shared'

interface Props {
  hatId: string
  storeKey: string
  viewImages: Record<string, string>
  onUploaded: (view: string, url: string) => void
}

export function AngleUploader({ hatId, storeKey, viewImages, onUploaded }: Props) {
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handle(view: string, file: File) {
    setBusy(view)
    setError(null)
    try {
      const res = await uploadHatAngle(hatId, view, file, storeKey)
      const url = res.view_images[view]
      if (url) onUploaded(view, url)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Upload failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {VIEWS.map((v) => (
          <div key={v} className="rounded-lg border border-gray-200 p-2 text-center">
            <div className="mb-1 text-xs font-medium uppercase text-gray-500">
              {v} {viewImages[v] && <span className="text-green-600">✓</span>}
            </div>
            <div className="flex h-24 items-center justify-center overflow-hidden rounded bg-gray-50">
              {viewImages[v] ? (
                <img src={viewImages[v]} alt={v} className="max-h-24 object-contain" />
              ) : (
                <span className="text-2xl text-gray-300">＋</span>
              )}
            </div>
            <label className="mt-2 block cursor-pointer text-xs text-[#ff5c00] hover:underline">
              {busy === v ? 'Uploading…' : viewImages[v] ? 'Replace' : 'Upload'}
              <input
                type="file"
                accept="image/*"
                aria-label={`Upload ${v}`}
                className="hidden"
                onChange={(e) => e.target.files?.[0] && handle(v, e.target.files[0])}
              />
            </label>
          </div>
        ))}
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/AngleUploader.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/hatTypes/AngleUploader.tsx frontend/src/admin/views/hatTypes/AngleUploader.test.tsx
git commit -m "feat(fe): AngleUploader with live thumbnails"
```

---

### Task 6: Frontend — `BasicsFields` component

**Files:**
- Create: `frontend/src/admin/views/hatTypes/BasicsFields.tsx`
- Test: `frontend/src/admin/views/hatTypes/BasicsFields.test.tsx`

**Interfaces:**
- Produces: `type BasicsValue = { name: string; style: string; description: string }`; `BasicsFields(props: { value: BasicsValue; onChange: (next: BasicsValue) => void }): JSX.Element`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/hatTypes/BasicsFields.test.tsx`:

```tsx
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { BasicsFields } from './BasicsFields'

describe('BasicsFields', () => {
  it('renders current values and reports edits', () => {
    const onChange = vi.fn()
    render(
      <BasicsFields value={{ name: 'Trucker', style: 'trucker', description: '' }} onChange={onChange} />,
    )
    expect(screen.getByLabelText('Name')).toHaveValue('Trucker')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Dad Cap' } })
    expect(onChange).toHaveBeenCalledWith({ name: 'Dad Cap', style: 'trucker', description: '' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/BasicsFields.test.tsx`
Expected: FAIL — cannot resolve `./BasicsFields`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/admin/views/hatTypes/BasicsFields.tsx`:

```tsx
export interface BasicsValue {
  name: string
  style: string
  description: string
}

interface Props {
  value: BasicsValue
  onChange: (next: BasicsValue) => void
}

export function BasicsFields({ value, onChange }: Props) {
  return (
    <div className="space-y-3">
      <label className="block text-sm font-medium">
        Name
        <input
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="block text-sm font-medium">
        Style <span className="font-normal text-gray-400">(e.g. trucker, dad cap)</span>
        <input
          value={value.style}
          onChange={(e) => onChange({ ...value, style: e.target.value })}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
      <label className="block text-sm font-medium">
        Description <span className="font-normal text-gray-400">(internal note)</span>
        <textarea
          value={value.description}
          onChange={(e) => onChange({ ...value, description: e.target.value })}
          rows={2}
          className="mt-1 block w-full rounded border border-gray-300 px-2 py-1 text-sm"
        />
      </label>
    </div>
  )
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/hatTypes/BasicsFields.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/hatTypes/BasicsFields.tsx frontend/src/admin/views/hatTypes/BasicsFields.test.tsx
git commit -m "feat(fe): BasicsFields"
```

---

### Task 7: Frontend — rewrite the List view

**Files:**
- Modify (rewrite): `frontend/src/admin/views/HatTypesView.tsx`
- Modify (rewrite): `frontend/src/admin/views/HatTypesView.test.tsx`

**Interfaces:**
- Consumes: `listStores`, `listHatTypes`, `deleteHatType`, `type HatType`, `type Store` from `adminApi`; `useStores`, `hatStatus`, `angleCount`, `VIEWS` from `shared`; `ErrorBanner`; `react-router-dom` (`Link`, `useSearchParams`).
- Produces: default export unchanged name `HatTypesView` (route element). Navigation targets: `/admin/hat-types/new?store=<id>` (add) and `/admin/hat-types/<id>?store=<id>` (edit).

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `frontend/src/admin/views/HatTypesView.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypesView } from './HatTypesView'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1',
  slug: 'madhats',
  name: 'MadHats',
  public_key: 'mh_pk_test',
  shopify_domain: null,
  status: 'active',
}

function hat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1',
    store_id: 's1',
    slug: '5p',
    name: '5-Panel',
    style: '',
    description: null,
    blank_view_images: {},
    view_images: {},
    colours: [],
    placement_zones: [],
    decoration_types: [],
    pricing_slabs: [],
    active: false,
    ...overrides,
  }
}

function renderView() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types']}>
      <HatTypesView />
    </MemoryRouter>,
  )
}

describe('HatTypesView (list)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
  })

  it('lists hat types for the selected store using its store key', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    renderView()
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    expect(api.listHatTypes).toHaveBeenCalledWith('mh_pk_test')
  })

  it('shows a "Needs images" status when angles are incomplete', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat({ blank_view_images: { front: 'a' } })])
    renderView()
    await waitFor(() => expect(screen.getByText(/needs images/i)).toBeInTheDocument())
  })

  it('shows "Active" for a live, fully-angled hat type', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([
      hat({ active: true, blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' } }),
    ])
    renderView()
    await waitFor(() => expect(screen.getByText('Active')).toBeInTheDocument())
  })

  it('filters the list by search text', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat(), hat({ id: 'h2', name: 'Beanie' })])
    renderView()
    await waitFor(() => expect(screen.getByText('Beanie')).toBeInTheDocument())
    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: 'bean' } })
    expect(screen.queryByText('5-Panel')).not.toBeInTheDocument()
    expect(screen.getByText('Beanie')).toBeInTheDocument()
  })

  it('links the Add button to the create wizard for the selected store', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([])
    renderView()
    await waitFor(() => expect(screen.getByRole('link', { name: /add hat type/i })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: /add hat type/i })).toHaveAttribute(
      'href',
      '/admin/hat-types/new?store=s1',
    )
  })

  it('deletes after inline confirm', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    vi.mocked(api.deleteHatType).mockResolvedValue({ deleted: true })
    renderView()
    await waitFor(() => expect(screen.getByText('5-Panel')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /delete/i }))
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() => expect(api.deleteHatType).toHaveBeenCalledWith('h1', 'mh_pk_test'))
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/admin/views/HatTypesView.test.tsx`
Expected: FAIL — new assertions (status text, search box, Add link, confirm button) not present.

- [ ] **Step 3: Rewrite the list view**

Replace the entire contents of `frontend/src/admin/views/HatTypesView.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { listHatTypes, deleteHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, hatStatus, angleCount, VIEWS, type HatStatus } from './hatTypes/shared'

const STATUS_LABEL: Record<HatStatus, string> = {
  active: 'Active',
  draft: 'Draft',
  needs_images: 'Needs images',
}
const STATUS_CLASS: Record<HatStatus, string> = {
  active: 'bg-green-100 text-green-700',
  draft: 'bg-amber-100 text-amber-700',
  needs_images: 'bg-gray-100 text-gray-500',
}

export function HatTypesView() {
  const { stores, error: storesError } = useStores()
  const [params, setParams] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const [hats, setHats] = useState<HatType[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [confirmId, setConfirmId] = useState<string | null>(null)

  // Default the store selection to the first store once loaded.
  useEffect(() => {
    if (!storeId && stores.length > 0) {
      setParams({ store: stores[0].id }, { replace: true })
    }
  }, [storeId, stores, setParams])

  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null

  function reload(key: string) {
    setLoading(true)
    listHatTypes(key)
      .then((data) => {
        setHats(data)
        setError(null)
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load hat types'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (storeKey) reload(storeKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [storeKey])

  const filtered = useMemo(
    () => hats.filter((h) => h.name.toLowerCase().includes(search.toLowerCase())),
    [hats, search],
  )

  async function onDelete(id: string) {
    if (!storeKey) return
    setError(null)
    try {
      await deleteHatType(id, storeKey)
      setConfirmId(null)
      reload(storeKey)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Delete failed')
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">Hat Types</h1>
        {storeId && (
          <Link
            to={`/admin/hat-types/new?store=${storeId}`}
            className="rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00]"
          >
            + Add hat type
          </Link>
        )}
      </div>

      {(error || storesError) && <ErrorBanner message={error ?? storesError!} />}

      <div className="flex flex-wrap items-end gap-4">
        <label className="block text-sm">
          Store
          <select
            value={storeId}
            onChange={(e) => setParams({ store: e.target.value }, { replace: true })}
            className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
          >
            {stores.length === 0 && <option value="">No stores</option>}
            {stores.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm">
          Search
          <input
            value={search}
            placeholder="Search hat types…"
            onChange={(e) => setSearch(e.target.value)}
            className="mt-1 block rounded border border-gray-300 px-2 py-1 text-sm"
          />
        </label>
      </div>

      {loading && <p className="text-sm text-gray-500">Loading…</p>}
      {!loading && filtered.length === 0 && (
        <p className="text-sm text-gray-500">No hat types yet — add your first.</p>
      )}

      <div className="space-y-3">
        {filtered.map((h) => {
          const status = hatStatus(h)
          return (
            <div
              key={h.id}
              className="flex flex-wrap items-center gap-4 rounded-lg border border-gray-200 bg-white p-3"
            >
              <div className="flex h-14 w-14 items-center justify-center overflow-hidden rounded bg-gray-50">
                {h.view_images.front ? (
                  <img src={h.view_images.front} alt={h.name} className="max-h-14 object-contain" />
                ) : (
                  <span className="text-gray-300">—</span>
                )}
              </div>
              <div className="min-w-[8rem] flex-1">
                <div className="font-semibold">{h.name}</div>
                <div className="text-xs text-gray-400">{h.style || '—'}</div>
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${STATUS_CLASS[status]}`}>
                {STATUS_LABEL[status]}
              </span>
              <span className="text-xs text-gray-500">
                {h.colours.length} colour{h.colours.length === 1 ? '' : 's'} · {angleCount(h)}/
                {VIEWS.length} angles
              </span>
              <div className="flex items-center gap-2">
                <Link
                  to={`/admin/hat-types/${h.id}?store=${storeId}`}
                  className="rounded border border-gray-300 px-3 py-1 text-sm hover:bg-gray-50"
                >
                  Edit
                </Link>
                {confirmId === h.id ? (
                  <>
                    <button
                      onClick={() => onDelete(h.id)}
                      className="rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setConfirmId(null)}
                      className="rounded px-2 py-1 text-sm text-gray-500 hover:text-gray-700"
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    onClick={() => setConfirmId(h.id)}
                    className="rounded border border-gray-300 px-3 py-1 text-sm text-red-600 hover:bg-red-50"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/admin/views/HatTypesView.test.tsx`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/HatTypesView.tsx frontend/src/admin/views/HatTypesView.test.tsx
git commit -m "feat(fe): hat-types list with thumbnails, status, search, delete"
```

---

### Task 8: Frontend — Create wizard + route

**Files:**
- Create: `frontend/src/admin/views/HatTypeWizard.tsx`
- Test: `frontend/src/admin/views/HatTypeWizard.test.tsx`
- Modify: `frontend/src/admin/AdminApp.tsx`

**Interfaces:**
- Consumes: `createHatType`, `updateHatType`, `type HatType` from `adminApi`; `useStores`, `slugify`, `allAngles` from `shared`; `BasicsFields`, `AngleUploader`, `ColourwayEditor`, `ChipListEditor`; `react-router-dom` (`useSearchParams`, `useNavigate`).
- Produces: named export `HatTypeWizard`. On activate, navigates to `/admin/hat-types?store=<id>`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/HatTypeWizard.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypeWizard } from './HatTypeWizard'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1', slug: 'madhats', name: 'MadHats',
  public_key: 'mh_pk_test', shopify_domain: null, status: 'active',
}

function fullHat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1', store_id: 's1', slug: 'trucker-cap', name: 'Trucker Cap', style: '', description: '',
    blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' },
    view_images: { front: 'u', back: 'u', left: 'u', right: 'u' },
    colours: [], placement_zones: [], decoration_types: [], pricing_slabs: [], active: false,
    ...overrides,
  }
}

function renderWizard() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types/new?store=s1']}>
      <Routes>
        <Route path="/admin/hat-types/new" element={<HatTypeWizard />} />
        <Route path="/admin/hat-types" element={<div>LIST</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HatTypeWizard', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
    vi.mocked(api.updateHatType).mockResolvedValue(fullHat({ active: true }))
  })

  it('creates a draft with a slugified slug when leaving Basics', async () => {
    vi.mocked(api.createHatType).mockResolvedValue(fullHat())
    renderWizard()
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Trucker Cap' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i }))
    await waitFor(() =>
      expect(api.createHatType).toHaveBeenCalledWith(
        { name: 'Trucker Cap', slug: 'trucker-cap', style: '', description: '' },
        'mh_pk_test',
      ),
    )
  })

  it('walks to review and activates, then returns to the list', async () => {
    vi.mocked(api.createHatType).mockResolvedValue(fullHat())
    renderWizard()
    await waitFor(() => expect(screen.getByLabelText('Name')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Trucker Cap' } })
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Basics -> Angles
    await waitFor(() => expect(screen.getByText(/step 2 of 5/i)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Angles -> Colourways
    await waitFor(() => expect(screen.getByText('Colourways')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Colourways -> Zones
    await waitFor(() => expect(screen.getByText('Zones & decoration')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /next/i })) // Zones -> Review
    await waitFor(() => expect(screen.getByRole('button', { name: /activate/i })).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))
    await waitFor(() => expect(api.updateHatType).toHaveBeenCalledWith('h1', { active: true }, 'mh_pk_test'))
    await waitFor(() => expect(screen.getByText('LIST')).toBeInTheDocument())
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/HatTypeWizard.test.tsx`
Expected: FAIL — cannot resolve `./HatTypeWizard`.

- [ ] **Step 3: Implement the wizard**

Create `frontend/src/admin/views/HatTypeWizard.tsx`:

```tsx
import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { createHatType, updateHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, slugify, allAngles } from './hatTypes/shared'
import { BasicsFields, type BasicsValue } from './hatTypes/BasicsFields'
import { AngleUploader } from './hatTypes/AngleUploader'
import { ColourwayEditor } from './hatTypes/ColourwayEditor'
import { ChipListEditor } from './hatTypes/ChipListEditor'

const ZONE_SUGGESTIONS = ['Front panel', 'Left side', 'Right side', 'Back', 'Under-brim']
const DECORATION_SUGGESTIONS = ['Embroidery', 'Print', 'Patch']
const TOTAL_STEPS = 5

export function HatTypeWizard() {
  const { stores } = useStores()
  const [params] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null
  const navigate = useNavigate()

  const [step, setStep] = useState(1)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [basics, setBasics] = useState<BasicsValue>({ name: '', style: '', description: '' })
  const [hat, setHat] = useState<HatType | null>(null)
  const [colours, setColours] = useState<{ name: string; hex: string }[]>([])
  const [zones, setZones] = useState<string[]>([])
  const [decoration, setDecoration] = useState<string[]>([])

  const canActivate = useMemo(() => (hat ? allAngles(hat) : false), [hat])

  function fail(e: unknown, fallback: string) {
    setError(e instanceof Error ? e.message : fallback)
  }

  async function leaveBasics() {
    if (!storeKey || !basics.name.trim()) {
      setError('Please enter a name.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created =
        hat ??
        (await createHatType(
          { name: basics.name, slug: slugify(basics.name), style: basics.style, description: basics.description },
          storeKey,
        ))
      setHat(created)
      setColours(created.colours ?? [])
      setZones(created.placement_zones ?? [])
      setDecoration(created.decoration_types ?? [])
      setStep(2)
    } catch (e: unknown) {
      fail(e, 'Could not create hat type')
    } finally {
      setBusy(false)
    }
  }

  async function saveColours() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { colours }, storeKey)
      setStep(4)
    } catch (e: unknown) {
      fail(e, 'Could not save colours')
    } finally {
      setBusy(false)
    }
  }

  async function saveZones() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { placement_zones: zones, decoration_types: decoration }, storeKey)
      setStep(5)
    } catch (e: unknown) {
      fail(e, 'Could not save zones')
    } finally {
      setBusy(false)
    }
  }

  async function activate() {
    if (!storeKey || !hat) return
    setBusy(true)
    setError(null)
    try {
      await updateHatType(hat.id, { active: true }, storeKey)
      navigate(`/admin/hat-types?store=${storeId}`)
    } catch (e: unknown) {
      fail(e, 'Could not activate')
    } finally {
      setBusy(false)
    }
  }

  const primary =
    'rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00] disabled:opacity-50'
  const secondary = 'rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50'

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-xl font-semibold">New hat type</h1>
      <p className="text-sm text-gray-500">Step {step} of {TOTAL_STEPS}</p>
      {error && <ErrorBanner message={error} />}

      <div className="rounded-lg border border-gray-200 bg-white p-5">
        {step === 1 && (
          <>
            <h2 className="mb-3 font-medium">Basics</h2>
            <BasicsFields value={basics} onChange={setBasics} />
            <div className="mt-5 flex justify-end">
              <button className={primary} disabled={busy} onClick={leaveBasics}>
                {busy ? 'Saving…' : 'Next'}
              </button>
            </div>
          </>
        )}

        {step === 2 && hat && (
          <>
            <h2 className="mb-3 font-medium">Upload the four angles</h2>
            <AngleUploader
              hatId={hat.id}
              storeKey={storeKey!}
              viewImages={hat.view_images}
              onUploaded={(view, url) =>
                setHat({
                  ...hat,
                  view_images: { ...hat.view_images, [view]: url },
                  blank_view_images: { ...hat.blank_view_images, [view]: url },
                })
              }
            />
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(1)}>Back</button>
              <button className={primary} disabled={!canActivate} onClick={() => setStep(3)}>Next</button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2 className="mb-3 font-medium">Colourways</h2>
            <ColourwayEditor value={colours} onChange={setColours} />
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(2)}>Back</button>
              <button className={primary} disabled={busy} onClick={saveColours}>Next</button>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2 className="mb-3 font-medium">Zones &amp; decoration</h2>
            <div className="space-y-4">
              <ChipListEditor label="Placement zones" value={zones} onChange={setZones} suggestions={ZONE_SUGGESTIONS} />
              <ChipListEditor label="Decoration types" value={decoration} onChange={setDecoration} suggestions={DECORATION_SUGGESTIONS} />
            </div>
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(3)}>Back</button>
              <button className={primary} disabled={busy} onClick={saveZones}>Next</button>
            </div>
          </>
        )}

        {step === 5 && hat && (
          <>
            <h2 className="mb-3 font-medium">Review &amp; activate</h2>
            <ul className="space-y-1 text-sm text-gray-600">
              <li><strong>{basics.name}</strong> {basics.style && `· ${basics.style}`}</li>
              <li>{colours.length} colourway(s)</li>
              <li>{zones.length} zone(s), {decoration.length} decoration type(s)</li>
              <li>Angles: {canActivate ? 'all four uploaded ✓' : 'incomplete — go back to step 2'}</li>
            </ul>
            <div className="mt-5 flex justify-between">
              <button className={secondary} onClick={() => setStep(4)}>Back</button>
              <button className={primary} disabled={busy || !canActivate} onClick={activate}>
                {busy ? 'Activating…' : 'Activate'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Add the route**

In `frontend/src/admin/AdminApp.tsx`, add the import (next to the other view imports):

```tsx
import { HatTypeWizard } from './views/HatTypeWizard'
```

Add the route immediately before the existing `<Route path="hat-types" ... />` line:

```tsx
          <Route path="hat-types/new" element={<HatTypeWizard />} />
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/admin/views/HatTypeWizard.test.tsx`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/HatTypeWizard.tsx frontend/src/admin/views/HatTypeWizard.test.tsx frontend/src/admin/AdminApp.tsx
git commit -m "feat(fe): guided hat-type create wizard"
```

---

### Task 9: Frontend — Edit view + route

**Files:**
- Create: `frontend/src/admin/views/HatTypeEditView.tsx`
- Test: `frontend/src/admin/views/HatTypeEditView.test.tsx`
- Modify: `frontend/src/admin/AdminApp.tsx`

**Interfaces:**
- Consumes: `listHatTypes`, `updateHatType`, `type HatType` from `adminApi`; `useStores`, `allAngles` from `shared`; `BasicsFields`, `AngleUploader`, `ColourwayEditor`, `ChipListEditor`, `ErrorBanner`; `react-router-dom` (`useParams`, `useSearchParams`, `Link`).
- Produces: named export `HatTypeEditView`. Loads the record by finding it in the store's list (no get-by-id endpoint).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/admin/views/HatTypeEditView.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { HatTypeEditView } from './HatTypeEditView'
import * as api from '../adminApi'

vi.mock('../adminApi')

const STORE = {
  id: 's1', slug: 'madhats', name: 'MadHats',
  public_key: 'mh_pk_test', shopify_domain: null, status: 'active',
}

function hat(overrides: Partial<api.HatType> = {}): api.HatType {
  return {
    id: 'h1', store_id: 's1', slug: '5p', name: '5-Panel', style: 'trucker', description: '',
    blank_view_images: { front: 'a', back: 'b', left: 'c', right: 'd' },
    view_images: { front: 'u', back: 'u', left: 'u', right: 'u' },
    colours: [{ name: 'Black', hex: '#000000' }],
    placement_zones: [], decoration_types: [], pricing_slabs: [], active: true,
    ...overrides,
  }
}

function renderEdit() {
  return render(
    <MemoryRouter initialEntries={['/admin/hat-types/h1?store=s1']}>
      <Routes>
        <Route path="/admin/hat-types/:id" element={<HatTypeEditView />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('HatTypeEditView', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(api.listStores).mockResolvedValue([STORE])
  })

  it('loads the record and populates fields', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    renderEdit()
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('5-Panel'))
  })

  it('saves the basics section independently', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat()])
    vi.mocked(api.updateHatType).mockResolvedValue(hat({ name: 'Six Panel' }))
    renderEdit()
    await waitFor(() => expect(screen.getByLabelText('Name')).toHaveValue('5-Panel'))
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Six Panel' } })
    fireEvent.click(screen.getByRole('button', { name: /save basics/i }))
    await waitFor(() =>
      expect(api.updateHatType).toHaveBeenCalledWith(
        'h1',
        { name: 'Six Panel', style: 'trucker', description: '' },
        'mh_pk_test',
      ),
    )
  })

  it('disables the active toggle until all four angles exist', async () => {
    vi.mocked(api.listHatTypes).mockResolvedValue([hat({ active: false, blank_view_images: { front: 'a' } })])
    renderEdit()
    await waitFor(() => expect(screen.getByRole('checkbox', { name: /active/i })).toBeInTheDocument())
    expect(screen.getByRole('checkbox', { name: /active/i })).toBeDisabled()
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/HatTypeEditView.test.tsx`
Expected: FAIL — cannot resolve `./HatTypeEditView`.

- [ ] **Step 3: Implement the edit view**

Create `frontend/src/admin/views/HatTypeEditView.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { listHatTypes, updateHatType, type HatType } from '../adminApi'
import { ErrorBanner } from '../components/ErrorBanner'
import { useStores, allAngles } from './hatTypes/shared'
import { BasicsFields, type BasicsValue } from './hatTypes/BasicsFields'
import { AngleUploader } from './hatTypes/AngleUploader'
import { ColourwayEditor } from './hatTypes/ColourwayEditor'
import { ChipListEditor } from './hatTypes/ChipListEditor'

const ZONE_SUGGESTIONS = ['Front panel', 'Left side', 'Right side', 'Back', 'Under-brim']
const DECORATION_SUGGESTIONS = ['Embroidery', 'Print', 'Patch']

const sectionCls = 'rounded-lg border border-gray-200 bg-white p-5 space-y-4'
const primary = 'rounded-lg bg-[#ff5c00] px-4 py-2 text-sm text-white hover:bg-[#e64f00] disabled:opacity-50'

export function HatTypeEditView() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const storeId = params.get('store') ?? ''
  const { stores } = useStores()
  const storeKey = stores.find((s) => s.id === storeId)?.public_key ?? null

  const [hat, setHat] = useState<HatType | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState<string | null>(null)

  const [basics, setBasics] = useState<BasicsValue>({ name: '', style: '', description: '' })
  const [colours, setColours] = useState<{ name: string; hex: string }[]>([])
  const [zones, setZones] = useState<string[]>([])
  const [decoration, setDecoration] = useState<string[]>([])

  useEffect(() => {
    if (!storeKey || !id) return
    listHatTypes(storeKey)
      .then((rows) => {
        const found = rows.find((r) => r.id === id) ?? null
        setHat(found)
        if (found) {
          setBasics({ name: found.name, style: found.style ?? '', description: found.description ?? '' })
          setColours(found.colours ?? [])
          setZones(found.placement_zones ?? [])
          setDecoration(found.decoration_types ?? [])
        } else {
          setError('Hat type not found')
        }
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : 'Failed to load hat type'))
  }, [storeKey, id])

  async function save(section: string, patch: Partial<HatType>) {
    if (!storeKey || !hat) return
    setSaving(section)
    setError(null)
    try {
      const updated = await updateHatType(hat.id, patch, storeKey)
      setHat(updated)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Save failed')
    } finally {
      setSaving(null)
    }
  }

  if (!hat) {
    return (
      <div className="space-y-4">
        {error && <ErrorBanner message={error} />}
        {!error && <p className="text-sm text-gray-500">Loading…</p>}
      </div>
    )
  }

  const canActivate = allAngles(hat)

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Edit: {hat.name}</h1>
        <Link to={`/admin/hat-types?store=${storeId}`} className="text-sm text-[#ff5c00] hover:underline">
          ← Back to list
        </Link>
      </div>
      {error && <ErrorBanner message={error} />}

      <section className={sectionCls}>
        <h2 className="font-medium">Basics</h2>
        <BasicsFields value={basics} onChange={setBasics} />
        <div className="flex items-center justify-between">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={hat.active}
              disabled={!canActivate}
              onChange={(e) => save('active', { active: e.target.checked })}
            />
            Active {!canActivate && <span className="text-xs text-gray-400">(needs all 4 angles)</span>}
          </label>
          <button
            className={primary}
            disabled={saving === 'basics'}
            onClick={() => save('basics', { name: basics.name, style: basics.style, description: basics.description })}
          >
            {saving === 'basics' ? 'Saving…' : 'Save basics'}
          </button>
        </div>
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Angle images</h2>
        <AngleUploader
          hatId={hat.id}
          storeKey={storeKey!}
          viewImages={hat.view_images}
          onUploaded={(view, url) =>
            setHat({
              ...hat,
              view_images: { ...hat.view_images, [view]: url },
              blank_view_images: { ...hat.blank_view_images, [view]: url },
            })
          }
        />
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Colourways</h2>
        <ColourwayEditor value={colours} onChange={setColours} />
        <div className="flex justify-end">
          <button className={primary} disabled={saving === 'colours'} onClick={() => save('colours', { colours })}>
            {saving === 'colours' ? 'Saving…' : 'Save colourways'}
          </button>
        </div>
      </section>

      <section className={sectionCls}>
        <h2 className="font-medium">Zones &amp; decoration</h2>
        <ChipListEditor label="Placement zones" value={zones} onChange={setZones} suggestions={ZONE_SUGGESTIONS} />
        <ChipListEditor label="Decoration types" value={decoration} onChange={setDecoration} suggestions={DECORATION_SUGGESTIONS} />
        <div className="flex justify-end">
          <button
            className={primary}
            disabled={saving === 'zones'}
            onClick={() => save('zones', { placement_zones: zones, decoration_types: decoration })}
          >
            {saving === 'zones' ? 'Saving…' : 'Save zones & decoration'}
          </button>
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 4: Add the route**

In `frontend/src/admin/AdminApp.tsx`, add the import:

```tsx
import { HatTypeEditView } from './views/HatTypeEditView'
```

Add the route immediately after the existing `<Route path="hat-types" ... />` line:

```tsx
          <Route path="hat-types/:id" element={<HatTypeEditView />} />
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/HatTypeEditView.test.tsx`
Expected: PASS (all 3).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/admin/views/HatTypeEditView.tsx frontend/src/admin/views/HatTypeEditView.test.tsx frontend/src/admin/AdminApp.tsx
git commit -m "feat(fe): scrollable per-section hat-type edit page"
```

---

### Task 10: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS except the 2 pre-existing `adminQuotes` failures noted in CLAUDE.md (missing Router context — unrelated). No new failures.

- [ ] **Step 2: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS (all, including the 2 new admin hat-type tests).

- [ ] **Step 3: Typecheck / build the frontend**

Run: `cd frontend && npm run build`
Expected: Type-checks and builds cleanly (no unused-import or type errors from the new files).

- [ ] **Step 4: Update project memory**

In `CLAUDE.md`, in the "Current implementation state" bullet about admin hat types, append a note that the Hat Types admin is now a list + guided create wizard + scrollable edit page, with colourway/zone/decoration editors and angle thumbnails (admin API returns `view_images` proxy URLs).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: note hat-types admin CMS UX in project memory"
```

---

## Self-Review Notes

- **Spec coverage:** List (Task 7), wizard (Task 8), edit (Task 9), preview thumbnails via `view_images` (Task 1 + used in 5/7/9), all four parameter groups (colourways T4, zones/decoration T3, style+description T6), slug auto-derived (T2 `slugify`, used T8), status pills (T7), delete-confirm (T7), activation gate (T8/T9 + backend T1), store persistence via `?store=` (T2 `useStores` + T7/T8/T9). `pricing_slabs` intentionally excluded per spec.
- **Type consistency:** `HatType.view_images` (T2) consumed by AngleUploader/list/edit; `uploadHatAngle` returns `{ blank_view_images, view_images }` (T1 backend, T2 type, T5 usage); `BasicsValue` defined in T6, imported in T8/T9; `hatStatus`/`allAngles`/`angleCount`/`slugify`/`VIEWS`/`useStores` all defined in T2 `shared.ts` and consumed downstream.
- **No placeholders:** every code step contains full source; every run step has an exact command + expected result.
