# Canvas colour disclaimer + final notes, and Mac voice-mic messaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre-quote colour-accuracy disclaimer + verbatim final-notes step to the v2 canvas flow (with admin-configurable reference links), and make the voice-mic error messaging honest and Mac-aware.

**Architecture:** The v2 canvas flow is a registry of `Step` records routed by first-unmet resolution (`state_machine_v2.next_step`). We add one new state/step between the design review and the quote request, render its copy from store branding (mirroring `canvas_intro`), and capture free text verbatim via a new `direct_capture` flag that bypasses the LLM interpreter. The mic fix is pure frontend error-message branching. Two admin URL fields and a chat linkifier round it out.

**Tech Stack:** Python 3.12 / FastAPI (backend), React 18 / Vite / Tailwind / Zustand (frontend), pytest + vitest.

## Global Constraints

- Target flow is **v2 canvas only** (`CANVAS_ORCHESTRATOR_V2` on, `flow_mode == "canvas"`). Do not touch v1 (customise/blank Q&A) or any other flow.
- **No secrets in code; no PII in logs.** The final-notes text is customer content but is not name/email — it is fine in `brief_notes` (already how notes are handled). Never log it.
- Reference-guide **links are admin-configurable** via `stores.brand`, with **neutral `example.com` dummy defaults**.
- Final-notes free text is captured **verbatim** — never reshaped by the LLM (may be a CMYK/Pantone code or embroidery thread number).
- Disclaimer copy must **not promise exact colour matching** — it says "closest match" unless the customer supplies a code.
- Mic button stays **visible**; only the error message changes. The real prod unblock (HTTPS) is **out of scope** — environmental, not built here.
- Backend suite baseline: run `CANVAS_ORCHESTRATOR_V2=false pytest -q`; run new/related tests with the flag **on** where they exercise v2. On this Windows host use the venv python: `cd backend && ./.venv/Scripts/python.exe -m pytest ...`.
- Frontend: run targeted `npx vitest run <file>` (full run is flaky on this host).
- Commit after each task.

---

### Task 1: Backend — colour disclaimer copy + admin link config

**Files:**
- Modify: `backend/app/prompts.py` (add copy + dummy default URLs near the v2 block, ~line 1149)
- Modify: `backend/app/services/branding.py` (validate two URL keys in `validate_brand`; add `colour_disclaimer_text`)
- Test: `backend/tests/test_branding_canvas_intro.py` (add cases; it already covers the `canvas_intro` sibling)

**Interfaces:**
- Produces: `prompts.V2_COLOUR_DISCLAIMER` (str, `.format` fields `name`, `embroidery_url`, `print_url`), `prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL`, `prompts.V2_DEFAULT_COLOUR_PRINT_URL`; `branding.colour_disclaimer_text(store: dict | None, name: str) -> str` (fully rendered, no remaining `{...}`); `validate_brand` now accepts optional `colour_ref_embroidery_url` / `colour_ref_print_url`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_branding_canvas_intro.py`:

```python
import pytest
from app import prompts
from app.services import branding


def test_colour_disclaimer_uses_store_links_when_set():
    store = {"brand": {
        "colour_ref_embroidery_url": "https://acme.test/embroidery",
        "colour_ref_print_url": "https://acme.test/print",
    }}
    out = branding.colour_disclaimer_text(store, "Sam")
    assert "https://acme.test/embroidery" in out
    assert "https://acme.test/print" in out
    assert "Sam" in out
    assert "{" not in out and "}" not in out  # fully rendered, single-pass safe


def test_colour_disclaimer_falls_back_to_dummy_defaults():
    out = branding.colour_disclaimer_text(None, "there")
    assert prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL in out
    assert prompts.V2_DEFAULT_COLOUR_PRINT_URL in out


def test_validate_brand_accepts_colour_ref_links():
    cleaned = branding.validate_brand({
        "colour_ref_embroidery_url": "https://acme.test/e",
        "colour_ref_print_url": "http://acme.test/p",
    })
    assert cleaned["colour_ref_embroidery_url"] == "https://acme.test/e"
    assert cleaned["colour_ref_print_url"] == "http://acme.test/p"


def test_validate_brand_rejects_non_http_colour_ref_link():
    with pytest.raises(ValueError):
        branding.validate_brand({"colour_ref_embroidery_url": "ftp://acme.test/e"})


def test_validate_brand_drops_empty_colour_ref_link():
    cleaned = branding.validate_brand({"colour_ref_embroidery_url": ""})
    assert "colour_ref_embroidery_url" not in cleaned
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_branding_canvas_intro.py -q`
Expected: FAIL (`AttributeError: module 'app.services.branding' has no attribute 'colour_disclaimer_text'`, and the validate cases erroring/not raising).

- [ ] **Step 3: Add the copy + dummy defaults to `prompts.py`**

Insert after `V2_EMAIL_VERIFY_NOTICE` (~line 1149):

```python
# The pre-quote colour-accuracy disclaimer (v2 canvas ASK_FINAL_NOTES). The two
# reference links are admin-configurable per store (branding.colour_disclaimer_text);
# these are neutral placeholders used until an admin sets real ones. Copy must not
# promise exact colour — it says "closest match" unless the customer gives a code.
V2_DEFAULT_COLOUR_EMBROIDERY_URL = "https://example.com/embroidery-chart"
V2_DEFAULT_COLOUR_PRINT_URL = "https://example.com/print-colour-guide"

V2_COLOUR_DISCLAIMER = (
    "One quick note before we send this over, {name} — screen colours aren't "
    "always exact. What you see is a guide; our team matches your design to the "
    "closest embroidery and print colours.\n\n"
    "Reference charts — embroidery: {embroidery_url} · print: {print_url}\n\n"
    "If you already have a specific print colour (CMYK or Pantone) or an "
    "embroidery thread number, pop it below and we'll use it — otherwise we'll "
    "pick the closest match.\n\n"
    "Any final notes or pointers for the team? Type them here, or tap "
    '"Nothing to add".'
)
```

- [ ] **Step 4: Add validation + the renderer to `branding.py`**

In `validate_brand`, after the `canvas_intro` check (after line 100, before `return cleaned`):

```python
    for key in ("colour_ref_embroidery_url", "colour_ref_print_url"):
        val = cleaned.get(key)
        if val in (None, ""):
            cleaned.pop(key, None)
            continue
        if not isinstance(val, str):
            raise ValueError(f"{key} must be a string URL")
        parsed = urlparse(val)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{key} must be an http(s) URL")
```

Add the renderer after `canvas_intro_text` (after line 110):

```python
def colour_disclaimer_text(store: dict | None, name: str) -> str:
    """The fully-rendered pre-quote colour disclaimer for the v2 canvas flow.

    Rendered here (name + both URLs already substituted) rather than left with a
    `{name}` placeholder, because reply_for runs a SINGLE str.format pass and
    would not expand a placeholder nested inside a substituted value.
    """
    brand = (store or {}).get("brand") or {}
    embroidery = (brand.get("colour_ref_embroidery_url")
                  or prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL)
    print_url = (brand.get("colour_ref_print_url")
                 or prompts.V2_DEFAULT_COLOUR_PRINT_URL)
    return prompts.V2_COLOUR_DISCLAIMER.format(
        name=name, embroidery_url=embroidery, print_url=print_url)
```

(`urlparse` and `prompts` are already imported in `branding.py`.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_branding_canvas_intro.py tests/test_branding.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/prompts.py backend/app/services/branding.py backend/tests/test_branding_canvas_intro.py
git commit -m "feat(branding): colour disclaimer copy + admin-configurable reference links"
```

---

### Task 2: Backend — new ASK_FINAL_NOTES state, step, routing, progress

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py:52` (add enum member)
- Modify: `backend/app/services/conversation/canvas_steps.py` (add `direct_capture` dataclass field ~line 51; add `_apply_final_notes`; insert the `Step` into `REGISTRY` between `REWORK_CANVAS` and `REQUEST_QUOTE`)
- Modify: `backend/app/services/conversation/state_machine_v2.py` (`reply_for` gains `colour_note` kwarg; add progress anchor + section mapping)
- Modify: `backend/tests/canvas_step_helpers.py` (add a `satisfy` branch so the registry walk still reaches later steps)
- Test: `backend/tests/test_state_machine_v2.py`, `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: nothing from Task 1 (this task is pure routing/copy).
- Produces: `ConversationState.ASK_FINAL_NOTES` (value `"ask_final_notes"`); a `Step` with `slots=("final_notes",)`, `direct_capture=True`, chip `"Nothing to add"` → `{"final_notes_done": True}`; `Step.direct_capture: bool` field; `reply_for(..., colour_note: str = "")`. `final_notes_done` is NOT a writable slot.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_state_machine_v2.py`:

```python
def test_final_notes_sits_between_review_and_quote():
    # After the design is confirmed at REVIEW_DESIGN, the next step is the
    # colour-disclaimer/final-notes step, then the quote request.
    c = _seed(name="Sam", intro_ack=True, has_logo=True,
              pending_logo=None, logos_done=True, email_captured=True,
              decor_done=True, quantity=12, decoration_done=True,
              needed_by="2-4 weeks", purpose="team caps", design_confirmed=True)
    assert v2.next_step(c).id is S.ASK_FINAL_NOTES
    c["final_notes_done"] = True
    assert v2.next_step(c).id is S.REQUEST_QUOTE


def test_final_notes_done_is_not_interpreter_writable():
    # The step must not be skippable by a hallucinated flag — final_notes_done
    # is set only by apply/the chip, never by the interpreter.
    assert "final_notes_done" not in cs.WRITABLE_SLOTS
    assert "final_notes" in cs.WRITABLE_SLOTS


def test_reply_for_renders_colour_note_verbatim():
    step = cs.by_id(S.ASK_FINAL_NOTES)
    out = v2.reply_for(step, {"name": "Sam"}, persona="Ricardo", intro="hi",
                       colour_note="SCREEN COLOURS ARE A GUIDE")
    assert out == "SCREEN COLOURS ARE A GUIDE"
```

Add to `backend/tests/test_canvas_steps.py`:

```python
def test_apply_final_notes_appends_typed_note_to_brief():
    from app.services.conversation import canvas_steps as cs
    c = {}
    cs._apply_final_notes(c, {"final_notes": "Pantone 186 C for the text"}, {})
    assert c["final_notes_done"] is True
    assert any("Pantone 186 C" in n for n in c["brief_notes"])


def test_apply_final_notes_nothing_to_add_adds_no_brief_note():
    from app.services.conversation import canvas_steps as cs
    # The chip sets final_notes_done directly (merged before apply); apply sees
    # no final_notes and must not append a brief note.
    c = {"final_notes_done": True}
    cs._apply_final_notes(c, {}, {})
    assert "brief_notes" not in c
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py tests/test_canvas_steps.py -q`
Expected: FAIL (`AttributeError: ASK_FINAL_NOTES`, `_apply_final_notes` missing).

- [ ] **Step 3: Add the enum member**

In `backend/app/services/conversation/state_machine.py`, after line 52 (`REQUEST_QUOTE = ...`):

```python
    ASK_FINAL_NOTES = "ask_final_notes"   # v2: colour disclaimer + final notes before quote
```

- [ ] **Step 4: Add the `direct_capture` field + apply hook + Step record**

In `canvas_steps.py`, add the field to the `Step` dataclass (after `direct_answer`, ~line 51):

```python
    # When True, free text on this step is banked VERBATIM via direct_answer
    # (no interpreter, no ack). For steps where the answer IS the message and an
    # LLM could corrupt it — e.g. a Pantone/CMYK code in the final notes.
    direct_capture: bool = False
```

Add the apply hook (near the other apply hooks, e.g. after `_apply_request_quote`):

```python
def _apply_final_notes(c: dict, f: dict, s: dict) -> None:
    """Verbatim capture into the team brief. The "Nothing to add" chip sets
    final_notes_done directly (merged before this runs); a typed note sets it
    here. final_notes_done is deliberately NOT a slot, so the interpreter can
    never fabricate it and skip the disclaimer."""
    note = (f.get("final_notes") or "").strip()
    if not note:
        return
    c.setdefault("brief_notes", []).append(f"Customer final notes: {note}")
    c["final_notes_done"] = True
```

Insert the `Step` into `REGISTRY` **immediately after the `REWORK_CANVAS` step and before the `REQUEST_QUOTE` step**:

```python
    Step(
        id=S.ASK_FINAL_NOTES,
        # Copy is rendered from store branding and passed in via reply_for's
        # colour_note kwarg (single-pass format; value has no braces).
        ask="{colour_note}",
        chips=(Chip("Nothing to add", {"final_notes_done": True}),),
        slots=("final_notes",),
        direct_capture=True,
        direct_answer=lambda m: {"final_notes": m.strip()},
        apply=_apply_final_notes,
        done_when=lambda c: bool(c.get("final_notes_done")),
    ),
```

- [ ] **Step 5: Thread `colour_note` through `reply_for` + progress maps**

In `state_machine_v2.py`, change `reply_for`'s signature and `.format` call:

```python
def reply_for(step: Step, collected: dict, *, persona: str, intro: str,
              ack: str = "", colour_note: str = "") -> str:
```

and in the `else` branch's `.format(...)` add `colour_note=colour_note,`:

```python
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
            colour_note=colour_note,
        )
```

Add the progress mappings. In `_PROGRESS_ANCHORS` add:

```python
    S.ASK_FINAL_NOTES: S.ASK_PURPOSE,
```

In `_STEP_SECTION` add (section 3 = "Review", matching REVIEW_DESIGN/REQUEST_QUOTE):

```python
    S.ASK_FINAL_NOTES: 3,
```

- [ ] **Step 6: Keep the registry-walk helper reaching later steps**

In `backend/tests/canvas_step_helpers.py`, add a branch in `satisfy` (before the `REQUEST_QUOTE` branch, ~line 62):

```python
    elif step.id is S.ASK_FINAL_NOTES:
        c["final_notes_done"] = True
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest tests/test_state_machine_v2.py tests/test_canvas_steps.py -q`
Expected: PASS (including the existing registry-walk tests, which now traverse the new step).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/app/services/conversation/canvas_steps.py backend/app/services/conversation/state_machine_v2.py backend/tests/canvas_step_helpers.py backend/tests/test_state_machine_v2.py backend/tests/test_canvas_steps.py
git commit -m "feat(canvas-v2): ASK_FINAL_NOTES step + verbatim direct_capture flag"
```

---

### Task 3: Backend — orchestrator wiring (render disclaimer + verbatim capture)

**Files:**
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (import `colour_disclaimer_text`; compute `colour_note`; thread into every `reply_for`; add the `direct_capture` branch in `handle_message`)
- Test: `backend/tests/test_orchestrator_v2.py`, `backend/tests/test_v2_e2e.py`

**Interfaces:**
- Consumes: `branding.colour_disclaimer_text` (Task 1); `Step.direct_capture`, `ASK_FINAL_NOTES`, `reply_for(colour_note=...)` (Task 2).
- Produces: at `ASK_FINAL_NOTES`, the reply is the rendered disclaimer and free text is banked verbatim into `collected["brief_notes"]` without calling `interpret_turn_v2`; the flow then advances to `REQUEST_QUOTE`.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_orchestrator_v2.py` (mirrors the file's existing `_FakeSB`/`_no_llm` harness):

```python
@pytest.mark.asyncio
async def test_final_notes_renders_disclaimer_and_captures_verbatim(monkeypatch):
    # Seed a session parked at ASK_FINAL_NOTES with the design confirmed.
    store = _new_store()
    store["session"]["state"] = S.ASK_FINAL_NOTES.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": True, "logos_done": True, "pending_logo": None,
        "email_captured": True, "lead_id": "L1", "decor_done": True,
        "quantity": 12, "decoration_done": True, "needed_by": "2-4 weeks",
        "purpose": "team caps", "design_confirmed": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "get_store", lambda _id: None)
    # Interpreter MUST NOT be called for a direct_capture step.
    async def _boom(*a, **k):
        raise AssertionError("interpreter must not run for direct_capture")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    out = await o2.handle_message("s1", "Text in Pantone 186 C please")

    assert "Customer final notes: Text in Pantone 186 C please" in \
        store["session"]["collected"]["brief_notes"]
    assert store["session"]["collected"]["final_notes_done"] is True
    assert store["session"]["state"] == S.REQUEST_QUOTE.value


@pytest.mark.asyncio
async def test_final_notes_ask_shows_disclaimer_links(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.REVIEW_DESIGN.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "has_logo": True, "logos_done": True, "pending_logo": None,
        "email_captured": True, "decor_done": True, "quantity": 12,
        "decoration_done": True, "needed_by": "2-4 weeks", "purpose": "team caps",
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "get_store", lambda _id: None)

    out = await o2.handle_message("s1", "Looks great, send it")

    assert store["session"]["state"] == S.ASK_FINAL_NOTES.value
    assert prompts.V2_DEFAULT_COLOUR_EMBROIDERY_URL in out["reply"]
    assert "closest match" in out["reply"]
    assert out["data"]["options"] == ["Nothing to add"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -q`
Expected: FAIL (interpreter called / disclaimer text absent — `colour_note` not threaded yet).

- [ ] **Step 3: Import the renderer and add the `direct_capture` branch**

In `orchestrator_v2.py`, extend the branding import (line 22):

```python
from app.services.branding import canvas_intro_text, colour_disclaimer_text
```

After `intro = canvas_intro_text(store)` (line 61), add:

```python
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
```

Add the `direct_capture` branch in the free-text handling (replace lines 96–116, keeping the outage handling intact):

```python
    fields = v2.resolve_chip(step, message, collected)
    if fields is None and step.slots:
        if step.direct_capture:
            # The answer IS the message; interpreting it adds nothing and an LLM
            # could reshape a colour code. Verbatim, still validated + apply-guarded.
            fields = ie.validate_fields(step.direct_answer(message))
        else:
            # Free text on a step that asks for something: the model reads it, or
            # we stall. No keyword fallback — a wrong field corrupts the design.
            try:
                fields = await ie.interpret_turn_v2(step, message, collected)
            except ie.LLMUnavailable:
                if step.direct_answer is None:
                    return await _stall(sb, session_id, collected, step,
                                        state_before, message, config=flow_config)
                fields = ie.validate_fields(step.direct_answer(message))
            else:
                ack = await ie.write_ack(persona, fields)
    elif fields is None:
        fields = {}                       # ack-only step (show_intro)
```

- [ ] **Step 4: Thread `colour_note` into every `reply_for` call**

In `handle_message`, add `colour_note=colour_note` to the `reply_for` calls at the GREETING branch, the empty-turn branch, and the main call:

```python
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)          # GREETING
```
```python
        reply = v2.reply_for(step, collected, persona=persona, intro=intro,
                             colour_note=colour_note)          # empty-turn
```
```python
    reply = v2.reply_for(next_, collected, persona=persona, intro=intro,
                         ack=ack, colour_note=colour_note)     # main
```

In `handle_back`, compute the same `colour_note` after its `intro = canvas_intro_text(store)` (line 186):

```python
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
```

and add `colour_note=colour_note` to its three `reply_for` calls (GREETING branch, no-target branch, and the final call).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_orchestrator_v2.py -q`
Expected: PASS.

- [ ] **Step 6: Extend the v2 e2e walk**

In `backend/tests/test_v2_e2e.py`, find the full chip-driven walk and add, after the design is confirmed at `REVIEW_DESIGN` and before `REQUEST_QUOTE`, a turn that answers `ASK_FINAL_NOTES` with the chip `"Nothing to add"` and assert the state then reaches `REQUEST_QUOTE`. (Match the existing walk's helper style — send the exact chip label the UI ships.) Concretely, insert a step asserting:

```python
    # colour disclaimer + final notes, then the quote ask
    assert state_now() == S.ASK_FINAL_NOTES.value
    out = await send("Nothing to add")
    assert state_now() == S.REQUEST_QUOTE.value
```

(Use the walk's existing `send`/`state_now` equivalents; if the walk raises `LLMUnavailable` throughout, the `"Nothing to add"` chip still resolves deterministically, proving the step needs no model.)

- [ ] **Step 7: Run the e2e + the full v2 subset**

Run: `cd backend && ./.venv/Scripts/python.exe -m pytest tests/test_v2_e2e.py tests/test_orchestrator_v2.py tests/test_state_machine_v2.py tests/test_canvas_steps.py -q`
Expected: PASS. Then the whole suite baseline: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` — expect the prior passing count, no new failures.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py backend/tests/test_orchestrator_v2.py backend/tests/test_v2_e2e.py
git commit -m "feat(canvas-v2): render colour disclaimer + capture final notes verbatim before quote"
```

---

### Task 4: Frontend — admin URL fields for the reference links

**Files:**
- Modify: `frontend/src/lib/types.ts:120-127` (add two keys to `Brand`)
- Modify: `frontend/src/admin/views/BrandingView.tsx` (add two URL inputs after the Canvas intro block; add client validation)
- Test: `frontend/src/admin/views/BrandingView.test.tsx`

**Interfaces:**
- Consumes: `Brand` type; `setField(k, v)` (already `(k: keyof Brand, v: string)`).
- Produces: two optional `Brand` keys `colour_ref_embroidery_url`, `colour_ref_print_url`, editable and validated in the Branding view.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/admin/views/BrandingView.test.tsx` (mirror the file's existing render/mock setup):

```tsx
it('renders and edits the colour reference link fields', async () => {
  // ...existing render harness that loads a store...
  const embroidery = await screen.findByLabelText('Embroidery colour chart URL')
  const print = screen.getByLabelText('Print colour guide URL')
  fireEvent.change(embroidery, { target: { value: 'https://acme.test/e' } })
  fireEvent.change(print, { target: { value: 'https://acme.test/p' } })
  expect((embroidery as HTMLInputElement).value).toBe('https://acme.test/e')
  expect((print as HTMLInputElement).value).toBe('https://acme.test/p')
})

it('rejects a non-http colour reference link on save', async () => {
  // ...render, set embroidery to 'ftp://x', click Save...
  fireEvent.change(await screen.findByLabelText('Embroidery colour chart URL'),
    { target: { value: 'ftp://acme.test/e' } })
  fireEvent.click(screen.getByRole('button', { name: /save/i }))
  expect(await screen.findByText(/http\(s\) URLs/i)).toBeInTheDocument()
})
```

(Adapt the render/save-button selectors to the existing test's helpers.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/admin/views/BrandingView.test.tsx`
Expected: FAIL (`Unable to find a label 'Embroidery colour chart URL'`).

- [ ] **Step 3: Add the `Brand` keys**

In `frontend/src/lib/types.ts`, inside `interface Brand` (after `canvas_intro?`):

```ts
  colour_ref_embroidery_url?: string
  colour_ref_print_url?: string
```

- [ ] **Step 4: Add the inputs + validation to `BrandingView.tsx`**

In `validate(brand)` (before `return null`):

```ts
  for (const k of ['colour_ref_embroidery_url', 'colour_ref_print_url'] as const) {
    const v = brand[k]
    if (v && !/^https?:\/\//i.test(v)) return 'Colour reference links must be full http(s) URLs'
  }
```

After the Canvas intro `</label>` block (line 192), insert:

```tsx
      {/* Colour reference guide links (shown in the pre-quote colour note) */}
      <div className="flex flex-col gap-2 rounded-xl border border-[#e0e1ea] bg-white p-4">
        <span className="text-sm text-textMuted">Colour reference guide links</span>
        <label className="flex flex-col gap-1 text-[12px] text-[#6b6b80]">
          <span>Embroidery colour chart URL</span>
          <input type="url" aria-label="Embroidery colour chart URL"
                 value={brand.colour_ref_embroidery_url ?? ''}
                 onChange={e => setField('colour_ref_embroidery_url', e.target.value)}
                 placeholder="https://…"
                 className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-2 text-sm" />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-[#6b6b80]">
          <span>Print colour guide URL</span>
          <input type="url" aria-label="Print colour guide URL"
                 value={brand.colour_ref_print_url ?? ''}
                 onChange={e => setField('colour_ref_print_url', e.target.value)}
                 placeholder="https://…"
                 className="rounded-lg border border-[#e0e1ea] bg-white px-3 py-2 text-sm" />
        </label>
      </div>
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/admin/views/BrandingView.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/admin/views/BrandingView.tsx frontend/src/admin/views/BrandingView.test.tsx
git commit -m "feat(admin): colour reference link fields in Branding view"
```

---

### Task 5: Frontend — clickable links in chat bubbles

**Files:**
- Create: `frontend/src/lib/linkify.tsx`
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:444` (render `{linkify(msg.text)}`)
- Test: `frontend/src/lib/linkify.test.tsx`

**Interfaces:**
- Produces: `linkify(text: string): ReactNode[]` — plain strings interleaved with `<a target="_blank" rel="noopener noreferrer">` for each `http(s)://…` URL.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/linkify.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { linkify } from './linkify'

describe('linkify', () => {
  it('turns a URL into a new-tab anchor and keeps surrounding text', () => {
    render(<p>{linkify('See https://acme.test/chart for colours.')}</p>)
    const a = screen.getByRole('link')
    expect(a).toHaveAttribute('href', 'https://acme.test/chart')
    expect(a).toHaveAttribute('target', '_blank')
    expect(a).toHaveAttribute('rel', 'noopener noreferrer')
    expect(screen.getByText(/for colours\./)).toBeInTheDocument()
  })

  it('does not include trailing punctuation in the href', () => {
    render(<p>{linkify('go to https://acme.test/x.')}</p>)
    expect(screen.getByRole('link')).toHaveAttribute('href', 'https://acme.test/x')
  })

  it('leaves plain text without links untouched', () => {
    render(<p>{linkify('no links here')}</p>)
    expect(screen.queryByRole('link')).toBeNull()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/linkify.test.tsx`
Expected: FAIL (`Cannot find module './linkify'`).

- [ ] **Step 3: Create the linkifier**

`frontend/src/lib/linkify.tsx`:

```tsx
import type { ReactNode } from 'react'

const URL_RE = /(https?:\/\/[^\s]+)/g

/**
 * Split text into plain strings and clickable <a> nodes for any http(s) URL.
 * Chat bubbles render assistant text as plain (whitespace-pre-wrap) — this makes
 * URLs (e.g. the colour reference links) clickable. Trailing sentence
 * punctuation is kept out of the href.
 */
export function linkify(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let key = 0
  let m: RegExpExecArray | null
  URL_RE.lastIndex = 0
  while ((m = URL_RE.exec(text)) !== null) {
    let url = m[0]
    const trail = url.match(/[.,;:!?)]+$/)
    const tail = trail ? trail[0] : ''
    if (tail) url = url.slice(0, -tail.length)
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(
      <a key={key++} href={url} target="_blank" rel="noopener noreferrer"
         className="underline break-all">{url}</a>,
    )
    if (tail) out.push(tail)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}
```

- [ ] **Step 4: Use it in the chat bubble**

In `ChatColumn.tsx`, add the import near the top:

```tsx
import { linkify } from '../../lib/linkify'
```

Replace line 444 (`{msg.text}`) with:

```tsx
              {linkify(msg.text)}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/linkify.test.tsx src/__tests__/ChatColumn.test.tsx`
Expected: PASS (ChatColumn test unaffected — plain-text messages render identically).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/linkify.tsx frontend/src/lib/linkify.test.tsx frontend/src/components/CustomiseStudio/ChatColumn.tsx
git commit -m "feat(chat): clickable http(s) links in message bubbles"
```

---

### Task 6: Frontend — honest, Mac-aware voice-mic messaging

**Files:**
- Modify: `frontend/src/hooks/useSpeechRecognition.ts` (insecure-context short-circuit + error-name branching)
- Test: `frontend/src/__tests__/useSpeechRecognition.test.tsx`

**Interfaces:**
- Produces: `start()` sets a secure-context message and returns without calling `getUserMedia` when `window.isSecureContext === false`; a `getUserMedia` rejection maps `NotAllowedError`/`SecurityError` → Mac-aware "blocked" message, `NotFoundError`/`OverconstrainedError` → "no microphone found".

- [ ] **Step 1: Write the failing tests**

First, make the existing suite deterministic about secure context — in the `beforeEach` of `useSpeechRecognition.test.tsx`, add:

```tsx
  Object.defineProperty(window, 'isSecureContext', {
    configurable: true, value: true,
  })
```

Then add:

```tsx
  it('reports voice unavailable on an insecure origin without touching getUserMedia', async () => {
    Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false })
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => { await result.current.start() })
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(currentRec.start).not.toHaveBeenCalled()
    expect(result.current.error).toMatch(/secure \(https\) connection/i)
  })

  it('gives Mac-aware guidance when the OS/site permission is denied', async () => {
    getUserMedia.mockRejectedValue(
      Object.assign(new Error('denied'), { name: 'NotAllowedError' }))
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toMatch(/System Settings/i)
  })

  it('reports when no microphone is found', async () => {
    getUserMedia.mockRejectedValue(
      Object.assign(new Error('none'), { name: 'NotFoundError' }))
    const { result } = renderHook(() => useSpeechRecognition(vi.fn()))
    await act(async () => { await result.current.start() })
    expect(result.current.error).toMatch(/no microphone/i)
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/__tests__/useSpeechRecognition.test.tsx`
Expected: the three new tests FAIL (current code has one generic blocked message, no secure-context check, no not-found branch).

- [ ] **Step 3: Add the messages + branching**

In `useSpeechRecognition.ts`, replace the single `MIC_BLOCKED_MESSAGE` constant (lines 17–20) with:

```ts
/** Shown when the site/OS has blocked microphone access. Mac-aware. */
const MIC_BLOCKED_MESSAGE =
  'Microphone access is blocked. Allow it via the mic icon in your browser’s ' +
  'address bar, and on Mac also check System Settings → Privacy & Security → ' +
  'Microphone → Chrome. Then hold to talk again.'
/** Shown on an insecure origin, where the browser refuses the mic outright. */
const MIC_INSECURE_MESSAGE =
  'Voice needs a secure (https) connection, so it’s unavailable on this site ' +
  'right now. You can type your message instead.'
/** Shown when the device exposes no microphone. */
const MIC_NOT_FOUND_MESSAGE = 'No microphone was found on this device.'
```

At the very top of `start()` (before the `if (!micReadyRef.current)` block, ~line 132), add:

```ts
    if (typeof window !== 'undefined' && window.isSecureContext === false) {
      // On http:// (non-localhost) Chrome refuses the mic and never prompts —
      // no address-bar icon appears — so the "unblock" hint would be wrong.
      setError(MIC_INSECURE_MESSAGE)
      setListening(false)
      return
    }
```

Change the `getUserMedia` catch (lines 140–144) to branch on the error name:

```ts
        } catch (err) {
          const name = (err as { name?: string })?.name
          setError(name === 'NotFoundError' || name === 'OverconstrainedError'
            ? MIC_NOT_FOUND_MESSAGE
            : MIC_BLOCKED_MESSAGE)
          setListening(false)
          return
        }
```

(The `onerror` `not-allowed` handler at line 109 keeps pointing at `MIC_BLOCKED_MESSAGE` — now Mac-aware — for mid-session revocation. No change needed there.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/__tests__/useSpeechRecognition.test.tsx src/__tests__/usePushToTalk.test.tsx`
Expected: PASS (all existing tests still green — the `isSecureContext: true` default in `beforeEach` keeps them on the secure path; the `/blocked/i` assertions still match the new Mac-aware copy, which contains "blocked").

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSpeechRecognition.ts frontend/src/__tests__/useSpeechRecognition.test.tsx
git commit -m "fix(voice): honest, Mac-aware mic messaging (insecure origin + error-name branching)"
```

---

## Post-implementation note (not a code task)

The mic will still not function on the deployed **`http://`** site regardless of these changes — Chrome only grants the mic on **HTTPS or localhost**. The definitive unblock is to serve the prod frontend over **HTTPS** (reverse proxy + certificate) and grant Chrome **macOS** mic permission (System Settings → Privacy & Security → Microphone → Chrome). Flag this to the deploy owner; it is environmental and deliberately out of scope for this plan.

---

## Self-Review

**Spec coverage:**
- A. Mic messaging → Task 6 (insecure-context + error-name branching); HTTPS gap documented (post-impl note). ✓
- B. New step placement (after review, before quote) → Task 2 (registry insert) + Task 3 (orchestrator). ✓
- Colour disclaimer copy + verbatim final notes → Task 1 (copy) + Task 2 (`_apply_final_notes`, `direct_capture`) + Task 3 (verbatim capture). ✓
- Admin-configurable links + dummy defaults → Task 1 (backend validate + defaults) + Task 4 (admin UI). ✓
- Clickable links in chat → Task 5. ✓
- Testing (pure routing, orchestrator, e2e, branding, frontend units) → each task's tests. ✓

**Placeholder scan:** No TBD/TODO. The one soft spot is the e2e insertion (Task 3 Step 6) and the BrandingView render harness (Task 4 Step 1), which must adapt to each test file's existing helpers — the exact assertions are given; only the surrounding `send`/`render` boilerplate is reused from the file. Acceptable (the harness already exists and is file-specific).

**Type consistency:** `colour_disclaimer_text(store, name)` (Task 1) is called identically in Task 3. `reply_for(..., colour_note="")` (Task 2) is called with `colour_note=` in Task 3. `Step.direct_capture` (Task 2 dataclass) is read in Task 3's branch. `final_notes` is a slot (writable); `final_notes_done` is not (set only in apply/chip) — consistent across Tasks 2 and 3. `linkify` signature identical in Task 5's util and its ChatColumn use. Brand keys `colour_ref_embroidery_url`/`colour_ref_print_url` identical across backend (Task 1) and frontend (Task 4). ✓
