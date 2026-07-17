# v2 Canvas Flow Gaps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close four gaps in the v2 canvas conversation — never asking about background removal, never asking where text/shapes go, marching a text-only customer through the logo loop, and never collecting the decoration method — by adding four steps to the v2 registry.

**Architecture:** Every change lives in the v2 registry (`canvas_steps.py`) and its generic engine (`state_machine_v2.py`). Routing is first-unmet resolution over `REGISTRY`, a pure function of `collected`, so almost every test is a plain dict. Three new `Step` capabilities (`instructions`, `chips_from` + `multiselect`, `prepare`) are added because the decoration options are store-scoped DB rows rather than literals. **No frontend change. No migration. v1 untouched.**

**Tech Stack:** Python 3.12, FastAPI, pytest, supabase-py.

**Spec:** `docs/superpowers/specs/2026-07-17-v2-canvas-flow-gaps-design.md`

## Global Constraints

- **Run tests with `CANVAS_ORCHESTRATOR_V2=false pytest -q`** — the repo-root `.env` default of `true` flips 3 unrelated tests red. Baseline is **660 passing**.
- **Work from `backend/`.** All paths below are relative to `C:\Users\satis\madhats-aidesign\backend`.
- **Task 1 must land first.** It changes `resolve_chip`'s signature, which every later task's tests use.
- **`ASK_LOGO_BG` MUST declare `tool="upload"`.** `Surface.tsx:111-113` locks every unlocked element when the flow leaves an editing step (`v2Editing = allowedTools.length > 0`), and `canvasStore.ts:36`: *"a locked layer can't be moved/resized/selected"*. The "Remove background" toggle lives in `SelectedToolbar`, which only renders for a **selected** element while `v2Editing` is true. Drop the tool and the customer is told to tick a toggle they cannot reach. Task 3 pins this with a test.
- **`auto_open` stays `None` on `ASK_LOGO_BG`** or the file picker reopens over the placed logo.
- **The interpreter must never write internal bookkeeping.** `WRITABLE_SLOTS` is derived from `Step.slots`; never add `logos`, `pending_logo`, `logos_done`, `email_captured`, `decoration_done` or `decoration_options` to a `slots` tuple.
- **Every new slot needs a `_SLOT_DOCS` entry** in `intent_extractor.py` — a slot missing from it is silently dropped from the interpreter prompt and the step re-asks forever. `test_every_writable_slot_is_documented_for_the_interpreter` enforces this.
- **Every new step needs a progress position** (`_PROGRESS_PATH` or `_PROGRESS_ANCHORS` resolving into it) or it silently reports "complete". `test_every_asking_step_has_a_progress_position` enforces this.
- **Chip labels are shipped to the browser and sent back verbatim.** A label and the fields it means are declared in the same `Chip(...)` literal — never re-derive a label's meaning by string-matching elsewhere.
- **Presence, not truthiness, for boolean/numeric answers**: `"has_logo" in c`, not `bool(c.get("has_logo"))` — `False` is a real answer.
- **Commit after each task.**

## Two deviations from the spec (discovered during planning)

1. **The cost caveat is NOT added to the ask copy.** The frontend already renders *"Heads up — each extra decoration adds to the cost, so pick only what you need."* whenever 2+ options are selected (`frontend/src/components/CustomiseStudio/ChatColumn.tsx:597-600`). Spec §3.F called for it in the copy upfront; that would duplicate it on screen. The ask says "Pick as many as apply" and the UI supplies the cost caveat contextually — which is also what CLAUDE.md documents ("a cost caveat when 2+ chosen").
2. **The `'none'` sentinel must resolve.** `ChatColumn.submitDeco:274` sends `decoSel.join(', ')`, or the literal `'none'` when the customer taps Continue with nothing selected. The spec didn't mention it. `'none'` is a string *we* ship, so Task 1 resolves it deterministically to an empty selection — otherwise it falls to the interpreter and stalls under `LLMUnavailable`.

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `app/services/conversation/state_machine.py` | the `ConversationState` enum | +3 states (Tasks 2-4) |
| `app/services/conversation/canvas_steps.py` | the registry: steps, chips, apply hooks | +4 steps, +4 `Step` fields, +apply/prepare hooks |
| `app/services/conversation/state_machine_v2.py` | the generic engine: routing, directives, copy | `_face` step-aware, `chips_of`, multiselect resolve, progress |
| `app/services/conversation/intent_extractor.py` | interpreter + slot validation | +4 `_SLOT_DOCS` entries |
| `app/services/conversation/orchestrator_v2.py` | per-turn driver | `prepare` hook, `resolve_chip` signature |
| `app/prompts.py` | all copy | +`V2_BG_INSTRUCTIONS`, text tip reflow |
| `tests/canvas_step_helpers.py` | registry-walk helper shared by two test modules | +4 `satisfy` branches |
| `tests/test_canvas_steps.py` | registry/routing unit tests (dicts only) | +tests per task |
| `tests/test_state_machine_v2.py` | directive/progress/chip-resolution tests | +tests per task |
| `tests/test_v2_e2e.py` | full front-half walk, no LLM | walk updated (Task 7) |

---

### Task 1: Registry capabilities — dynamic chips and multi-select resolution

**Files:**
- Modify: `app/services/conversation/canvas_steps.py` (`Step.chips_from`, `Step.multiselect`, `chips_of`)
- Modify: `app/services/conversation/state_machine_v2.py:110-160` (`public_data_for`, `resolve_chip`)
- Modify: `app/services/conversation/orchestrator_v2.py:64` (call site)
- Test: `tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: the existing `Chip`/`Step` dataclasses.
- Produces:
  - `canvas_steps.chips_of(step: Step, collected: dict) -> tuple[Chip, ...]`
  - `Step.chips_from: Callable[[dict], tuple[Chip, ...]] | None`
  - `Step.multiselect: bool`
  - `state_machine_v2.resolve_chip(step: Step, message: str, collected: dict) -> dict | None` — **signature changed**, gains `collected`. Every later task calls it with three arguments, which is why this task is first.

This task adds the mechanism only; Task 6 adds the step that uses it. It is tested here with an inline throwaway `Step`, so the two stay independently reviewable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_machine_v2.py`:

```python
def _multi_step():
    """A throwaway registry record — the mechanism is tested without depending
    on Task 6's ASK_DECORATION."""
    return cs.Step(
        id=S.ASK_DECORATION,
        ask="pick some",
        chips_from=lambda c: tuple(
            cs.Chip(n, {"decoration_types": [n]})
            for n in (c.get("decoration_options") or [])
        ),
        multiselect=True,
        slots=("decoration_types",),
        done_when=lambda c: False,
    )


def test_chips_from_builds_chips_out_of_collected():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    labels = [ch.label for ch in cs.chips_of(_multi_step(), c)]
    assert labels == ["Embroidery", "Screen Print"]


def test_static_chips_are_unaffected_by_chips_of():
    step = cs.by_id(S.ASK_QUANTITY)
    assert cs.chips_of(step, {}) == step.chips


def test_multiselect_resolves_a_comma_joined_selection_in_order():
    """The UI ships `decoSel.join(', ')` (ChatColumn.submitDeco:274)."""
    c = {"decoration_options": ["Embroidery", "Screen Print", "Vinyl"]}
    fields = v2.resolve_chip(_multi_step(), "Screen Print, Embroidery", c)
    assert fields == {"decoration_types": ["Screen Print", "Embroidery"]}


def test_multiselect_drops_tokens_that_were_never_offered():
    c = {"decoration_options": ["Embroidery"]}
    fields = v2.resolve_chip(_multi_step(), "Embroidery, Sublimation", c)
    assert fields == {"decoration_types": ["Embroidery"]}


def test_multiselect_resolves_the_uis_empty_continue_sentinel():
    """Continue with nothing selected sends the literal 'none'. It is a string
    WE ship, so it must resolve deterministically — otherwise it falls through
    to the interpreter and stalls under LLMUnavailable."""
    c = {"decoration_options": ["Embroidery"]}
    assert v2.resolve_chip(_multi_step(), "none", c) == {"decoration_types": []}


def test_multiselect_free_text_falls_through_to_the_interpreter():
    c = {"decoration_options": ["Embroidery"]}
    assert v2.resolve_chip(_multi_step(), "whatever looks best", c) is None


def test_public_data_marks_a_multiselect_step_for_the_frontend():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    data = v2.public_data_for(_multi_step(), c)
    assert data["options"] == ["Embroidery", "Screen Print"]
    assert data["multiselect"] is True
    assert data["selected"] == []


def test_public_data_does_not_mark_a_single_select_step_as_multiselect():
    data = v2.public_data_for(cs.by_id(S.ASK_QUANTITY), {})
    assert "multiselect" not in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_state_machine_v2.py -k "multiselect or chips_of or chips_from" -v`
Expected: FAIL — `TypeError: Step.__init__() got an unexpected keyword argument 'chips_from'`.

- [ ] **Step 3: Add the `Step` fields and `chips_of`**

In `canvas_steps.py`, add to the `Step` dataclass (after `chips`):

```python
    # Chips that can't be literals because they come from store-scoped data.
    # `chips_of` is the single read path, so a dynamic step is invisible to
    # every consumer (public_data_for, resolve_chip) — they just ask for chips.
    chips_from: Callable[[dict], tuple[Chip, ...]] | None = None
    # The customer may pick several. The UI comma-joins the labels it was given
    # (ChatColumn.submitDeco:274), so resolution stays an identity lookup on the
    # closed set we shipped — just one per token instead of one per message.
    multiselect: bool = False
```

Add after `by_id`:

```python
def chips_of(step: Step, collected: dict) -> tuple[Chip, ...]:
    """The step's chips — derived from `collected` when they can't be literals."""
    return step.chips_from(collected) if step.chips_from else step.chips
```

- [ ] **Step 4: Resolve dynamic + multi-select chips**

In `state_machine_v2.py`, replace `resolve_chip` and add `_resolve_multi`:

```python
def resolve_chip(step: Step, message: str, collected: dict) -> dict | None:
    """The fields for an offered chip, or None if `message` isn't one of them.

    A chip tap is not natural language: we generated the label in this registry
    and shipped it to the browser, which sent it straight back. Matching it is an
    identity lookup on a closed set we own — no model, no latency, no failure
    mode. Only the CURRENT step's chips match; a stale chip tapped on an older
    message falls through to the interpreter, which reads it in context.
    """
    chips = cs.chips_of(step, collected)
    if step.multiselect:
        return _resolve_multi(step, chips, message)
    target = _norm(message)
    for chip in chips:
        if _norm(chip.label) == target:
            return dict(chip.fields)
    return None


def _resolve_multi(step: Step, chips: tuple[cs.Chip, ...], message: str) -> dict | None:
    """A multi-select submission: the labels we shipped, comma-joined.

    Both strings the UI can send here are ours: `decoSel.join(', ')` and the
    literal 'none' when Continue is tapped with nothing selected
    (ChatColumn.submitDeco:274). Anything else is free text and belongs to the
    interpreter, so this returns None for it.
    """
    if _norm(message) == "none":
        return {slot: [] for slot in step.slots}
    by_label = {_norm(c.label): c for c in chips}
    out: dict = {}
    matched = False
    for tok in message.split(","):
        chip = by_label.get(_norm(tok))
        if chip is None:
            continue
        matched = True
        for key, val in chip.fields.items():
            if isinstance(val, list):
                cur = out.setdefault(key, [])
                cur.extend(v for v in val if v not in cur)
            else:
                out[key] = val
    return out if matched else None
```

In `public_data_for`, replace the chips block:

```python
    chips = cs.chips_of(step, collected)
    if chips:
        data["options"] = [c.label for c in chips]
    if step.multiselect:
        # The shape ChatColumn's multi-select already consumes from v1.
        data["multiselect"] = True
        data["selected"] = []
```

- [ ] **Step 5: Update the orchestrator call site**

In `orchestrator_v2.py`, in `handle_message`:

```python
    fields = v2.resolve_chip(step, message, collected)
```

- [ ] **Step 6: Run the full suite**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest -q`
Expected: PASS (660). If any existing test calls `resolve_chip` with two arguments, update it to pass `collected` (`{}` where the step's chips are static).

- [ ] **Step 7: Commit**

```bash
git add app/services/conversation/canvas_steps.py app/services/conversation/state_machine_v2.py app/services/conversation/orchestrator_v2.py tests/test_state_machine_v2.py
git commit -m "feat(v2): registry supports dynamic chips and multi-select steps"
```

---

### Task 2: `ASK_HAS_LOGO` — a text-only customer can skip the logo loop

**Files:**
- Modify: `app/services/conversation/state_machine.py:39-47` (v2 state block)
- Modify: `app/services/conversation/canvas_steps.py` (apply hook + step + `REGISTRY`)
- Modify: `app/services/conversation/intent_extractor.py:620-632` (`_SLOT_DOCS`)
- Modify: `app/services/conversation/state_machine_v2.py:41-50` (`_PROGRESS_ANCHORS`)
- Modify: `tests/canvas_step_helpers.py:24-44` (`satisfy`)
- Test: `tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: `resolve_chip(step, message, collected)` from Task 1.
- Produces: `ConversationState.ASK_HAS_LOGO`; `canvas_steps._apply_has_logo(c: dict, f: dict, s: dict) -> None`; slot `has_logo: bool`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canvas_steps.py`:

```python
def test_no_logo_skips_the_entire_logo_branch():
    """has_logo=False sets logos_done, and every logo step's done_when already
    short-circuits on `not _logos_open(c)` — so first-unmet skips all four with
    no new routing."""
    c = {"name": "Sam", "intro_ack": True}
    step = cs.by_id(S.ASK_HAS_LOGO)
    fields = v2.resolve_chip(step, "No — text only", c)
    assert fields == {"has_logo": False}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_has_logo_routes_into_the_logo_loop():
    c = {"name": "Sam", "intro_ack": True}
    step = cs.by_id(S.ASK_HAS_LOGO)
    fields = v2.resolve_chip(step, "Yes, I have a logo", c)
    assert fields == {"has_logo": True}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_ask_has_logo_is_satisfied_by_a_false_answer():
    """Presence, not truthiness — bool(False) is False, which would re-ask
    forever (the bug already fixed on ASK_ANYTHING_ELSE and ASK_QUANTITY)."""
    assert cs.by_id(S.ASK_HAS_LOGO).done_when({"has_logo": False})
    assert not cs.by_id(S.ASK_HAS_LOGO).done_when({})
```

`tests/test_canvas_steps.py` already imports `canvas_steps as cs` and `ConversationState as S`. Add this import at the top if absent:

```python
from app.services.conversation import state_machine_v2 as v2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py -k has_logo -v`
Expected: FAIL — `AttributeError: ASK_HAS_LOGO` (the enum member does not exist).

- [ ] **Step 3: Add the state**

In `app/services/conversation/state_machine.py`, in the v2 block (after `SHOW_INTRO = "show_intro"`):

```python
    ASK_HAS_LOGO = "ask_has_logo"
```

- [ ] **Step 4: Add the apply hook and the step**

In `app/services/conversation/canvas_steps.py`, add after `_apply_intro`:

```python
def _apply_has_logo(c: dict, f: dict, s: dict) -> None:
    """A text-only customer closes the logo loop before it opens.

    Every logo step's done_when short-circuits on `not _logos_open(c)`, so
    setting logos_done here makes first-unmet skip all four by itself — no
    branch, no back-edge. `has_logo is False` (not falsy) because the slot is
    absent until answered.
    """
    if f.get("has_logo") is False:
        c["logos_done"] = True
        c["pending_logo"] = None
```

In `REGISTRY`, insert between the `SHOW_INTRO` and `ASK_LOGO_PLACEMENT` records:

```python
    Step(
        id=S.ASK_HAS_LOGO,
        ask="Great, {name}! Do you have a logo or image you'd like on the cap?",
        chips=(Chip("Yes, I have a logo", {"has_logo": True}),
               Chip("No — text only", {"has_logo": False})),
        slots=("has_logo",),
        apply=_apply_has_logo,
        # Presence, not truthiness: False is a real answer.
        done_when=lambda c: "has_logo" in c,
    ),
```

Change the `ASK_LOGO_PLACEMENT` record's `ask` (it no longer opens the logo topic — this step does):

```python
        ask="Which part of the cap should it go on — front, back, left or right?",
```

- [ ] **Step 5: Document the slot for the interpreter**

In `app/services/conversation/intent_extractor.py`, add to `_SLOT_DOCS`:

```python
    "has_logo": "has_logo (bool) — true if they have a logo/image to upload, false if they want text only",
```

- [ ] **Step 6: Give the step a progress position**

In `app/services/conversation/state_machine_v2.py`, add to `_PROGRESS_ANCHORS`:

```python
    S.ASK_HAS_LOGO: S.ASK_LOGO_PLACEMENT,
```

- [ ] **Step 7: Teach the shared test helper to satisfy it**

In `tests/canvas_step_helpers.py`, inside `satisfy`, add before the `ASK_LOGO_PLACEMENT` branch:

```python
    elif step.id is S.ASK_HAS_LOGO:
        c["has_logo"] = True
```

- [ ] **Step 8: Run the full backend suite**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest -q`
Expected: PASS, except `tests/test_v2_e2e.py` — its walk does not yet answer this step; Task 7 updates it. If it is the only failure, that is expected at this point.

- [ ] **Step 9: Commit**

```bash
git add app/services/conversation/state_machine.py app/services/conversation/canvas_steps.py app/services/conversation/intent_extractor.py app/services/conversation/state_machine_v2.py tests/canvas_step_helpers.py tests/test_canvas_steps.py
git commit -m "feat(v2): ask whether the customer has a logo before the logo loop"
```

---

### Task 3: `ASK_LOGO_BG` — ask about background removal

**Files:**
- Modify: `app/services/conversation/state_machine.py` (v2 state block)
- Modify: `app/prompts.py:1035-1050` (add `V2_BG_INSTRUCTIONS` after `V2_TOOL_TIPS`)
- Modify: `app/services/conversation/canvas_steps.py` (`Step.instructions`, apply hook, step, `SLOT_ENUMS`)
- Modify: `app/services/conversation/state_machine_v2.py:85-101` (`directive_for`)
- Modify: `app/services/conversation/intent_extractor.py` (`_SLOT_DOCS`)
- Modify: `tests/canvas_step_helpers.py`
- Test: `tests/test_canvas_steps.py`, `tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `resolve_chip(step, message, collected)` (Task 1); `ASK_HAS_LOGO` (Task 2 — `satisfy` must set `has_logo` for the walk to reach this step).
- Produces: `ConversationState.ASK_LOGO_BG`; `Step.instructions: str | None`; `canvas_steps._apply_logo_bg`; slot `logo_bg` ∈ `{"removed", "none"}`; `prompts.V2_BG_INSTRUCTIONS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canvas_steps.py`:

```python
def test_logo_bg_is_asked_after_the_logo_is_placed_and_before_another_logo():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    assert v2.next_step(c).id is S.ASK_LOGO_BG

    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "Yes, I've removed it", c)
    assert fields == {"logo_bg": "removed"}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["pending_logo"]["bg"] == "removed"
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_bg_declined_still_satisfies_the_step():
    c = {"name": "Sam", "intro_ack": True, "has_logo": True,
         "pending_logo": {"face": "front", "placed": True}}
    step = cs.by_id(S.ASK_LOGO_BG)
    fields = v2.resolve_chip(step, "No, it's fine as is", c)
    assert fields == {"logo_bg": "none"}
    c.update(fields)
    step.apply(c, fields, {})
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_bg_is_skipped_when_there_is_no_logo():
    c = {"name": "Sam", "intro_ack": True, "has_logo": False,
         "logos_done": True, "pending_logo": None}
    assert cs.by_id(S.ASK_LOGO_BG).done_when(c)
```

Append to `tests/test_state_machine_v2.py`:

```python
def test_ask_logo_bg_keeps_a_tool_allowed_so_the_logo_stays_selectable():
    """LOAD-BEARING. Surface.tsx:111-113 locks every unlocked element when the
    flow leaves an editing step (v2Editing = allowedTools.length > 0), and a
    locked layer can't be selected (canvasStore.ts:36). The "Remove background"
    toggle lives in SelectedToolbar, which only renders for a SELECTED element.
    Drop this tool and the customer is told to tick a toggle they cannot reach —
    a failure invisible from the backend. Do not "tidy" the tool away.
    """
    step = cs.by_id(S.ASK_LOGO_BG)
    d = v2.directive_for(step, {"pending_logo": {"face": "back", "placed": True}})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] is None          # or the file picker reopens
    assert d["target_face"] == "back"
    assert d["instructions"] == prompts.V2_BG_INSTRUCTIONS   # not the upload tip


def test_ask_logo_bg_copy_does_not_append_the_upload_tip():
    step = cs.by_id(S.ASK_LOGO_BG)
    reply = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="hi")
    assert "Upload image" not in reply
    assert "background" in reply.lower()
```

`tests/test_state_machine_v2.py` already imports `canvas_steps as cs`, `state_machine_v2 as v2` and `ConversationState as S`. Add if absent:

```python
from app import prompts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py -k logo_bg -v`
Expected: FAIL — `AttributeError: ASK_LOGO_BG`.

- [ ] **Step 3: Add the state and the copy**

In `app/services/conversation/state_machine.py`, in the v2 block after `ASK_ANOTHER_LOGO`:

```python
    ASK_LOGO_BG = "ask_logo_bg"
```

In `app/prompts.py`, immediately after the `V2_TOOL_TIPS` dict:

```python
# The canvas instruction for ASK_LOGO_BG. Not a V2_TOOL_TIPS entry: those are
# keyed by TOOL, and this step hands over the upload tool only to keep the
# placed logo selectable (see Step.instructions / the lock note on the step) —
# the upload tip's "tap Upload image" would be actively wrong here.
V2_BG_INSTRUCTIONS = (
    "Click your logo on the cap to select it, then tick \"Remove background\" "
    "in the toolbar underneath. Give it a few seconds to process."
)
```

- [ ] **Step 4: Add `Step.instructions`, the apply hook, and the step**

In `app/services/conversation/canvas_steps.py`, add to the `Step` dataclass (after `tip`):

```python
    instructions: str | None = None            # overrides V2_TOOL_TIPS[tool] in the directive
```

Add after `_apply_logo_placed`:

```python
def _apply_logo_bg(c: dict, f: dict, s: dict) -> None:
    bg = f.get("logo_bg")
    if bg and c.get("pending_logo") is not None:
        c["pending_logo"]["bg"] = bg
```

Insert into `REGISTRY` between `LOGO_ADJUST` and `ASK_ANOTHER_LOGO`:

```python
    Step(
        id=S.ASK_LOGO_BG,
        ask=("Does your logo have a background that needs removing? If it does, "
             "click it on the cap and tick \"Remove background\" in the toolbar "
             "underneath — I'll wait."),
        chips=(Chip("Yes, I've removed it", {"logo_bg": "removed"}),
               Chip("No, it's fine as is", {"logo_bg": "none"})),
        slots=("logo_bg",),
        apply=_apply_logo_bg,
        done_when=lambda c: not _logos_open(c) or "bg" in _pending(c),
        # tool="upload" is LOAD-BEARING, not decoration: it keeps v2Editing true
        # on the frontend, so the just-placed logo is NOT locked and stays
        # selectable — which is the only way the customer can reach the
        # "Remove background" toggle in SelectedToolbar. The lock fires on
        # ASK_ANOTHER_LOGO instead. See Surface.tsx:111-113 + canvasStore.ts:36.
        tool="upload",
        tip=None,                              # the upload tip is wrong here
        instructions=prompts.V2_BG_INSTRUCTIONS,
        auto_open=None,                        # or the file picker reopens
        show_done=False,
        face_target=True,
    ),
```

Add to `SLOT_ENUMS`:

```python
    "logo_bg": frozenset({"removed", "none"}),
```

- [ ] **Step 5: Honour `instructions` in the directive**

In `app/services/conversation/state_machine_v2.py`, in `directive_for`, replace the `instructions` line:

```python
        "instructions": step.instructions or prompts.V2_TOOL_TIPS[tool],
```

- [ ] **Step 6: Document the slot**

In `intent_extractor.py`, add to `_SLOT_DOCS`:

```python
    "logo_bg": "logo_bg (one of: removed, none) — 'removed' if they removed the logo's background, 'none' if it doesn't need it",
```

- [ ] **Step 7: Progress anchor + test helper**

In `state_machine_v2.py`, add to `_PROGRESS_ANCHORS`:

```python
    S.ASK_LOGO_BG: S.ASK_LOGO_PLACEMENT,
```

In `tests/canvas_step_helpers.py`, add to `satisfy` before the `ASK_ANOTHER_LOGO` branch:

```python
    elif step.id is S.ASK_LOGO_BG:
        c.setdefault("pending_logo", {})["bg"] = "none"
```

- [ ] **Step 8: Run the tests**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add app/services/conversation/state_machine.py app/prompts.py app/services/conversation/canvas_steps.py app/services/conversation/state_machine_v2.py app/services/conversation/intent_extractor.py tests/canvas_step_helpers.py tests/test_canvas_steps.py tests/test_state_machine_v2.py
git commit -m "feat(v2): ask about logo background removal without locking the logo"
```

---

### Task 4: `ASK_DECOR_PLACEMENT` — ask where text/shapes go (and fix the always-front bug)

**Files:**
- Modify: `app/services/conversation/state_machine.py` (v2 state block)
- Modify: `app/services/conversation/canvas_steps.py` (step, `SLOT_ENUMS`, `_apply_anything_else`)
- Modify: `app/services/conversation/state_machine_v2.py:76-101` (`_face`, `directive_for`)
- Modify: `app/services/conversation/intent_extractor.py` (`_SLOT_DOCS`)
- Modify: `tests/canvas_step_helpers.py`
- Test: `tests/test_canvas_steps.py`, `tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `resolve_chip(step, message, collected)` (Task 1).
- Produces: `ConversationState.ASK_DECOR_PLACEMENT`; slot `decor_face` ∈ `FACES`; `state_machine_v2._face(step, collected)` — **signature changed** from `_face(collected)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canvas_steps.py`:

```python
def _decor_seed() -> dict:
    return {"name": "Sam", "intro_ack": True, "has_logo": False,
            "logos_done": True, "pending_logo": None}


def test_decor_placement_is_asked_before_the_decor_tool_opens():
    c = _decor_seed()
    c["decor_choice"] = "text"
    assert v2.next_step(c).id is S.ASK_DECOR_PLACEMENT

    step = cs.by_id(S.ASK_DECOR_PLACEMENT)
    fields = v2.resolve_chip(step, "Back", c)
    assert fields == {"decor_face": "back"}
    c.update(fields)
    assert v2.next_step(c).id is S.DECOR_ADJUST


def test_adding_a_second_decoration_re_asks_the_face():
    """_apply_anything_else must clear decor_face too, or the second decoration
    silently reuses the first one's face."""
    c = _decor_seed()
    c.update({"decor_choice": "text", "decor_face": "back", "decor_placed": True})
    step = cs.by_id(S.ASK_ANYTHING_ELSE)
    fields = v2.resolve_chip(step, "Add something else", c)
    c.update(fields)
    step.apply(c, fields, {})
    assert "decor_face" not in c
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_decor_placement_is_skipped_when_no_decoration_is_wanted():
    assert cs.by_id(S.ASK_DECOR_PLACEMENT).done_when({"decor_done": True})
```

Append to `tests/test_state_machine_v2.py`:

```python
def test_decor_adjust_targets_the_face_the_customer_named():
    """Regression: DECOR_ADJUST has always set face_target=True while _face()
    read pending_logo — which is None once the logo loop closes — so text
    silently always targeted "front"."""
    c = {"logos_done": True, "pending_logo": None,
         "decor_choice": "text", "decor_face": "left"}
    d = v2.directive_for(cs.by_id(S.DECOR_ADJUST), c)
    assert d["target_face"] == "left"
    assert d["allowed_tools"] == ["text"]


def test_decor_adjust_targets_the_named_face_for_a_shape_too():
    c = {"logos_done": True, "pending_logo": None,
         "decor_choice": "shape", "decor_face": "right"}
    d = v2.directive_for(cs.by_id(S.DECOR_ADJUST), c)
    assert d["target_face"] == "right"
    assert d["allowed_tools"] == ["shape"]


def test_logo_steps_still_read_the_logo_face():
    """_face is now step-aware; the logo branch must be unaffected."""
    c = {"pending_logo": {"face": "back"}, "decor_face": "left"}
    d = v2.directive_for(cs.by_id(S.LOGO_ADJUST), c)
    assert d["target_face"] == "back"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py -k "decor_placement or decor_adjust_targets or second_decoration or logo_face" -v`
Expected: FAIL — `AttributeError: ASK_DECOR_PLACEMENT`, and `test_decor_adjust_targets_the_face_the_customer_named` fails with `target_face == 'front'` (the live bug).

- [ ] **Step 3: Add the state**

In `state_machine.py`, in the v2 block after `ASK_ADD_DECOR`:

```python
    ASK_DECOR_PLACEMENT = "ask_decor_placement"
```

- [ ] **Step 4: Add the step and clear `decor_face` on loop**

In `canvas_steps.py`, insert into `REGISTRY` between `ASK_ADD_DECOR` and `DECOR_ADJUST`:

```python
    Step(
        id=S.ASK_DECOR_PLACEMENT,
        ask="Which part of the cap should it go on — front, back, left or right?",
        chips=(Chip("Front", {"decor_face": "front"}),
               Chip("Back", {"decor_face": "back"}),
               Chip("Left", {"decor_face": "left"}),
               Chip("Right", {"decor_face": "right"})),
        slots=("decor_face",),
        done_when=lambda c: bool(c.get("decor_done")) or c.get("decor_face") in FACES,
        # Mirrors ASK_LOGO_PLACEMENT: hand the tool over (highlighted) but do
        # NOT auto-open it until the face is answered, or the decoration lands
        # on whatever face is already active.
        tool="text",                           # resolved per decor_choice at runtime
        tip=None,
        auto_open=None,
        face_target=True,
    ),
```

In `_apply_anything_else`, add `"decor_face"` to the cleared keys:

```python
    if f.get("more_decor"):
        for k in ("decor_choice", "decor_face", "decor_placed", "more_decor",
                  "decor_done"):
            c.pop(k, None)
```

Add to `SLOT_ENUMS`:

```python
    "decor_face": FACES,
```

- [ ] **Step 5: Make `_face` step-aware and resolve the decor tool for both decor steps**

In `state_machine_v2.py`, replace `_face` and `_decor_tool`:

```python
# The decor branch's steps. They read `decor_face`; the logo branch reads the
# pending logo's face. DECOR_ADJUST always set face_target=True but _face read
# pending_logo — which is None once the logo loop closes — so text silently
# always targeted "front".
_DECOR_STEPS: frozenset[S] = frozenset({S.ASK_DECOR_PLACEMENT, S.DECOR_ADJUST})


def _face(step: Step, collected: dict) -> str:
    if step.id in _DECOR_STEPS:
        face = collected.get("decor_face")
    else:
        face = (collected.get("pending_logo") or {}).get("face")
    return face if face in cs.FACES else "front"


def _decor_tool(collected: dict) -> str:
    return "shape" if collected.get("decor_choice") == "shape" else "text"
```

In `directive_for`, update the two call sites:

```python
    tool = _decor_tool(collected) if step.id in _DECOR_STEPS else step.tool
    return {
        "allowed_tools": [tool],
        "target_face": _face(step, collected) if step.face_target else None,
        "auto_open": tool if step.auto_open else None,
        "instructions": step.instructions or prompts.V2_TOOL_TIPS[tool],
        "show_done": step.show_done,
    }
```

`reply_for`'s `DECOR_ADJUST` branch is unchanged (`ASK_DECOR_PLACEMENT` sets `tip=None`, so it falls through the normal path and appends nothing).

- [ ] **Step 6: Document the slot, add the progress anchor and the test helper**

In `intent_extractor.py`, add to `_SLOT_DOCS`:

```python
    "decor_face": "decor_face (one of: front, back, left, right) — where the text/shape goes",
```

In `state_machine_v2.py`, add to `_PROGRESS_ANCHORS`:

```python
    S.ASK_DECOR_PLACEMENT: S.ASK_ADD_DECOR,
```

In `tests/canvas_step_helpers.py`, add to `satisfy` before the `DECOR_ADJUST` branch:

```python
    elif step.id is S.ASK_DECOR_PLACEMENT:
        c["decor_face"] = "front"
```

- [ ] **Step 7: Run the tests**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services/conversation/state_machine.py app/services/conversation/canvas_steps.py app/services/conversation/state_machine_v2.py app/services/conversation/intent_extractor.py tests/canvas_step_helpers.py tests/test_canvas_steps.py tests/test_state_machine_v2.py
git commit -m "feat(v2): ask where text/shapes go; fix decor target_face always resolving to front"
```

---

### Task 5: Copy — the logo loop stops repeating itself, and the styling tip stands alone

**Files:**
- Modify: `app/services/conversation/canvas_steps.py` (`ASK_LOGO_PLACEMENT.ask_retry`)
- Modify: `app/prompts.py:1041-1045` (`V2_TOOL_TIPS["text"]`)
- Test: `tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `ASK_LOGO_PLACEMENT` (its `ask` was rewritten in Task 2).
- Produces: nothing new — copy only.

Context: in the reviewed session the second logo re-asked with the first ask **verbatim** ("Great, Satish! Let's add your logo…"), reading as a reset. `reply_for` already selects `ask_retry` when the step id is in `collected["_asked"]`, which is true from the second logo onward. The copy must read correctly in **both** senses — a re-ask after an unparsed answer, and the next logo.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_state_machine_v2.py`:

```python
def test_the_second_logo_does_not_repeat_the_first_ask_verbatim():
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)
    first = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="hi")
    second = v2.reply_for(step, {"name": "Sam", "_asked": ["ask_logo_placement"]},
                          persona="Ricardo", intro="hi")
    assert first != second
    assert "this one" in second.lower()


def test_the_text_tip_puts_the_styling_instruction_on_its_own_line():
    """The tip already named font/size/colour, but as a trailing clause the
    customer read straight past it."""
    tip = prompts.V2_TOOL_TIPS["text"]
    lines = [l for l in tip.split("\n") if l.strip()]
    assert len(lines) == 2
    assert "size" in lines[1] and "colour" in lines[1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_state_machine_v2.py -k "second_logo or styling_instruction" -v`
Expected: FAIL — `first == second` (no `ask_retry`), and the tip is one line.

- [ ] **Step 3: Add the loop-aware re-ask**

In `canvas_steps.py`, add to the `ASK_LOGO_PLACEMENT` record (after `ask=`):

```python
        # Fires from the SECOND logo onward (reply_for selects ask_retry once the
        # step id is in `_asked`) and also on a genuine re-ask — the copy must
        # read correctly for both. The first ask opened the topic; repeating it
        # verbatim read as a reset rather than a second logo.
        ask_retry="Where should this one go — front, back, left or right?",
```

- [ ] **Step 4: Reflow the text tip**

In `app/prompts.py`, replace the `"text"` entry of `V2_TOOL_TIPS`:

```python
    "text": (
        'Tap the highlighted "Add text" button, type your wording, then drag '
        "to position it.\n"
        "You can change the font, size and colour from the toolbar under the cap."
    ),
```

- [ ] **Step 5: Run the tests**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_state_machine_v2.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/conversation/canvas_steps.py app/prompts.py tests/test_state_machine_v2.py
git commit -m "fix(v2): loop-aware logo re-ask; put the text styling tip on its own line"
```

---

### Task 6: `ASK_DECORATION` — collect the decoration method after quantity

**Files:**
- Modify: `app/services/conversation/canvas_steps.py` (`Step.prepare`, hooks, step)
- Modify: `app/services/conversation/state_machine_v2.py:47-50` (`_PROGRESS_PATH`)
- Modify: `app/services/conversation/orchestrator_v2.py:96` (run `prepare`)
- Modify: `app/services/conversation/intent_extractor.py` (`_SLOT_DOCS`)
- Modify: `tests/canvas_step_helpers.py`
- Test: `tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: `chips_of`, `Step.chips_from`, `Step.multiselect`, `resolve_chip(step, message, collected)` — all from Task 1.
- Produces: `Step.prepare: Callable[[dict, dict | None], None] | None`; `canvas_steps._prepare_decoration(c, store)`; `canvas_steps._apply_decoration(c, f, s)`; slot `decoration_types: list[str]`; sets `collected["decoration_type"]` (the render-style bucket the prompt builder reads).

`ConversationState.ASK_DECORATION` already exists (v1 uses it) — no enum change.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_canvas_steps.py`:

```python
def _quantity_done() -> dict:
    return {"name": "Sam", "intro_ack": True, "has_logo": False,
            "logos_done": True, "pending_logo": None, "decor_done": True,
            "quantity": 50}


def test_decoration_is_asked_after_quantity_and_before_email():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    assert v2.next_step(c).id is S.ASK_DECORATION


def test_decoration_chips_come_from_the_stores_active_methods():
    c = {"decoration_options": ["Embroidery", "Screen Print"]}
    labels = [ch.label for ch in cs.chips_of(cs.by_id(S.ASK_DECORATION), c)]
    assert labels == ["Embroidery", "Screen Print"]


def test_choosing_decorations_sets_the_brief_and_the_render_style_bucket():
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = v2.resolve_chip(step, "Embroidery, Screen Print", c)
    c.update(fields)
    step.apply(c, fields, {})

    assert c["decoration_types"] == ["Embroidery", "Screen Print"]
    # The customer's FIRST choice drives the render style.
    assert c["decoration_type"] == "embroidery"
    assert "Decoration method: Embroidery, Screen Print" in c["brief_notes"]
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_decoration_names_not_offered_by_the_store_never_reach_the_brief():
    """decoration_types is store-dynamic so it cannot go in SLOT_ENUMS — this
    filter IS the interpreter guard."""
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = {"decoration_types": ["Sublimation", "Embroidery"]}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["decoration_types"] == ["Embroidery"]


def test_a_decoration_answer_as_a_bare_string_is_still_filtered():
    """The interpreter may return a string rather than a list."""
    c = _quantity_done()
    c["decoration_options"] = ["Embroidery", "Screen Print"]
    step = cs.by_id(S.ASK_DECORATION)
    fields = {"decoration_types": "Screen Print"}
    c.update(fields)
    step.apply(c, fields, {})
    assert c["decoration_types"] == ["Screen Print"]
    assert c["decoration_type"] == "print"


def test_prepare_loads_the_stores_active_methods_once(monkeypatch):
    calls = []

    def _fake(store_id, active_only=False):
        calls.append(store_id)
        return [{"name": "Embroidery"}, {"name": "Vinyl"}]

    monkeypatch.setattr("app.services.decoration_types.list_types", _fake)
    c = _quantity_done()
    step = cs.by_id(S.ASK_DECORATION)
    step.prepare(c, {"id": "store-1"})
    assert c["decoration_options"] == ["Embroidery", "Vinyl"]

    step.prepare(c, {"id": "store-1"})          # already loaded
    assert calls == ["store-1"]


def test_a_store_with_no_decoration_methods_skips_the_step(monkeypatch):
    """No options means no chips and no way to answer — that would dead-end the
    funnel just before the email step."""
    monkeypatch.setattr("app.services.decoration_types.list_types",
                        lambda *a, **k: [])
    c = _quantity_done()
    step = cs.by_id(S.ASK_DECORATION)
    step.prepare(c, {"id": "store-1"})
    assert step.done_when(c)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_prepare_survives_a_missing_store():
    c = _quantity_done()
    cs.by_id(S.ASK_DECORATION).prepare(c, None)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_decoration_bookkeeping_is_not_interpreter_writable():
    assert "decoration_types" in cs.WRITABLE_SLOTS
    assert "decoration_done" not in cs.WRITABLE_SLOTS
    assert "decoration_options" not in cs.WRITABLE_SLOTS
    assert "decoration_type" not in cs.WRITABLE_SLOTS   # the render-style bucket
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_canvas_steps.py -k decoration -v`
Expected: FAIL — `cs.by_id(S.ASK_DECORATION)` returns `None` (`AttributeError: 'NoneType' object has no attribute 'apply'`).

- [ ] **Step 3: Add `Step.prepare`**

In `canvas_steps.py`, add to the `Step` dataclass (after `apply`):

```python
    # Impure setup run before the step is rendered: loads store-scoped data the
    # step's chips need. Declared on the record — the alternative is an
    # `if next_.id is ASK_DECORATION` branch in the orchestrator, which is the
    # per-state switch this registry exists to avoid. May satisfy its own step
    # (see _prepare_decoration), so the orchestrator re-resolves after it runs.
    prepare: Callable[[dict, dict | None], None] | None = None
```

- [ ] **Step 4: Add the hooks and the step**

In `canvas_steps.py`, add after `_apply_email`:

```python
def _decoration_chips(c: dict) -> tuple[Chip, ...]:
    """One chip per method the store actually offers (loaded by _prepare_decoration)."""
    return tuple(Chip(name, {"decoration_types": [name]})
                 for name in (c.get("decoration_options") or []))


def _prepare_decoration(c: dict, store: dict | None) -> None:
    """Load the store's active decoration methods before the step renders.

    A store with none configured would leave the step with no chips and no way
    to answer, dead-ending the funnel one step before the email — so mark it
    done and let first-unmet skip it. Same for a store we can't read: the
    decoration method is a nice-to-have on the brief, never worth losing a lead.
    """
    if "decoration_options" not in c:
        from app.services import decoration_types as deco_svc  # noqa: PLC0415 cycle

        opts: list[str] = []
        if store and store.get("id"):
            try:
                opts = [t["name"] for t in
                        deco_svc.list_types(store["id"], active_only=True)]
            except Exception:  # noqa: BLE001 — never lose the lead over this
                opts = []
        c["decoration_options"] = opts
    if not c["decoration_options"]:
        c["decoration_done"] = True


def _apply_decoration(c: dict, f: dict, s: dict) -> None:
    """Filter the answer to what the store actually offers, then set the brief.

    This filter IS the interpreter guard: `decoration_types` is store-dynamic,
    so it cannot live in SLOT_ENUMS. An invented method yields nothing and never
    reaches the brief. Exact token match (not substring) so a shorter name can't
    match inside a longer one — "Print" inside "Screen Print".
    """
    if "decoration_types" not in f:
        return
    raw = f["decoration_types"]
    if isinstance(raw, str):
        raw = raw.split(",")            # the interpreter may return a bare string
    if not isinstance(raw, list):
        raw = []
    offered = {str(o).casefold(): o for o in (c.get("decoration_options") or [])}
    chosen: list[str] = []
    for tok in raw:
        opt = offered.get(str(tok).strip().casefold())
        if opt and opt not in chosen:
            chosen.append(opt)

    c["decoration_types"] = chosen
    c["decoration_done"] = True
    if chosen:
        c.setdefault("brief_notes", []).append(
            f"Decoration method: {', '.join(chosen)}"
        )
        # v1's mapping, imported rather than re-typed: one keyword table, one
        # behaviour. Local import — orchestrator imports this module's siblings.
        from app.services.conversation.orchestrator import (  # noqa: PLC0415 cycle
            _decoration_style_bucket,
        )
        c["decoration_type"] = _decoration_style_bucket(chosen[0])
```

Insert into `REGISTRY` between `ASK_QUANTITY` and `ASK_EMAIL`:

```python
    Step(
        id=S.ASK_DECORATION,
        # No cost caveat here: ChatColumn already renders "each extra decoration
        # adds to the cost" when 2+ are selected, so saying it again duplicates
        # it on screen.
        ask=("How would you like this decorated? Pick as many as apply — our "
             "team will confirm what suits your artwork best."),
        chips_from=_decoration_chips,
        multiselect=True,
        slots=("decoration_types",),
        prepare=_prepare_decoration,
        apply=_apply_decoration,
        done_when=lambda c: bool(c.get("decoration_done")),
    ),
```

- [ ] **Step 5: Run `prepare` in the orchestrator**

In `orchestrator_v2.py`, in `handle_message`, replace `next_ = v2.next_step(collected)`:

```python
    next_ = v2.next_step(collected)
    if next_.prepare:
        # Load whatever the step needs to render (store-scoped chips). prepare
        # may SATISFY its own step — a store with no decoration methods
        # configured — so re-resolve. One pass is enough: only one step declares
        # prepare, and a satisfied step routes forward to steps that don't.
        next_.prepare(collected, store)
        next_ = v2.next_step(collected)
```

- [ ] **Step 6: Document the slot, add the progress position and the test helper**

In `intent_extractor.py`, add to `_SLOT_DOCS`:

```python
    "decoration_types": "decoration_types (list of strings) — decoration methods they chose, copied EXACTLY from the options offered in the question",
```

In `state_machine_v2.py`, add `S.ASK_DECORATION` to `_PROGRESS_PATH` between `ASK_QUANTITY` and `ASK_EMAIL`:

```python
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_DECORATION, S.ASK_EMAIL, S.ASK_PURPOSE,
]
```

In `tests/canvas_step_helpers.py`, add to `satisfy` before the `ASK_EMAIL` branch:

```python
    elif step.id is S.ASK_DECORATION:
        c["decoration_done"] = True
```

- [ ] **Step 7: Run the full suite**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest -q`
Expected: PASS except `tests/test_v2_e2e.py` (Task 7).

- [ ] **Step 8: Commit**

```bash
git add app/services/conversation/canvas_steps.py app/services/conversation/state_machine_v2.py app/services/conversation/orchestrator_v2.py app/services/conversation/intent_extractor.py tests/canvas_step_helpers.py tests/test_canvas_steps.py
git commit -m "feat(v2): collect the decoration method after quantity"
```

---

### Task 7: End-to-end — the whole front half still needs no model

**Files:**
- Modify: `tests/test_v2_e2e.py:52-66` (`_new_store`), `:84-200` (the walk)

**Interfaces:**
- Consumes: every step from Tasks 1-6.
- Produces: nothing — this is the integration gate.

The walk drives the **exact chip labels the UI ships** with the interpreter raising `LLMUnavailable` for the entire run, proving chips resolve deterministically and the v2 front half completes with no model at all. That property must survive.

- [ ] **Step 1: Seed the fake session with decoration options**

The fake session has no `store_id`, so `_prepare_decoration` would load `[]` and skip the step. Seed the options so the walk exercises the real multi-select instead (`prepare` itself is unit-tested in Task 6). In `tests/test_v2_e2e.py`, in `_new_store`:

```python
def _new_store():
    return {
        "session": {
            "id": "s1",
            "state": S.GREETING.value,
            # decoration_options pre-seeded: _prepare_decoration only loads when
            # the key is absent, and this fake session has no store to load from.
            "collected": {"flow_mode": "canvas",
                          "decoration_options": ["Embroidery", "Screen Print"]},
            "upsell_count": 0,
        }
    }
```

- [ ] **Step 2: Update the walk**

In `test_full_v2_walk_using_the_exact_chip_labels`, replace the `walk` list:

```python
    walk = [
        ("",                        S.ASK_NAME),
        ("Sam",                     S.SHOW_INTRO),
        ("ok",                      S.ASK_HAS_LOGO),         # intro ack (no slots)
        ("Yes, I have a logo",      S.ASK_LOGO_PLACEMENT),
        ("Front",                   S.LOGO_ADJUST),
        ("Done",                    S.ASK_LOGO_BG),
        ("Yes, I've removed it",    S.ASK_ANOTHER_LOGO),
        ("Yes, another logo",       S.ASK_LOGO_PLACEMENT),   # THE bug
        ("Back",                    S.LOGO_ADJUST),
        ("Done",                    S.ASK_LOGO_BG),
        ("No, it's fine as is",     S.ASK_ANOTHER_LOGO),
        ("No, that's it",           S.ASK_ADD_DECOR),
        ("Add text",                S.ASK_DECOR_PLACEMENT),
        ("Left",                    S.DECOR_ADJUST),
        ("Done",                    S.ASK_ANYTHING_ELSE),
        ("No, that's everything",   S.ASK_QUANTITY),
        ("50-99",                   S.ASK_DECORATION),
        ("Embroidery, Screen Print", S.ASK_EMAIL),
        ("sam@example.com",         S.ASK_PURPOSE),
        ("for the team",            S.FINALIZE_CANVAS),
    ]
```

- [ ] **Step 3: Assert the new steps' directives inside the loop**

In the same loop, extend the directive assertions:

```python
        d = res["data"]["canvas"]
        if expected is S.ASK_LOGO_PLACEMENT:
            assert d["allowed_tools"] == ["upload"] and d["auto_open"] is None
        elif expected is S.LOGO_ADJUST:
            assert d["auto_open"] == "upload" and d["show_done"] is True
        elif expected is S.ASK_LOGO_BG:
            # Through the REAL pipeline: the tool must stay allowed or the logo
            # is locked and the "Remove background" toggle is unreachable.
            assert d["allowed_tools"] == ["upload"] and d["auto_open"] is None
        elif expected is S.ASK_DECOR_PLACEMENT:
            assert d["allowed_tools"] == ["text"] and d["auto_open"] is None
        elif expected is S.DECOR_ADJUST:
            assert d["target_face"] == "left"      # the face the customer named
```

- [ ] **Step 4: Extend the end-of-walk assertions**

After the existing `assert c["quantity"] == 50`:

```python
    assert c["logos"][0]["bg"] == "removed"
    assert c["logos"][1]["bg"] == "none"
    assert c["decor_face"] == "left"
    assert c["decoration_types"] == ["Embroidery", "Screen Print"]
    assert c["decoration_type"] == "embroidery"   # first choice drives the style
```

- [ ] **Step 5: Run the e2e test**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest tests/test_v2_e2e.py -v`
Expected: PASS — including `test_v2_no_longer_uses_the_shared_keyword_matchers`.

- [ ] **Step 6: Run the full backend suite**

Run: `CANVAS_ORCHESTRATOR_V2=false pytest -q`
Expected: PASS, **no failures**. Baseline was 660 passing; expect roughly 690 with the new tests.

- [ ] **Step 7: Commit**

```bash
git add tests/test_v2_e2e.py
git commit -m "test(v2): e2e walk covers has-logo, background removal, decor placement and decoration"
```

---

### Task 8: Verify in the browser and update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (the v2 registry bullet in §13 "Current implementation state")

**Interfaces:**
- Consumes: the finished flow from Tasks 1-7.
- Produces: nothing — this is the real-world gate. The whole spec rests on the claim that no frontend change is needed; this is where that claim is tested.

- [ ] **Step 1: Run the flow for real**

The v2 flag must be on for the app (only the test run forces it off). Confirm `CANVAS_ORCHESTRATOR_V2=true` in the repo-root `.env`, then:

```bash
docker compose up -d --force-recreate backend
```

Open `http://localhost:5173/?mode=blank`, walk to the logo step, upload an image, press Done, and confirm **all three**:
1. the bot asks about the background;
2. the logo is **still selectable** — click it and `SelectedToolbar` appears with "Remove background";
3. ticking the toggle actually mattes the image.

Then add text and confirm the bot asks which face first, and that the canvas switches to that face before the text tool opens. Finish the flow and confirm the decoration multi-select appears after the quantity question with the store's methods as chips.

If the store has no decoration types configured, add one at `http://localhost:5173/admin` → Decorations — or confirm the step correctly skips itself.

- [ ] **Step 2: Update CLAUDE.md**

In §13, in the "v2 is registry-driven" bullet, add after the loops sentence:

```markdown
  The flow asks `ask_has_logo` first (a "No — text only" answer sets
  `logos_done`, so first-unmet skips the whole logo branch), asks
  `ask_logo_bg` after each logo is placed (the customer ticks the existing
  `SelectedToolbar` toggle — **the step declares `tool="upload"` so
  `v2Editing` stays true and the logo is NOT locked, which is the only way the
  toggle is reachable**), asks `ask_decor_placement` before any text/shape
  (fixing a bug where `DECOR_ADJUST` read the logo's face and so always
  targeted "front"), and asks `ask_decoration` after quantity — a
  **multi-select of the store's `decoration_types`**, whose first choice sets
  the `decoration_type` render-style bucket. That last step is the registry's
  only user of three capabilities added for it: `Step.prepare` (loads
  store-scoped data before the step renders; may satisfy its own step when a
  store has no methods configured, so the orchestrator re-resolves after it),
  `Step.chips_from` (chips derived from `collected`), and `Step.multiselect`
  (the UI comma-joins the labels it was given, or ships the literal `none`).
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the v2 canvas flow steps and the ASK_LOGO_BG lock constraint"
```

---

## Self-Review

**Spec coverage:** §2 lock constraint → Task 3 (+ a global constraint + an e2e assertion in Task 7 + in-browser proof in Task 8). §3.A → Task 3. §3.B → Task 4. §3.C → Task 2. §3.D → Task 5. §3.E → Task 5. §3.F → Tasks 1 + 6. Progress path → Tasks 2, 3, 4, 6. §4 "no frontend change" → held; Task 8 verifies. §5 caveat → accepted, no task. §6 testing → every listed case has a test.

**Placeholder scan:** none — every step carries the literal code or command it needs.

**Type consistency:** `resolve_chip(step, message, collected)` is introduced in Task 1 and every later task's tests call it with three arguments — hence Task 1 is first, and the ordering is restated in Global Constraints. `_face(step, collected)` changes signature in Task 4; its only callers are inside `directive_for`, updated in the same task. `Step.instructions` is added in Task 3 and read by `directive_for` in Tasks 3 and 4 (the Task 4 snippet includes it). `chips_of`, `chips_from` and `multiselect` are defined in Task 1 and used in Task 6. `prepare(collected, store)` is defined and called in Task 6 only.
