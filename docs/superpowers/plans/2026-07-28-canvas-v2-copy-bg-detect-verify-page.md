# Canvas v2 — copy, background-tick detection, branded verify page — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the v2 canvas greeting and email-step copy, make the chat notice when a customer has already ticked "Remove background" themselves (skip + acknowledge the question), and bring the email-verification landing page under per-store branding with a highlighted close-and-return message.

**Architecture:** Four independent changes. The copy edits touch one constant each. The background detection adds a *pure* function to the v2 step registry that reads the frontend's live canvas blob off a turn that already exists — the registry's first-unmet router then skips the step by itself, with no new branch. The verify page converts two HTML constants to `string.Template` shells and resolves the store the same way the resume email already does.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React 18 / Zustand / Vitest (frontend). Supabase via `supabase-py`.

**Spec:** `docs/superpowers/specs/2026-07-28-canvas-v2-copy-bg-detect-verify-page-design.md`

## Global Constraints

- **v1 is never modified.** `orchestrator.py` and `state_machine.py` stay byte-identical. `handle_message` (v1) does not gain a parameter. v1 is the retained backup path.
- **The v2 registry stays a pure function of `collected`.** Routing is first-unmet resolution over `cs.REGISTRY`. Do not add a per-state `if` branch to the orchestrator to implement a step's behaviour — that is the switch statement the registry exists to delete.
- **Run backend tests with the flag off:** `CANVAS_ORCHESTRATOR_V2=false` — the repo-root `.env` default of `true` flips 3 unrelated tests red.
- **Backend test command (Docker not required):** `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
- **Frontend test command:** `cd frontend && npx vitest run src/__tests__/<file>` (`npm test` is watch mode and hangs).
- **Baseline before this work:** backend **1028 passing**; frontend `npx vitest run src/__tests__` **246 passing, 2 failing** (the 2 are pre-existing `adminQuotes` Router-context failures). Do not treat those 2 as regressions.
- **No PII in logs.** Customer name/email must never reach a log line or Sentry breadcrumb.
- **v2 copy register is formal and guarded.** `tests/test_v2_copy_guards.py` fails on the `_CASUAL` word list (`pop your`, `pop it`, `grab your`, `love where`, `no worries`, `are you after`, `tap`) and on the string `under the cap`. Any new customer-facing v2 string must be added to `_v2_copy_strings()` in that file.
- **Copy is owner-dictated and ships verbatim.** Do not "improve" the wording in Task 1.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `backend/app/prompts.py` | Modify | `V2_ASK_NAME` copy (T1); new `V2_BG_ALREADY_REMOVED` (T3); `VERIFICATION_SUCCESS_HTML` / `VERIFICATION_ERROR_HTML` → `Template` shells + new `VERIFY_HEADER_DEFAULT_HTML` (T5) |
| `backend/app/services/conversation/canvas_steps.py` | Modify | `ASK_EMAIL.ask` copy (T1); new pure `observe_canvas()` (T2) |
| `backend/app/services/conversation/orchestrator_v2.py` | Modify | Call `observe_canvas`, prepend the ack (T3) |
| `backend/app/api/routes/chat.py` | Modify | Thread `body.canvas_design` through `_dispatch` → v2 only (T3) |
| `backend/app/api/routes/leads.py` | Modify | Resolve store, render branded success page (T5) |
| `frontend/src/store/chatStore.ts` | Modify | Send the live canvas at `logo_adjust` as well as `describe_changes` (T4) |
| `backend/tests/test_v2_copy_guards.py` | Modify | Register `V2_BG_ALREADY_REMOVED` (T3) |
| `backend/tests/test_canvas_copy_render.py` | Create | T1 |
| `backend/tests/test_observe_canvas.py` | Create | T2 |
| `backend/tests/test_v2_bg_autodetect.py` | Create | T3 |
| `backend/tests/test_verify_page_branding.py` | Create | T5 |
| `frontend/src/__tests__/chatStore.test.ts` | Modify | T4 |

**Task order.** T1, T4 and T5 are independent of everything. T2 must precede T3 (T3 calls what T2 builds). T4 can land before or after T3 — the backend tolerates a missing blob, and the frontend just sends one nothing reads yet. Any order otherwise.

---

## Task 1: Greeting and email-step copy

Two single-constant rewrites, dictated by the product owner. Both ship verbatim.

**Files:**
- Modify: `backend/app/prompts.py` (`V2_ASK_NAME`, ~line 1130)
- Modify: `backend/app/services/conversation/canvas_steps.py` (`ASK_EMAIL.ask`, ~line 528)
- Test: `backend/tests/test_canvas_copy_render.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing other tasks depend on.

**Background for the implementer.** `Step.ask` strings are rendered by `state_machine_v2.reply_for(step, collected, *, persona, intro, ack="", colour_note="")`, which calls `.format(name=…, persona=…, intro=…, colour_note=…)`. A format key you don't supply — or a typo like `{Name}` — raises `KeyError` **at runtime, in front of a customer**, not at import. That is what the test below actually guards; it is not a copy-pinning test.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_canvas_copy_render.py`:

```python
"""The two owner-dictated copy strings render, and their format keys resolve.

`Step.ask` is `.format()`-ed at reply time (state_machine_v2.reply_for), so a
mistyped placeholder — `{Name}`, `{customer}` — raises KeyError in front of a
live customer rather than at import. These tests render the real strings
through the real code path.
"""
from __future__ import annotations

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


def _render(step, collected):
    return v2.reply_for(step, collected, persona="Ricardo", intro="", colour_note="")


def test_greeting_introduces_the_persona_by_name():
    out = _render(cs.by_id(S.ASK_NAME), {})
    assert "I'm Ricardo, your design assistant" in out
    assert "bring your cap design to life" in out
    assert "{" not in out            # every placeholder resolved


def test_email_step_greets_the_customer_by_name():
    out = _render(cs.by_id(S.ASK_EMAIL), {"name": "Sam"})
    assert out.startswith("Great job, Sam.")
    assert "reference code" in out
    assert "{" not in out


def test_email_step_falls_back_when_no_name_was_captured():
    """reply_for defaults `name` to "there" — the step must not render "{name}"
    or crash for a session that somehow reached it without a name."""
    out = _render(cs.by_id(S.ASK_EMAIL), {})
    assert out.startswith("Great job, there.")


def test_the_greeting_constant_is_the_one_the_step_uses():
    """Guards against the copy being edited in prompts.py while the step quietly
    holds a stale literal (or vice versa)."""
    assert cs.by_id(S.ASK_NAME).ask is prompts.V2_ASK_NAME
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_copy_render.py -q
```

Expected: FAIL. `test_greeting_introduces_the_persona_by_name` fails on `bring your cap design to life` (current copy says "I'll take you through putting your design onto the cap"), and both email tests fail on `Great job,` (current copy starts "You're making good progress,").

- [ ] **Step 3: Rewrite the greeting**

In `backend/app/prompts.py`, replace the `V2_ASK_NAME` assignment. **Keep the existing explanatory comment block above it unchanged.**

```python
V2_ASK_NAME = (
    "Welcome! I'm {persona}, your design assistant. I'll help bring your cap "
    "design to life. May I please know your name?"
)
```

Do not touch `V2_ASK_NAME_RETRY`.

Note for the reviewer: this line carries an exclamation mark, which the rest of the v2 register avoids (`V2_ACK_PROMPT` instructs the model "no exclamation marks"). This is the owner's wording and is intentional — see the spec's "Register note". Do not normalise it.

- [ ] **Step 4: Rewrite the email step's ask**

In `backend/app/services/conversation/canvas_steps.py`, inside the `Step(id=S.ASK_EMAIL, …)` record, replace **only** the `ask=` value:

```python
        ask=("Great job, {name}. Please enter your email address so I can save "
             "your design, provide you a reference code and send you your "
             "artwork and quotation."),
```

Leave every other field on that step exactly as it is — `slots`, `apply=_apply_email`, `direct_answer=_direct_email`, and especially the `done_when` and its comment block, which encodes load-bearing early-skip logic.

Note for the reviewer: this copy promises a reference code, but `leads.reference_code` is minted later, at `REQUEST_QUOTE`. That is a deliberate forward promise (see the spec). **Do not** "fix" it by minting the code earlier — the code is the quote-request tracking reference, and minting it before finalize would create references for abandoned sessions.

- [ ] **Step 5: Run the new test to verify it passes**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_canvas_copy_render.py -q
```

Expected: 4 passed.

- [ ] **Step 6: Run the copy guards and the v2 suites**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_v2_copy_guards.py tests/test_v2_e2e.py tests/test_canvas_steps.py \
  tests/test_orchestrator_v2.py tests/test_state_machine_v2.py
```

Expected: all pass. Neither new string contains a `_CASUAL` phrase or "under the cap". If `test_v2_e2e.py` fails, a chip label was changed by mistake — the e2e walk types chip labels verbatim, and this task changes no chip.

- [ ] **Step 7: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/canvas_steps.py backend/tests/test_canvas_copy_render.py
git commit -m "feat(canvas-v2): rewrite the greeting and email-step copy"
```

---

## Task 2: `observe_canvas` — read a manual background tick off the live canvas

The pure half of the fix. No wiring, no HTTP, no DB — just the rule, tested in isolation.

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py` (add after `_ops_logo_bg`, ~line 213)
- Test: `backend/tests/test_observe_canvas.py` (create)

**Interfaces:**
- Consumes: `canvas_steps._pending(collected) -> dict` (existing helper, line 100).
- Produces: `canvas_steps.observe_canvas(collected: dict, canvas_design: dict | None) -> bool`. Mutates `collected["pending_logo"]["bg"] = "removed"` and returns `True` when it did; returns `False` and mutates nothing otherwise. Task 3 calls this.

**Background for the implementer.** `removeBg` is a field on a canvas element in the frontend's Zustand store. The canvas blob is only persisted to the database at finalize, so during the design phase **the backend cannot see it** — which is the entire bug: a customer who ticks the toggle themselves is still asked "Does your logo have a background that needs removing?".

The blob shape is whatever `canvasStore.toCanvasDesign()` returns: `{colourway, faces}` where `faces` is `{front: [...], back: [...], left: [...], right: [...]}` and each element carries at least `type`, `locked` and (for images) `removeBg`.

There is no element **id** to target, because ids are only assigned into `canvas_design` at finalize. So the anchor is positional, and it must be the **same** anchor the frontend already uses for exactly this concept: *the last unlocked element of type `image` on the face* — see `canvasStore.ts:188-192` (`patchPendingLogo`) and the `lockPlaced` note at `canvasStore.ts:73-76`. Using any other rule (first image, last image regardless of lock) would silently pick a **previous** logo on a second pass of the logo loop, because earlier logos are locked as each step completes.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_observe_canvas.py`:

```python
"""canvas_steps.observe_canvas — read a manually-ticked "Remove background".

Pure over plain dicts: no DB, no HTTP, no model. The blob is whatever the
frontend's canvasStore.toCanvasDesign() produces.
"""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs


def _design(front_elements):
    return {"colourway": None,
            "faces": {"front": front_elements, "back": [], "left": [], "right": []}}


def _img(**kw):
    base = {"type": "image", "locked": False, "removeBg": False}
    base.update(kw)
    return base


def test_a_ticked_logo_is_recorded_as_removed():
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is True
    assert c["pending_logo"]["bg"] == "removed"


def test_an_unticked_logo_writes_nothing():
    """Absence of a tick is silence, not a "no" — the step must still be asked."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    assert cs.observe_canvas(c, _design([_img(removeBg=False)])) is False
    assert "bg" not in c["pending_logo"]


def test_an_already_answered_bg_is_never_overwritten():
    """The customer answered the chip "No, it's fine as it is". A stale tick on
    the canvas must not silently flip their answer."""
    c = {"pending_logo": {"face": "front", "bg": "none"}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False
    assert c["pending_logo"]["bg"] == "none"


def test_a_locked_ticked_image_is_ignored():
    """Second pass of the logo loop: the FIRST logo is locked and was ticked;
    the new pending one is not. Reading the locked one would answer this step
    with the previous logo's setting."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(locked=True, removeBg=True), _img(removeBg=False)])
    assert cs.observe_canvas(c, design) is False
    assert "bg" not in c["pending_logo"]


def test_it_reads_the_last_unlocked_image_not_the_first():
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(removeBg=False), _img(removeBg=True)])
    assert cs.observe_canvas(c, design) is True


def test_non_image_elements_are_skipped():
    """A text element placed after the logo must not shadow it."""
    c = {"pending_logo": {"face": "front", "placed": True}}
    design = _design([_img(removeBg=True), {"type": "text", "locked": False}])
    assert cs.observe_canvas(c, design) is True


def test_it_reads_the_pending_logos_own_face():
    c = {"pending_logo": {"face": "back", "placed": True}}
    design = {"colourway": None,
              "faces": {"front": [_img(removeBg=True)], "back": [_img(removeBg=False)],
                        "left": [], "right": []}}
    assert cs.observe_canvas(c, design) is False


def test_no_pending_logo_is_a_no_op():
    c = {"logos_done": True, "pending_logo": None}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False


def test_a_pending_logo_with_no_face_is_a_no_op():
    """Before ASK_LOGO_PLACEMENT is answered there is no face to read."""
    c = {"pending_logo": {}}
    assert cs.observe_canvas(c, _design([_img(removeBg=True)])) is False


def test_a_missing_or_malformed_blob_never_raises():
    for blob in (None, {}, {"faces": None}, {"faces": {"front": None}},
                 {"faces": {"front": ["not-a-dict"]}}, "nonsense", []):
        c = {"pending_logo": {"face": "front", "placed": True}}
        assert cs.observe_canvas(c, blob) is False
        assert "bg" not in c["pending_logo"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_observe_canvas.py -q
```

Expected: FAIL — `AttributeError: module 'app.services.conversation.canvas_steps' has no attribute 'observe_canvas'`.

- [ ] **Step 3: Implement `observe_canvas`**

In `backend/app/services/conversation/canvas_steps.py`, insert immediately **after** `_ops_logo_bg` (which ends ~line 212) and **before** `_apply_another_logo`:

```python
def observe_canvas(collected: dict, canvas_design: dict | None) -> bool:
    """Read a manually-ticked "Remove background" off the frontend's live canvas.

    The mirror of `_ops_logo_bg`: that writes the tick FOR the customer when they
    tap the chip; this reads a tick they made THEMSELVES, so ASK_LOGO_BG can be
    skipped instead of asking a question they have already answered on screen.
    Without it the toggle is invisible to the backend — `removeBg` lives only in
    the frontend store until finalize.

    The anchor is positional because there is no element id yet (`canvas_design`
    is written at finalize): the LAST UNLOCKED image on the pending logo's face —
    the same rule `canvasStore.patchPendingLogo` / `lockPlaced` use. Any other
    rule reads a PREVIOUS logo on a second pass of the loop, since each completed
    logo is locked.

    One-way and idempotent by design: it only ever writes "removed", and never
    over an existing answer. Returns True only when it wrote.
    """
    pending = _pending(collected)
    face = pending.get("face")
    if not face or "bg" in pending:
        return False                  # nothing in progress, or already answered
    if not isinstance(canvas_design, dict):
        return False
    faces = canvas_design.get("faces")
    if not isinstance(faces, dict):
        return False
    elements = faces.get(face)
    if not isinstance(elements, list):
        return False
    for el in reversed(elements):
        if not isinstance(el, dict):
            continue
        if el.get("type") != "image" or el.get("locked"):
            continue
        if not el.get("removeBg"):
            return False              # this IS the pending logo, and it's unticked
        collected.setdefault("pending_logo", {})["bg"] = "removed"
        return True
    return False
```

Note the `return False` inside the loop rather than `continue`: the first unlocked image found (scanning backwards) *is* the pending logo. If it is unticked, the answer is "not ticked" — scanning further back would find an older, already-handled logo.

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_observe_canvas.py -q
```

Expected: 10 passed.

- [ ] **Step 5: Confirm nothing else moved**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q tests/test_canvas_steps.py tests/test_state_machine_v2.py tests/test_v2_e2e.py
```

Expected: all pass. This step adds a function and changes no existing behaviour.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/tests/test_observe_canvas.py
git commit -m "feat(canvas-v2): add observe_canvas to read a manual background tick"
```

---

## Task 3: Wire the detection through the orchestrator, and acknowledge it

**Files:**
- Modify: `backend/app/prompts.py` (add `V2_BG_ALREADY_REMOVED` near the other v2 constants)
- Modify: `backend/app/api/routes/chat.py` (`_dispatch`, ~line 67; the route body, ~line 84)
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (`handle_message` signature ~line 48; body ~lines 139-180)
- Modify: `backend/tests/test_v2_copy_guards.py` (register the new constant)
- Test: `backend/tests/test_v2_bg_autodetect.py` (create)

**Interfaces:**
- Consumes: `canvas_steps.observe_canvas(collected, canvas_design) -> bool` (Task 2).
- Produces:
  - `orchestrator_v2.handle_message(session_id: str, message: str, canvas_design: dict | None = None) -> dict`
  - `chat._dispatch(session_id: str, message: str, canvas_design: dict | None = None) -> dict`
  - `prompts.V2_BG_ALREADY_REMOVED: str`

**Background for the implementer.** Read `orchestrator_v2.handle_message` before editing. The turn pipeline is: resolve chip or interpret → `merge_fields` → `collected.update` → `step.apply` → `step.ops` → `next_ = v2.next_step(collected, flow_config)` → build reply → `_persist`.

`observe_canvas` must run **after `step.apply`** and **before `v2.next_step`**:
- After `apply`, because on the Done turn it is `_apply_logo_placed` that marks the logo placed; observing first would read a half-applied state.
- Before `next_step`, because the whole point is that the write satisfies `ASK_LOGO_BG.done_when` so first-unmet skips it. Observing after routing would be too late.

**Do not add an `if step.id is S.LOGO_ADJUST` guard.** `observe_canvas` is already self-guarding (it no-ops without a pending logo carrying a face and no `bg`), and only the frontend's narrow send condition puts a blob on the wire. A state check here would be a second source of truth that can drift from the frontend's.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_v2_bg_autodetect.py`:

```python
"""The chat notices a background tick the customer made themselves.

End-to-end through orchestrator_v2: a "Done" turn at LOGO_ADJUST carrying the
live canvas skips ASK_LOGO_BG and says so, instead of asking a question the
customer has already answered on screen.
"""
from __future__ import annotations

import pytest

from app import prompts
from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *_):
        return self

    def order(self, *a, **k):
        return self

    def execute(self):
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.store["session"]]})()
        return type("R", (), {"data": []})()

    def update(self, patch):
        self.store["session"].update(patch)
        return self

    def insert(self, rows):
        return self


class _FakeSB:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _FakeTable(self.store, name)


def _at_logo_adjust():
    return {"session": {
        "id": "s1",
        "state": S.LOGO_ADJUST.value,
        "collected": {"flow_mode": "canvas", "name": "Sam", "intro_ack": True,
                      "has_logo": True, "pending_logo": {"face": "front"}},
        "upsell_count": 0,
    }}


def _no_llm(monkeypatch):
    """A chip tap must need no model at all."""
    async def _boom(*a, **k):
        raise ie.LLMUnavailable("no key")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


def _design(remove_bg: bool):
    return {"colourway": None,
            "faces": {"front": [{"type": "image", "locked": False,
                                 "removeBg": remove_bg}],
                      "back": [], "left": [], "right": []}}


@pytest.mark.asyncio
async def test_a_ticked_logo_skips_the_background_question(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(True))

    assert res["state"] == S.ASK_ANOTHER_LOGO.value
    assert store["session"]["collected"]["pending_logo"]["bg"] == "removed"


@pytest.mark.asyncio
async def test_the_skip_is_acknowledged_in_the_reply(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(True))

    assert prompts.V2_BG_ALREADY_REMOVED in res["reply"]


@pytest.mark.asyncio
async def test_an_unticked_logo_still_gets_asked(monkeypatch):
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done", canvas_design=_design(False))

    assert res["state"] == S.ASK_LOGO_BG.value
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]


@pytest.mark.asyncio
async def test_no_canvas_blob_behaves_exactly_as_before(monkeypatch):
    """Every other turn in the flow sends no blob; none of them may change."""
    store = _at_logo_adjust()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)

    res = await o2.handle_message("s1", "Done")

    assert res["state"] == S.ASK_LOGO_BG.value
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]


@pytest.mark.asyncio
async def test_the_ack_is_not_prepended_on_an_unrelated_turn(monkeypatch):
    """A blob arriving at a step with no pending logo must be inert.

    Note this drives the FULL turn (interpreter returns a real field) rather
    than letting it stall — a stalled turn returns before observe_canvas is
    ever reached, which would make this pass for the wrong reason.
    """
    store = _at_logo_adjust()
    store["session"]["state"] = S.ASK_QUANTITY.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos": [{"face": "front", "placed": True, "bg": "none"}],
        "logos_done": True, "pending_logo": None, "decor_done": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _ok(*a, **k):
        return {"quantity": 50}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _ok)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "50", canvas_design=_design(True))

    assert store["session"]["collected"]["quantity"] == 50   # the turn advanced
    assert prompts.V2_BG_ALREADY_REMOVED not in res["reply"]
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_v2_bg_autodetect.py -q
```

Expected: FAIL — `TypeError: handle_message() got an unexpected keyword argument 'canvas_design'`, and `AttributeError` on `prompts.V2_BG_ALREADY_REMOVED`.

- [ ] **Step 3: Add the acknowledgement constant**

In `backend/app/prompts.py`, immediately **after** the `V2_BG_INSTRUCTIONS` block (which ends ~line 1116), add:

```python
# Prepended to the next step's copy when the customer ticked "Remove background"
# in the Adjust panel themselves, so ASK_LOGO_BG is skipped rather than asked.
# Concatenated verbatim (never through a model), like the tool tips: the whole
# value is that the customer sees their own action reflected back accurately.
V2_BG_ALREADY_REMOVED = (
    "I can see you've already removed the background on that logo, so I'll "
    "skip that question."
)
```

- [ ] **Step 4: Register it with the copy guards**

In `backend/tests/test_v2_copy_guards.py`, add one line to the `out.extend([...])` list inside `_v2_copy_strings()` (after `prompts.V2_BG_INSTRUCTIONS`):

```python
        prompts.V2_BG_ALREADY_REMOVED,
```

- [ ] **Step 5: Thread the blob through the orchestrator**

In `backend/app/services/conversation/orchestrator_v2.py`:

**5a.** Change the signature (line 48):

```python
async def handle_message(session_id: str, message: str,
                         canvas_design: dict | None = None) -> dict:
```

**5b.** The v1 delegation a few lines below stays **exactly** as it is — v1 takes no blob:

```python
    if current not in v2.V2_OWNED:
        return await _v1.handle_message(session_id, message)
```

**5c.** Insert the observation between `step.apply(...)` and the `canvas_ops` line (currently lines 138-143). The block becomes:

```python
    if step.apply:
        step.apply(collected, fields, session)
    # The customer may have ticked "Remove background" in the Adjust panel
    # themselves. That lives only in the frontend store until finalize, so the
    # live canvas blob (sent on this turn only) is the sole way to see it.
    # AFTER apply — on the Done turn it is _apply_logo_placed that marks the
    # logo placed — and BEFORE next_step, because the write satisfies
    # ASK_LOGO_BG.done_when and that is what makes first-unmet skip it.
    # observe_canvas is self-guarding; no step check belongs here.
    bg_auto_marked = cs.observe_canvas(collected, canvas_design)
    # Canvas mutations this answer implies. Computed from the step just
    # ANSWERED (not the next one), so it must be read before next_step
    # re-resolves.
    canvas_ops = step.ops(collected, fields) if step.ops else []
```

**5d.** Prepend the ack. After the reply is assembled (currently line 171) and alongside the existing `ASK_EMAIL` notice block, add:

```python
    reply = v2.reply_for(next_, collected, persona=persona, intro=intro, ack=ack,
                        colour_note=colour_note)
    if bg_auto_marked:
        # Say what we noticed. Without this the background question simply
        # vanishes, which reads as the bot skipping a step at random.
        reply = f"{prompts.V2_BG_ALREADY_REMOVED} {reply}".strip()
    if step.id is S.ASK_EMAIL and collected.get("email_captured"):
```

Leave the `ASK_EMAIL` block that follows unchanged.

- [ ] **Step 6: Thread the blob through the route**

In `backend/app/api/routes/chat.py`, change `_dispatch` (line 67) and its call site (line 84):

```python
async def _dispatch(session_id: str, message: str,
                    canvas_design: dict | None = None) -> dict:
    """Route a chat turn to v2 (canvas sessions, flag on) or v1 (everything else).

    `canvas_design` reaches v2 ONLY. v1's handle_message takes no blob and its
    signature is deliberately untouched — v1 is the retained backup path.
    """
    if _is_v2_canvas(session_id):
        return await handle_message_v2(session_id, message, canvas_design)
    return await handle_message(session_id, message)
```

and in the route body:

```python
        result = await _dispatch(session_id, body.message, body.canvas_design)
```

`_persist_live_canvas_design(session_id, body.canvas_design)` on the line above stays exactly as it is — that writes the blob to the database and is hard-scoped to `describe_changes` / `rework_canvas`. This change is a separate, read-only path.

- [ ] **Step 7: Run the new test to verify it passes**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_v2_bg_autodetect.py -q
```

Expected: 5 passed.

- [ ] **Step 8: Run the surrounding suites**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py \
  tests/test_chat_route.py tests/test_chat_route_dispatch.py tests/test_canvas_refine.py
```

Expected: all pass. `test_chat_route_dispatch.py` is the one most likely to notice the `_dispatch` signature — if it asserts call arity, update the assertion to the new three-argument form rather than reverting the signature.

- [ ] **Step 9: Commit**

```bash
git add backend/app/prompts.py backend/app/api/routes/chat.py \
        backend/app/services/conversation/orchestrator_v2.py \
        backend/tests/test_v2_copy_guards.py backend/tests/test_v2_bg_autodetect.py
git commit -m "feat(canvas-v2): skip and acknowledge a self-ticked background removal"
```

---

## Task 4: Send the live canvas on the logo "Done" turn

**Files:**
- Modify: `frontend/src/store/chatStore.ts` (`sendMessage`, ~lines 194-200)
- Test: `frontend/src/__tests__/chatStore.test.ts` (modify the existing describe block, ~lines 64-88)

**Interfaces:**
- Consumes: `sendChat(sessionId, message, canvasDesign?)` from `lib/api.ts:78` (existing, unchanged); `useCanvasStore.getState().toCanvasDesign()` (existing, unchanged).
- Produces: nothing other tasks import. Task 3's backend reads what this sends.

**Background for the implementer.** `sendMessage` is the single choke point every user turn flows through. It currently attaches the live canvas only at `describe_changes`. `logo_adjust` is the state the customer is in when they press **Done** to close logo placement — the one turn on which the backend needs to see the canvas.

Keep the condition narrow. The deliberate hard scoping on `_persist_live_canvas_design` (`chat.py:31-53`) exists so a stray or hostile blob on an unrelated turn cannot overwrite saved work; the same restraint applies here.

- [ ] **Step 1: Write the failing test**

In `frontend/src/__tests__/chatStore.test.ts`, replace the whole existing `describe('sendMessage sends the live canvas_design only at describe_changes', …)` block (lines 64-88) with:

```ts
describe('sendMessage sends the live canvas_design on exactly two states', () => {
  beforeEach(() => {
    useCanvasStore.getState().reset()
    useCanvasStore.getState().addImage('logo.png')
  })

  it('passes the live canvas_design as the 3rd sendChat arg at describe_changes', async () => {
    useChatStore.setState({ chatState: 'describe_changes' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'Moved it up.', state: 'confirm_canvas_edit', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'move it up more')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', 'move it up more', liveDesign)
  })

  it('passes the live canvas_design at logo_adjust so a self-ticked background is seen', async () => {
    useChatStore.setState({ chatState: 'logo_adjust' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'Noted.', state: 'ask_another_logo', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'Done')
    const liveDesign = useCanvasStore.getState().toCanvasDesign()
    expect(sendChat).toHaveBeenCalledWith('s1', 'Done', liveDesign)
  })

  it('sends undefined as the 3rd arg on any other state', async () => {
    useChatStore.setState({ chatState: 'offer_refine' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'ok', state: 'offer_refine', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'hello')
    expect(sendChat).toHaveBeenCalledWith('s1', 'hello', undefined)
  })

  it('sends undefined at ask_logo_bg — the blob is for the Done turn only', async () => {
    useChatStore.setState({ chatState: 'ask_logo_bg' })
    vi.mocked(sendChat).mockResolvedValue({
      reply: 'ok', state: 'ask_another_logo', data: {},
    } as never)
    await useChatStore.getState().sendMessage('s1', 'No, it\'s fine as it is')
    expect(sendChat).toHaveBeenCalledWith('s1', "No, it's fine as it is", undefined)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd frontend && npx vitest run src/__tests__/chatStore.test.ts
```

Expected: FAIL on `passes the live canvas_design at logo_adjust…` — it currently receives `undefined` as the third argument.

- [ ] **Step 3: Widen the send condition**

In `frontend/src/store/chatStore.ts`, replace the `liveDesign` block (lines 195-199):

```ts
      // Send the live canvas on exactly two turns:
      //  - describe_changes: so an edit resolves against what's on screen
      //    (accumulated edits), not the last saved design.
      //  - logo_adjust: the "Done" turn closing logo placement. The backend
      //    reads a self-ticked "Remove background" off it (canvas_steps.
      //    observe_canvas) and skips ask_logo_bg. removeBg lives only in this
      //    store until finalize, so this turn is the only chance to see it.
      // Deliberately narrow — a blob on an unrelated turn is a way to overwrite
      // saved work, which is why chat.py's persist path is scoped just as hard.
      const st = get().chatState
      const liveDesign = (st === 'describe_changes' || st === 'logo_adjust')
        ? useCanvasStore.getState().toCanvasDesign()
        : undefined
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd frontend && npx vitest run src/__tests__/chatStore.test.ts
```

Expected: all pass (4 in the new describe block, plus the file's other tests).

- [ ] **Step 5: Run the canvas-adjacent frontend tests**

```bash
cd frontend && npx vitest run src/__tests__/canvasOps.test.ts src/__tests__/canvasStoreOps.test.ts src/__tests__/chatStoreCanvasDirective.test.ts src/__tests__/surfaceDirective.test.tsx
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/__tests__/chatStore.test.ts
git commit -m "feat(canvas): send the live canvas on the logo Done turn"
```

---

## Task 5: Brand the verification landing page

**Files:**
- Modify: `backend/app/prompts.py` (`VERIFICATION_SUCCESS_HTML` ~line 871, `VERIFICATION_ERROR_HTML` ~line 901; add `VERIFY_HEADER_DEFAULT_HTML`)
- Modify: `backend/app/api/routes/leads.py` (`_error_page` ~line 75, `confirm_verification` ~line 86)
- Test: `backend/tests/test_verify_page_branding.py` (create)

**Interfaces:**
- Consumes: `app.services.stores.get_store(store_id) -> dict | None` (existing); `app.services.branding.public_brand(brand, base_url) -> dict` (existing, `branding.py:139`).
- Produces: nothing other tasks depend on.

**Background for the implementer.** These two pages are the last customer-facing surface that missed the per-store branding work: they hardcode `#ff5c00` and a "MAD HATS / AI Design Studio" lockup, so a branded store's customer clicks a themed email and lands on a MadHats-orange page.

Use `string.Template`, **not** `.format()` — these are HTML/CSS blobs and `.format()` chokes on literal braces. This is the same reason `BRANDED_EMAIL_HTML` uses `Template`; see `email.py:66-72` for the established call shape.

Two things are non-negotiable:

1. **Branding must never turn a successful verification into an error page.** By the time the page renders, the verification has already been committed to the database (`leads.py:114-115`). A store lookup that throws must fall back to defaults and still return HTTP 200 — the same best-effort treatment `_maybe_send_resume_email` already gets.
2. **The default header block is a literal, never derived from `store_name`.** `"MadHats".upper()` is `"MADHATS"` — no space — which is the exact trap already documented at `email.py:205`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_verify_page_branding.py`:

```python
"""GET /leads/verify/{token} — the landing page follows the store's brand.

The last customer-facing surface the per-store branding work missed: it
hardcoded #ff5c00 and the MadHats lockup, so a branded store's customer clicked
a themed email and landed on an orange MadHats page.

Branding here is strictly cosmetic and strictly best-effort: the verification is
already committed to the database before the page renders, so a store lookup
that fails must still return 200.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.routes import leads as leads_route
from app.config import settings
from app.main import app


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, session_row):
        self._session_row = session_row

    def table(self, name):
        if name == "email_verifications":
            return _Query([{"id": "ver-1"}])
        if name == "leads":
            return _Query([{"id": "lead-1", "session_id": "sess-1",
                            "email": "c@x.example", "name": "Sam"}])
        if name == "design_sessions":
            return _Query([self._session_row])
        raise AssertionError(f"unexpected table {name}")


client = TestClient(app)


def _token():
    return jwt.encode({"lead_id": "lead-1"}, settings.admin_secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _quiet_side_effects(monkeypatch):
    """The route's post-verification email sends are irrelevant here and must not
    hit the network. Each is already best-effort in the route."""
    monkeypatch.setattr(leads_route.delivery, "maybe_send_preview", lambda sid: False)
    monkeypatch.setattr(leads_route.delivery, "maybe_send_quote_confirmation", lambda sid: None)
    monkeypatch.setattr(leads_route, "_maybe_send_resume_email", lambda *a, **k: None)
    monkeypatch.setattr(leads_route, "_mark_session_verified", lambda *a, **k: None)


def _setup(monkeypatch, session_row, store):
    monkeypatch.setattr(leads_route, "get_supabase", lambda: _FakeSB(session_row))
    monkeypatch.setattr("app.services.stores.get_store", lambda sid: store)


def test_a_branded_store_themes_the_success_page(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "#123456" in resp.text
    assert "Acme Caps" in resp.text
    assert "#ff5c00" not in resp.text
    assert "MAD HATS" not in resp.text


def test_an_unconfigured_store_keeps_the_madhats_defaults(monkeypatch):
    _setup(monkeypatch, {"store_id": None}, None)

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "#ff5c00" in resp.text
    assert "MAD HATS" in resp.text
    assert "AI Design Studio" in resp.text


def test_a_store_lookup_that_raises_still_verifies(monkeypatch):
    """The verification is already committed. Branding must never downgrade a
    success into an error page."""
    def _boom(_sid):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(leads_route, "get_supabase", lambda: _FakeSB({"store_id": "store-1"}))
    monkeypatch.setattr("app.services.stores.get_store", _boom)

    resp = client.get(f"/leads/verify/{_token()}")

    assert resp.status_code == 200
    assert "Your email is now verified" in resp.text
    assert "#ff5c00" in resp.text


def test_the_close_message_is_highlighted_on_the_success_page(monkeypatch):
    _setup(monkeypatch, {"store_id": None}, None)

    resp = client.get(f"/leads/verify/{_token()}")

    assert "You can close this page now and head back to the chat." in resp.text
    assert "border-left:4px solid" in resp.text     # the callout treatment


def test_the_callout_border_follows_the_store_colour(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert "border-left:4px solid #123456" in resp.text


def test_a_configured_logo_is_rendered_as_a_media_url(monkeypatch):
    _setup(monkeypatch, {"store_id": "store-1"},
           {"id": "store-1", "name": "Acme Caps",
            "brand": {"primary_colour": "#123456", "logo_url": "brands/acme.png"}})

    resp = client.get(f"/leads/verify/{_token()}")

    assert "<img" in resp.text
    assert "/media/" in resp.text


def test_an_expired_link_renders_the_default_themed_error_page():
    """No lead is loaded for an expired token, so there is no store to resolve.
    Documented in the spec as accepted."""
    expired = jwt.encode(
        {"lead_id": "lead-1", "exp": 0}, settings.admin_secret, algorithm="HS256")

    resp = client.get(f"/leads/verify/{expired}")

    assert resp.status_code == 400
    assert "This link has expired" in resp.text
    assert "MAD HATS" in resp.text


def test_a_malformed_link_renders_the_error_page():
    resp = client.get("/leads/verify/not-a-real-token")

    assert resp.status_code == 400
    assert "doesn&#x27;t look right" in resp.text or "doesn't look right" in resp.text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_verify_page_branding.py -q
```

Expected: FAIL. `test_a_branded_store_themes_the_success_page` fails on `#123456 in resp.text` (page is hardcoded orange); the close-message and callout tests fail on the new copy and `border-left`.

- [ ] **Step 3: Convert the page constants to Template shells**

In `backend/app/prompts.py`, replace the two constants (keeping the explanatory comment block above `VERIFICATION_SUCCESS_HTML` at lines 865-869 intact) and add the default header literal.

```python
# The default header lockup, used when no store brand is configured. A LITERAL,
# never derived from store_name: "MadHats".upper() is "MADHATS" (no space), the
# same trap email.py:205 documents.
VERIFY_HEADER_DEFAULT_HTML = (
    '<div style="font-size:20px;font-weight:bold;color:#ffffff;'
    'letter-spacing:0.5px;">MAD HATS</div>\n'
    '          <div style="font-size:12px;color:#ffd9b2;">AI Design Studio</div>'
)

VERIFICATION_SUCCESS_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Email verified — $store_name</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:$primary_colour;padding:18px 28px;">
          $header_html
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9989;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">Your email is now verified</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">Thanks for confirming — we'll send your design across shortly. Keep an eye on your inbox.</p>
          <div style="margin:26px 0 0 0;padding:14px 18px;background:#f3f4f6;border-left:4px solid $primary_colour;border-radius:6px;text-align:left;">
            <p style="font-size:15px;line-height:22px;color:#1a1a2e;font-weight:700;margin:0;">You can close this page now and head back to the chat.</p>
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""

# Substituted with $message (plus $store_name/$primary_colour/$header_html) for
# expired / invalid / already-used links. Always renders on the MadHats defaults:
# two of the three branches reject the token before any lead is loaded, so there
# is no store to resolve, and the third is not worth a DB round-trip for a
# dead-end page. See the spec's error-page note.
VERIFICATION_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Verification problem — $store_name</title>
</head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:Inter,Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" height="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;min-height:100vh;">
    <tr><td align="center" style="padding:40px 16px;">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">
        <tr><td style="background:$primary_colour;padding:18px 28px;">
          $header_html
        </td></tr>
        <tr><td style="padding:40px 28px;text-align:center;">
          <div style="font-size:44px;line-height:1;">&#9888;&#65039;</div>
          <h1 style="font-size:22px;color:#1a1a2e;margin:18px 0 8px 0;">We couldn't verify that link</h1>
          <p style="font-size:14px;line-height:22px;color:#6b6b80;margin:0;">$message</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
```

Check the tail of the original `VERIFICATION_ERROR_HTML` (lines ~922-926) and make sure the closing `</table></td></tr></table></body></html>` structure matches what you replaced — do not leave a stray fragment behind.

- [ ] **Step 4: Render the branded page in the route**

In `backend/app/api/routes/leads.py`:

**4a.** Add imports at the top, beside the existing ones:

```python
import html as html_lib
from string import Template

from fastapi import APIRouter, HTTPException, Request
```

`public_brand` and `get_store` are imported **locally, inside the function** —
matching the established pattern in this module (`leads.py:67`, `leads.py:212`),
which uses function-level imports for `app.services.*` to stay clear of an
import cycle. Do not hoist them to the top.

**4b.** Add a header-block builder above `_error_page`:

```python
def _brand_bits(store: dict | None, base_url: str) -> tuple[str, str]:
    """(primary_colour, header_html) for the verification pages.

    Falls back to the MadHats lockup for a store with no brand — and the lockup
    is a literal, never store_name.upper(), which would render "MADHATS".
    """
    if not store:
        return "#ff5c00", prompts.VERIFY_HEADER_DEFAULT_HTML
    from app.services.branding import public_brand  # noqa: PLC0415 — import cycle

    brand = store.get("brand") or {}
    colour = brand.get("primary_colour") or "#ff5c00"
    name = html_lib.escape(store.get("name") or "MadHats")
    logo = public_brand(brand, base_url).get("logo_url")
    if logo:
        header = (f'<img src="{html_lib.escape(logo, quote=True)}" alt="{name}" '
                  f'style="max-height:40px;display:block;" />')
    else:
        header = ('<div style="font-size:20px;font-weight:bold;color:#ffffff;'
                  f'letter-spacing:0.5px;">{name}</div>')
    return colour, header
```

**4c.** Update `_error_page` to substitute the Template. Its body text is our own literal (never customer input), so it is passed through unescaped:

```python
def _error_page(message: str) -> HTMLResponse:
    """A friendly HTML page for a bad/expired/used verification link.

    The customer clicks this link in their inbox, so every outcome must render
    as a browser page — never raw JSON or a stack trace. Always the MadHats
    defaults: an expired/invalid token is rejected before any lead is loaded,
    so there is no store to theme from.
    """
    return HTMLResponse(
        Template(prompts.VERIFICATION_ERROR_HTML).substitute(
            message=message,
            store_name="MadHats",
            primary_colour="#ff5c00",
            header_html=prompts.VERIFY_HEADER_DEFAULT_HTML,
        ),
        status_code=400,
    )
```

**4d.** Take a `Request` and render the branded success page. Change the signature:

```python
@router.get("/leads/verify/{token}", response_class=HTMLResponse)
async def confirm_verification(request: Request, token: str) -> HTMLResponse:
```

and replace the final `return` (line 157):

```python
    log.info("lead_verified", lead_id=lead_id, session_id=session_id)

    # Theme the landing page to the session's store, the same way the emails
    # that led here are themed. STRICTLY best-effort: the verification is
    # already committed above, so a branding failure must never downgrade a
    # success into an error page.
    store = None
    try:
        sess = (sb.table("design_sessions").select("store_id")
                .eq("id", session_id).limit(1).execute())
        store_id = sess.data[0].get("store_id") if sess.data else None
        if store_id:
            from app.services.stores import get_store

            store = get_store(store_id)
    except Exception as exc:  # noqa: BLE001 — cosmetic only
        log.warning("verify_page_branding_failed", session_id=session_id,
                    error_type=type(exc).__name__)
    colour, header = _brand_bits(store, str(request.base_url))

    # Confirmation only — NO design image/preview here. The design is delivered
    # exclusively via the preview email dispatched above.
    return HTMLResponse(Template(prompts.VERIFICATION_SUCCESS_HTML).substitute(
        store_name=html_lib.escape((store or {}).get("name") or "MadHats"),
        primary_colour=colour,
        header_html=header,
    ))
```

Note `_brand_bits` sits **outside** the `try` so a malformed store dict still renders defaults rather than raising.

- [ ] **Step 5: Run the new test to verify it passes**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_verify_page_branding.py -q
```

Expected: 8 passed.

- [ ] **Step 6: Run the leads / branding / email suites**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_leads_verify_route.py tests/test_leads_reference_code.py \
  tests/test_branding.py tests/test_email_branding.py \
  tests/test_email_transactional_branding.py tests/test_verification_poll.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/prompts.py backend/app/api/routes/leads.py backend/tests/test_verify_page_branding.py
git commit -m "feat(leads): brand the verification landing page and highlight the close message"
```

---

## Final verification

- [ ] **Step 1: Full backend suite**

```bash
cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q
```

Expected: **1051 passing** (1028 baseline + 4 T1 + 10 T2 + 5 T3 + 8 T5 — the T3 count includes no removals). If the number differs, do not adjust the expectation: find which test changed status. Re-measure the baseline by stashing rather than trusting a recorded number.

- [ ] **Step 2: Frontend suite**

```bash
cd frontend && npx vitest run src/__tests__
```

Expected: **249 passing, 2 failing** (246 + 3 net new from T4; the 2 failures are the pre-existing `adminQuotes` Router-context ones). Confirm those 2 are the same two by name — do not accept a different pair.

- [ ] **Step 3: Manual check in the browser**

Docker stack up (`docker compose up`), studio at `https://localhost`:

1. Start a canvas session, answer the name step — confirm the new greeting reads "Welcome! I'm Ricardo, your design assistant. I'll help bring your cap design to life."
2. Say you have a logo, choose a face, upload one.
3. **Before** pressing Done, select the logo and tick "Remove background" in the Adjust panel.
4. Press Done. Expect: the chat says "I can see you've already removed the background on that logo, so I'll skip that question." and goes straight to "Would you like to add another logo?" — the background question is not asked.
5. Repeat without ticking. Expect the background question as normal.
6. Reach the email step — confirm it reads "Great job, <your name>. Please enter your email address…".
7. Open the verification link. Confirm the page carries the store's colour and logo (configure one under admin → Branding first) and shows the highlighted "You can close this page now and head back to the chat." callout.

- [ ] **Step 4: Update project memory**

Add to `CLAUDE.md` under the canvas v2 bullets: `observe_canvas` is the read-half of the background-removal mark (`_ops_logo_bg` is the write-half), it is anchored on "last unlocked image on the face" to match `patchPendingLogo`/`lockPlaced`, and the live canvas is now sent on **two** turns (`describe_changes`, `logo_adjust`) — not one. Note that the verification landing page is now store-branded while the error page deliberately is not.
