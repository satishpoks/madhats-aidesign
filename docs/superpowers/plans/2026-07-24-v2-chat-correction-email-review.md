# v2 Chat Correction + Early Email + Pre-Submit Review — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three coupled v2-canvas conversation changes — capture the email right after the first design element (humble copy), add a `↩ Back` affordance that undoes the last answer, and add a pre-submit `REVIEW_DESIGN` step (confirm / rework-on-canvas) before the quote.

**Architecture:** All backend work is registry-local in `services/conversation/canvas_steps.py` (the `Step` records) and `state_machine_v2.py` (the pure first-unmet router, progress, and directives). The Haiku interpreter is untouched — it fills slots, never routes. The canvas stays the only frontend-owned surface; every new step drives the UI through the existing `canvas` directive. v1 and non-canvas flows are byte-identical (every change is v2-registry-local).

**Tech Stack:** Python 3.12, FastAPI, pytest; React 18 / Zustand / react-konva, Vitest.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-24-v2-chat-correction-email-review-design.md` — read it before starting.
- v2 routing is **pure first-unmet** over `canvas_steps.REGISTRY`. Never add a per-state switch to route; add/position `Step` records and let `next_step` resolve them.
- The interpreter fills **slots only**; a new slot reaches it only via a step's `slots` (which feeds `WRITABLE_SLOTS`). `email_captured`, `design_rework` internal flags are set by `apply`/handlers, and the writable-slot filter must keep the interpreter from faking `email_captured`.
- Chips carry BOTH label and the fields that label means, in the same literal.
- `FINALIZE_CANVAS` must stay unreachable without `email_captured` (ASK_EMAIL precedes it).
- **All pytest runs from `backend/`** (`cd backend` first) — the suite has no `conftest.py` and imports `from tests.canvas_step_helpers import …`. Docker not required; use the local venv: `./.venv/Scripts/python.exe -m pytest …`.
- **Baseline gate:** `CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` is **882 passed** on the starting commit and must stay green; new tests push it up. Also run the v2 files under `CANVAS_ORCHESTRATOR_V2=true` (they are flag-insensitive — the flag is only read in `chat.py::_dispatch`).
- **Frontend:** run only TARGETED `npx vitest run <path>` from `frontend/` (full `vitest run` stalls on this Windows host). NEVER `npm test` (watch mode hangs).
- Coupled declaration sites are guarded by existing tests (`test_canvas_steps::test_registry_declares_the_v2_flow_in_order`, `test_state_machine_v2` progress/routing guards, `test_v2_e2e::test_full_v2_walk_using_the_exact_chip_labels`, `tests/canvas_step_helpers.py::satisfy`, `test_branding::test_configurable_step_ids_are_exactly_the_safe_subset`). A half-wired change turns them red on purpose — each task leaves every touched test file green before committing.
- Implement in order: **A (email) → B (review) → C (Back)** — Back's `last_answered_step` must see the final registry order.

---

## File Structure

- `backend/app/services/conversation/canvas_steps.py` — `Step` records (reposition ASK_EMAIL; add REVIEW_DESIGN + REWORK_CANVAS; `_has_first_element`, `_apply_review`); `WRITABLE_SLOTS` derives from step slots automatically.
- `backend/app/services/conversation/state_machine_v2.py` — `_PROGRESS_PATH`/`_PROGRESS_ANCHORS`; `directive_for` (rework directive); new pure `last_answered_step`.
- `backend/app/services/conversation/orchestrator_v2.py` — new `handle_back`; `can_go_back` in `public_data_for` payloads.
- `backend/app/services/conversation/intent_extractor.py` — `_SLOT_DOCS` entries for any new interpreter-visible slot.
- `backend/app/api/routes/chat.py` — new `POST /chat/{id}/back`; extend `_persist_live_canvas_design` scope to the rework turn.
- `backend/app/prompts.py` — new copy strings.
- `frontend/src/lib/api.ts` — `sendBack`.
- `frontend/src/store/chatStore.ts` — `canGoBack` state + `goBack` action; read `can_go_back`.
- `frontend/src/components/CustomiseStudio/ChatColumn.tsx` — `↩ Back` control.
- `frontend/src/components/DesignStudio/Surface.tsx` + `ToolRail.tsx` — rework directive (unlock-all + Done→chat, not render).
- Test files: `backend/tests/test_canvas_steps.py`, `test_state_machine_v2.py`, `test_orchestrator_v2.py`, `test_v2_e2e.py`, `tests/canvas_step_helpers.py`; `frontend/src/__tests__/*`.

---

## PART A — Email moves to right after the first element

### Task A1: `_has_first_element` + conditional ASK_EMAIL, repositioned

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py`
- Modify: `backend/app/services/conversation/state_machine_v2.py` (`_PROGRESS_PATH`, `_PROGRESS_ANCHORS`)
- Modify: `backend/app/prompts.py`
- Test: `backend/tests/test_state_machine_v2.py`, `test_canvas_steps.py`, `test_v2_e2e.py`, `test_orchestrator_v2.py`

**Interfaces:**
- Produces: `canvas_steps._has_first_element(c: dict) -> bool`; ASK_EMAIL repositioned between ASK_LOGO_BG and ASK_ANOTHER_LOGO with `done_when = lambda c: bool(c.get("email_captured")) or not _has_first_element(c)`.

- [ ] **Step 1 — Failing tests.** Add to `backend/tests/test_state_machine_v2.py`:

```python
def test_email_is_skipped_before_any_element_is_placed():
    # Right after the intro, no element yet: the email step must not fire.
    c = _seed(name="Sam", intro_ack=True, has_logo=True)
    assert v2.next_step(c).id is not S.ASK_EMAIL


def test_email_fires_right_after_the_first_logo_is_placed():
    # First logo placed (pending_logo.placed) + its bg answered -> email is next,
    # before "add another logo".
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"})
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_email_fires_right_after_the_first_text_element_on_the_text_only_path():
    # Text-only: logo loop closed, first decor placed -> email is next.
    c = _seed(name="Sam", intro_ack=True, has_logo=False, logos_done=True,
              pending_logo=None, decor_choice="text", decor_placed=True)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_email_step_is_satisfied_once_captured():
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"},
              email_captured=True)
    assert v2.next_step(c).id is not S.ASK_EMAIL
```

- [ ] **Step 2 — Run → FAIL.** `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py -k email -v` → the three "fires/skipped" tests fail (ASK_EMAIL is still late).

- [ ] **Step 3 — Add the helper** in `canvas_steps.py`, next to `_pending`/`_logos_open` (~line 92):

```python
def _has_first_element(c: dict) -> bool:
    """True once the customer has placed their first design element — a logo
    (pending placed, or banked into `logos`) or a text/shape (`decor_placed`).
    Gates the email ask so it rides the first placement, not the intro."""
    return (bool(c.get("logos"))
            or bool(_pending(c).get("placed"))
            or bool(c.get("decor_placed")))
```

- [ ] **Step 4 — Reposition ASK_EMAIL.** Cut the whole `Step(id=S.ASK_EMAIL, …)` record from its current place (after `ASK_DECORATION_MIX`) and paste it into the `REGISTRY` tuple **immediately after the `Step(id=S.ASK_LOGO_BG, …)` record and before `Step(id=S.ASK_ANOTHER_LOGO, …)`**. Change its `ask` and `done_when`:

```python
    Step(
        id=S.ASK_EMAIL,
        ask=("Love where this is going, {name}! While you keep designing, could "
             "I grab your email so I can save your progress and send your "
             "finished design over?"),
        slots=("email",),
        apply=_apply_email,
        direct_answer=_direct_email,
        # Conditional: skipped until the first element exists, then asked until
        # captured. `email_captured` is set ONLY by _apply_email (not writable),
        # so the interpreter can't fake it and FINALIZE stays gated on a real
        # lead. Same skip-until pattern as ASK_DECORATION_MIX.
        done_when=lambda c: bool(c.get("email_captured")) or not _has_first_element(c),
    ),
```

- [ ] **Step 5 — Progress: anchor email to the design phase.** In `state_machine_v2.py`, remove `S.ASK_EMAIL` from `_PROGRESS_PATH` and add an anchor so the interleaved email ask doesn't move the counter backward:

```python
_PROGRESS_ANCHORS: dict[S, S] = {
    # …existing entries…
    S.ASK_EMAIL: S.ASK_LOGO_PLACEMENT,   # email rides the design phase; not a numbered step
}
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE,
]
```

- [ ] **Step 6 — Run the new tests → PASS.** `CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py -k email -v` → 4 pass.

- [ ] **Step 7 — Surface coupled failures.** Run the touched files:
`CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py tests/test_v2_e2e.py tests/test_orchestrator_v2.py -q`
Expect these to fail; fix each exactly:
  - `test_canvas_steps::test_registry_declares_the_v2_flow_in_order` — move `S.ASK_EMAIL` in the expected list to between `S.ASK_LOGO_BG` and `S.ASK_ANOTHER_LOGO`; remove it from the tail. New tail: `… S.ASK_QUANTITY, S.ASK_DECORATION, S.ASK_DECORATION_MIX, S.NEEDED_BY, S.ASK_PURPOSE, S.REQUEST_QUOTE, S.FINALIZE_CANVAS`. New head order after `ASK_LOGO_BG`: `S.ASK_LOGO_BG, S.ASK_EMAIL, S.ASK_ANOTHER_LOGO, …`.
  - `test_state_machine_v2::test_needed_by_has_a_progress_slot_immediately_before_purpose` — `len(path)` is now **8** (email left the path); update the `assert len(path) == 9` to `== 8`. `needed_by` is still `index(ASK_PURPOSE) - 1`.
  - `test_state_machine_v2::test_progress_v2_is_state_keyed_and_survives_a_tail_state` and `test_progress_collapses_loop_steps_onto_their_anchor` — recompute expected step numbers against the 8-item path (e.g. `ASK_QUANTITY` is step 5). Update the literals.
  - `tests/canvas_step_helpers.py::satisfy` — the walk `satisfy()` performs must reach ASK_EMAIL at its new position. Ensure the ASK_EMAIL branch sets `email_captured=True` (it already does) AND that the branches for the logo/decor steps set a first-element signal so `_has_first_element` is true when the walk reaches ASK_EMAIL. If `satisfy(LOGO_ADJUST)` doesn't already set `pending_logo["placed"]`, add it; likewise `satisfy(DECOR_ADJUST)` sets `decor_placed=True`.
  - `test_v2_e2e::test_full_v2_walk_using_the_exact_chip_labels` — the email turn now lands earlier. Update the `walk` list so `"sam@example.com"` is answered right after the first logo's bg step (`"Yes, remove background"` → then the email prompt appears → `"sam@example.com"` → `S.ASK_ANOTHER_LOGO`). Remove the later email turn. Keep the interpreter raising `LLMUnavailable` for the whole walk (email resolves via `Step.direct_answer`).
  - `test_orchestrator_v2` — any test seeding a session at `ASK_EMAIL` or asserting the state after decoration now differs; update the seed/expected-state literals to the new order (e.g. the email-notice test: seed a session with a first element placed so ASK_EMAIL is reachable, and assert the notice fires).

- [ ] **Step 8 — Re-run touched files → PASS**, then the full gate:
`CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` → all green (882 + 4 new).

- [ ] **Step 9 — Commit.**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/app/services/conversation/state_machine_v2.py backend/app/prompts.py backend/tests
git commit -m "feat(v2): capture email right after the first design element"
```

---

## PART B — Pre-submit REVIEW_DESIGN + REWORK_CANVAS

### Task B1: enum members + registry steps + progress

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (enum), `canvas_steps.py` (steps + `_apply_review`), `state_machine_v2.py` (progress anchors).
- Modify: `backend/app/prompts.py`
- Test: `backend/tests/test_state_machine_v2.py`, `test_canvas_steps.py`, `tests/canvas_step_helpers.py`

**Interfaces:**
- Produces: `S.REVIEW_DESIGN` / `S.REWORK_CANVAS`; slots `design_confirmed`, `design_rework`; `_apply_review`.
- Routing contract:
  - `REVIEW_DESIGN.done_when = lambda c: bool(c.get("design_confirmed") or c.get("design_rework"))` — satisfied while reworking so first-unmet advances to `REWORK_CANVAS`.
  - `REWORK_CANVAS.done_when = lambda c: not c.get("design_rework")` — unmet only while reworking.

- [ ] **Step 1 — Failing tests** in `test_state_machine_v2.py`:

```python
def _seed_at_review(**over):
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"},
              logos_done=True, decor_done=True, quantity=50, decoration_done=True,
              email_captured=True, needed_by="ASAP", purpose="team caps")
    c.update(over)
    return c


def test_review_is_asked_after_purpose():
    assert v2.next_step(_seed_at_review()).id is S.REVIEW_DESIGN


def test_confirming_review_advances_to_request_quote():
    assert v2.next_step(_seed_at_review(design_confirmed=True)).id is S.REQUEST_QUOTE


def test_rework_routes_to_the_canvas_rework_step():
    assert v2.next_step(_seed_at_review(design_rework=True)).id is S.REWORK_CANVAS


def test_finishing_rework_returns_to_review():
    # design_rework cleared, not yet confirmed -> back to REVIEW_DESIGN.
    assert v2.next_step(_seed_at_review(design_rework=False)).id is S.REVIEW_DESIGN
```

- [ ] **Step 2 — Run → FAIL.** `… pytest tests/test_state_machine_v2.py -k "review or rework" -v` → `AttributeError: REVIEW_DESIGN`.

- [ ] **Step 3 — Add enum members** in `state_machine.py`, immediately after `FINALIZE_CANVAS = "finalize_canvas"`:

```python
    REVIEW_DESIGN = "review_design"       # v2: recheck all views before submit
    REWORK_CANVAS = "rework_canvas"       # v2: reopened canvas during review rework
```

- [ ] **Step 4 — Add `_apply_review`** in `canvas_steps.py` (near `_apply_request_quote`):

```python
def _apply_review(c: dict, f: dict, s: dict) -> None:
    """Confirm ends the review; rework reopens the canvas. Tapping rework must
    clear any prior confirm; the two flags are mutually exclusive per turn."""
    if f.get("design_confirmed"):
        c.pop("design_rework", None)
    elif f.get("design_rework"):
        c.pop("design_confirmed", None)
```

- [ ] **Step 5 — Add the two Step records** in `REGISTRY`, immediately **before** `Step(id=S.REQUEST_QUOTE, …)`:

```python
    Step(
        id=S.REVIEW_DESIGN,
        ask=("Before I send this to our team, {name} — take a moment to look "
             "over your design across all the views. Happy with it, or would "
             "you like to rework anything?"),
        chips=(Chip("Looks great, send it", {"design_confirmed": True}),
               Chip("I'd like to rework it", {"design_rework": True})),
        slots=("design_confirmed", "design_rework"),
        apply=_apply_review,
        # Satisfied while reworking so first-unmet moves to REWORK_CANVAS; only a
        # real confirm satisfies it for good.
        done_when=lambda c: bool(c.get("design_confirmed") or c.get("design_rework")),
    ),
    Step(
        id=S.REWORK_CANVAS,
        ask=("Go ahead — tweak anything you like on the canvas, then press Done "
             "and I'll bring you back to the review."),
        chips=(Chip("Done", {"design_rework": False}),),
        slots=("design_rework",),
        # Unmet only while reworking. `design_rework` is this step's own slot, so
        # clearing it (truthy->falsy) is the allowed answer per merge_fields.
        done_when=lambda c: not c.get("design_rework"),
        tool="rework",                         # sentinel: unlock-all directive (B2)
        show_done=True,
    ),
```

- [ ] **Step 6 — Progress anchors** in `state_machine_v2.py` (`_PROGRESS_ANCHORS`) — both new steps fold onto the final beat (`ASK_PURPOSE`), like `REQUEST_QUOTE`, so the counter stays at the last step and doesn't grow:

```python
    S.REVIEW_DESIGN: S.ASK_PURPOSE,
    S.REWORK_CANVAS: S.ASK_PURPOSE,
```

- [ ] **Step 7 — `satisfy()` helper** in `tests/canvas_step_helpers.py` — add branches (before the `REQUEST_QUOTE` branch) so the registry walk passes through:

```python
    elif step.id is S.REVIEW_DESIGN:
        c["design_confirmed"] = True
    elif step.id is S.REWORK_CANVAS:
        c.pop("design_rework", None)     # not reworking -> satisfied
```

- [ ] **Step 8 — Run new tests → PASS**, then surface coupled failures on the touched files and fix:
  - `test_canvas_steps::test_registry_declares_the_v2_flow_in_order` — insert `S.REVIEW_DESIGN, S.REWORK_CANVAS` before `S.REQUEST_QUOTE` in the expected list.
  - `test_state_machine_v2::test_finalize_reached_when_everything_done` — add `design_confirmed=True` to the seed.
  - `test_v2_e2e::test_full_v2_walk_using_the_exact_chip_labels` — after `"for the team"` (→ REVIEW_DESIGN), add `("Looks great, send it", S.REQUEST_QUOTE)` before the `("Request a quote", S.FINALIZE_CANVAS)` turn.
  - `test_orchestrator_v2::test_daily_cap_reroutes_to_the_quote_ask` and any capped-seed test — add `design_confirmed=True` (and `needed_by`, from Part A/B baseline) so the walk still reaches the capped `FINALIZE_CANVAS` branch.

- [ ] **Step 9 — Full gate → PASS.** `CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`.

- [ ] **Step 10 — Commit.**

```bash
git add backend/app/services/conversation/state_machine.py backend/app/services/conversation/canvas_steps.py backend/app/services/conversation/state_machine_v2.py backend/app/prompts.py backend/tests
git commit -m "feat(v2): pre-submit REVIEW_DESIGN + REWORK_CANVAS steps"
```

### Task B2: rework directive (unlock-all) + backend persist on rework turn

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (`directive_for`)
- Modify: `backend/app/api/routes/chat.py` (`_persist_live_canvas_design` scope)
- Test: `backend/tests/test_state_machine_v2.py`, `backend/tests/test_chat_persist_live_canvas.py` (or the existing persist test file)

**Interfaces:**
- Produces: `directive_for` returns, for `REWORK_CANVAS`, `{"allowed_tools": ["upload","text","shape"], "target_face": None, "auto_open": None, "instructions": <copy>, "show_done": True, "unlock_all": True}`. All other steps' directives gain `"unlock_all": False` (default).

- [ ] **Step 1 — Failing test** in `test_state_machine_v2.py`:

```python
def test_rework_directive_unlocks_all_tools():
    d = v2.directive_for(cs.by_id(S.REWORK_CANVAS), {"design_rework": True})
    assert set(d["allowed_tools"]) == {"upload", "text", "shape"}
    assert d["show_done"] is True
    assert d["unlock_all"] is True


def test_non_rework_directive_does_not_unlock_all():
    d = v2.directive_for(cs.by_id(S.ASK_QUANTITY), {})
    assert d["unlock_all"] is False
```

- [ ] **Step 2 — Run → FAIL** (`KeyError: 'unlock_all'` / rework has `tool="rework"` not in `V2_TOOL_TIPS`).

- [ ] **Step 3 — Handle the `rework` sentinel tool** in `directive_for`. Replace the function body's tool branch so the `rework` sentinel emits the unlock-all directive and every other path carries `unlock_all: False`:

```python
def directive_for(step: Step, collected: dict) -> dict:
    if step.id is S.REWORK_CANVAS:
        return {"allowed_tools": ["upload", "text", "shape"], "target_face": None,
                "auto_open": None, "instructions": prompts.V2_REWORK_INSTRUCTIONS,
                "show_done": True, "unlock_all": True}
    if step.tool is None:
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False, "unlock_all": False}
    tool = _decor_tool(collected) if step.id in _DECOR_STEPS else step.tool
    return {
        "allowed_tools": [tool],
        "target_face": _face(step, collected) if step.face_target else None,
        "auto_open": tool if step.auto_open else None,
        "instructions": step.instructions or prompts.V2_TOOL_TIPS[tool],
        "show_done": step.show_done,
        "unlock_all": False,
    }
```

Add to `prompts.py`:

```python
V2_REWORK_INSTRUCTIONS = (
    "Tweak anything on the canvas — move, resize, recolour, add or remove. "
    "Press Done when it's how you want it."
)
```

- [ ] **Step 4 — Persist canvas edits on the rework-Done turn.** In `chat.py::_persist_live_canvas_design`, the final guard is currently:

```python
    if row.get("state") == "describe_changes" and flow == "canvas":
        (sb.table("design_sessions").update({"canvas_design": canvas_design})
         .eq("id", session_id).execute())
```

Widen the state check to also accept the rework turn (the malformed-payload guard at the top of the function already blocks a hostile design; the `flow == "canvas"` guard is unchanged):

```python
    if row.get("state") in ("describe_changes", "rework_canvas") and flow == "canvas":
        (sb.table("design_sessions").update({"canvas_design": canvas_design})
         .eq("id", session_id).execute())
```

- [ ] **Step 5 — Failing persist test.** In the existing persist test file, add a case: at state `rework_canvas`, a well-formed `canvas_design` on the turn is written to `design_sessions.canvas_design`; a non-canvas / malformed payload is not.

- [ ] **Step 6 — Run → PASS** for both directive and persist tests, then full gate.

- [ ] **Step 7 — Commit.**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/app/api/routes/chat.py backend/app/prompts.py backend/tests
git commit -m "feat(v2): rework directive unlocks the canvas + persists edits on the rework turn"
```

### Task B3: frontend — rework unlock + Done-sends-chat

**Files:**
- Modify: `frontend/src/store/chatStore.ts` (parse `unlock_all` onto `canvasDirective`)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx`
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx` (hide render button when reworking)
- Test: `frontend/src/__tests__/surfaceDirective.test.tsx`

**Interfaces:**
- Consumes: `canvasDirective.unlockAll: boolean`, `canvasDirective.showDone: boolean`, `canvasDirective.allowedTools`.

- [ ] **Step 1 — Failing test** in `surfaceDirective.test.tsx`: when the directive has `unlock_all: true`, mounting Surface calls `useCanvasStore.getState().unlockAll` (spy), and the Done button (show_done) sends a chat message (`sendChat`/`sendMessage`) rather than calling `finalizeCanvas`.

- [ ] **Step 2 — Run → FAIL.**

- [ ] **Step 3 — Parse `unlock_all`.** In `chatStore.ts` where `canvasDirective` is built from `data.canvas` (the directive blob), map `unlock_all` → `unlockAll` (camelCase) alongside `allowedTools`/`showDone`/`autoOpen`/`targetFace`/`instructions`.

- [ ] **Step 4 — Unlock on rework in `Surface.tsx`.** Add an effect that calls `unlockAll()` when `canvasDirective?.unlockAll` becomes true:

```tsx
useEffect(() => {
  if (canvasDirective?.unlockAll) unlockAll()
}, [canvasDirective?.unlockAll, unlockAll])
```

- [ ] **Step 5 — Rework Done reuses the existing per-step Done; hide the render button during rework.** No new Done handler is needed: `REWORK_CANVAS` sets `show_done=True`, so the existing `{canvasDirective?.showDone && <button onClick={postDone}>Done</button>}` (Surface.tsx ~297) already fires. `postDone` (~150) calls `sendMessage(sid, 'done')`, which sends the message with the live `canvas_design`; the backend resolves `'done'` against the `"Done"` chip case-insensitively (`resolve_chip` casefolds) → `{design_rework: False}`, and the widened `_persist_live_canvas_design` (B2 Step 4) persists the edits. The one guard to ADD: the ToolRail render / "Done designing" button (`onRender` → `doRender` → `finalizeCanvas`) must NOT be active during rework, or clicking it would finalize→quote prematurely. Pass a prop so ToolRail hides/disables its render button when `canvasDirective?.unlockAll` is true (rework), leaving the per-step Done as the only submit.

- [ ] **Step 6 — Run → PASS** the targeted file: `npx vitest run src/__tests__/surfaceDirective.test.tsx`. Also run the canvas subset: `npx vitest run src/__tests__/surfaceRework.test.tsx src/__tests__/chatStoreCanvasDirective.test.ts`.

- [ ] **Step 7 — Typecheck + commit.** `npx tsc --noEmit` (exit 0), then:

```bash
git add frontend/src/store/chatStore.ts frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__
git commit -m "feat(v2): review rework reopens the canvas; Done returns to review"
```

---

## PART C — `↩ Back` correction affordance

### Task C1: pure `last_answered_step`

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Produces: `last_answered_step(collected: dict, config: dict | None = None) -> Step | None` — the most-recent answered step whose *writable* slots, when cleared, flip its `done_when` to False; `None` if nothing can be undone.

- [ ] **Step 1 — Failing tests** in `test_state_machine_v2.py`:

```python
def test_last_answered_is_none_at_the_very_start():
    assert v2.last_answered_step(_seed()) is None


def test_last_answered_is_the_previous_question_step():
    # Answered up to quantity; the step before the current unmet one is quantity.
    c = _seed(name="Sam", intro_ack=True, has_logo=False, logos_done=True,
              pending_logo=None, decor_done=True, quantity=50,
              decor_placed=True, email_captured=True)
    # current unmet is ASK_DECORATION; last answered is ASK_QUANTITY.
    assert v2.next_step(c).id is S.ASK_DECORATION
    assert v2.last_answered_step(c).id is S.ASK_QUANTITY


def test_last_answered_never_targets_ask_email():
    # email_captured is not a writable slot, so clearing ASK_EMAIL's writable
    # slots (email — already popped) cannot un-answer it: it is never a target.
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo={"face": "front", "placed": True, "bg": "none"},
              email_captured=True, logos_done=True, decor_done=True, quantity=12,
              decor_placed=True)
    tgt = v2.last_answered_step(c)
    assert tgt is None or tgt.id is not S.ASK_EMAIL
```

- [ ] **Step 2 — Run → FAIL** (`AttributeError: last_answered_step`).

- [ ] **Step 3 — Implement** in `state_machine_v2.py`:

```python
def last_answered_step(collected: dict, config: dict | None = None) -> Step | None:
    """The step a `↩ Back` should re-open: the highest-index answered step,
    before the current unmet one, whose WRITABLE slots — when cleared — flip its
    done_when back to False. Pure; no side effects.

    A step whose done_when stays True after clearing its own writable slots
    (e.g. ASK_EMAIL, satisfied by the non-writable email_captured) is skipped —
    Back can't un-answer it, so it is never offered as a target.
    """
    reg = effective_registry(config)
    current = next_step(collected, config)
    writable = cs.WRITABLE_SLOTS
    target: Step | None = None
    for step in reg:
        if step.id is current.id:
            break
        probe = {k: v for k, v in collected.items()
                 if k not in (set(step.slots) & writable)}
        if not step.done_when(probe):
            target = step
    return target
```

- [ ] **Step 4 — Run → PASS.** `… pytest tests/test_state_machine_v2.py -k last_answered -v`.

- [ ] **Step 5 — Commit.**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(v2): pure last_answered_step for the Back affordance"
```

### Task C2: `handle_back` + `POST /chat/{id}/back` + `can_go_back` flag

**Files:**
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (`handle_back`, `can_go_back` in payloads)
- Modify: `backend/app/api/routes/chat.py` (route)
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Produces: `orchestrator_v2.handle_back(session_id: str) -> dict` (same response shape as `handle_message`); `POST /chat/{session_id}/back`; every v2 `public_data_for` payload carries `can_go_back: bool`.

- [ ] **Step 1 — Failing tests** in `test_orchestrator_v2.py` (reuse the `_FakeSB`/store fixtures):

```python
@pytest.mark.asyncio
async def test_back_clears_the_last_answer_and_re_asks(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_DECORATION.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "decor_placed": True,
        "quantity": 50, "email_captured": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_QUANTITY.value          # re-asked
    assert "quantity" not in store["session"]["collected"]  # answer cleared


@pytest.mark.asyncio
async def test_back_at_the_start_is_a_no_op(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_NAME.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    out = await o2.handle_back("s1")
    assert out["state"] == S.ASK_NAME.value


def test_public_data_carries_can_go_back():
    # A mid-flow step can go back; the very first cannot.
    from app.services.conversation import state_machine_v2 as v2
    d_mid = o2._public(cs.by_id(S.ASK_QUANTITY),
                       {"name": "Sam", "intro_ack": True, "decor_placed": True,
                        "logos_done": True, "pending_logo": None,
                        "decor_done": True, "email_captured": True})
    assert d_mid["can_go_back"] is True
```

(If the orchestrator builds payload data inline rather than via a helper, add a tiny `_public(step, collected)` wrapper around `v2.public_data_for` that also sets `can_go_back`, and use it everywhere `public_data_for` is called; the test calls that wrapper.)

- [ ] **Step 2 — Run → FAIL** (`AttributeError: handle_back`).

- [ ] **Step 3 — Add `can_go_back` to every v2 payload.** In `orchestrator_v2.py`, add a wrapper and use it wherever `v2.public_data_for(...)` feeds a response:

```python
def _public(step, collected) -> dict:
    data = v2.public_data_for(step, collected)
    data["can_go_back"] = v2.last_answered_step(collected) is not None
    return data
```

Replace the `data = v2.public_data_for(next_, collected)` call in `handle_message` with `data = _public(next_, collected)`.

- [ ] **Step 4 — Implement `handle_back`:**

```python
async def handle_back(session_id: str) -> dict:
    """Undo the last answer: clear the last-answered step's writable slots and
    re-ask it. One level per call; the frontend can call it repeatedly. No
    interpreter — this is the single legitimate slot-clearing gesture."""
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    current = S(session["state"])
    if current not in v2.V2_OWNED:
        return await _v1.handle_message(session_id, "")   # not a v2 turn; no-op-ish
    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)

    target = v2.last_answered_step(collected)
    if target is None:
        step = cs.by_id(current)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro)
        return await _persist(sb, session_id, collected, step, reply,
                              current.value, current, user_message="",
                              data=_public(step, collected))
    for slot in (set(target.slots) & cs.WRITABLE_SLOTS):
        collected.pop(slot, None)
    nxt = v2.next_step(collected)
    reply = v2.reply_for(nxt, collected, persona=persona, intro=intro)
    return await _persist(sb, session_id, collected, nxt, reply,
                          current.value, nxt.id, user_message="",
                          data=_public(nxt, collected))
```

- [ ] **Step 5 — Add the route** in `chat.py`:

```python
@router.post("/chat/{session_id}/back", response_model=ChatResponse)
async def chat_back(session_id: str) -> ChatResponse:
    try:
        result = await handle_back_v2(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return ChatResponse(**result)
```

Add `from app.services.conversation.orchestrator_v2 import handle_back as handle_back_v2` to the imports.

- [ ] **Step 6 — Run → PASS** the new tests, then full gate.

- [ ] **Step 7 — Commit.**

```bash
git add backend/app/services/conversation/orchestrator_v2.py backend/app/api/routes/chat.py backend/tests/test_orchestrator_v2.py
git commit -m "feat(v2): handle_back endpoint clears the last answer and re-asks"
```

### Task C3: frontend `↩ Back` control

**Files:**
- Modify: `frontend/src/lib/api.ts` (`sendBack`)
- Modify: `frontend/src/store/chatStore.ts` (`canGoBack` + `goBack`)
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx`
- Test: `frontend/src/__tests__/chatStoreCanvasDirective.test.ts` (or a new `chatStoreBack.test.ts`)

**Interfaces:**
- Consumes: `ChatResponse.data.can_go_back: boolean`; `POST /chat/{id}/back`.
- Produces: `chatStore.canGoBack: boolean`; `chatStore.goBack(sessionId): Promise<void>`.

- [ ] **Step 1 — Failing test** in a new `frontend/src/__tests__/chatStoreBack.test.ts`: `applyResponse('r','ask_quantity',{ can_go_back: true })` sets `canGoBack === true`; `goBack(id)` calls `sendBack(id)` (mocked) and applies its response.

- [ ] **Step 2 — Run → FAIL.**

- [ ] **Step 3 — `sendBack`** in `api.ts`:

```ts
export function sendBack(sessionId: string): Promise<ChatResponse> {
  return request<ChatResponse>(`/chat/${sessionId}/back`, { method: 'POST' })
}
```

- [ ] **Step 4 — Store.** In `chatStore.ts`: add `canGoBack: boolean` to the state and its reset defaults (`false`); in `applyResponse`, set `canGoBack: data.can_go_back === true`; add:

```ts
goBack: async (sessionId: string) => {
  if (get().sending) return
  set({ sending: true })
  try {
    const res = await sendBack(sessionId)
    get().applyResponse(res.reply, res.state, res.data as Record<string, unknown>)
  } finally {
    set({ sending: false })
  }
},
```

Import `sendBack` from `../lib/api`.

- [ ] **Step 5 — Control** in `ChatColumn.tsx`, beside the chip rows (render only when there's something to undo and not mid-send):

```tsx
{canGoBack && !sending && (
  <button
    onClick={() => goBack(sessionId)}
    className="self-start text-xs text-textSecondary hover:text-accent underline underline-offset-2 disabled:opacity-50"
  >
    ↩ Back
  </button>
)}
```

Wire `canGoBack` and `goBack` from the store, and `sessionId` from the component's existing props/store.

- [ ] **Step 6 — Run → PASS** `npx vitest run src/__tests__/chatStoreBack.test.ts`, then `npx tsc --noEmit`.

- [ ] **Step 7 — Commit.**

```bash
git add frontend/src/lib/api.ts frontend/src/store/chatStore.ts frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__
git commit -m "feat(v2): ↩ Back control to correct the last answer"
```

---

## Final verification

- [ ] **Backend full gate:** `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` → green (882 + new tests).
- [ ] **Flag-on v2 files:** `CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py tests/test_canvas_steps.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py -q` → green.
- [ ] **Frontend targeted:** `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx src/__tests__/surfaceRework.test.tsx src/__tests__/chatStoreCanvasDirective.test.ts src/__tests__/chatStoreBack.test.ts && npx tsc --noEmit`.
- [ ] **Manual (needs the running stack — Docker + `supabase start`, migrations applied):** walk a v2 canvas session end-to-end: place first element → humble email ask fires → verify link arrives → keep designing → quantity/decoration/needed-by/purpose → REVIEW_DESIGN → "rework" reopens the canvas, edit, Done → back to review → "Looks great" → Request a quote → reference shown. Press `↩ Back` at a couple of question steps and confirm the prior answer re-asks. (Record any gaps as follow-ups; do not claim live-verified without running this.)

---

## Notes / out of scope (from the spec)

- v2 resume email stays suppressed this batch even though email is now early (follow-up).
- Back re-asks a question; it does not delete canvas elements (canvas edits are corrected on the canvas). One level per press, repeatable.
- No multi-level "edit any earlier answer" jump-back UI.
