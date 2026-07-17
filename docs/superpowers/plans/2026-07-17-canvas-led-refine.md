# Canvas-led refine + background removal that ticks itself — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Ricardo apply a described change to the canvas (free, instant, deterministic) and only render on confirm, and have the background-removal chip do the ticking itself.

**Architecture:** One new backend→canvas channel, `data.canvas_ops`, carrying fully-resolved flat patches. The backend does all arithmetic and clamping; the frontend applies patches verbatim. Ops are applied in the frontend store's response handler (not a React effect) so they run exactly once and never on resume. Background removal emits an op from the v2 step registry; refine emits ops from a new pure resolver driven by a closed LLM vocabulary.

**Tech Stack:** Python 3.12 / FastAPI / pytest; React 18 / Zustand / Konva / vitest.

**Spec:** `docs/superpowers/specs/2026-07-17-canvas-led-refine-design.md`

## Global Constraints

- **The LLM reads the customer; it never routes and never computes geometry.** Models emit closed-vocabulary intent only. All arithmetic and clamping is code.
- **Background-removal copy must never promise processing or ask the customer to wait.** Ticking is instant — nothing is matted client-side. This is a standing rule (`prompts.V2_BG_INSTRUCTIONS`, the `ask_logo_bg` step).
- **Do not reintroduce canvas-level background processing.** Removal is a MARK the image model acts on at render time.
- **`pending_logo["bg"]` stays.** It is `ask_logo_bg`'s answered-marker (`done_when` reads `"bg" in _pending(c)`, `canvas_steps.py:412`). Deleting it strands the step.
- **`ask_logo_bg` keeps `tool="upload"`.** Documented load-bearing; pinned by `test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable`.
- **Every refine branch is gated on `flow_mode == "canvas"`.** Non-canvas (`session`/`blank`) refine keeps `change_request` → regenerate exactly as today.
- **No PII in logs.** Never log the customer's description text or email.
- **Backend tests run as** `CANVAS_ORCHESTRATOR_V2=false pytest -q` from `backend/` (the repo-root `.env` default of `true` flips unrelated tests red).
- **Frontend tests run as** `npx vitest run <path>` from `frontend/` (`npm test` is watch mode and hangs). Full `vitest run` is flaky on this Windows host — run targeted paths.

---

### Task 1: Face-aware canvas store actions

`updateElement`/`removeElement` only touch `s.activeFace` (`canvasStore.ts:138-143`, `:160`). Ops carry their own face and must not depend on what the customer is looking at.

**Files:**
- Modify: `frontend/src/store/canvasStore.ts`
- Test: `frontend/src/__tests__/canvasStoreOps.test.ts` (create)

**Interfaces:**
- Produces:
  - `patchElement(face: Face, id: string, patch: Partial<CanvasElement>): void`
  - `removeElementOn(face: Face, id: string): void`
  - `patchPendingLogo(face: Face, patch: Partial<CanvasElement>): void` — patches the **last unlocked `type === 'image'`** element on `face`; no-op if there is none.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/canvasStoreOps.test.ts`:

```ts
import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

test('patchElement patches the named face, not the active one', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('back'); s.addText('b')
  const backId = useCanvasStore.getState().faces.back[0].id
  s.setActiveFace('front')          // customer is looking elsewhere
  s.patchElement('back', backId, { x: 0.9 })
  expect(useCanvasStore.getState().faces.back[0].x).toBe(0.9)
})

test('patchElement patches a locked element', () => {
  // Ops arrive after lockAll() has frozen the canvas at finalize; the lock
  // stops the CUSTOMER dragging, not the bot editing.
  const s = useCanvasStore.getState()
  s.addText('a')
  const id = useCanvasStore.getState().faces.front[0].id
  s.lockAll()
  s.patchElement('front', id, { x: 0.1 })
  expect(useCanvasStore.getState().faces.front[0].x).toBe(0.1)
})

test('removeElementOn removes from the named face', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('left'); s.addText('x')
  const id = useCanvasStore.getState().faces.left[0].id
  s.setActiveFace('front')
  s.removeElementOn('left', id)
  expect(useCanvasStore.getState().faces.left).toHaveLength(0)
})

test('patchPendingLogo targets the last unlocked image on the face', () => {
  const s = useCanvasStore.getState()
  s.addImage('old.png')                       // an earlier logo…
  s.lockPlaced()                              // …already locked in by a prior step
  s.addImage('new.png')                       // the one just placed
  s.patchPendingLogo('front', { removeBg: true })
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].removeBg).toBeFalsy()
  expect(faces.front[1].removeBg).toBe(true)
})

test('patchPendingLogo ignores text and shapes', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  s.addText('later text')                     // unlocked, but not an image
  s.patchPendingLogo('front', { removeBg: true })
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].removeBg).toBe(true)
})

test('patchPendingLogo is a no-op when the face has no unlocked image', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  s.lockAll()
  expect(() => s.patchPendingLogo('front', { removeBg: true })).not.toThrow()
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBeFalsy()
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreOps.test.ts`
Expected: FAIL — `s.patchElement is not a function`

- [ ] **Step 3: Write minimal implementation**

In `frontend/src/store/canvasStore.ts`, add to the `CanvasState` interface next to `removeElement` (~line 64):

```ts
  /** Ops channel: patch by explicit face — `updateElement` only sees activeFace. */
  patchElement: (face: Face, id: string, patch: Partial<CanvasElement>) => void
  removeElementOn: (face: Face, id: string) => void
  /** Patch the last unlocked image on `face` — the logo just placed. Same
   *  "last unlocked" anchor `lockPlaced` uses, because the backend has no id
   *  for it: canvas_design isn't persisted until finalize. */
  patchPendingLogo: (face: Face, patch: Partial<CanvasElement>) => void
```

And to the store body, after `removeElement` (~line 163):

```ts
  patchElement: (face, id, patch) => set(s => ({
    faces: { ...s.faces, [face]: s.faces[face].map(e => (e.id === id ? { ...e, ...patch } : e)) },
  })),

  removeElementOn: (face, id) => set(s => ({
    faces: { ...s.faces, [face]: s.faces[face].filter(e => e.id !== id) },
  })),

  patchPendingLogo: (face, patch) => set(s => {
    const arr = s.faces[face]
    let idx = -1
    for (let i = arr.length - 1; i >= 0; i--) {
      if (arr[i].type === 'image' && !arr[i].locked) { idx = i; break }
    }
    if (idx === -1) return s
    const next = arr.slice()
    next[idx] = { ...next[idx], ...patch }
    return { faces: { ...s.faces, [face]: next } }
  }),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreOps.test.ts src/__tests__/canvasStoreLock.test.ts src/store/canvasStore.test.ts`
Expected: PASS (all three files — the lock tests must stay green)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/__tests__/canvasStoreOps.test.ts
git commit -m "feat(canvas): face-aware patch/remove store actions for the ops channel"
```

---

### Task 2: The `canvas_ops` channel on the frontend

**Files:**
- Create: `frontend/src/lib/canvasOps.ts`
- Modify: `frontend/src/store/chatStore.ts`
- Test: `frontend/src/__tests__/canvasOps.test.ts` (create)

**Interfaces:**
- Consumes: `patchElement`, `removeElementOn`, `patchPendingLogo` (Task 1).
- Produces:
  - `parseCanvasOps(data: Record<string, unknown>): CanvasOp[]`
  - `applyCanvasOps(ops: CanvasOp[]): void`
  - `type CanvasOp = { target: CanvasOpTarget; patch?: Partial<CanvasElement>; remove?: boolean }`
  - `type CanvasOpTarget = { kind: 'element'; id: string; face: Face } | { kind: 'pending_logo'; face: Face }`

Lives in `lib/`, not `chatStore`, so the parse/apply logic is unit-testable on its own and `chatStore`'s dependency on `canvasStore` stays a single shallow import.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/canvasOps.test.ts`:

```ts
import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'
import { parseCanvasOps, applyCanvasOps } from '../lib/canvasOps'

beforeEach(() => useCanvasStore.getState().reset())

test('parseCanvasOps returns [] when the key is absent or malformed', () => {
  expect(parseCanvasOps({})).toEqual([])
  expect(parseCanvasOps({ canvas_ops: 'nope' })).toEqual([])
})

test('parseCanvasOps drops ops with an unknown target kind or bad face', () => {
  const ops = parseCanvasOps({
    canvas_ops: [
      { target: { kind: 'wat', face: 'front' }, patch: { x: 0.1 } },
      { target: { kind: 'element', id: 'a', face: 'nose' }, patch: { x: 0.1 } },
      { target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } },
    ],
  })
  expect(ops).toHaveLength(1)
  expect(ops[0].target.kind).toBe('pending_logo')
})

test('applyCanvasOps patches a pending logo', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png')
  applyCanvasOps([{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }])
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBe(true)
})

test('applyCanvasOps patches and removes elements by id', () => {
  const s = useCanvasStore.getState()
  s.addText('a'); s.addText('b')
  const [a, b] = useCanvasStore.getState().faces.front.map(e => e.id)
  applyCanvasOps([
    { target: { kind: 'element', id: a, face: 'front' }, patch: { x: 0.75 } },
    { target: { kind: 'element', id: b, face: 'front' }, remove: true },
  ])
  const { faces } = useCanvasStore.getState()
  expect(faces.front).toHaveLength(1)
  expect(faces.front[0].x).toBe(0.75)
})
```

Append to `frontend/src/__tests__/chatStore.test.ts`:

```ts
import { useCanvasStore } from '../store/canvasStore'

test('sendMessage applies canvas_ops from the response exactly once', async () => {
  useCanvasStore.getState().reset()
  useCanvasStore.getState().addImage('logo.png')
  const api = await import('../lib/api')
  vi.spyOn(api, 'sendChat').mockResolvedValue({
    reply: 'Marked it.', state: 'ask_another_logo',
    data: { canvas_ops: [{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }] },
  } as never)
  await useChatStore.getState().sendMessage('s1', 'Yes, remove background')
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBe(true)
})

test('hydrate never applies canvas_ops — a resume must not re-edit the design', () => {
  useCanvasStore.getState().reset()
  useCanvasStore.getState().addImage('logo.png')
  useChatStore.getState().hydrate([], 'ask_another_logo', {
    canvas_ops: [{ target: { kind: 'pending_logo', face: 'front' }, patch: { removeBg: true } }],
  })
  expect(useCanvasStore.getState().faces.front[0].removeBg).toBeFalsy()
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/canvasOps.test.ts src/__tests__/chatStore.test.ts`
Expected: FAIL — cannot resolve `../lib/canvasOps`

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/lib/canvasOps.ts`:

```ts
import { useCanvasStore, FACES, type CanvasElement, type Face } from '../store/canvasStore'

export type CanvasOpTarget =
  | { kind: 'element'; id: string; face: Face }
  | { kind: 'pending_logo'; face: Face }

export interface CanvasOp {
  target: CanvasOpTarget
  patch?: Partial<CanvasElement>
  remove?: boolean
}

function isFace(v: unknown): v is Face {
  return typeof v === 'string' && (FACES as string[]).includes(v)
}

/** Ops are already fully resolved by the backend (arithmetic, clamping, colour
 *  names). This only rejects structurally invalid rows. */
export function parseCanvasOps(data: Record<string, unknown>): CanvasOp[] {
  if (!Array.isArray(data.canvas_ops)) return []
  const out: CanvasOp[] = []
  for (const raw of data.canvas_ops as unknown[]) {
    if (!raw || typeof raw !== 'object') continue
    const op = raw as Record<string, unknown>
    const t = op.target as Record<string, unknown> | undefined
    if (!t || !isFace(t.face)) continue
    if (t.kind === 'pending_logo') {
      out.push({ target: { kind: 'pending_logo', face: t.face }, patch: op.patch as Partial<CanvasElement>, remove: op.remove === true })
    } else if (t.kind === 'element' && typeof t.id === 'string') {
      out.push({ target: { kind: 'element', id: t.id, face: t.face }, patch: op.patch as Partial<CanvasElement>, remove: op.remove === true })
    }
  }
  return out
}

/** Applied imperatively where the response lands — NOT in a React effect.
 *  An effect fires on change, which would re-apply on resume/hydrate and
 *  re-flag the wrong logo on a later loop pass. */
export function applyCanvasOps(ops: CanvasOp[]): void {
  if (!ops.length) return
  const s = useCanvasStore.getState()
  for (const op of ops) {
    if (op.target.kind === 'pending_logo') {
      if (op.patch) s.patchPendingLogo(op.target.face, op.patch)
      continue
    }
    if (op.remove) s.removeElementOn(op.target.face, op.target.id)
    else if (op.patch) s.patchElement(op.target.face, op.target.id, op.patch)
  }
}
```

In `frontend/src/store/chatStore.ts`, add the import at the top:

```ts
import { parseCanvasOps, applyCanvasOps } from '../lib/canvasOps'
```

In `sendMessage`, inside the `try` after `const parsed = parseData(res.data)`, add one line **before** the `set(...)`:

```ts
      const res = await sendChat(sessionId, text)
      const parsed = parseData(res.data)
      applyCanvasOps(parseCanvasOps(res.data))   // before set(): patch, then Surface's lock effect
      set(state => ({
```

Do **not** add it to `hydrate`, `kickoff`, `applyResponse`, or any poll: a resume must never re-edit the design, and ops only ever answer a customer turn.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/canvasOps.test.ts src/__tests__/chatStore.test.ts src/__tests__/chatStoreCanvasDirective.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/canvasOps.ts frontend/src/store/chatStore.ts frontend/src/__tests__/canvasOps.test.ts frontend/src/__tests__/chatStore.test.ts
git commit -m "feat(canvas): data.canvas_ops channel, applied at the response site not in an effect"
```

---

### Task 3: Background removal ticks itself

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py` (the `Step` dataclass ~line 38-75; `_apply_logo_bg` ~line 159; the `ASK_LOGO_BG` record ~line 398-424)
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (~line 87-92)
- Modify: `backend/app/prompts.py` (`V2_BG_INSTRUCTIONS`)
- Test: `backend/tests/test_canvas_steps.py`, `backend/tests/test_v2_e2e.py`

**Interfaces:**
- Consumes: the `canvas_ops` wire shape from Task 2.
- Produces: `Step.ops: Callable[[dict, dict], list[dict]] | None` — `(collected, fields) -> canvas_ops`. Declared on the record; the alternative is an `if step.id is ASK_LOGO_BG` branch in the orchestrator, which is the per-state switch this registry exists to avoid (same reasoning as `Step.prepare`).

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_canvas_steps.py`:

```python
def test_ask_logo_bg_chips_no_longer_ask_the_customer_to_tick():
    step = cs.by_id(S.ASK_LOGO_BG)
    labels = [c.label for c in step.chips]
    assert labels == ["Yes, remove background", "No, it's fine as is"]
    assert "tick" not in step.ask.lower()


def test_yes_emits_an_op_that_flags_the_pending_logo():
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "back", "placed": True}}
    ops = step.ops(c, {"logo_bg": "removed"})
    assert ops == [{"target": {"kind": "pending_logo", "face": "back"},
                    "patch": {"removeBg": True}}]


def test_no_emits_no_op():
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert step.ops(c, {"logo_bg": "none"}) == []


def test_bg_copy_never_promises_processing_or_a_wait():
    # Standing rule: ticking is instant; nothing is matted client-side.
    step = cs.by_id(S.ASK_LOGO_BG)
    blob = (step.ask + " " + (step.instructions or "")).lower()
    for banned in ("wait", "processing", "hang on", "just a moment"):
        assert banned not in blob


def test_bg_still_marks_the_step_answered():
    # pending_logo["bg"] is the done_when marker — the op is an ADDITION to it.
    step = cs.by_id(S.ASK_LOGO_BG)
    c = {"pending_logo": {"face": "front", "placed": True}}
    step.apply(c, {"logo_bg": "removed"}, {})
    assert step.done_when(c) is True
```

Append to `backend/tests/test_v2_e2e.py`:

```python
@pytest.mark.asyncio
async def test_v2_bg_chip_ships_an_op_to_the_canvas(monkeypatch):
    """The chip and the flag are the same act: tapping yes must reach the canvas.
    Before this, 'Yes, I've ticked it' without ticking rendered no knockout."""
    sess = _session(state=S.ASK_LOGO_BG.value, collected={
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "front", "placed": True},
    })
    sb = _FakeSupabase(sess)
    monkeypatch.setattr(o2, "get_supabase", lambda: sb)
    monkeypatch.setattr(o2, "get_store", lambda _id: None)
    out = await o2.handle_message(sess["id"], "Yes, remove background")
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "front"},
         "patch": {"removeBg": True}}
    ]
```

> Reuse the existing `_session` / `_FakeSupabase` fakes already in `test_v2_e2e.py`. If their names differ, match the file — do not add new fakes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_steps.py tests/test_v2_e2e.py -q -p no:warnings`
Expected: FAIL — `'Step' object has no attribute 'ops'`, and the chip labels differ.

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/conversation/canvas_steps.py`, add to the `Step` dataclass (after `prepare`):

```python
    # Canvas mutations this step's ANSWER implies, as fully-resolved canvas_ops
    # (see docs/superpowers/specs/2026-07-17-canvas-led-refine-design.md).
    # (collected, fields) -> list of {"target": …, "patch": …}. Declared on the
    # record for the same reason as `prepare`: the alternative is an
    # `if step.id is ASK_LOGO_BG` branch in the orchestrator.
    ops: Callable[[dict, dict], list[dict]] | None = None
```

Add next to `_apply_logo_bg` (~line 159):

```python
def _ops_logo_bg(c: dict, f: dict) -> list[dict]:
    """Tick the box for the customer.

    The backend has no element id here — `canvas_design` isn't persisted until
    finalize — so the target is the semantic "pending logo": the last unlocked
    image on the face, the same anchor `lockPlaced` leans on.
    """
    if f.get("logo_bg") != "removed":
        return []
    return [{"target": {"kind": "pending_logo",
                        "face": _pending(c).get("face") or "front"},
             "patch": {"removeBg": True}}]
```

Replace the `ASK_LOGO_BG` record's `ask`, `chips`, and add `ops=`:

```python
    Step(
        id=S.ASK_LOGO_BG,
        # "Remove background" is a MARK, not an edit: the op only flags the
        # element (a ✂ badge, `name="export-hide"` so it never bakes into the
        # layout guide). Nothing is matted client-side — `prompt_builder`
        # instructs the image model to knock the background out at render time.
        # So this copy must not promise processing or ask the customer to wait.
        ask="Does your logo have a background that needs removing?",
        # The chip IS the tick (see _ops_logo_bg). Previously this asked the
        # customer to tick it themselves and only recorded their claim —
        # pending_logo["bg"] routes but nothing on the RENDER path reads it, so
        # "Yes, I've ticked it" without ticking silently rendered no knockout.
        chips=(Chip("Yes, remove background", {"logo_bg": "removed"}),
               Chip("No, it's fine as is", {"logo_bg": "none"})),
        slots=("logo_bg",),
        apply=_apply_logo_bg,
        ops=_ops_logo_bg,
        done_when=lambda c: not _logos_open(c) or "bg" in _pending(c),
        # tool="upload" is LOAD-BEARING, not decoration: it keeps v2Editing true
        # on the frontend, so the just-placed logo is NOT locked and stays
        # selectable. The customer no longer NEEDS the toggle (the op ticks it),
        # but it stays reachable as a manual override / untick. The lock fires on
        # ASK_ANOTHER_LOGO instead. See Surface.tsx:111-113 + canvasStore.ts:36.
        tool="upload",
        tip=None,                              # the upload tip is wrong here
        instructions=prompts.V2_BG_INSTRUCTIONS,
        auto_open=None,                        # or the file picker reopens
        show_done=False,
        face_target=True,
    ),
```

In `backend/app/prompts.py`, replace `V2_BG_INSTRUCTIONS`:

```python
# The canvas instruction for ASK_LOGO_BG. Not a V2_TOOL_TIPS entry: those are
# keyed by TOOL, and this step hands over the upload tool only to keep the
# placed logo selectable (see Step.instructions / the lock note on the step) —
# the upload tip's "tap Upload image" would be actively wrong here.
# Must not promise processing or a wait: the mark is instant and the canvas
# does not change. The knockout happens at render.
V2_BG_INSTRUCTIONS = (
    "If it does, I'll mark it and we'll knock the background out when we "
    "render your design — the cap on screen won't change. You can also tick "
    "or untick \"Remove background\" yourself in the toolbar under the cap."
)
```

In `backend/app/services/conversation/orchestrator_v2.py`, after `step.apply(...)` (~line 90), capture the ops:

```python
    collected.pop("_fail_count", None)
    # Filter BEFORE apply, so an effect never sees a field the router rejected.
    fields = v2.merge_fields(step, collected, fields)
    collected.update(fields)
    if step.apply:
        step.apply(collected, fields, session)
    # Canvas mutations this answer implies. Computed from the step just
    # ANSWERED (not the next one), so it must be read before next_step.
    canvas_ops = step.ops(collected, fields) if step.ops else []
```

Then where `data` is built (~line 159, `data = v2.public_data_for(next_, collected)`), add immediately after:

```python
    data = v2.public_data_for(next_, collected)
    if canvas_ops:
        data["canvas_ops"] = canvas_ops
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q -p no:warnings`
Expected: PASS — full suite. `test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable` must still be green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/app/services/conversation/orchestrator_v2.py backend/app/prompts.py backend/tests/test_canvas_steps.py backend/tests/test_v2_e2e.py
git commit -m "fix(canvas-v2): the background-removal chip ticks the box itself

pending_logo[bg] routes (ask_logo_bg's done_when marker) but nothing on the
render path reads it — the knockout comes solely from el.removeBg on the canvas
blob. So 'Yes, I've ticked it' without ticking silently produced no knockout.
The chip now emits a canvas op, making the answer and the flag one act."
```

---

### Task 4: `canvas_edit` — pure op resolution

**Files:**
- Create: `backend/app/services/conversation/canvas_edit.py`
- Test: `backend/tests/test_canvas_edit.py` (create)

**Interfaces:**
- Produces:
  - `inventory(canvas_design: dict) -> list[dict]` — `[{"id", "face", "type", "description"}]`
  - `resolve_ops(raw_ops: list[dict], canvas_design: dict) -> list[dict]` — closed-vocab intent → `canvas_ops` (the Task 2 wire shape). **Pure**: no LLM, no Supabase.
  - `AMOUNTS`, `SCALES`, `ROTATIONS`, `NAMED_COLOURS` (module constants)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_canvas_edit.py`:

```python
"""Op resolution is a pure function of (raw ops, canvas_design) — plain dicts,
no LLM, no Supabase. The model picks intent; this module does the arithmetic."""
import pytest

from app.services.conversation import canvas_edit as ce


def _design():
    return {
        "colourway": None,
        "faces": {
            "front": [
                {"id": "logo1", "type": "image", "x": 0.4, "y": 0.4,
                 "width": 0.2, "height": 0.2, "rotation": 0, "zIndex": 0,
                 "assetUrl": "u.png"},
                {"id": "txt1", "type": "text", "x": 0.1, "y": 0.8,
                 "width": 0.3, "height": 0.1, "rotation": 0, "zIndex": 1,
                 "content": "MadHats", "colour": "#ffffff"},
            ],
            "back": [], "left": [], "right": [],
        },
    }


def test_inventory_lists_every_element_with_its_face():
    inv = ce.inventory(_design())
    assert [(e["id"], e["face"], e["type"]) for e in inv] == [
        ("logo1", "front", "image"), ("txt1", "front", "text")]
    assert "MadHats" in inv[1]["description"]


def test_move_up_subtracts_from_y_and_targets_the_right_face():
    ops = ce.resolve_ops(
        [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "small"}],
        _design())
    assert ops == [{"target": {"kind": "element", "id": "logo1", "face": "front"},
                    "patch": {"y": pytest.approx(0.35)}}]


def test_move_clamps_to_the_stage_and_never_goes_off_canvas():
    ops = ce.resolve_ops(
        [{"op": "move", "element_id": "txt1", "direction": "down", "amount": "large"}],
        _design())
    # y 0.8 + 0.20 = 1.0, but height 0.1 -> clamped to 0.9
    assert ops[0]["patch"]["y"] == pytest.approx(0.9)


def test_resize_bigger_scales_around_the_centre():
    ops = ce.resolve_ops(
        [{"op": "resize", "element_id": "logo1", "direction": "bigger", "amount": "small"}],
        _design())
    p = ops[0]["patch"]
    assert p["width"] == pytest.approx(0.23)      # 0.2 * 1.15
    assert p["x"] == pytest.approx(0.385)         # centre 0.5 held
    assert p["y"] == pytest.approx(0.385)


def test_rotate_accumulates_onto_the_current_rotation():
    ops = ce.resolve_ops(
        [{"op": "rotate", "element_id": "logo1", "direction": "clockwise", "amount": "medium"}],
        _design())
    assert ops[0]["patch"]["rotation"] == pytest.approx(15.0)


def test_recolour_writes_the_field_that_matches_the_element_type():
    ops = ce.resolve_ops(
        [{"op": "recolour", "element_id": "txt1", "colour": "red"}], _design())
    assert ops[0]["patch"] == {"colour": "#dc2626"}


def test_recolour_accepts_a_raw_hex():
    ops = ce.resolve_ops(
        [{"op": "recolour", "element_id": "txt1", "colour": "#123abc"}], _design())
    assert ops[0]["patch"] == {"colour": "#123abc"}


def test_set_text_and_font_and_curve():
    d = _design()
    assert ce.resolve_ops([{"op": "set_text", "element_id": "txt1", "text": "Hi"}], d)[0]["patch"] == {"content": "Hi"}
    assert ce.resolve_ops([{"op": "font", "element_id": "txt1", "font": "Bebas Neue"}], d)[0]["patch"] == {"font": "Bebas Neue"}
    assert ce.resolve_ops([{"op": "curve", "element_id": "txt1", "direction": "up"}], d)[0]["patch"] == {"curve": 40}


def test_delete_emits_a_remove_op():
    ops = ce.resolve_ops([{"op": "delete", "element_id": "txt1"}], _design())
    assert ops == [{"target": {"kind": "element", "id": "txt1", "face": "front"},
                    "remove": True}]


def test_a_hallucinated_element_id_is_dropped():
    # Ids are a closed set we own, so validation is an identity lookup.
    assert ce.resolve_ops(
        [{"op": "move", "element_id": "nope", "direction": "up", "amount": "small"}],
        _design()) == []


def test_an_unknown_op_or_amount_is_dropped_not_guessed():
    d = _design()
    assert ce.resolve_ops([{"op": "explode", "element_id": "logo1"}], d) == []
    assert ce.resolve_ops(
        [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "heaps"}], d) == []


def test_text_ops_are_dropped_for_a_non_text_element():
    assert ce.resolve_ops(
        [{"op": "set_text", "element_id": "logo1", "text": "no"}], _design()) == []


def test_resolve_ops_never_mutates_the_design_it_is_given():
    d = _design()
    ce.resolve_ops([{"op": "move", "element_id": "logo1", "direction": "up", "amount": "large"}], d)
    assert d["faces"]["front"][0]["y"] == 0.4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_edit.py -q -p no:warnings`
Expected: FAIL — `No module named 'app.services.conversation.canvas_edit'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/conversation/canvas_edit.py`:

```python
"""Turn a described change into canvas ops — the arithmetic half.

Split deliberately: `intent_extractor.interpret_canvas_edit` asks Haiku WHAT the
customer wants, from a closed vocabulary, and this module works out the numbers.
The model never emits a coordinate. That extends v2's existing stance — the LLM
reads the customer, it never routes — to: it never computes geometry. Everything
here is a pure function of plain dicts, so it needs no LLM and no Supabase.
"""
from __future__ import annotations

# Normalised (0-1) stage units.
AMOUNTS: dict[str, float] = {"small": 0.05, "medium": 0.10, "large": 0.20}
SCALES: dict[str, float] = {"small": 1.15, "medium": 1.35, "large": 1.70}
ROTATIONS: dict[str, float] = {"small": 5.0, "medium": 15.0, "large": 45.0}
CURVES: dict[str, int] = {"up": 40, "down": -40, "none": 0}

# Small on purpose: an unresolvable colour is DROPPED, not guessed at.
NAMED_COLOURS: dict[str, str] = {
    "white": "#ffffff", "black": "#111827", "red": "#dc2626", "blue": "#2563eb",
    "navy": "#1e3a8a", "green": "#16a34a", "yellow": "#facc15",
    "orange": "#ea580c", "purple": "#9333ea", "pink": "#ec4899",
    "grey": "#6b7280", "gray": "#6b7280",
}

_MOVE = {"up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}
# Which field carries "the colour" depends on the element type.
_COLOUR_FIELD = {"text": "colour", "shape": "fill", "drawing": "stroke"}
_TEXT_ONLY = {"set_text", "font", "curve"}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _describe(el: dict) -> str:
    t = el.get("type")
    if t == "text":
        return f'the text "{el.get("content") or ""}"'
    if t == "image":
        return "the uploaded logo/artwork"
    if t == "shape":
        return f'the {el.get("shapeKind") or "shape"}'
    return "the hand-drawn line"


def inventory(canvas_design: dict) -> list[dict]:
    """Every element the customer can refer to. Ids are a closed set we own, so
    validating the model's choice is an identity lookup."""
    out: list[dict] = []
    for face, els in (canvas_design.get("faces") or {}).items():
        for el in els or []:
            if not el.get("id"):
                continue
            out.append({"id": el["id"], "face": face,
                        "type": el.get("type") or "", "description": _describe(el)})
    return out


def _index(canvas_design: dict) -> dict[str, tuple[str, dict]]:
    idx: dict[str, tuple[str, dict]] = {}
    for face, els in (canvas_design.get("faces") or {}).items():
        for el in els or []:
            if el.get("id"):
                idx[el["id"]] = (face, el)
    return idx


def _colour(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    v = raw.strip().lower()
    if v.startswith("#") and len(v) == 7:
        return v
    return NAMED_COLOURS.get(v)


def _patch_for(op: dict, el: dict) -> dict | None:
    """The patch one op implies, or None to drop it. Never mutates `el`."""
    kind = op.get("op")
    etype = el.get("type")

    if kind in _TEXT_ONLY and etype != "text":
        return None

    if kind == "move":
        step = AMOUNTS.get(op.get("amount") or "")
        vec = _MOVE.get(op.get("direction") or "")
        if step is None or vec is None:
            return None
        w = float(el.get("width") or 0.0)
        h = float(el.get("height") or 0.0)
        patch: dict = {}
        if vec[0]:
            patch["x"] = _clamp(float(el.get("x") or 0.0) + vec[0] * step, 0.0, max(0.0, 1.0 - w))
        if vec[1]:
            patch["y"] = _clamp(float(el.get("y") or 0.0) + vec[1] * step, 0.0, max(0.0, 1.0 - h))
        return patch

    if kind == "resize":
        scale = SCALES.get(op.get("amount") or "")
        direction = op.get("direction")
        if scale is None or direction not in ("bigger", "smaller"):
            return None
        if direction == "smaller":
            scale = 1.0 / scale
        w, h = float(el.get("width") or 0.0), float(el.get("height") or 0.0)
        cx = float(el.get("x") or 0.0) + w / 2
        cy = float(el.get("y") or 0.0) + h / 2
        nw, nh = _clamp(w * scale, 0.02, 1.0), _clamp(h * scale, 0.02, 1.0)
        return {"width": nw, "height": nh,
                "x": _clamp(cx - nw / 2, 0.0, max(0.0, 1.0 - nw)),
                "y": _clamp(cy - nh / 2, 0.0, max(0.0, 1.0 - nh))}

    if kind == "rotate":
        deg = ROTATIONS.get(op.get("amount") or "")
        direction = op.get("direction")
        if deg is None or direction not in ("clockwise", "anticlockwise"):
            return None
        if direction == "anticlockwise":
            deg = -deg
        return {"rotation": (float(el.get("rotation") or 0.0) + deg) % 360}

    if kind == "recolour":
        hexv = _colour(op.get("colour"))
        field = _COLOUR_FIELD.get(etype or "")
        if hexv is None or field is None:
            return None
        return {field: hexv}

    if kind == "set_text":
        text = (op.get("text") or "").strip()
        return {"content": text[:120]} if text else None

    if kind == "font":
        font = (op.get("font") or "").strip()
        return {"font": font[:60]} if font else None

    if kind == "curve":
        curve = CURVES.get(op.get("direction") or "")
        return None if curve is None else {"curve": curve}

    return None


def resolve_ops(raw_ops: list[dict], canvas_design: dict) -> list[dict]:
    """Closed-vocabulary intent -> canvas_ops. Anything unrecognised is dropped,
    never guessed at: a wrong nudge lands on a design the customer approved."""
    idx = _index(canvas_design)
    out: list[dict] = []
    for op in raw_ops or []:
        if not isinstance(op, dict):
            continue
        found = idx.get(op.get("element_id") or "")
        if not found:
            continue                       # hallucinated id
        face, el = found
        target = {"kind": "element", "id": el["id"], "face": face}
        if op.get("op") == "delete":
            out.append({"target": target, "remove": True})
            continue
        patch = _patch_for(op, el)
        if patch:
            out.append({"target": target, "patch": patch})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_edit.py -q -p no:warnings`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/canvas_edit.py backend/tests/test_canvas_edit.py
git commit -m "feat(canvas): pure resolver turning closed-vocab edit intent into canvas ops"
```

---

### Task 5: Reading the customer's change

**Files:**
- Modify: `backend/app/services/conversation/intent_extractor.py` (add at the end, next to `interpret_turn_v2`)
- Modify: `backend/app/prompts.py` (add `CANVAS_EDIT_PROMPT`)
- Test: `backend/tests/test_canvas_edit.py`

**Interfaces:**
- Consumes: `canvas_edit.inventory` (Task 4).
- Produces: `async interpret_canvas_edit(message: str, inventory: list[dict]) -> list[dict]` — raw closed-vocab ops. Raises `LLMUnavailable` (the existing class) when Haiku is unreachable. Returns `[]` when nothing is expressible on the canvas.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_canvas_edit.py`:

```python
from app.services.conversation import intent_extractor as ie


@pytest.mark.asyncio
async def test_interpret_returns_closed_vocab_ops(monkeypatch):
    async def fake(_prompt, **kw):
        return '{"ops": [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "small"}]}'
    monkeypatch.setattr(ie, "_complete", fake)
    monkeypatch.setattr(ie, "_has_llm", True)
    ops = await ie.interpret_canvas_edit("move the logo up a bit", ce.inventory(_design()))
    assert ops == [{"op": "move", "element_id": "logo1", "direction": "up", "amount": "small"}]


@pytest.mark.asyncio
async def test_interpret_returns_empty_for_a_render_level_request(monkeypatch):
    async def fake(_prompt, **kw):
        return '{"ops": []}'
    monkeypatch.setattr(ie, "_complete", fake)
    monkeypatch.setattr(ie, "_has_llm", True)
    assert await ie.interpret_canvas_edit("make the embroidery thicker",
                                          ce.inventory(_design())) == []


@pytest.mark.asyncio
async def test_interpret_raises_when_haiku_is_down(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", False)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_canvas_edit("move it up", ce.inventory(_design()))


@pytest.mark.asyncio
async def test_interpret_never_logs_the_customers_words(monkeypatch, caplog):
    async def boom(_prompt, **kw):
        raise RuntimeError("upstream 500")
    monkeypatch.setattr(ie, "_complete", boom)
    monkeypatch.setattr(ie, "_has_llm", True)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_canvas_edit("move my secret text SHIBBOLETH up",
                                       ce.inventory(_design()))
    assert "SHIBBOLETH" not in caplog.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_edit.py -q -p no:warnings -k interpret`
Expected: FAIL — `module 'app.services.conversation.intent_extractor' has no attribute 'interpret_canvas_edit'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/prompts.py`, add next to the other v2 prompts:

```python
# Refine on the canvas: read the customer's change into a CLOSED vocabulary.
# The model never emits a coordinate — canvas_edit.resolve_ops does the maths.
# An empty list is a real answer: it means "the canvas can't express this",
# which routes to the refuse path rather than a render.
CANVAS_EDIT_PROMPT = """The customer has a cap design and wants to change it.
Here is every element currently on the design:

{inventory}

The customer says: "{message}"

Return JSON: {{"ops": [...]}} — one op per change they asked for.
Each op MUST use an `element_id` from the list above. Never invent an id.

Allowed ops (use EXACTLY these shapes, no other fields, no numbers):
- {{"op": "move", "element_id": "…", "direction": "up|down|left|right", "amount": "small|medium|large"}}
- {{"op": "resize", "element_id": "…", "direction": "bigger|smaller", "amount": "small|medium|large"}}
- {{"op": "rotate", "element_id": "…", "direction": "clockwise|anticlockwise", "amount": "small|medium|large"}}
- {{"op": "recolour", "element_id": "…", "colour": "a plain colour name or #rrggbb"}}
- {{"op": "font", "element_id": "…", "font": "font family name"}}
- {{"op": "curve", "element_id": "…", "direction": "up|down|none"}}
- {{"op": "set_text", "element_id": "…", "text": "the new wording"}}
- {{"op": "delete", "element_id": "…"}}

Return {{"ops": []}} if they are asking for something the LAYOUT cannot express —
how the decoration is made or finished ("thicker embroidery", "make it pop",
"less shiny", "different material"), or anything not about the elements listed.
Do NOT force an unrelated request into an op.

JSON only."""
```

In `backend/app/services/conversation/intent_extractor.py`, add at the end:

```python
async def interpret_canvas_edit(message: str, inventory: list[dict]) -> list[dict]:
    """Raw closed-vocabulary ops for one described change.

    Raises LLMUnavailable rather than guessing — geometry is exactly where a
    wrong guess wrecks a design the customer already approved. `[]` is a real
    answer meaning "not expressible on the canvas" (the refuse path).
    """
    if not _has_llm:
        raise LLMUnavailable("no anthropic api key")
    lines = "\n".join(
        f"- id={e['id']} ({e['face']} face): {e['description']}" for e in inventory
    ) or "(nothing on the design)"
    prompt = prompts.CANVAS_EDIT_PROMPT.format(inventory=lines, message=message)
    try:
        raw = await _complete(prompt, max_tokens=400)
    except Exception as exc:  # noqa: BLE001 — any SDK error is "unavailable"
        # err=type(exc).__name__, not str(exc): the prompt carries the
        # customer's own words and some SDK errors stringify request content.
        log.warning("canvas_edit_interpret_failed", err=type(exc).__name__)
        raise LLMUnavailable(str(exc)) from exc
    ops = _parse_json(raw).get("ops")
    return ops if isinstance(ops, list) else []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_edit.py -q -p no:warnings`
Expected: PASS (19 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/intent_extractor.py backend/app/prompts.py backend/tests/test_canvas_edit.py
git commit -m "feat(canvas): read a described change into closed-vocab ops, or refuse"
```

---

### Task 6: Wire the describe branch to the canvas

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (add `CONFIRM_CANVAS_EDIT` to the enum ~line 48; routing ~line 265)
- Modify: `backend/app/services/conversation/goal_planner.py` (`GATE_STATES` ~line 17-47)
- Modify: `backend/app/services/conversation/orchestrator.py` (`handle_message` refine dispatch ~line 372-377; `_public_data` ~line 1140-1200)
- Test: `backend/tests/test_canvas_refine.py` (create)

**CRITICAL — read before writing code.** `_route` (`orchestrator.py:765-772`)
only consults `advance_state` for states in `goal_planner.GATE_STATES`;
everything else is routed by `goal_planner.next_goal`. For a canvas session
`_canvas_next_goal` walks a FORWARD questionnaire that is already complete
post-design, so it answers `GENERATING` — a **fresh** generation, which burns
the daily design cap instead of regenerating. A new state that is not in
`GATE_STATES` is therefore silently mis-routed. `goal_planner.py:27-34` records
this exact trap biting `ASK_CHANGE_METHOD`. `CONFIRM_CANVAS_EDIT` must be added
to `GATE_STATES`, and the test below pins it.

**Interfaces:**
- Consumes: `canvas_edit.inventory`, `canvas_edit.resolve_ops` (Task 4); `ie.interpret_canvas_edit`, `ie.LLMUnavailable` (Task 5).
- Produces: `ConversationState.CONFIRM_CANVAS_EDIT = "confirm_canvas_edit"`; `async _apply_canvas_edit(session, collected, message) -> list[dict]` in `orchestrator.py` — returns canvas_ops and sets `collected["canvas_edit_ops"]` / `collected["canvas_edit_refused"]`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_canvas_refine.py`:

```python
"""The describe branch edits the canvas instead of paying for a render.
Canvas-only: session/blank flows keep change_request -> regenerate."""
import pytest

from app.services.conversation import orchestrator as o
from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation.state_machine import advance_state


def _design():
    return {"colourway": None, "faces": {
        "front": [{"id": "logo1", "type": "image", "x": 0.4, "y": 0.4,
                   "width": 0.2, "height": 0.2, "rotation": 0, "zIndex": 0}],
        "back": [], "left": [], "right": []}}


def _session(collected=None):
    return {"id": "s1", "flow_mode": "canvas", "canvas_design": _design(),
            "collected": collected or {"flow_mode": "canvas"}}


@pytest.mark.asyncio
async def test_an_expressible_change_produces_ops_and_asks_to_confirm(monkeypatch):
    async def fake(_msg, _inv):
        return [{"op": "resize", "element_id": "logo1", "direction": "smaller", "amount": "small"}]
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", fake)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "the logo's a bit big")
    assert ops and ops[0]["target"]["id"] == "logo1"
    assert c["canvas_edit_ops"] is True
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.CONFIRM_CANVAS_EDIT


@pytest.mark.asyncio
async def test_a_render_level_change_is_refused_and_noted_for_the_team(monkeypatch):
    async def fake(_msg, _inv):
        return []
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", fake)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "make the embroidery thicker")
    assert ops == []
    assert c["canvas_edit_refused"] is True
    assert any("embroidery thicker" in n for n in c["brief_notes"])
    # Refused changes never render: the customer stays where they were.
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.OFFER_REFINE


@pytest.mark.asyncio
async def test_an_outage_stalls_rather_than_guessing_geometry(monkeypatch):
    async def boom(_msg, _inv):
        raise o.ie.LLMUnavailable("down")
    monkeypatch.setattr(o.ie, "interpret_canvas_edit", boom)
    c = {"flow_mode": "canvas"}
    ops = await o._apply_canvas_edit(_session(c), c, "move it up")
    assert ops == []
    assert c["canvas_edit_stalled"] is True
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.DESCRIBE_CHANGES


def test_confirm_routes_to_regeneration_or_back_to_describe():
    assert advance_state(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas", "edit_confirmed": True}) is S.REGENERATING
    assert advance_state(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas", "edit_confirmed": False}) is S.DESCRIBE_CHANGES


def test_a_non_canvas_session_still_uses_the_old_describe_route():
    # session/blank flows must be untouched: change_request -> regenerate.
    c = {"flow_mode": "session", "refine_followups": []}
    assert advance_state(S.DESCRIBE_CHANGES, c) is S.REFINE_CONFIRM


def test_confirm_offers_the_two_chips():
    d = o._public_data(S.CONFIRM_CANVAS_EDIT, {"flow_mode": "canvas"})
    assert d["options"] == ["Looks right", "Not quite"]


def test_confirm_is_a_gate_state_so_the_goal_planner_cannot_hijack_it():
    """_route sends any non-GATE_STATE to goal_planner.next_goal, which for a
    finished canvas session answers GENERATING — a FRESH generation that burns
    the daily design cap. goal_planner.py:27-34 records this exact trap biting
    ASK_CHANGE_METHOD."""
    from app.services.conversation import goal_planner
    assert S.CONFIRM_CANVAS_EDIT in goal_planner.GATE_STATES


def test_route_sends_a_confirmed_edit_to_regeneration_not_generation():
    # The end-to-end guarantee the gate exists for, through the real router.
    c = {"flow_mode": "canvas", "edit_confirmed": True, "name": "Sam",
         "canvas_finalized": True, "decoration_done": True, "notes_done": True}
    assert o._route(S.CONFIRM_CANVAS_EDIT, c, 0) is S.REGENERATING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_refine.py -q -p no:warnings`
Expected: FAIL — `type object 'ConversationState' has no attribute 'CONFIRM_CANVAS_EDIT'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/conversation/state_machine.py`, add to the enum next to `ASK_CHANGE_METHOD`:

```python
    CONFIRM_CANVAS_EDIT = "confirm_canvas_edit"   # canvas refine: ops applied, awaiting yes/no
```

Replace the `DESCRIBE_CHANGES` branch in `advance_state` (~line 265):

```python
    if current is S.DESCRIBE_CHANGES:
        # Canvas sessions edit the CANVAS, not the prompt: the change is applied
        # to the design on screen and confirmed before a render is spent. A
        # described change never becomes a change_request for these sessions.
        if collected.get("flow_mode") == "canvas":
            if collected.get("canvas_edit_stalled"):
                return S.DESCRIBE_CHANGES     # Haiku down — ask again, guess nothing
            if collected.get("canvas_edit_ops"):
                return S.CONFIRM_CANVAS_EDIT
            return S.OFFER_REFINE             # refused: noted for the team, no render
        if collected.get("pending_element"):
            return S.ELEMENT_DEEPDIVE
        return S.REFINE_FOLLOWUP if (collected.get("refine_followups") or []) else S.REFINE_CONFIRM

    if current is S.CONFIRM_CANVAS_EDIT:
        return S.REGENERATING if collected.get("edit_confirmed") else S.DESCRIBE_CHANGES
```

In `backend/app/services/conversation/goal_planner.py`, add to `GATE_STATES`
next to `ASK_CHANGE_METHOD` (~line 34):

```python
        # Confirming a canvas edit ("Looks right") — resolved by advance_state.
        # It MUST be a gate: the planner only knows the forward questionnaire,
        # which is already complete post-design, so it would answer GENERATING —
        # a fresh generation burning the daily cap instead of a regeneration.
        # Same trap as ASK_CHANGE_METHOD above.
        S.CONFIRM_CANVAS_EDIT,
```

In `backend/app/services/conversation/orchestrator.py`, add next to `_apply_refine` (~line 200):

```python
async def _apply_canvas_edit(session: dict, collected: dict, message: str) -> list[dict]:
    """Apply a described change to the CANVAS rather than to the prompt.

    Canvas sessions only. Returns fully-resolved canvas_ops for the frontend and
    records which of the three outcomes happened, which is what advance_state
    routes on:
      - ops        -> CONFIRM_CANVAS_EDIT (free; no render until they say yes)
      - refused    -> OFFER_REFINE, noted to brief_notes for the team
      - stalled    -> DESCRIBE_CHANGES (Haiku down; never guess geometry)
    """
    from app.services.conversation import canvas_edit as ce

    text = (message or "").strip()
    for k in ("canvas_edit_ops", "canvas_edit_refused", "canvas_edit_stalled"):
        collected.pop(k, None)
    design = session.get("canvas_design") or {}
    try:
        raw = await ie.interpret_canvas_edit(text, ce.inventory(design))
    except ie.LLMUnavailable:
        collected["canvas_edit_stalled"] = True
        return []
    ops = ce.resolve_ops(raw, design)
    if not ops:
        # Render-level ("thicker embroidery") or unreadable: the team sees it at
        # quote time rather than it evaporating. No PII — this is design text.
        collected.setdefault("brief_notes", []).append(f"Refine request: {text[:300]}")
        collected["canvas_edit_refused"] = True
        return []
    collected["canvas_edit_ops"] = True
    return ops
```

In `handle_message`, initialise `canvas_ops` **before** the refine block (it must
still be in scope where `data` is built, ~line 585):

```python
    canvas_ops: list[dict] = []
```

Then gate the existing refine dispatch. The current code (~line 372-377) reads
exactly:

```python
        # Refine capture runs BEFORE the brief-merge so an "add element" seeds a
        # pending_element and doesn't ALSO leak into the flat design brief.
        if current in (
            ConversationState.DESCRIBE_CHANGES,
            ConversationState.REFINE_FOLLOWUP,
            ConversationState.REFINE_CONFIRM,
        ):
            await _apply_refine(current, collected, message)
        elif current is ConversationState.CONFIRM_BRIEF:
```

Add one leg **in front of it**, leaving the existing legs byte-identical so
non-canvas behaviour cannot drift (note the 8-space indent — this sits inside an
enclosing block):

```python
        # Refine capture runs BEFORE the brief-merge so an "add element" seeds a
        # pending_element and doesn't ALSO leak into the flat design brief.
        if (current is ConversationState.DESCRIBE_CHANGES
                and collected.get("flow_mode") == "canvas"):
            # Canvas sessions edit the canvas, not the prompt — so this never
            # touches refine_details, and change_request stays None for them.
            canvas_ops = await _apply_canvas_edit(session, collected, message)
        elif current in (
            ConversationState.DESCRIBE_CHANGES,
            ConversationState.REFINE_FOLLOWUP,
            ConversationState.REFINE_CONFIRM,
        ):
            await _apply_refine(current, collected, message)
        elif current is ConversationState.CONFIRM_BRIEF:
```

Capture the confirm answer — add to the field-capture block next to the other
`elif state is S.…` confirmations (~line 952):

```python
    elif state is S.CONFIRM_CANVAS_EDIT:
        # Chip labels are "Looks right" / "Not quite" (see _public_data).
        collected["edit_confirmed"] = "looks right" in low or is_affirmative(message)
```

Then where `data = _public_data(new_state, collected)` is built for the reply
(~line 585), merge the ops in:

```python
    data = _public_data(new_state, collected)
    if canvas_ops:
        data["canvas_ops"] = canvas_ops
```

Add to `_public_data` next to the `ASK_CHANGE_METHOD` entry (~line 1192):

```python
    if state is S.CONFIRM_CANVAS_EDIT:
        return {"options": ["Looks right", "Not quite"]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q -p no:warnings`
Expected: PASS — full suite.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/app/services/conversation/orchestrator.py backend/tests/test_canvas_refine.py
git commit -m "feat(canvas): a described change edits the canvas, not the prompt

Canvas sessions only. Expressible changes apply to the design on screen and wait
for confirmation; render-level requests are refused and noted to brief_notes; an
interpreter outage stalls rather than guessing geometry."
```

---

### Task 7: Confirm renders, via the existing rework path

`Surface`'s finalize effect guards on a `finalizeStarted` ref that is **never re-armed** (`Surface.tsx:118-127`). A v2 canvas session already fired `trigger_finalize` once at `FINALIZE_CANVAS`, so a second one would be silently swallowed. This task re-arms it.

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (the `CANVAS_DESIGN`/rework block ~line 447-452)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx` (~line 118-127)
- Test: `backend/tests/test_canvas_refine.py`, `frontend/src/__tests__/surfaceDirective.test.tsx`

**Interfaces:**
- Consumes: `CONFIRM_CANVAS_EDIT` + `edit_confirmed` (Task 6).
- Produces: `data.trigger_finalize` on the `CONFIRM_CANVAS_EDIT → REGENERATING` turn, with `collected["reworking"] = True` so `sessions.py:251-263` re-renders instead of re-running the outro.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_canvas_refine.py`:

```python
def test_confirming_reuses_the_rework_path_rather_than_a_parallel_one():
    # reworking=True is what makes canvas-finalize (sessions.py) re-render and
    # skip the decoration/notes outro. trigger_finalize makes the frontend
    # re-flatten the EDITED canvas first, so the layout guide matches.
    c = {"flow_mode": "canvas", "reworking": True}
    d = o._public_data(S.REGENERATING, c)
    assert d.get("trigger_finalize") is True
    assert d.get("trigger_regeneration") is not True   # finalize drives it, not this


def test_a_plain_regeneration_still_triggers_the_render_directly():
    # Non-rework REGENERATING (the v1 describe->regen path) is unchanged.
    d = o._public_data(S.REGENERATING, {"flow_mode": "session"})
    assert d.get("trigger_regeneration") is True
    assert d.get("trigger_finalize") is not True


def test_confirming_marks_the_session_as_reworking():
    c = {"flow_mode": "canvas", "edit_confirmed": True}
    o._mark_canvas_rework(S.CONFIRM_CANVAS_EDIT, S.REGENERATING, c)
    assert c["reworking"] is True
    assert c["canvas_finalized"] is False
```

Append to `frontend/src/__tests__/surfaceDirective.test.tsx`:

```tsx
test('a second trigger_finalize re-arms and fires again', async () => {
  // The refine confirm step fires trigger_finalize a SECOND time. The ref guard
  // was never re-armed, so the re-render was silently swallowed.
  const doRender = vi.fn()
  const { rerender } = renderSurface({ triggerFinalize: true, doRender })
  expect(doRender).toHaveBeenCalledTimes(1)
  rerender({ triggerFinalize: false, doRender })   // intervening turns
  rerender({ triggerFinalize: true, doRender })    // confirm
  expect(doRender).toHaveBeenCalledTimes(2)
})
```

> Match the existing harness in `surfaceDirective.test.tsx` — if it renders
> `<Surface/>` against a mocked `useChatStore`, drive `triggerFinalize` through
> that mock rather than adding a `renderSurface` helper.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_canvas_refine.py -q -p no:warnings -k rework`
Expected: FAIL — `module 'orchestrator' has no attribute '_mark_canvas_rework'`

- [ ] **Step 3: Write minimal implementation**

In `backend/app/services/conversation/orchestrator.py`, replace the existing
`CANVAS_DESIGN`/rework block (~line 447-452) with a named helper covering both
ways into a rework:

```python
def _mark_canvas_rework(current: ConversationState, new_state: ConversationState,
                        collected: dict) -> None:
    """Reopen the canvas for a re-render, from either refine route.

    "Rework on the canvas" (ASK_CHANGE_METHOD -> CANVAS_DESIGN) hands the canvas
    back to the customer; confirming a described edit (CONFIRM_CANVAS_EDIT ->
    REGENERATING) re-renders the canvas Ricardo just edited. Both need
    canvas-finalize to re-render instead of re-running the outro questions,
    which is what `reworking` means to sessions.py.
    """
    reopened = (new_state is ConversationState.CANVAS_DESIGN
                and current is ConversationState.ASK_CHANGE_METHOD)
    confirmed = (current is ConversationState.CONFIRM_CANVAS_EDIT
                 and new_state is ConversationState.REGENERATING)
    if reopened or confirmed:
        collected["canvas_finalized"] = False
        collected["reworking"] = True
```

and call it where the old inline block was:

```python
        _mark_canvas_rework(current, new_state, collected)
```

In `_public_data`, replace the `REGENERATING` entry:

```python
    if state is S.REGENERATING:
        # A confirmed canvas edit must re-FLATTEN first: the layout guide has to
        # match the design Ricardo just changed. doRender -> canvas-finalize ->
        # sessions.py sees `reworking` and returns trigger_regeneration itself.
        if collected.get("reworking"):
            return {"trigger_finalize": True}
        return {"trigger_regeneration": True}
```

In `frontend/src/components/DesignStudio/Surface.tsx`, re-arm the guard:

```tsx
  const finalizeStarted = useRef(false)
  useEffect(() => {
    if (!triggerFinalize) {
      // Re-arm: the refine confirm step fires trigger_finalize a SECOND time.
      // Without this the ref stays true from the first finalize and the
      // re-render is silently swallowed.
      finalizeStarted.current = false
      return
    }
    if (!finalizeStarted.current) {
      finalizeStarted.current = true
      lockAll()
      void doRender()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [triggerFinalize])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q -p no:warnings`
Then: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx src/__tests__/canvasOps.test.ts`
Expected: PASS both.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py frontend/src/components/DesignStudio/Surface.tsx backend/tests/test_canvas_refine.py frontend/src/__tests__/surfaceDirective.test.tsx
git commit -m "feat(canvas): confirming an edit re-renders through the existing rework path

Re-arms Surface's finalize guard, which was never reset — the second
trigger_finalize a refine needs was silently swallowed."
```

---

### Task 8: Verify end-to-end in the browser, then document

The whole point is a customer-visible loop; tests can't see a Konva stage move.

**Files:**
- Modify: `CLAUDE.md` (the canvas bullet in §13 "Current implementation state")

- [ ] **Step 1: Drive the real flow**

```bash
docker compose up -d --force-recreate backend frontend   # .env: CANVAS_ORCHESTRATOR_V2=true
```

Open `http://localhost:5173/?product_id=<id>` and walk it:
1. Answer to `ask_logo_bg`, upload a logo, tap **"Yes, remove background"**.
   Confirm the ✂ badge appears **without** touching the toolbar.
2. Finish the flow to a render and delivery.
3. At `OFFER_REFINE` → "Request changes" → "Describe the change here".
4. Type *"move the logo up a bit and make it smaller"*. Confirm the logo visibly
   moves and shrinks on the canvas, and the chat asks Looks right / Not quite.
5. Type *"make the embroidery thicker"*. Confirm it is refused, not rendered.
6. Tap **"Looks right"**. Confirm the canvas re-flattens and a new render arrives.

- [ ] **Step 2: Record what you observed**

Note in the commit message which of the six steps you actually saw work. If a
step failed, STOP and fix it — do not document it as working.

- [ ] **Step 3: Update CLAUDE.md**

Extend the canvas bullet in §13 with:

```markdown
- **Canvas-led refine + self-ticking background removal (2026-07-17):** the
  backend can mutate the canvas via `data.canvas_ops` — fully-resolved flat
  patches (`{target, patch|remove}`), applied in `chatStore.sendMessage`'s
  response handler via `lib/canvasOps.ts`, **never in a React effect** (an
  effect fires on change, which re-applies on resume and re-flags the wrong
  logo on a later loop pass) and never on `hydrate`. Two target kinds:
  `{kind:"element", id, face}` (refine — ids come from the persisted
  `canvas_design`) and `{kind:"pending_logo", face}` (v2 background removal —
  the backend has NO id there, since `canvas_design` is only written at
  finalize, so the frontend resolves "last unlocked image on that face", the
  same anchor `lockPlaced` uses). `canvasStore` gained face-aware
  `patchElement`/`removeElementOn`/`patchPendingLogo` because
  `updateElement` only ever sees `activeFace`.
  **Background removal now ticks itself** (`canvas_steps._ops_logo_bg`): the
  chip is "Yes, remove background" and emits the op. This fixed a live bug —
  `pending_logo["bg"]` routes (it is `ask_logo_bg`'s `done_when` marker, so do
  NOT delete it) but nothing on the RENDER path reads it; the knockout comes
  solely from `el.removeBg` on the canvas blob, so "Yes, I've ticked it"
  without ticking silently rendered no knockout. `tool="upload"` still stays —
  the toggle remains as a manual override. Copy still must never promise
  processing or a wait.
  **A described change now edits the canvas, not the prompt**
  (`services/conversation/canvas_edit.py` + `ie.interpret_canvas_edit`):
  `OFFER_REFINE` → "Describe the change here" → Haiku returns a **closed
  vocabulary** (`move/resize/rotate/recolour/font/curve/set_text/delete`) and
  **never a number** — `canvas_edit.resolve_ops` does the arithmetic and
  clamping, a pure function over plain dicts (v2's "the LLM reads the customer,
  it never routes" extended to "it never computes geometry"). Element ids are
  validated against an inventory built from `canvas_design`, so a hallucinated
  id is dropped. Ops → `CONFIRM_CANVAS_EDIT` (Looks right / Not quite);
  iteration before confirming is free and burns no edit cap. Render-level
  requests ("thicker embroidery") return `[]` → refused, appended to
  `brief_notes` for the team, back to `OFFER_REFINE` — **`change_request` is
  retired for canvas sessions**; non-canvas (`session`/`blank`) refine keeps it
  unchanged. `LLMUnavailable` stalls rather than guessing. Confirming reuses the
  existing rework path (`reworking=True` → `trigger_finalize` → `doRender` →
  `sessions.py:251-263` → `REGENERATING`); `Surface`'s `finalizeStarted` ref is
  now **re-armed when `triggerFinalize` goes false**, without which the second
  finalize a refine needs was silently swallowed.
  Spec/plan: `docs/superpowers/{specs,plans}/2026-07-17-canvas-led-refine*`.
```

- [ ] **Step 4: Run both suites once more**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q -p no:warnings`
Run: `cd frontend && npx vitest run src/__tests__/canvasOps.test.ts src/__tests__/canvasStoreOps.test.ts src/__tests__/chatStore.test.ts src/__tests__/surfaceDirective.test.tsx src/__tests__/canvasStoreLock.test.ts`
Expected: PASS both.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: canvas-led refine + self-ticking background removal"
```

---

## Known gaps (deliberately not addressed)

Pre-existing and orthogonal — recorded in the spec's scope fence:

- **429 `edit_limit` is swallowed** (`ChatColumn.tsx:306-313`): a rejected regeneration is treated identically to success, so a capped edit lands back at `OFFER_REFINE` as if a render happened.
- **`wants_changes` is substring keyword matching** (`orchestrator.py:952`): "can you make it pop more?" registers as neither a change request nor a refusal and falls through to `QUOTE_REQUESTED`. It only works because the chips are worded to match.
- **`canvas_design` is only persisted at finalize** — no mid-design autosave.
- **`state_machine.py`'s `OFFER_REFINE` branch is a dead duplicate** of the live one in `orchestrator.py:432-443` and lacks its `_can_edit` gate.

---

### Task 9: Edit against the live canvas (added from the final review)

See `.superpowers/sdd/task-9-brief.md`. Root cause: `_apply_canvas_edit` resolves ops against the persisted `canvas_design` (written only at finalize), so the "Not quite" iterate loop recomputes relative nudges from the original geometry and the second nudge no-ops. Fix: the frontend sends its live `canvas_design` on a describe turn; `chat.py` adopts it (scoped to `describe_changes` + canvas) before dispatch — also fixing the ops-ephemeral reload bug.
