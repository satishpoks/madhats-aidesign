# v2 Canvas Back — element-aware restart + single-step lock — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the v2 canvas `↩ Back` button remove-and-restart the in-progress element when the customer is mid-element, and allow only one Back per forward turn.

**Architecture:** Backend owns the data work and the "which steps are mid-element" truth (`orchestrator_v2` / `state_machine_v2`); the frontend owns the confirm dialog and the canvas element removal. A per-turn `_back_used` flag enforces the single-step lock. Mid-element Back clears the element's slots, emits a `canvas_ops` remove, and re-asks the element from its first step.

**Tech Stack:** Python 3.12 / FastAPI (backend); React 18 / Zustand / TypeScript (frontend); pytest; vitest.

## Global Constraints

- v2 canvas flow only: changes apply when `settings.canvas_orchestrator_v2` is on **and** `flow_mode == "canvas"`. Never touch v1 (`orchestrator.py`) or non-canvas flows — they never emit `can_go_back`.
- Run backend tests with the flag forced off so the repo `.env` default doesn't skew unrelated tests: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q <path>`.
- No `browser confirm()` — blocking dialogs are banned. The confirm is inline chat UI.
- Internal bookkeeping keys are `_`-prefixed and MUST NOT be in `WRITABLE_SLOTS` (the interpreter can't write them) and MUST NOT reach an LLM context.
- The element-adjust step set is exactly `{LOGO_ADJUST, ASK_LOGO_BG, DECOR_ADJUST}` — the steps where an element is on the canvas. `ASK_LOGO_PLACEMENT` / `ASK_DECOR_PLACEMENT` are pre-placement and keep the normal rewind.
- Decor restart re-asks `ASK_ADD_DECOR` (re-pick text/shape); logo restart re-asks `ASK_LOGO_PLACEMENT`.

---

### Task 1: Backend — element-adjust step set, gated `can_go_back`, `back_removes_element`, and lock-clear

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (add `_ELEMENT_ADJUST_STEPS` near the top-level constants, ~line 27–34)
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (`_public` ~line 34–43; `handle_message` insert after the empty-turn guard ~line 94)
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Produces: `state_machine_v2._ELEMENT_ADJUST_STEPS: frozenset[S]` = `{S.LOGO_ADJUST, S.ASK_LOGO_BG, S.DECOR_ADJUST}`.
- Produces: `orchestrator_v2._public(step, collected, config)` now returns `data["can_go_back"]` gated on `not collected.get("_back_used")` and `data["back_removes_element"]: bool`.
- Consumes (Task 2): `handle_back` will set `collected["_back_used"] = True`; this task makes `_public` honour it and `handle_message` clear it.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_orchestrator_v2.py` (near the `handle_back` block, after line 545):

```python
# --- Task 1: element-adjust set + back lock -----------------------------------

def test_public_flags_back_removes_element_only_mid_element():
    from app.services.conversation import state_machine_v2 as v2
    base = {"name": "Sam", "intro_ack": True, "has_logo": True,
            "pending_logo": {"face": "front", "placed": True}, "email_captured": True}
    d_adjust = o2._public(cs.by_id(S.ASK_LOGO_BG), dict(base))
    assert d_adjust["can_go_back"] is True
    assert d_adjust["back_removes_element"] is True

    # A non-element step that can still go back keeps the flag false.
    d_plain = o2._public(cs.by_id(S.ASK_QUANTITY),
                         {"name": "Sam", "intro_ack": True, "decor_placed": True,
                          "logos_done": True, "pending_logo": None,
                          "decor_done": True, "email_captured": True})
    assert d_plain["can_go_back"] is True
    assert d_plain["back_removes_element"] is False


def test_public_can_go_back_is_suppressed_while_back_used():
    base = {"name": "Sam", "intro_ack": True, "has_logo": True,
            "pending_logo": {"face": "front", "placed": True}, "email_captured": True,
            "_back_used": True}
    d = o2._public(cs.by_id(S.ASK_LOGO_BG), dict(base))
    assert d["can_go_back"] is False
    assert d["back_removes_element"] is False   # gated on can_go_back too


@pytest.mark.asyncio
async def test_forward_turn_clears_the_back_lock(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "has_logo": True,
                                     "_back_used": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)                        # chip tap needs no model
    await o2.handle_message("s1", "Yes, another logo")
    assert "_back_used" not in store["session"]["collected"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -k "back_removes_element or back_lock or clears_the_back_lock" -v`
Expected: FAIL — `back_removes_element` KeyError / `can_go_back` still True with `_back_used`.

- [ ] **Step 3: Add the element-adjust set in `state_machine_v2.py`**

After the existing `_TERMINAL_FLAGS` constant (~line 33), add:

```python
# The steps where an element is actually ON the canvas being adjusted. Back at
# one of these means "remove this element and start it over" (a UI-confirmed
# gesture), not the per-slot rewind every other step uses. The placement steps
# (ASK_LOGO_PLACEMENT / ASK_DECOR_PLACEMENT) are pre-placement — nothing on the
# canvas yet — so they keep the normal rewind.
_ELEMENT_ADJUST_STEPS: frozenset[S] = frozenset(
    {S.LOGO_ADJUST, S.ASK_LOGO_BG, S.DECOR_ADJUST}
)
```

(`state_machine_v2.py` line 22 imports `ConversationState as S`, so `S.LOGO_ADJUST` is correct as written.)

- [ ] **Step 4: Gate `can_go_back` and add `back_removes_element` in `_public`**

Replace `orchestrator_v2._public` (lines 34–43) with:

```python
def _public(step: cs.Step, collected: dict, config: dict | None = None) -> dict:
    """`v2.public_data_for` plus `can_go_back` (whether `Back` has anywhere to
    go) and `back_removes_element` (whether that Back removes the in-progress
    element rather than rewinding one slot). `_back_used` suppresses Back until
    the next forward turn — one step per Back, no two consecutive."""
    data = v2.public_data_for(step, collected)
    can_back = (not collected.get("_back_used")) and (
        v2.last_answered_step(collected, config) is not None)
    data["can_go_back"] = can_back
    data["back_removes_element"] = bool(
        can_back and step is not None and step.id in v2._ELEMENT_ADJUST_STEPS)
    return data
```

- [ ] **Step 5: Clear the lock on a real forward turn in `handle_message`**

In `orchestrator_v2.handle_message`, immediately after the empty-turn guard's `return` block (after line 94, before `ack = ""` at line 96), insert:

```python
    # A real forward answer re-enables Back: the single-step lock is per-Back.
    # Popped AFTER the empty-turn guard so a blank kickoff turn never clears it,
    # and BEFORE the interpreter runs so `_back_used` never enters an LLM context.
    collected.pop("_back_used", None)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -k "back_removes_element or back_lock or clears_the_back_lock" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full v2 orchestrator + state-machine suites for regressions**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py tests/test_state_machine_v2.py tests/test_v2_e2e.py -q`
Expected: PASS (existing `test_public_data_carries_can_go_back` still passes — no `_back_used` in its collected).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/app/services/conversation/orchestrator_v2.py backend/tests/test_orchestrator_v2.py
git commit -m "feat(canvas-v2): element-adjust set + back_removes_element flag + single-step Back lock"
```

---

### Task 2: Backend — `handle_back` element-restart branch + restart copy

**Files:**
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (`handle_back` ~line 178–230; add helper above it)
- Modify: `backend/app/prompts.py` (add `V2_BACK_RESTART_ACK` after `V2_NUDGE_REPLY` ~line 1199)
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes (Task 1): `v2._ELEMENT_ADJUST_STEPS`, `_public` honouring `_back_used`.
- Consumes: `cs._pending(collected) -> dict`, `cs.FACES`, existing `v2.next_step`, `v2.last_answered_step`, `v2.reply_for`.
- Produces: `handle_back` sets `collected["_back_used"] = True` on every Back; mid-element Back resets the element's slots, emits `data["canvas_ops"] = [{"target": {"kind": "pending_logo", "face": <face>}, "remove": True}]`, and routes to the element's first step.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_orchestrator_v2.py`:

```python
# --- Task 2: element-restart Back --------------------------------------------

@pytest.mark.asyncio
async def test_back_at_logo_bg_removes_the_logo_and_restarts_placement(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_LOGO_BG.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "pending_logo": {"face": "left", "placed": True},
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_LOGO_PLACEMENT.value          # restart the element
    assert store["session"]["collected"]["pending_logo"] == {} # face/placed/bg cleared
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "left"}, "remove": True}]
    assert store["session"]["collected"]["_back_used"] is True # lock set
    assert out["data"]["can_go_back"] is False                 # can't back again yet


@pytest.mark.asyncio
async def test_back_at_decor_adjust_removes_the_decor_and_restarts(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.DECOR_ADJUST.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": False,
        "logos_done": True, "pending_logo": None, "email_captured": True,
        "decor_choice": "text", "decor_face": "back", "decor_placed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_ADD_DECOR.value               # re-pick text/shape
    collected = store["session"]["collected"]
    assert "decor_choice" not in collected
    assert "decor_face" not in collected
    assert "decor_placed" not in collected
    assert out["data"]["canvas_ops"] == [
        {"target": {"kind": "pending_logo", "face": "back"}, "remove": True}]


@pytest.mark.asyncio
async def test_non_element_back_sets_the_lock_and_carries_no_canvas_op(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_QUANTITY.value                # normal rewind
    assert "canvas_ops" not in out["data"]
    assert store["session"]["collected"]["_back_used"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -k "removes_the_logo or removes_the_decor or non_element_back" -v`
Expected: FAIL — state is `ASK_LOGO_BG` (unchanged) / no `canvas_ops` / no `_back_used`.

- [ ] **Step 3: Add the restart copy in `prompts.py`**

After `V2_NUDGE_REPLY` (line 1199), add:

```python
V2_BACK_RESTART_ACK = (
    "No worries — I've removed that one so you can start it over."
)
```

- [ ] **Step 4: Add the element-restart helper + branch in `handle_back`**

In `orchestrator_v2.py`, add this helper just above `handle_back` (before line 178):

```python
def _restart_element(collected: dict, current: S) -> str:
    """Clear the in-progress element's slots so first-unmet re-asks it from the
    top, and return the face the (now-removed) canvas element sat on. Logo:
    reset pending_logo to {} (loop stays open) -> re-asks ASK_LOGO_PLACEMENT.
    Decor: drop the decor slots -> re-asks ASK_ADD_DECOR (re-pick text/shape)."""
    if current in (S.LOGO_ADJUST, S.ASK_LOGO_BG):
        face = cs._pending(collected).get("face") or "front"
        collected["pending_logo"] = {}
        return face
    # DECOR_ADJUST
    face = collected.get("decor_face") or "front"
    for key in ("decor_choice", "decor_face", "decor_placed"):
        collected.pop(key, None)
    return face
```

Then, inside `handle_back`, after the `GREETING` branch (after line 212) and before `target = v2.last_answered_step(...)` (line 214), insert the element branch, and set the lock on the existing non-element path. Replace lines 214–230 with:

```python
    if current in v2._ELEMENT_ADJUST_STEPS:
        face = _restart_element(collected, current)
        collected["_back_used"] = True
        nxt = v2.next_step(collected, flow_config)
        reply = v2.reply_for(nxt, collected, persona=persona, intro=intro,
                             ack=prompts.V2_BACK_RESTART_ACK, colour_note=colour_note)
        data = _public(nxt, collected, flow_config)
        data["canvas_ops"] = [
            {"target": {"kind": "pending_logo", "face": face}, "remove": True}]
        return await _persist(sb, session_id, collected, nxt, reply,
                              current.value, nxt.id, user_message="", data=data)

    target = v2.last_answered_step(collected, flow_config)
    if target is None:
        step = cs.by_id(current)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)
        return await _persist(sb, session_id, collected, step, reply,
                              current.value, current, user_message="",
                              data=_public(step, collected, flow_config))
    clear = ((set(target.slots) & cs.WRITABLE_SLOTS) | set(target.back_clears)) - v2._TERMINAL_FLAGS
    for key in clear:
        collected.pop(key, None)
    collected["_back_used"] = True
    nxt = v2.next_step(collected, flow_config)
    reply = v2.reply_for(nxt, collected, persona=persona, intro=intro,
                         colour_note=colour_note)
    return await _persist(sb, session_id, collected, nxt, reply,
                          current.value, nxt.id, user_message="",
                          data=_public(nxt, collected, flow_config))
```

Note: the reused `pending_logo` op kind means "the element being worked on, resolved by last-unlocked-on-face" — the same anchor `_ops_logo_bg` already uses. It carries a text/shape decor too (the frontend `removePending` doesn't filter by type).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -k "removes_the_logo or removes_the_decor or non_element_back" -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full v2 + prompts suites**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py tests/test_state_machine_v2.py tests/test_v2_e2e.py tests/test_prompts.py -q`
Expected: PASS. The existing `test_back_clears_the_last_answer_and_re_asks`, `test_back_from_post_decoration_state_...`, `test_handle_back_at_finalize_...` still pass (non-element states use the unchanged rewind path, now also setting `_back_used`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py backend/app/prompts.py backend/tests/test_orchestrator_v2.py
git commit -m "feat(canvas-v2): mid-element Back removes the element and restarts it"
```

---

### Task 3: Frontend — `removePending` canvas action + `canvas_ops` remove verb

**Files:**
- Modify: `frontend/src/store/canvasStore.ts` (interface near line 86; implementation near line 183)
- Modify: `frontend/src/lib/canvasOps.ts` (`applyCanvasOps` pending_logo branch, line 43–45)
- Test: `frontend/src/__tests__/canvasStoreOps.test.ts`

**Interfaces:**
- Produces: `useCanvasStore` action `removePending(face: Face): void` — removes the last unlocked element (ANY type) on `face`; no-op if none.
- Produces: `applyCanvasOps` handles `{ target: { kind: 'pending_logo', face }, remove: true }` by calling `removePending(face)`. (`parseCanvasOps` already parses `remove` for `pending_logo` — no change there.)

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/__tests__/canvasStoreOps.test.ts`:

```typescript
import { applyCanvasOps } from '../lib/canvasOps'

test('removePending drops the last unlocked element of any type on the face', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('back'); s.addText('t')       // a decor, not an image
  s.removePending('back')
  expect(useCanvasStore.getState().faces.back).toHaveLength(0)
})

test('removePending keeps locked elements and older placed ones', () => {
  const s = useCanvasStore.getState()
  s.addImage('kept.png'); s.lockPlaced()        // locked, must survive
  s.addImage('current.png')                     // the one just placed
  s.removePending('front')
  const { faces } = useCanvasStore.getState()
  expect(faces.front).toHaveLength(1)
  expect(faces.front[0].url).toBe('kept.png')
})

test('removePending is a no-op when nothing is unlocked', () => {
  const s = useCanvasStore.getState()
  s.addImage('logo.png'); s.lockAll()
  expect(() => s.removePending('front')).not.toThrow()
  expect(useCanvasStore.getState().faces.front).toHaveLength(1)
})

test('applyCanvasOps remove on a pending_logo target calls removePending', () => {
  const s = useCanvasStore.getState()
  s.setActiveFace('left'); s.addText('x')
  applyCanvasOps([{ target: { kind: 'pending_logo', face: 'left' }, remove: true }])
  expect(useCanvasStore.getState().faces.left).toHaveLength(0)
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreOps.test.ts`
Expected: FAIL — `removePending` is not a function.

- [ ] **Step 3: Declare `removePending` in the store interface**

In `frontend/src/store/canvasStore.ts`, after the `patchPendingLogo` declaration (~line 86), add:

```typescript
  /** Remove the last unlocked element (any type) on `face` — the in-progress
   *  element being worked on. Same "last unlocked" anchor patchPendingLogo
   *  uses, but not restricted to images, since a mid-flow decor is text/shape. */
  removePending: (face: Face) => void
```

- [ ] **Step 4: Implement `removePending`**

In the store body, right after the `patchPendingLogo` implementation (~line 193), add:

```typescript
  removePending: (face) => set(s => {
    const arr = s.faces[face]
    let idx = -1
    for (let i = arr.length - 1; i >= 0; i--) {
      if (!arr[i].locked) { idx = i; break }
    }
    if (idx === -1) return s
    const removed = arr[idx]
    const next = arr.slice()
    next.splice(idx, 1)
    return {
      faces: { ...s.faces, [face]: next },
      selectedId: s.selectedId === removed.id ? null : s.selectedId,
    }
  }),
```

- [ ] **Step 5: Wire the remove verb into `applyCanvasOps`**

In `frontend/src/lib/canvasOps.ts`, replace the `pending_logo` branch (lines 43–46):

```typescript
    if (op.target.kind === 'pending_logo') {
      if (op.remove) s.removePending(op.target.face)
      else if (op.patch) s.patchPendingLogo(op.target.face, op.patch)
      continue
    }
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreOps.test.ts`
Expected: PASS.

- [ ] **Step 7: Run the neighbouring canvas suites**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreLock.test.ts src/store/canvasStore.test.ts`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/lib/canvasOps.ts frontend/src/__tests__/canvasStoreOps.test.ts
git commit -m "feat(canvas-v2): removePending canvas action + canvas_ops remove verb"
```

---

### Task 4: Frontend — `backRemovesElement` in the store + confirm dialog in ChatColumn

**Files:**
- Modify: `frontend/src/store/chatStore.ts` (interface ~line 56; `parseData` ~line 112–113; defaults ~line 141; reset ~line 337)
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx` (hooks ~line 174–176; Back render block ~line 632–639)
- Test: `frontend/src/__tests__/chatStoreBack.test.ts`, `frontend/src/__tests__/ChatColumn.test.tsx`

**Interfaces:**
- Consumes (Task 2): backend `data.back_removes_element: boolean`.
- Produces: `useChatStore` field `backRemovesElement: boolean` (from `data.back_removes_element`).
- Produces: ChatColumn shows an inline confirm (*"Remove this element and start it over?"* with **Remove & start over** / **Keep going**) only when `backRemovesElement`; **Remove & start over** calls `goBack(sessionId)`; the plain-rewind path is unchanged when the flag is false.

- [ ] **Step 1: Write the failing store test**

Add to `frontend/src/__tests__/chatStoreBack.test.ts`:

```typescript
test('applyResponse sets backRemovesElement from data.back_removes_element', () => {
  useChatStore.getState().applyResponse('r', 'ask_logo_bg',
    { can_go_back: true, back_removes_element: true })
  expect(useChatStore.getState().backRemovesElement).toBe(true)

  useChatStore.getState().applyResponse('r', 'ask_quantity', { can_go_back: true })
  expect(useChatStore.getState().backRemovesElement).toBe(false)
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/chatStoreBack.test.ts`
Expected: FAIL — `backRemovesElement` is undefined.

- [ ] **Step 3: Add `backRemovesElement` to the store**

In `frontend/src/store/chatStore.ts`:

Interface — after `canGoBack: boolean` (line 56):
```typescript
  /** v2 canvas: whether Back at the current step removes the in-progress
   *  element (and re-asks it) rather than rewinding one slot — drives the
   *  "remove & restart?" confirm in ChatColumn. */
  backRemovesElement: boolean
```

`parseData` — replace lines 112–113:
```typescript
  const canGoBack = data.can_go_back === true
  const backRemovesElement = data.back_removes_element === true
  return { options, options2, triggerGeneration, triggerRegeneration, continuable, tintReady, tintHex, colourSwatches, colourPicker, progress, multiselect, selected, quoteUrl, canvasDirective, triggerFinalize, canGoBack, backRemovesElement }
```

Initial state — after `canGoBack: false,` (line 141):
```typescript
  backRemovesElement: false,
```

`reset` — after the `canGoBack: false,` inside `reset` (line 337):
```typescript
      backRemovesElement: false,
```

- [ ] **Step 4: Run the store test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/chatStoreBack.test.ts`
Expected: PASS.

- [ ] **Step 5: Write the failing ChatColumn confirm test**

Add to `frontend/src/__tests__/ChatColumn.test.tsx` (follow the file's existing render/setup helpers for `sessionStore` + `chatStore`; use its established pattern for seeding chat state). The behavioural assertions:

```typescript
import { fireEvent, screen } from '@testing-library/react'
// ...existing imports / render helper...

test('Back shows a confirm and only removes on confirm when backRemovesElement', async () => {
  const goBack = vi.fn()
  // Seed the chat store: a session exists, canGoBack + backRemovesElement true,
  // not sending. (Use the file's existing store-seeding helper; set goBack via
  // useChatStore.setState({ goBack }) so the click target is observable.)
  useChatStore.setState({ canGoBack: true, backRemovesElement: true, sending: false, goBack })
  // ...render ChatColumn with a sessionId (reuse the file's render helper)...

  fireEvent.click(screen.getByText('↩ Back'))
  expect(goBack).not.toHaveBeenCalled()                 // confirm first, no immediate back
  expect(screen.getByText(/start it over/i)).toBeInTheDocument()

  fireEvent.click(screen.getByText('Keep going'))
  expect(goBack).not.toHaveBeenCalled()                 // declined

  fireEvent.click(screen.getByText('↩ Back'))
  fireEvent.click(screen.getByText('Remove & start over'))
  expect(goBack).toHaveBeenCalledTimes(1)
})

test('Back goes straight through when backRemovesElement is false', async () => {
  const goBack = vi.fn()
  useChatStore.setState({ canGoBack: true, backRemovesElement: false, sending: false, goBack })
  // ...render...
  fireEvent.click(screen.getByText('↩ Back'))
  expect(goBack).toHaveBeenCalledTimes(1)               // no confirm step
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: FAIL — no confirm UI; Back calls `goBack` immediately.

- [ ] **Step 7: Add the confirm state + render block in ChatColumn**

In `frontend/src/components/CustomiseStudio/ChatColumn.tsx`:

Hooks — after `const goBack = useChatStore(s => s.goBack)` (line 175):
```typescript
  const backRemovesElement = useChatStore(s => s.backRemovesElement)
  const [confirmingBack, setConfirmingBack] = useState(false)
```

Render — replace the Back block (lines 632–639):
```tsx
        {sessionId && canGoBack && !sending && (
          confirmingBack && backRemovesElement ? (
            <div className="self-start flex flex-wrap items-center gap-2 text-xs text-textMuted">
              <span>Remove this element and start it over?</span>
              <button
                onClick={() => { setConfirmingBack(false); void goBack(sessionId) }}
                className="text-accent hover:underline underline-offset-2"
              >
                Remove &amp; start over
              </button>
              <button
                onClick={() => setConfirmingBack(false)}
                className="hover:underline underline-offset-2"
              >
                Keep going
              </button>
            </div>
          ) : (
            <button
              onClick={() => (backRemovesElement ? setConfirmingBack(true) : void goBack(sessionId))}
              className="self-start text-xs text-textMuted hover:text-accent underline underline-offset-2 disabled:opacity-50"
            >
              ↩ Back
            </button>
          )
        )}
```

Gating the confirm UI on `confirmingBack && backRemovesElement` (not `confirmingBack` alone) means a stale `confirmingBack` after the step changes falls back to the plain button — no stuck confirm.

- [ ] **Step 8: Run the ChatColumn test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ChatColumn.test.tsx`
Expected: PASS.

- [ ] **Step 9: Run the touched frontend suites together**

Run: `cd frontend && npx vitest run src/__tests__/chatStoreBack.test.ts src/__tests__/ChatColumn.test.tsx src/__tests__/canvasStoreOps.test.ts`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__/chatStoreBack.test.ts frontend/src/__tests__/ChatColumn.test.tsx
git commit -m "feat(canvas-v2): confirm remove-and-restart on mid-element Back"
```

---

## Self-Review

**Spec coverage:**
- §5.1 element-adjust set → Task 1 Step 3.
- §5.2 `back_removes_element` flag → Task 1 Step 4.
- §5.3 `handle_back` element branch (logo → `ASK_LOGO_PLACEMENT`, decor → `ASK_ADD_DECOR`, remove op) → Task 2 Steps 3–4.
- §5.4 single-step lock (`_back_used` set on Back, gates `can_go_back`, cleared on forward turn, not writable, not leaked) → Task 1 Steps 4–5 + Task 2 Step 4. (Not in `WRITABLE_SLOTS`: satisfied by not adding it. Not leaked: popped before the interpreter runs — Task 1 Step 5.)
- §5.5 `removePending` + canvas op remove verb → Task 3.
- §5.6 confirm dialog + `backRemovesElement` → Task 4.
- §6 edge cases: post-submit/GREETING unchanged (Task 2 keeps those branches); pre-placement steps excluded (set definition); no-unlocked-element no-op (Task 3 Step 4); second Back gated (Task 1 `can_go_back` false → button not rendered).
- §7 testing → tests in every task.

**Placeholder scan:** none — all code blocks are concrete. The ChatColumn test (Task 4 Step 5) references "the file's existing render helper" because the harness setup is file-local; the behavioural assertions are fully specified.

**Type consistency:** `_ELEMENT_ADJUST_STEPS` (frozenset of `ConversationState`) used identically in `_public` and `handle_back`. `removePending(face)` signature matches its call in `applyCanvasOps` and tests. `backRemovesElement` spelled identically across store interface, `parseData`, defaults, reset, and ChatColumn. Canvas op shape `{target:{kind:'pending_logo',face}, remove:true}` matches `parseCanvasOps` (already parses `remove`) and the backend emit in Task 2.
