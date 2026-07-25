# v2 Canvas Back — element-aware restart + single-step lock

**Date:** 2026-07-25
**Status:** Approved (design)
**Scope:** The `↩ Back` affordance in the v2 canvas conversation (`CANVAS_ORCHESTRATOR_V2` on, `flow_mode == "canvas"`). No change to v1 or to any non-canvas flow.

---

## 1. Problem

The `↩ Back` button is emitted only by the v2 canvas orchestrator (`orchestrator_v2._public` → `data.can_go_back`; rendered in `ChatColumn.tsx`). Today `handle_back` finds the **last-answered step**, clears **that one step's writable slots**, and re-asks it — one slot per press, and it can be pressed repeatedly.

Two problems, both mid-element (while placing/adjusting a logo or a text/shape):

1. **Chat/canvas desync.** Per-slot rewind walks the chat backward through an element's attributes (e.g. `ASK_LOGO_BG` → `LOGO_ADJUST`) while the placed element stays on the canvas. The customer sees the bot re-ask about an element that visually looks finished.
2. **Unbounded rewind.** Nothing stops consecutive Back presses, so the customer can rewind arbitrarily far in one burst.

## 2. Goals

- **Mid-element Back = "remove this element and start it over".** When the customer is actively adjusting an element and presses Back, confirm — *"Remove this element and start it over?"*. Confirming removes the in-progress element (from the canvas **and** from `collected`) and re-asks that element from its first question. Declining keeps them where they are (move forward).
- **One step per Back, no two consecutive.** After any Back, the button is unavailable until the customer sends the next forward answer.
- **Everything else unchanged.** Outside the element-adjust steps, Back keeps its existing single-step rewind. Non-canvas / v1 flows are untouched (they never emit `can_go_back`).

## 3. Non-goals

- No change to v1 (`orchestrator.py`) or the shared tail states.
- No backend-driven confirmation step (the "are you sure?" is a UI concern — see §4, Approach A vs B).
- No new persistence of the pending element's canvas geometry (the remove op resolves the element by the same "last unlocked on face" anchor the codebase already uses).

## 4. Approach

**Chosen: A — UI confirm + backend does the work.**

The confirmation dialog is a pure UI concern and lives in the frontend. The data work (clear the element's slots, route to the re-ask step, emit the canvas-remove op) and the single source of truth for *which* steps are "mid-element" stay in the backend. Minimal new state.

**Rejected: B — a transient `confirm_back` registry step** with two chips. More faithful to "backend drives the conversation," but a confirmation is not part of the design data model; it would add a stateful step, a `_pending_back` flag, and interpreter handling for its chips — more moving parts for no gain.

## 5. Design

### 5.1 Which steps are "mid-element"

Define, in `state_machine_v2` (or `canvas_steps`), the set of steps where an element is **actually on the canvas being adjusted**:

```
_ELEMENT_ADJUST_STEPS = { LOGO_ADJUST, ASK_LOGO_BG, DECOR_ADJUST }
```

Rationale:
- `LOGO_ADJUST` (auto_open `upload`) and `ASK_LOGO_BG` — the logo is placed on the canvas.
- `DECOR_ADJUST` — the text/shape is placed on the canvas.
- `ASK_LOGO_PLACEMENT` and `ASK_DECOR_PLACEMENT` are **pre-placement** (face chosen, tool not yet opened, nothing on canvas) → they keep the normal single-step rewind. Backing from there un-answers the face choice with nothing to remove, which is already correct.

### 5.2 Backend — surface the flag

`orchestrator_v2._public()` adds:

```
data["back_removes_element"] = (
    step.id in _ELEMENT_ADJUST_STEPS and data["can_go_back"] is True
)
```

So the frontend knows whether this Back needs the confirm dialog. `_public` is already called on every v2 turn's `data`, so no caller changes.

### 5.3 Backend — `handle_back` element branch

In `handle_back`, after resolving `current`:

- **If `current in _ELEMENT_ADJUST_STEPS`:** remove the whole element and restart it.
  - **Logo** (`current in {LOGO_ADJUST, ASK_LOGO_BG}`):
    - Capture the pending logo's face (`_pending(collected).get("face")`) for the remove op.
    - Reset `collected["pending_logo"] = {}` — clears `face`/`placed`/`bg`, leaving the logo loop open. First-unmet then routes to `ASK_LOGO_PLACEMENT` (the element's first question).
    - Emit a `canvas_ops` remove targeting the last-unlocked element on that face (see §5.5).
  - **Decor** (`current is DECOR_ADJUST`):
    - Capture `collected.get("decor_face")` for the remove op.
    - Pop `decor_choice`, `decor_face`, `decor_placed`. First-unmet then routes to `ASK_ADD_DECOR` (re-pick text vs shape — the element is fully removed).
    - Emit a `canvas_ops` remove for the last-unlocked element on that face.
  - Re-ask the routed step; persist with `data` carrying the remove op.
- **Else:** the existing single-step rewind (`last_answered_step` → clear its slots → `next_step`), unchanged.

Both branches set the single-step lock (§5.4).

### 5.4 Backend — the single-step lock (all v2 steps)

- `handle_back` sets internal flag `collected["_back_used"] = True` on every Back (both branches).
- `_public` forces `can_go_back = False` while `_back_used` is set:
  ```
  data["can_go_back"] = (not collected.get("_back_used")) and last_answered_step(...) is not None
  ```
- `handle_message` pops `_back_used` at the start of a real forward turn (alongside where it processes a forward message), so the next customer answer re-enables Back.

`_back_used` is `_`-prefixed and **not** in `WRITABLE_SLOTS`, so `validate_fields` drops any interpreter attempt to write it, and `public_data_for` / the LLM-ack path must not leak it (verify it is stripped by the existing `_`-prefix / safe-collected filtering; add stripping if not).

Net effect: Back → button hidden → reappears only after the customer sends the next answer. The element-removal re-ask lands with `can_go_back = false` until they answer forward.

### 5.5 Frontend — canvas remove op for a pending element

`canvasOps.ts` / `canvasStore.ts`:

- The existing `pending_logo` op target only supports `patch`. A mid-flow **decor** is text/shape, not an image, so we need a remove that resolves "the last unlocked element on a face" for **any** element type.
- Add store action `removePending(face)` — remove the last-unlocked element on `face` (mirror of `patchPendingLogo`'s reverse-scan anchor, but not restricted to `type === 'image'`).
- Extend `parseCanvasOps` / `applyCanvasOps` so a `{ target: { kind: 'pending_logo', face }, remove: true }` op calls `removePending(face)`. (Reuse the `pending_logo` kind — it already means "the element being worked on, resolved by last-unlocked-on-face"; `remove: true` is the new verb.)

### 5.6 Frontend — confirm dialog

`chatStore.ts`:
- `parseData` reads `back_removes_element` → store field `backRemovesElement: boolean`.

`ChatColumn.tsx`:
- Back click handler:
  - If `backRemovesElement`: show an inline confirm — *"Remove this element and start it over?"* with **[Remove & start over]** and **[Keep going]**. **Remove & start over** → `goBack(sessionId)`; **Keep going** → dismiss (no call).
  - Else: `goBack(sessionId)` directly (normal rewind, unchanged).
- The confirm is a lightweight inline two-button prompt (consistent with the existing chip styling), not a browser `confirm()` (blocking dialogs are banned).

`goBack` itself is unchanged — it calls `sendBack` and applies the response (which now carries the remove op in `data.canvas_ops`, applied by the existing `applyCanvasOps` path in the response handler).

## 6. Edge cases

- **Post-submit (`quote_requested`) / GREETING:** Back already off / specially handled in `handle_back` — unchanged.
- **`ASK_LOGO_PLACEMENT` / `ASK_DECOR_PLACEMENT`:** not in `_ELEMENT_ADJUST_STEPS` → normal rewind, nothing to remove.
- **No unlocked element on the face** (defensive): `removePending` is a no-op if it finds none, so the op is safe even if the canvas and chat momentarily disagree.
- **Second Back attempt with `_back_used` set:** `can_go_back` is false, so the button isn't rendered; even a stale click can't fire (the render is gated on `canGoBack`).

## 7. Testing

**Backend (`test_orchestrator_v2.py` / `test_state_machine_v2.py`):**
- Back at `LOGO_ADJUST` / `ASK_LOGO_BG` resets `pending_logo` to `{}`, routes to `ASK_LOGO_PLACEMENT`, and emits a `pending_logo` remove op for the right face.
- Back at `DECOR_ADJUST` pops the decor slots, routes to `ASK_ADD_DECOR`, and emits a remove op for the right face.
- Back at a non-element step (e.g. `ASK_QUANTITY`) keeps the existing single-step rewind (no remove op).
- `_back_used` is set by Back and makes `can_go_back` false on the resulting turn; the next forward `handle_message` clears it so `can_go_back` is true again.
- `back_removes_element` is true only at the three element-adjust steps and false elsewhere.
- `_back_used` is never interpreter-writable (dropped by `validate_fields`) and not leaked in public data.

**Frontend:**
- `canvasStore`: `removePending(face)` drops the last-unlocked element (image, text, or shape) on the face and no-ops when empty.
- `canvasOps`: a `pending_logo` + `remove: true` op calls `removePending`.
- `chatStore`: `backRemovesElement` reflects `data.back_removes_element`; extend `chatStoreBack` for the lock.
- `ChatColumn`: confirm shown only when `backRemovesElement`; **Remove & start over** calls `goBack`, **Keep going** does not; plain Back path unchanged when the flag is false.

## 8. Files touched

- `backend/app/services/conversation/state_machine_v2.py` — `_ELEMENT_ADJUST_STEPS`, `can_go_back` lock in the public-data helper (or wherever it's computed).
- `backend/app/services/conversation/orchestrator_v2.py` — `_public` flag, `handle_back` element branch + `_back_used`, `handle_message` clears `_back_used`.
- `frontend/src/store/canvasStore.ts` — `removePending`.
- `frontend/src/lib/canvasOps.ts` — remove verb for `pending_logo`.
- `frontend/src/store/chatStore.ts` — `backRemovesElement`.
- `frontend/src/components/CustomiseStudio/ChatColumn.tsx` — confirm dialog.
- Tests as in §7.
