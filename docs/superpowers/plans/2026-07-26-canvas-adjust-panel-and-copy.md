# Canvas Adjust Panel + v2 Copy Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the element adjustment toolbar above the cap as a sticky, brand-coloured "Adjust" panel so it is visible on small screens, point the chat copy at it, make the v2 canvas copy formal, and tell the customer at the final step that the team will email their finished design (background knocked out where asked) with the quote.

**Architecture:** Frontend change is confined to `SelectedToolbar`'s own root element (it already returns `null` when nothing is selected, so making its root `sticky` avoids an empty wrapper) plus a one-line reorder in `Surface.tsx`. Backend changes are pure copy edits in `prompts.py` / `canvas_steps.py`, with one new pure helper (`bg_note_for`) threaded into the existing `reply_for` `.format()` kwargs — no orchestrator signature change.

**Tech Stack:** React 18 + Tailwind + Zustand + react-konva (frontend, vitest); Python 3.12 + FastAPI (backend, pytest).

## Global Constraints

- **Backend tests run as** `CANVAS_ORCHESTRATOR_V2=false pytest -q` from `backend/`. The repo-root `.env` default of `true` flips 3 unrelated tests red. Without Docker: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`.
- **Frontend tests run focused**, e.g. `cd frontend && npx vitest run src/__tests__/<file>` — a full `vitest run` intermittently stalls on this Windows host (tinypool "Worker exited").
- **No copy may name a colour** ("the orange panel"). `bg-accent` is `var(--brand-primary, #FF5C00)` and is themed per store. Copy says "the Adjust panel above the cap".
- **"Remove background" stays a mark, not an edit.** No client-side matting, and no copy may promise processing or ask the customer to wait — ticking is instant, the knockout happens at render.
- **`ask_logo_bg` must keep `tool="upload"`.** It is what keeps `v2Editing` true so the placed logo stays selectable and the toggle is reachable. Do not touch it.
- **Chip labels are matched by exact literal** (`state_machine_v2.resolve_chip`). Any label edit must update every test that types that label.
- **Australian English** (`colour`, not `color`) in customer-facing copy, matching the codebase.
- **No changes to** `delivery.py`, `maybe_send_quote_confirmation`, the admin render endpoint, or any v1 (non-canvas) conversation copy.

**Spec:** `docs/superpowers/specs/2026-07-26-canvas-adjust-panel-and-copy-design.md`

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `frontend/src/components/DesignStudio/SelectedToolbar.tsx` | Becomes a titled, sticky, accent-headed panel. Owns its own positioning. | 1 |
| `frontend/src/components/DesignStudio/Surface.tsx` | Renders the toolbar **before** the stage; adds a test hook on the stage wrapper. | 1 |
| `frontend/src/__tests__/selectedToolbarPlacement.test.tsx` | **New.** Pins DOM order, the header label, and the sticky class. | 1 |
| `backend/app/prompts.py` | All v2 customer-facing copy constants. | 2, 3, 4 |
| `backend/app/services/conversation/canvas_steps.py` | Step registry copy, chip labels, new `bg_note_for` helper. | 2, 3, 4 |
| `backend/app/services/conversation/state_machine_v2.py` | Passes `bg_note` into `reply_for`'s `.format()`. | 4 |
| `backend/tests/test_v2_copy_guards.py` | **New.** Guards: no "under the cap", no casual phrases. | 2, 3 |
| `backend/tests/test_state_machine_v2.py` | Existing assertions on literal copy + chip labels. | 3, 4 |
| `backend/tests/test_canvas_steps.py`, `test_orchestrator_v2.py`, `test_v2_e2e.py` | Existing assertions typing exact chip labels. | 3 |

---

## Task 1: Sticky accent Adjust panel above the cap

**Files:**
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx:38-39` (root element), `:185` (closing tag)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:298-313` (centre column order)
- Test: `frontend/src/__tests__/selectedToolbarPlacement.test.tsx` (new)

**Interfaces:**
- Consumes: `useCanvasStore` (`activeFace`, `faces`, `selectedId`, `updateElement`, `removeElement`, `duplicate`, `reorder`) — unchanged.
- Produces: DOM contract used by tests and by Task 2/3 copy — `data-testid="adjust-panel"` on the toolbar root, `data-testid="canvas-stage-wrap"` on the stage wrapper, and a header string of the exact form `Adjust — Text` / `Adjust — Image` / `Adjust — Shape` / `Adjust — Drawing`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/selectedToolbarPlacement.test.tsx`:

```tsx
import { beforeEach, describe, expect, test, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn().mockResolvedValue({ reply: 'ok', state: 'ask_another_logo', data: {} }),
  uploadLogo: vi.fn().mockResolvedValue({ asset_url: 'u', asset_hash: 'h' }),
  uploadCanvasLayouts: vi.fn().mockResolvedValue(undefined),
  finalizeCanvas: vi.fn().mockResolvedValue({ reply: 'ok', state: 'generating', data: {} }),
}))

import { SelectedToolbar } from '../components/DesignStudio/SelectedToolbar'
import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useCanvasStore } from '../store/canvasStore'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'

// jsdom has no real <canvas> 2D backend, so a react-konva Stage cannot mount
// unless getContext is stubbed. Same permissive no-op proxy surfaceDirective.test.tsx uses.
function stubCanvasContext(): CanvasRenderingContext2D {
  const noop = () => {}
  const store: Record<string, unknown> = {}
  return new Proxy(store, {
    get(target, prop: string) {
      if (prop in target) return target[prop]
      switch (prop) {
        case 'measureText': return () => ({ width: 0 })
        case 'createLinearGradient':
        case 'createRadialGradient': return () => ({ addColorStop: noop })
        case 'createPattern': return () => ({})
        case 'getImageData': return () => ({ data: new Uint8ClampedArray(4), width: 1, height: 1 })
        case 'canvas': return undefined
        default: return noop
      }
    },
    set(target, prop: string, value) { target[prop] = value; return true },
  }) as unknown as CanvasRenderingContext2D
}
HTMLCanvasElement.prototype.getContext = ((() => stubCanvasContext()) as unknown) as typeof HTMLCanvasElement.prototype.getContext

beforeEach(() => {
  useCanvasStore.getState().reset()
  useChatStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

function selectText() {
  const s = useCanvasStore.getState()
  s.addText('hi')
  s.select(useCanvasStore.getState().faces.front[0].id)
}

describe('Adjust panel', () => {
  test('is titled for the selected element type', () => {
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByText('Adjust — Text')).toBeInTheDocument()
  })

  test('titles an image element as Image', () => {
    const s = useCanvasStore.getState()
    s.addImage('http://x/a.png', 1)
    s.select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar />)
    expect(screen.getByText('Adjust — Image')).toBeInTheDocument()
  })

  test('its root is sticky so it stays visible while the canvas column scrolls', () => {
    selectText()
    render(<SelectedToolbar />)
    expect(screen.getByTestId('adjust-panel').className).toContain('sticky')
  })

  test('renders ABOVE the cap, not below it (small screens hid it under the fold)', () => {
    useChatStore.setState({
      chatState: 'logo_adjust',
      canvasDirective: { allowedTools: ['text'], targetFace: null, autoOpen: null, instructions: null, showDone: false },
    } as never)
    selectText()
    render(<DesignStudioSurface />)
    const panel = screen.getByTestId('adjust-panel')
    const stage = screen.getByTestId('canvas-stage-wrap')
    // DOCUMENT_POSITION_FOLLOWING means `stage` comes after `panel` in the document.
    expect(panel.compareDocumentPosition(stage) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/selectedToolbarPlacement.test.tsx`
Expected: FAIL — `Unable to find an element with the text: Adjust — Text` and `Unable to find an element by: [data-testid="adjust-panel"]`.

- [ ] **Step 3: Turn `SelectedToolbar`'s root into the sticky titled panel**

In `frontend/src/components/DesignStudio/SelectedToolbar.tsx`, add the label map just above the component (after the imports):

```tsx
/** Header label per element type — the panel names what it is adjusting, so a
 *  customer who selects something knows the panel that just appeared is for it. */
const ADJUST_LABELS: Record<string, string> = {
  text: 'Text', image: 'Image', shape: 'Shape', drawing: 'Drawing',
}
```

Replace the opening root `<div>` (currently line 39):

```tsx
    <div className="flex flex-wrap items-center gap-2 p-3 bg-surface border border-border rounded-xl">
```

with:

```tsx
    // sticky: the centre column of Surface is the scroll container, so this pins
    // the panel to the top of the canvas area. It used to render BELOW the cap,
    // which on a phone (chat already owns 45vh) put it under the fold entirely.
    // The controls region scrolls within itself so a wrapped toolbar can never
    // push the cap off-screen.
    <div data-testid="adjust-panel"
      className="sticky top-0 z-20 w-full bg-surface border border-accent rounded-xl overflow-hidden shadow-sm">
      <div className="bg-accent text-white px-3 py-1.5 text-xs font-semibold uppercase tracking-wide">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>
      <div className="flex flex-wrap items-center gap-2 p-3 max-h-[45vh] overflow-y-auto">
```

and replace the closing `</div>` of the root (currently line 185) with:

```tsx
      </div>
    </div>
```

Note: JSX does not allow a `//` comment before an element inside a return — put the comment block above the `return (` line as a normal `//` comment, not inside the JSX.

- [ ] **Step 4: Move the panel above the stage in `Surface.tsx`**

Replace the centre-column block (`Surface.tsx:298-313`):

```tsx
        {/* Centre — canvas + contextual toolbar */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto min-w-0">
          <CanvasStage stageRef={stageRef} locked={stageLocked} />
```

with:

```tsx
        {/* Centre — Adjust panel (sticky, ABOVE the cap) then the canvas.
            The panel is rendered first so it is the first thing in view on a
            phone; it returns null until an element is selected, so nothing is
            reserved when there is nothing to adjust. */}
        <div className="flex-1 flex flex-col items-center gap-3 p-4 overflow-auto min-w-0">
          {(isV2 ? v2Editing : unlocked) && <SelectedToolbar />}
          <div data-testid="canvas-stage-wrap" className="w-full flex justify-center">
            <CanvasStage stageRef={stageRef} locked={stageLocked} />
          </div>
```

Then delete the now-duplicate toolbar line and its comment further down the same block:

```tsx
          {/* v2 mounts the toolbar on its editing steps: the instruction copy
              tells the customer to change font/size/colour "in the toolbar
              under the cap". It no-ops (returns null) until an element is
              selected, so it only surfaces once they pick a placed element —
              exactly when needed. On a no-tool step it stays out entirely. */}
          {(isV2 ? v2Editing : unlocked) && <SelectedToolbar />}
```

The gating expression is unchanged — only its position moved.

- [ ] **Step 5: Run the new test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/selectedToolbarPlacement.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the neighbouring suites for regressions**

Run: `cd frontend && npx vitest run src/__tests__/selectedToolbarTransform.test.tsx src/__tests__/surfaceDirective.test.tsx src/__tests__/surfaceRework.test.tsx src/__tests__/designStudioCenterPivotSmoke.test.tsx`
Expected: PASS. In particular `surfaceDirective.test.tsx`'s "v2: SelectedToolbar mounts so a selected element is editable" and "the stage is read-only on a step that hands over no tools" must both still pass — they pin the gating this step moved.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DesignStudio/SelectedToolbar.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/selectedToolbarPlacement.test.tsx
git commit -m "fix(canvas): sticky Adjust panel above the cap, titled per element

The element toolbar rendered below the stage inside a scroll column, so on
small screens (chat owns 45vh) it sat under the fold and selecting an element
appeared to do nothing. It now renders first in the centre column, sticky to
the top, with a solid brand-accent header naming the element it adjusts."
```

---

## Task 2: Chat copy points at the Adjust panel

**Files:**
- Modify: `backend/app/prompts.py:1084-1099` (`V2_TOOL_TIPS`), `:1107-1111` (`V2_BG_INSTRUCTIONS`)
- Modify: `backend/app/services/conversation/canvas_steps.py:481-484` (`LOGO_ADJUST.ask`)
- Test: `backend/tests/test_v2_copy_guards.py` (new)

**Interfaces:**
- Consumes: `canvas_steps.REGISTRY`, `canvas_steps.Step` fields `ask` / `ask_retry` / `tip` / `instructions` / `chips` (each `Chip` has `.label`), and the `prompts.V2_*` constants.
- Produces: `backend/tests/test_v2_copy_guards.py::_v2_copy_strings()` — a helper Task 3 extends with a second guard.

- [ ] **Step 1: Write the failing guard test**

Create `backend/tests/test_v2_copy_guards.py`:

```python
"""Guards on the v2 canvas copy.

These are cheap regression pins on things that are easy to reintroduce by
hand-editing one constant: copy that points at the toolbar's OLD position, and
casual phrasing the brand has moved away from.
"""
from app import prompts
from app.services.conversation import canvas_steps as cs


def _v2_copy_strings() -> list[str]:
    """Every customer-facing v2 string: registry copy + the shared constants."""
    out: list[str] = []
    for step in cs.REGISTRY:
        for s in (step.ask, step.ask_retry, step.tip, step.instructions):
            if s:
                out.append(s)
        for chip in step.chips:
            out.append(chip.label)
    out.extend(prompts.V2_TOOL_TIPS.values())
    out.extend([
        prompts.V2_BG_INSTRUCTIONS,
        prompts.V2_REWORK_INSTRUCTIONS,
        prompts.V2_ASK_NAME,
        prompts.V2_ASK_NAME_RETRY,
        prompts.V2_DEFAULT_INTRO,
        prompts.V2_EMAIL_VERIFY_NOTICE,
        prompts.V2_COLOUR_DISCLAIMER,
        prompts.V2_STALL_REPLY,
        prompts.V2_NUDGE_REPLY,
        prompts.V2_BACK_RESTART_ACK,
    ])
    return out


def test_no_v2_copy_points_below_the_cap():
    """The Adjust panel moved ABOVE the cap. Copy saying "under the cap" sends
    the customer looking at empty space — and on a phone that was exactly the
    bug this move fixes."""
    for s in _v2_copy_strings():
        assert "under the cap" not in s.lower(), f"stale toolbar position in: {s!r}"


def test_the_adjust_panel_is_named_where_the_customer_needs_it():
    """The tool tips are the only place a customer is told how to restyle what
    they placed, and they are concatenated verbatim (never through a model), so
    naming the panel there is what makes it discoverable."""
    for key in ("text", "shape"):
        assert "Adjust panel above the cap" in prompts.V2_TOOL_TIPS[key]
    assert "Adjust panel above the cap" in prompts.V2_BG_INSTRUCTIONS
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_copy_guards.py -q`
Expected: FAIL — both tests; `"under the cap"` is present in `V2_TOOL_TIPS["text"]`, `["shape"]`, `V2_BG_INSTRUCTIONS` and `LOGO_ADJUST.ask`.

- [ ] **Step 3: Rewrite the tool tips**

In `backend/app/prompts.py`, replace `V2_TOOL_TIPS` (lines 1084-1099):

```python
V2_TOOL_TIPS = {
    "upload": (
        'Select the highlighted "Upload image" button to add your logo. '
        "Once it's on the cap you can drag it to move it, pull a corner to "
        "resize, and use the top handle to rotate. Select the logo at any "
        "time to open the Adjust panel above the cap."
    ),
    "text": (
        'Select the highlighted "Add text" button, type your wording, then '
        "drag to position it.\n"
        "Select the text to open the Adjust panel above the cap, where you "
        "can change the font, size and colour."
    ),
    "shape": (
        'Select the highlighted "Graphics" button to drop in a shape, then '
        "drag to position and resize it. Select the shape to open the Adjust "
        "panel above the cap and recolour it."
    ),
}
```

- [ ] **Step 4: Rewrite `V2_BG_INSTRUCTIONS`**

Replace lines 1107-1111 (keep the comment block above it — it documents why this is not a `V2_TOOL_TIPS` entry and that the copy must not promise processing):

```python
V2_BG_INSTRUCTIONS = (
    "If it does, I'll mark it and we'll knock the background out when we "
    "render your design — the cap on screen won't change. You can also tick "
    'or untick "Remove background" yourself in the Adjust panel above the cap.'
)
```

- [ ] **Step 5: Rewrite `LOGO_ADJUST.ask`**

In `backend/app/services/conversation/canvas_steps.py`, replace the `ask=` of the `S.LOGO_ADJUST` step (lines 481-484):

```python
        ask=("I've opened the image picker for you. Once your logo is on the "
             "cap, drag to move it, pull a corner to resize, or rotate it. "
             "Select it to open the Adjust panel above the cap, where you'll "
             "also find the background-removal toggle. Select Done when the "
             "placement looks right."),
```

This step's `tip` is deliberately not appended for `LOGO_ADJUST` (`state_machine_v2.py:336`), which is why the instructions are spelled out in the ask itself.

- [ ] **Step 6: Run the guard test to verify it passes**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_copy_guards.py -q`
Expected: PASS (2 tests).

- [ ] **Step 7: Run the v2 suites for regressions**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_state_machine_v2.py tests/test_canvas_steps.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py -q`
Expected: PASS. These reference `V2_TOOL_TIPS[...]` by constant, not by literal, so rewording is safe.

- [ ] **Step 8: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/canvas_steps.py backend/tests/test_v2_copy_guards.py
git commit -m "fix(canvas-v2): copy points at the Adjust panel above the cap

The tips said 'the toolbar under the cap', which is now the wrong place and
was easy to miss even when it was right. Each tip now names the Adjust panel
and the interaction that opens it (select the element). Guard test pins it."
```

---

## Task 3: Formality pass over the v2 canvas copy

**Files:**
- Modify: `backend/app/prompts.py:1116-1119, 1125-1138, 1146-1149, 1158-1168, 1192-1214`
- Modify: `backend/app/services/conversation/canvas_steps.py` — `ask`/chip labels across `REGISTRY`
- Modify: `backend/tests/test_v2_copy_guards.py` (add the banned-phrase guard)
- Modify: `backend/tests/test_state_machine_v2.py:291, 324`; `backend/tests/test_canvas_steps.py:98, 439, 639`; `backend/tests/test_orchestrator_v2.py:163`; `backend/tests/test_v2_e2e.py:131-132`

**Interfaces:**
- Consumes: `_v2_copy_strings()` from Task 2's test module.
- Produces: two changed chip labels — `"No, that's all"` (was `"No, that's it"`) and `"No, it's fine as it is"` (was `"No, it's fine as is"`). Every other chip label is unchanged.

- [ ] **Step 1: Write the failing banned-phrase guard**

Append to `backend/tests/test_v2_copy_guards.py`:

```python
# Phrases from the pre-2026-07-26 casual register. Not a style engine — just a
# pin on the specific wording that was rewritten, so a later hand-edit that
# reintroduces the old voice fails loudly instead of shipping.
_CASUAL = ("pop your", "pop it", "grab your", "love where", "no worries",
           "are you after", "tap ")


def test_v2_copy_stays_out_of_the_casual_register():
    for s in _v2_copy_strings():
        low = s.lower()
        for phrase in _CASUAL:
            assert phrase not in low, f"casual phrasing {phrase!r} in: {s!r}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_copy_guards.py::test_v2_copy_stays_out_of_the_casual_register -q`
Expected: FAIL — first offender is `"How many caps are you after?"` (or another, depending on registry order).

- [ ] **Step 3: Rewrite the `prompts.py` v2 constants**

In `backend/app/prompts.py`, replace each constant's body (keep every surrounding comment — they document non-obvious constraints):

```python
V2_REWORK_INSTRUCTIONS = (
    "Every tool is open again — move, resize, add or remove anything you "
    "need, then select Done when you're happy with it."
)

V2_ASK_NAME = (
    "Welcome — I'm {persona}, your design assistant. I'll take you through "
    "putting your design onto the cap. To begin, may I have your name?"
)

V2_ASK_NAME_RETRY = (
    "Apologies, I didn't catch that — what name should I put on your design "
    "brief?"
)

V2_DEFAULT_INTRO = (
    "Welcome. I'll help you put your design onto the cap. We'll start with "
    "your logo, then add any text or graphics, and I'll guide you through "
    "each tool as we go."
)

V2_EMAIL_VERIFY_NOTICE = (
    "Thank you. I've sent a verification link to {email} — please open it to "
    "confirm your address so we can email your finished design there."
)

V2_COLOUR_DISCLAIMER = (
    "One note before we send this over, {name} — screen colours aren't "
    "always exact. What you see is a guide; our team matches your design to "
    "the closest embroidery and print colours.\n\n"
    "Reference charts — embroidery: {embroidery_url} · print: {print_url}\n\n"
    "If you already have a specific print colour (CMYK or Pantone) or an "
    "embroidery thread number, please enter it below and we'll use it — "
    "otherwise we'll match as closely as we can.\n\n"
    "Any final notes for the team? Type them here, or select "
    '"Nothing to add".'
)

V2_STALL_REPLY = (
    "Apologies — I didn't quite catch that. Could you say it once more?"
)

V2_NUDGE_REPLY = (
    "Apologies, I'm having trouble reading that one. Please select one of "
    "the options below and we'll continue."
)

V2_BACK_RESTART_ACK = (
    "Of course — I've removed that one so you can start it again."
)
```

And `V2_ACK_PROMPT` (line 1205) — this is where an otherwise-formal turn regains a casual tone, because the ack is prepended to every reply:

```python
V2_ACK_PROMPT = """You are {persona}, a professional cap-design assistant.

Write ONE short, courteous sentence acknowledging what the customer just told you. Then stop.

Keep it businesslike — no slang, no exclamation marks.

Do NOT ask a question. Do NOT give instructions. Do NOT mention buttons or tools — that copy is added separately.

We understood: {fields}

Reply with the sentence only.
"""
```

- [ ] **Step 4: Rewrite the registry copy**

In `backend/app/services/conversation/canvas_steps.py`, apply each of these (leave every surrounding comment intact; `LOGO_ADJUST` was already rewritten in Task 2 and is not touched again):

| Step | New `ask` |
|---|---|
| `SHOW_INTRO` | `"{intro}\n\nWhen you're ready, please select Continue."` |
| `ASK_HAS_LOGO` | `"Thank you, {name}. Do you have a logo or image you'd like on the cap?"` |
| `ASK_EMAIL` | `("You're making good progress, {name}. Could I take your email address so I can save your progress and send your finished design through?")` |
| `ASK_ANOTHER_LOGO` | `"That's saved. Would you like to add another logo?"` |
| `DECOR_ADJUST` | `"Select Done when you're happy with it."` |
| `ASK_QUANTITY` | `"How many caps do you need?"` |
| `ASK_DECORATION` | `("How would you like this decorated? Please choose the method that suits — our team will confirm what works best for your artwork. Select '{MIX_CHIP_LABEL}' if you need more than one method; please note that mixing costs more per hat.")` (keep the existing f-string interpolation of `MIX_CHIP_LABEL`) |
| `ASK_DECORATION_MIX` | `("Certainly — please tell me which methods you'd like and where each one goes, and I'll pass that straight to the team. (Mixing methods does add to the cost per hat.)")` |
| `ASK_PURPOSE` | `"Finally, may I ask what the caps are for?"` |
| `REVIEW_DESIGN` | `("Before I send this to our team, {name}, please take a moment to review your design across all the views. Are you happy with it, or would you like to rework anything?")` |
| `REWORK_CANVAS` | `("Please adjust anything you'd like on the canvas, then select Done and I'll bring you back to the review.")` |
| `FINALIZE_CANVAS` | `"Thank you — I'm putting your design together now…"` |

Two chip labels change (and only these two):

```python
        chips=(Chip("Yes, another logo", {"another_logo": True}),
               Chip("No, that's all", {"another_logo": False})),
```

```python
        chips=(Chip("Yes, remove background", {"logo_bg": "removed"}),
               Chip("No, it's fine as it is", {"logo_bg": "none"})),
```

`REQUEST_QUOTE` also needs its casual wording removed now, or the `"tap "` guard
fails this task. Give it the formal-but-not-yet-promising form; Task 4 replaces
the tail with the delivery promise:

```python
        ask=("Your design is ready, {name}. Select \"Request a quote\" below "
             "and our team will review it and prepare a quote."),
```

- [ ] **Step 5: Update the tests that type the old literals**

Five files, eight sites:

```python
# backend/tests/test_canvas_steps.py:98
    assert v2.resolve_chip(step, "No, that's all", {}) == {"another_logo": False}

# backend/tests/test_canvas_steps.py:439
    fields = v2.resolve_chip(step, "No, it's fine as it is", c)

# backend/tests/test_canvas_steps.py:639
    assert labels == ["Yes, remove background", "No, it's fine as it is"]

# backend/tests/test_orchestrator_v2.py:163
    assert res["data"]["options"] == ["Yes, another logo", "No, that's all"]

# backend/tests/test_state_machine_v2.py:291
    assert d["options"] == ["Yes, another logo", "No, that's all"]

# backend/tests/test_state_machine_v2.py:324
    assert out == "How many caps do you need?"

# backend/tests/test_v2_e2e.py:131-132
        ("No, it's fine as it is",  S.ASK_ANOTHER_LOGO),
        ("No, that's all",          S.ASK_ADD_DECOR),
```

- [ ] **Step 6: Run the guard and the v2 suites**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py -q`
Expected: PASS. If the banned-phrase guard still fails, the reported string names the file and constant — rewrite that one string; do not weaken `_CASUAL`.

- [ ] **Step 7: Run the whole backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q`
Expected: PASS (baseline on this branch is 1003 passing; this task adds 3 and changes no count elsewhere).

- [ ] **Step 8: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/canvas_steps.py backend/tests/
git commit -m "feat(canvas-v2): formal register across the canvas conversation

Rewrites the v2 step copy, shared constants and the ack prompt from the
casual voice ('Pop your logo on there', 'Love where this is going!') to a
warm-but-businesslike one. Two chip labels change; every test typing them
is updated in this commit. A banned-phrase guard pins the register."
```

---

## Task 4: Final stage states what the customer receives

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py` (new `bg_note_for` helper + `REQUEST_QUOTE.ask`)
- Modify: `backend/app/services/conversation/state_machine_v2.py:330-335` (`reply_for` format kwargs)
- Modify: `backend/app/prompts.py:806-818` (`QUOTE_REFERENCE_EMAIL_BODY`)
- Test: `backend/tests/test_state_machine_v2.py` (append)

**Interfaces:**
- Consumes: `collected["logos"]` (list of dicts, each optionally `{"bg": "removed" | "none"}`, written by `_apply_logo_bg` and banked by `_apply_another_logo`) and `collected["pending_logo"]` (same shape or `None`).
- Produces: `canvas_steps.bg_note_for(collected: dict) -> str` — returns `", with the logo background removed"` or `""`. Consumed by `state_machine_v2.reply_for` as the `bg_note` format kwarg.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_state_machine_v2.py` (the `_reply` helper already exists at line 305):

```python
def test_request_quote_promises_the_design_and_the_quote():
    out = _reply(S.REQUEST_QUOTE, {"name": "Sam"})
    assert "finished design" in out
    assert "quote" in out


def test_request_quote_promises_the_knockout_only_when_one_was_asked_for():
    """A customer who declined background removal must not be told their
    background was removed — the render only knocks out what was flagged."""
    asked = _reply(S.REQUEST_QUOTE,
                   {"name": "Sam", "logos": [{"face": "front", "bg": "removed"}]})
    assert "with the logo background removed" in asked

    declined = _reply(S.REQUEST_QUOTE,
                      {"name": "Sam", "logos": [{"face": "front", "bg": "none"}]})
    assert "background" not in declined
    assert "finished design, along with your quote" in declined


def test_bg_note_reads_a_still_pending_logo_too():
    """Defensive: by REQUEST_QUOTE the loop has banked every logo into `logos`,
    but reading pending_logo as well cannot be wrong and cannot be stale."""
    assert cs.bg_note_for({"pending_logo": {"bg": "removed"}}) != ""
    assert cs.bg_note_for({"pending_logo": None, "logos": []}) == ""
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_state_machine_v2.py -k "request_quote or bg_note" -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'bg_note_for'`, and the reply assertions fail because the current copy says only "they'll put together a quote and get back to you".

- [ ] **Step 3: Add the `bg_note_for` helper**

In `backend/app/services/conversation/canvas_steps.py`, add next to the other pure helpers (above `REGISTRY`):

```python
def bg_note_for(collected: dict) -> str:
    """The background clause for REQUEST_QUOTE's copy, or "" when none applies.

    "Remove background" is a per-logo MARK: only logos the customer flagged are
    knocked out at render. So a blanket "without the background" would be false
    for a customer who answered "No, it's fine as it is" — this reads the real
    state instead. Pure: `reply_for` calls it with `collected` alone.
    """
    logos = [l for l in (collected.get("logos") or []) if l]
    pending = collected.get("pending_logo")
    if pending:
        logos.append(pending)
    if any(l.get("bg") == "removed" for l in logos):
        return ", with the logo background removed"
    return ""
```

- [ ] **Step 4: Pass `bg_note` into `reply_for`**

In `backend/app/services/conversation/state_machine_v2.py`, extend the `.format()` call (lines 330-335):

```python
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
            colour_note=colour_note,
            # Computed here, not threaded through orchestrator_v2 like
            # colour_note: it needs only `collected`, so there is no store to
            # plumb. Unused kwargs are ignored by str.format, so no other
            # step's copy is affected.
            bg_note=cs.bg_note_for(collected),
        )
```

- [ ] **Step 5: Rewrite `REQUEST_QUOTE.ask`**

In `canvas_steps.py`, replace the `S.REQUEST_QUOTE` step's `ask=`:

```python
        ask=("Your design is ready, {name}. Select \"Request a quote\" below "
             "and our team will review it and email you your finished "
             "design{bg_note}, along with your quote."),
```

The chip label stays `"Request a quote"` — it is what the copy names, and label changes ripple into the e2e walk.

- [ ] **Step 6: Make the reference email agree**

In `backend/app/prompts.py`, replace `QUOTE_REFERENCE_EMAIL_BODY` (lines 808-818). The chat now promises the design arrives with the quote; the immediate email must not contradict that by mentioning only a quote:

```python
QUOTE_REFERENCE_EMAIL_BODY = """Hi {name},

Thank you for your request. We've received your design and our team is
reviewing it.

Your reference is: {reference_code}

Please quote the reference above if you get in touch. We'll be in touch soon
with your finished design and a quote for your caps.

— Ricardo, MadHats AI Design Studio
"""
```

Leave `QUOTE_REFERENCE_EMAIL_SUBJECT` and the "NO design image" comment above it unchanged — this email still carries no design. `email.py:298` formats it with `name` and `reference_code` only, so no new placeholder may be introduced.

- [ ] **Step 7: Run the new tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest tests/test_state_machine_v2.py -k "request_quote or bg_note" -q`
Expected: PASS (3 tests).

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false python -m pytest -q`
Expected: PASS. `test_v2_e2e.py`'s walk reaches `REQUEST_QUOTE` and types `"Request a quote"` — unchanged, so the walk must still be green.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/app/services/conversation/state_machine_v2.py backend/app/prompts.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): final step states the design arrives with the quote

REQUEST_QUOTE now tells the customer the team will email their finished
design along with the quote, and names the background knockout only when a
logo was actually flagged for it (bg_note_for reads the real per-logo state).
The reference email is reworded to match. No delivery behaviour changes:
the design is still not auto-emailed — the team sends it."
```

---

## Task 5: Verify in the browser

**Files:** none (verification only)

- [ ] **Step 1: Start the stack**

Run: `docker compose up -d` from the repo root, then open `https://localhost`.
If ports 80/443 are held on this Windows host, the dev Caddy aborts the whole stack — check with `netstat -ano | findstr ":443"` and stop the holder, or comment out the dev `caddy` service and use `http://localhost:5173`.

- [ ] **Step 2: Walk the canvas flow on a narrow viewport**

Open a canvas session (`?product_id=<id>`), set the browser to a 390×844 viewport, and walk: name → intro → "Yes, I have a logo" → Front → upload an image.

Confirm:
- the Adjust panel appears **above** the cap the moment the logo is selected, with a solid brand-accent header reading `Adjust — Image`
- it stays pinned when the canvas column is scrolled
- the chat instruction names "the Adjust panel above the cap"
- at `ask_logo_bg`, the logo is still selectable and "Remove background" is reachable in the panel

- [ ] **Step 3: Check the final step copy**

Continue to `REQUEST_QUOTE`. With a logo flagged for background removal, the copy must read "…email you your finished design, with the logo background removed, along with your quote." Repeat a session declining removal and confirm the clause is absent.

- [ ] **Step 4: Report**

Report what was confirmed and anything that did not match. Do not claim the flow works without having walked it.

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §3 Adjust panel placement (sticky, above, `max-h-[45vh]`) | 1 |
| §4 Appearance (accent header, element-type label, themeable) | 1 |
| §5 Chat points at the panel (5 copy sites) | 2 |
| §6 Formality pass (registry + constants + `V2_ACK_PROMPT` + 2 chip labels) | 3 |
| §7 Final-stage promise (`{bg_note}`, `reply_for`, reference email) | 4 |
| §8 Testing (frontend placement, backend guards, e2e updates) | 1, 2, 3, 4 |
| §2 Non-goals (no delivery changes) | Enforced by touching none of `delivery.py` |

**Placeholder scan:** none — every step carries the literal code or the exact command.

**Type consistency:** `bg_note_for(collected: dict) -> str` is defined in Task 4 Step 3 and consumed under that exact name in Step 4 (`cs.bg_note_for`) and in the Task 4 tests. `data-testid="adjust-panel"` / `"canvas-stage-wrap"` are introduced in Task 1 Steps 3-4 and used in Task 1 Step 1's test under the same names. `_v2_copy_strings()` is defined in Task 2 Step 1 and extended in Task 3 Step 1.
