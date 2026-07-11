# Wider Design Brief + Goal-Leading Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a customer build a full multi-element design brief (logo + text + graphics + colours + style) through conversation before generating, allow adding/modifying elements during post-generation refinement, and collapse the three redundant post-verification "your design is on its way" statements into one message that lands on the tweak offer.

**Architecture:** Backend-only (Python/FastAPI conversation engine). A new "anything else?" gather loop (two states, modelled on the existing pin-annotation pair) sits between the design-source branch and placement; both the logo and describe paths funnel into it. A `merge_brief` helper accumulates elements into one canonical structured `design_description` dict, which the (previously dead) rich extractor now feeds and the prompt builder enumerates for both the described-design and uploaded-logo paths. The post-verification collapse is achieved by adding three statement states to `AUTO_ADVANCE_STATES` so `check_verification` walks straight to `OFFER_REFINE`.

**Tech Stack:** Python 3.12, FastAPI, pytest / pytest-asyncio. No new dependencies. No frontend changes (verified: `ChatPanel` renders option chips and the text input together; `RELEASED_STATES` already includes `offer_refine`).

## Global Constraints

- Python target: **3.12** (dev machine may run 3.14 — final suite must be verified on 3.12 / Docker before merge).
- No PII (name/email/phone) in logs or LLM contexts — reuse the existing `_safe_collected` redaction; never log raw messages.
- The engine must keep working **with no `ANTHROPIC_API_KEY`** (deterministic heuristic fallbacks) — every new LLM touchpoint needs a no-key path. Degraded structure without a key is acceptable, but nothing may crash.
- The LLM never decides routing — it only interprets input and words replies. Routing stays in `state_machine` / `goal_planner`.
- Composite onto the real product reference photo — never regenerate the cap. (Unchanged; prompt builder already enforces.)
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- Run backend tests from `backend/` with the project venv: `pytest -q`.

---

## File Structure

- `backend/app/services/conversation/brief.py` — **new.** `merge_brief(existing, incoming)` pure helper. One responsibility: accumulate structured design elements losslessly.
- `backend/app/services/prompt_builder.py` — refactor `_design_block` to a shared `_element_lines(design)` used by both the described-design and uploaded-logo branches.
- `backend/app/services/conversation/state_machine.py` — two new states, transitions, backtracks, `advance_state` branches, `AUTO_ADVANCE_STATES` collapse.
- `backend/app/services/conversation/goal_planner.py` — insert the gather goal; add the two states to `GATE_STATES`.
- `backend/app/services/conversation/orchestrator.py` — derive gather booleans + one-shot flag in `_apply_fields`; `_public_data` for the new states; new async `_maybe_gather_element`; `check_verification` acknowledgment aside.
- `backend/app/prompts.py` — `STATE_PROMPTS` + `CANNED_REPLIES` for the two new states (goal-leading wording).
- `backend/tests/` — `test_brief.py` (new), plus additions to `test_prompt_builder.py`, `test_state_machine.py`, `test_goal_planner.py` (or the existing goal-planner test file), `test_conversation_smart.py`.

---

## Task 1: `merge_brief` accumulation helper

**Files:**
- Create: `backend/app/services/conversation/brief.py`
- Test: `backend/tests/test_brief.py`

**Interfaces:**
- Produces: `merge_brief(existing: dict, incoming: dict) -> dict`. Returns a new dict with keys among `summary`, `style` (scalars, fill-if-empty) and `text_elements`, `colours`, `imagery` (lists, appended + de-duplicated, order-preserving). Empty keys are pruned. A non-empty `incoming.summary` arriving when `existing.summary` is already set, with no structured lists in `incoming`, is appended to `text_elements` (lossless accumulation for the no-LLM path).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_brief.py
"""merge_brief — lossless accumulation of design elements into one brief."""
from __future__ import annotations

from app.services.conversation.brief import merge_brief


def test_merge_appends_and_dedupes_lists():
    existing = {"text_elements": ["SUMMIT CO"], "imagery": ["mountain"]}
    incoming = {"text_elements": ["SUMMIT CO", "EST 2020"], "imagery": ["compass"]}
    out = merge_brief(existing, incoming)
    assert out["text_elements"] == ["SUMMIT CO", "EST 2020"]
    assert out["imagery"] == ["mountain", "compass"]


def test_merge_fills_empty_scalars_only():
    out = merge_brief({"summary": "first"}, {"summary": "second", "style": "bold"})
    assert out["summary"] == "first"      # first non-empty summary wins
    assert out["style"] == "bold"          # style was empty -> filled


def test_incoming_summary_becomes_text_element_when_summary_taken():
    # No-LLM path: a second freeform element arrives as {"summary": ...}. It must
    # not be dropped just because summary is already set.
    out = merge_brief({"summary": "our logo"}, {"summary": "team name in gold"})
    assert out["summary"] == "our logo"
    assert "team name in gold" in out["text_elements"]


def test_empty_fields_pruned():
    out = merge_brief({}, {"summary": "x", "text_elements": [], "colours": [""]})
    assert out == {"summary": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_brief.py -v`
Expected: FAIL with `ModuleNotFoundError: app.services.conversation.brief`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/conversation/brief.py
"""Accumulate structured design elements into one canonical brief.

The brief is the single source of design intent for both flows (uploaded logo
and described design) and for post-generation refinement. Merging is additive
and lossless: lists grow (de-duplicated), scalars fill once, and a freeform
element that arrives as a bare ``summary`` when we already have one is kept as a
text element rather than dropped (the no-LLM path produces summary-only dicts).
"""
from __future__ import annotations

_LIST_KEYS = ("text_elements", "colours", "imagery")
_SCALAR_KEYS = ("summary", "style")


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def merge_brief(existing: dict | None, incoming: dict | None) -> dict:
    existing = existing or {}
    incoming = incoming or {}
    out: dict = {}

    for key in _LIST_KEYS:
        out[key] = _dedupe(list(existing.get(key) or []) + list(incoming.get(key) or []))

    for key in _SCALAR_KEYS:
        out[key] = (existing.get(key) or incoming.get(key) or "").strip()

    inc_summary = (incoming.get(key := "summary") and incoming[key].strip()) or ""
    has_incoming_lists = any(incoming.get(k) for k in _LIST_KEYS)
    if inc_summary and existing.get("summary") and not has_incoming_lists:
        if inc_summary not in out["text_elements"]:
            out["text_elements"].append(inc_summary)

    # Prune empties so the prompt builder never emits dangling labels.
    return {k: v for k, v in out.items() if v}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_brief.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/brief.py backend/tests/test_brief.py
git commit -m "feat(convo): merge_brief helper accumulates design elements losslessly"
```

---

## Task 2: Prompt builder enumerates elements on the uploaded-logo path

**Files:**
- Modify: `backend/app/services/prompt_builder.py:31-68` (`_design_block`)
- Test: `backend/tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: `collected["design_description"]` as the structured brief dict (from Task 1's merge).
- Produces: no signature change to `build_prompt`; the uploaded-asset branch now enumerates `text_elements` / `colours` / `imagery` / `style` in addition to `summary`.

**Context:** Today `_design_block` only appends `summary` for uploaded assets, and the rich described-design branch duplicates the enumeration inline. Extract one `_element_lines(design)` helper and use it in both branches so a logo **plus** gathered text/graphics all reach the model. The described-design branch behaviour (tested by `test_described_design_weaves_all_structured_fields` / `test_described_design_omits_empty_fields`) must stay identical.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_prompt_builder.py
def test_uploaded_asset_includes_gathered_elements():
    collected = {
        "uploaded_asset_path": "uploads/logo.png",
        "design_description": {
            "text_elements": ["TEAM SPIRIT"],
            "colours": ["gold"],
            "imagery": ["star"],
        },
    }
    prompt = _build(collected)
    assert "SECOND image" in prompt          # logo still composited
    assert "TEAM SPIRIT" in prompt           # gathered text reaches the model
    assert "gold" in prompt
    assert "star" in prompt


def test_uploaded_asset_without_extras_has_no_dangling_labels():
    collected = {"uploaded_asset_path": "uploads/logo.png"}
    prompt = _build(collected)
    assert "SECOND image" in prompt
    assert "Text to include" not in prompt
    assert "Graphics/icons" not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompt_builder.py::test_uploaded_asset_includes_gathered_elements -v`
Expected: FAIL (assert "TEAM SPIRIT" in prompt — currently the uploaded branch ignores text_elements)

- [ ] **Step 3: Write minimal implementation**

Replace the `_design_block` function (lines 31-68) with:

```python
def _element_lines(design: dict) -> list[str]:
    """Enumerate the described decoration elements as prompt lines. Empty fields
    are skipped so no dangling labels leak into the prompt."""
    lines: list[str] = []
    summary = design.get("summary")
    if summary:
        lines.append(summary)
    text_elements = [t for t in (design.get("text_elements") or []) if t]
    if text_elements:
        quoted = ", ".join(f'"{t}"' for t in text_elements)
        lines.append(f"Text to include (render exactly as written): {quoted}")
    colours = [c for c in (design.get("colours") or []) if c]
    if colours:
        lines.append(f"Design colours (of the decoration, not the cap): {', '.join(colours)}")
    imagery = [i for i in (design.get("imagery") or []) if i]
    if imagery:
        lines.append(f"Graphics/icons: {', '.join(imagery)}")
    style = design.get("style")
    if style:
        lines.append(f"Design style: {style}")
    return lines


def _design_block(collected: dict) -> str:
    """Describe ONLY the decoration to add — never the base cap.

    Both flows funnel through one structured brief (``design_description``). Flow
    B (uploaded logo) points the model at the second image AND enumerates any
    extra elements the customer gathered; Flow A (described design) enumerates
    the same fields with no logo.
    """
    design = collected.get("design_description") or {}
    if not isinstance(design, dict):
        design = {"summary": str(design)} if design else {}
    if not design.get("summary") and collected.get("design_summary"):
        design = {**design, "summary": collected["design_summary"]}

    lines = _element_lines(design)

    if collected.get("uploaded_asset_path"):
        block = prompts.UPLOADED_ASSET_DESIGN_BLOCK
        if lines:
            block += "\nAlso incorporate these customer details:\n" + "\n".join(lines)
        return block

    return "\n".join(lines) if lines else prompts.FALLBACK_DESIGN_BLOCK
```

- [ ] **Step 4: Run the prompt-builder tests**

Run: `pytest tests/test_prompt_builder.py -v`
Expected: PASS — the two new tests plus all pre-existing tests (Flow A weaving, empty-field omission, uploaded-asset second-image, collage locks) stay green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/prompt_builder.py backend/tests/test_prompt_builder.py
git commit -m "feat(prompt): enumerate gathered elements onto the uploaded-logo path"
```

---

## Task 3: State machine — gather-loop states + post-verification collapse

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py`
- Test: `backend/tests/test_state_machine.py`

**Interfaces:**
- Produces: two new `ConversationState` members `ASK_MORE_ELEMENTS = "ask_more_elements"` and `ADD_ELEMENTS_MODE = "add_elements_mode"`; `advance_state` branches on `collected["wants_more_elements"]` and `collected["add_another_element"]`; `AUTO_ADVANCE_STATES` additionally contains `EMAIL_VERIFIED`, `SEND_PREVIEW_EMAIL`, `SHOW_DESIGN`.
- Consumes: booleans set by the orchestrator (Task 5).

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_state_machine.py
def test_more_elements_branch():
    assert advance_state(S.ASK_MORE_ELEMENTS, {"wants_more_elements": True}) is S.ADD_ELEMENTS_MODE
    assert advance_state(S.ASK_MORE_ELEMENTS, {"wants_more_elements": False}) is S.ASK_PLACEMENT_ZONE


def test_add_elements_loops_then_exits():
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": True}) is S.ADD_ELEMENTS_MODE
    assert advance_state(S.ADD_ELEMENTS_MODE, {"add_another_element": False}) is S.ASK_PLACEMENT_ZONE


def test_design_source_paths_reach_more_elements():
    # Both the logo path (via remove-bg) and the describe path funnel into the
    # gather loop, not straight to placement.
    assert advance_state(S.ASK_REMOVE_BG, {}) is S.ASK_MORE_ELEMENTS
    assert advance_state(S.DESCRIBE_DESIGN, {}) is S.ASK_MORE_ELEMENTS


def test_post_verification_collapses_to_offer_refine():
    # After verification the chat must walk EMAIL_VERIFIED -> SEND_PREVIEW_EMAIL
    # -> SHOW_DESIGN without resting, landing on OFFER_REFINE.
    from app.services.conversation.state_machine import AUTO_ADVANCE_STATES
    state = advance_state(S.VERIFY_EMAIL, {"email_verified": True})  # EMAIL_VERIFIED
    for _ in range(10):
        if state in AUTO_ADVANCE_STATES:
            state = advance_state(state, {})
            continue
        break
    assert state is S.OFFER_REFINE
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_state_machine.py::test_more_elements_branch -v`
Expected: FAIL with `AttributeError: ASK_MORE_ELEMENTS` (enum member does not exist yet)

- [ ] **Step 3: Implement**

3a. Add the two enum members after `DESCRIBE_DESIGN` (line 27):

```python
    DESCRIBE_DESIGN = "describe_design"
    ASK_MORE_ELEMENTS = "ask_more_elements"
    ADD_ELEMENTS_MODE = "add_elements_mode"
    ASK_PLACEMENT_ZONE = "ask_placement_zone"
```

3b. In `TRANSITIONS`, change the two design-source successors and add the loop:

```python
    S.UPLOAD_LOGO: [S.ASK_REMOVE_BG],
    S.ASK_REMOVE_BG: [S.ASK_MORE_ELEMENTS],
    S.DESCRIBE_DESIGN: [S.ASK_MORE_ELEMENTS],
    S.ASK_MORE_ELEMENTS: [S.ADD_ELEMENTS_MODE, S.ASK_PLACEMENT_ZONE],
    S.ADD_ELEMENTS_MODE: [S.ADD_ELEMENTS_MODE, S.ASK_PLACEMENT_ZONE],
    S.ASK_PLACEMENT_ZONE: [S.ASK_PLACEMENT_POSITION],
```

3c. In `ALLOWED_BACKTRACKS`, let the gather states rewind to the design source, and let placement rewind to the gather offer:

```python
    S.ASK_MORE_ELEMENTS: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.UPLOAD_LOGO],
    S.ADD_ELEMENTS_MODE: [S.ASK_MORE_ELEMENTS],
    S.ASK_PLACEMENT_ZONE: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.ASK_MORE_ELEMENTS],
```

(Replace the existing `S.ASK_PLACEMENT_ZONE` backtrack entry; add the two new keys.)

3d. In `advance_state`, add the two branches immediately before the `# --- Email capture branch ---` comment:

```python
    # --- Additional-elements gather loop ---
    if current is S.ASK_MORE_ELEMENTS:
        return S.ADD_ELEMENTS_MODE if collected.get("wants_more_elements") else S.ASK_PLACEMENT_ZONE

    if current is S.ADD_ELEMENTS_MODE:
        return S.ADD_ELEMENTS_MODE if collected.get("add_another_element") else S.ASK_PLACEMENT_ZONE
```

3e. Extend `AUTO_ADVANCE_STATES` (currently CHECK_YOUTH / DECORATION_ENGINE / CONFIRM_DECORATION) with the three post-verification statement states so `check_verification` collapses them:

```python
AUTO_ADVANCE_STATES: frozenset[ConversationState] = frozenset(
    {
        ConversationState.CHECK_YOUTH,
        ConversationState.DECORATION_ENGINE,
        ConversationState.CONFIRM_DECORATION,
        ConversationState.EMAIL_VERIFIED,
        ConversationState.SEND_PREVIEW_EMAIL,
        ConversationState.SHOW_DESIGN,
    }
)
```

- [ ] **Step 4: Run the state-machine suite**

Run: `pytest tests/test_state_machine.py -v`
Expected: PASS — the 4 new tests plus all pre-existing tests. `_progress_path` is unchanged (the gather loop is optional and not counted), so `test_progress_*` totals stay 8/9.

- [ ] **Step 5: Run the full backend suite to catch collapse fallout**

Run: `pytest -q`
Expected: PASS. If a `check_verification` test asserted the chat rests at `email_verified`/`show_design` after verification, update it to expect `offer_refine` (that is the intended new behaviour). Note any such change in the commit body.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(convo): add element-gather loop states; collapse post-verification statements"
```

---

## Task 4: Goal planner — insert the gather goal

**Files:**
- Modify: `backend/app/services/conversation/goal_planner.py`
- Test: `backend/tests/test_goal_planner.py` (create if absent — see note)

**Interfaces:**
- Consumes: `ConversationState.ASK_MORE_ELEMENTS` / `ADD_ELEMENTS_MODE` (Task 3); one-shot flag `collected["elements_offered"]` (set by the orchestrator in Task 5).
- Produces: `next_goal` returns `S.ASK_MORE_ELEMENTS` after the design source is satisfied and before placement, guarded by `elements_offered`; `GATE_STATES` includes both new states.

**Note:** Task 1 of the prior goal-oriented plan added goal-planner tests — check for `backend/tests/test_goal_planner.py`. If it does not exist, create it with the imports below.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_goal_planner.py  (add to it, or create with these imports)
from app.services.conversation import goal_planner
from app.services.conversation.state_machine import ConversationState as S


def _base():
    # Everything up to and including the design source is satisfied.
    return {
        "name": "Al", "purpose": "gifts", "purpose_asked": True,
        "quantity": 24, "decoration_type": "embroidery",
        "has_logo": False, "design_description": {"summary": "a crest"},
    }


def test_gather_goal_offered_once_before_placement():
    collected = _base()
    assert goal_planner.next_goal(collected) is S.ASK_MORE_ELEMENTS


def test_gather_goal_skipped_once_offered():
    collected = {**_base(), "elements_offered": True}
    assert goal_planner.next_goal(collected) is S.ASK_PLACEMENT_ZONE


def test_gather_states_are_gates():
    assert S.ASK_MORE_ELEMENTS in goal_planner.GATE_STATES
    assert S.ADD_ELEMENTS_MODE in goal_planner.GATE_STATES
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_goal_planner.py::test_gather_goal_offered_once_before_placement -v`
Expected: FAIL (returns `S.ASK_PLACEMENT_ZONE` — the gather goal is not inserted yet)

- [ ] **Step 3: Implement**

3a. Add both states to `GATE_STATES` (after `S.PIN_ANNOTATE_MODE`):

```python
        S.ASK_PIN_ANNOTATION,
        S.PIN_ANNOTATE_MODE,
        S.ASK_MORE_ELEMENTS,
        S.ADD_ELEMENTS_MODE,
        S.GENERATING,
```

3b. In `next_goal`, insert the gather goal between the design-source block (step 5) and placement (step 6):

```python
    # 5b. additional elements (optional, offered exactly once)
    if not collected.get("elements_offered"):
        return S.ASK_MORE_ELEMENTS

    # 6. placement (required; zone only — position defaults to centre elsewhere)
    if not collected.get("placement_zone"):
        return S.ASK_PLACEMENT_ZONE
```

- [ ] **Step 4: Run the goal-planner suite**

Run: `pytest tests/test_goal_planner.py -v`
Expected: PASS (3 new tests + any pre-existing).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/goal_planner.py backend/tests/test_goal_planner.py
git commit -m "feat(convo): goal planner offers the element-gather step before placement"
```

---

## Task 5: Orchestrator — gather booleans, one-shot flag, option chips

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (`_apply_fields`, one-shot flag block ~line 130-135, `_public_data`)
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `is_affirmative` / `is_negative` (already imported), the new states (Task 3).
- Produces: `_apply_fields` sets `collected["wants_more_elements"]` at `ASK_MORE_ELEMENTS` and `collected["add_another_element"]` at `ADD_ELEMENTS_MODE`; the one-shot flag `collected["elements_offered"] = True` is set when `new_state` first becomes `ASK_MORE_ELEMENTS`; `_public_data` returns option chips for both new states.

**Note:** This task does NOT yet extract elements (that is Task 6). It only wires routing so the loop advances/exits correctly without a key.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_conversation_smart.py
@pytest.mark.asyncio
async def test_more_elements_yes_enters_add_mode(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "design_description": {"summary": "a crest"},
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what would you like to add?"))
    res = await orch.handle_message("s1", "Add text")
    assert res["state"] == S.ADD_ELEMENTS_MODE.value


@pytest.mark.asyncio
async def test_more_elements_decline_goes_to_placement(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "design_description": {"summary": "a crest"},
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("where should it go?"))
    res = await orch.handle_message("s1", "That's everything")
    assert res["state"] == S.ASK_PLACEMENT_ZONE.value


@pytest.mark.asyncio
async def test_add_mode_exits_on_done(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ADD_ELEMENTS_MODE.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "design_description": {"summary": "a crest"},
                                       "elements_offered": True}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("placing it"))
    res = await orch.handle_message("s1", "that's it, generate")
    assert res["state"] == S.ASK_PLACEMENT_ZONE.value


def test_public_data_offers_element_chips():
    data = orch._public_data(S.ASK_MORE_ELEMENTS, {})
    assert "That's everything" in data["options"]
    data2 = orch._public_data(S.ADD_ELEMENTS_MODE, {})
    assert "That's everything" in data2["options"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_conversation_smart.py::test_more_elements_yes_enters_add_mode -v`
Expected: FAIL — without `wants_more_elements` set, `advance_state(ASK_MORE_ELEMENTS, ...)` returns `ASK_PLACEMENT_ZONE`, so state != `add_elements_mode`.

- [ ] **Step 3: Implement**

3a. Add the done-signal constant near the top of `orchestrator.py` (after the imports / `log =` line):

```python
# Phrases that end the element-gather loop ("that's everything").
_DONE_ELEMENTS = (
    "that's it", "thats it", "that's all", "thats all", "that's everything",
    "thats everything", "nothing else", "no more", "all set", "generate",
    "ready", "done",
)
```

3b. In `_apply_fields`, extend the confirmation-state block (the `if state is S.ASK_PIN_ANNOTATION: ...` chain, ~lines 353-364) with two branches:

```python
    elif state is S.ASK_MORE_ELEMENTS:
        decline = is_negative(message) or any(w in low for w in _DONE_ELEMENTS)
        collected["wants_more_elements"] = not decline
    elif state is S.ADD_ELEMENTS_MODE:
        decline = is_negative(message) or any(w in low for w in _DONE_ELEMENTS)
        collected["add_another_element"] = not decline
```

3c. In `handle_message`, add the one-shot flag alongside the existing `pin_offered` one-shot (~lines 130-135):

```python
        if new_state is ConversationState.ASK_PURPOSE:
            collected["purpose_asked"] = True
        elif new_state is ConversationState.YOUTH_REFERRAL:
            collected["youth_referred"] = True
        elif new_state is ConversationState.ASK_MORE_ELEMENTS:
            collected["elements_offered"] = True
        elif new_state is ConversationState.ASK_PIN_ANNOTATION:
            collected["pin_offered"] = True
```

3d. In `_public_data`, add the two states (near the `ASK_PIN_ANNOTATION` entry):

```python
    if state is S.ASK_MORE_ELEMENTS:
        return {"options": ["Add text", "Add a graphic", "That's everything"]}
    if state is S.ADD_ELEMENTS_MODE:
        return {"options": ["That's everything"]}
```

- [ ] **Step 4: Run the new tests**

Run: `pytest tests/test_conversation_smart.py -k "more_elements or add_mode or element_chips" -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): route the element-gather loop (booleans, one-shot flag, chips)"
```

---

## Task 6: Orchestrator — accumulate the structured brief across turns

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (remove `design_description` from the copy loop; add async `_maybe_gather_element`; call it in `handle_message`)
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `brief.merge_brief` (Task 1), `ie.extract_design_description` (existing; LLM → structured dict, no-key → `{"summary": message}`), the gather booleans (Task 5).
- Produces: `collected["design_description"]` is always a merged dict; elements from the describe turn, the gather loop, out-of-order volunteering, and refinement change requests all accumulate.

**Context:** `extract_design_description` (rich: summary/text_elements/colours/imagery/style) exists but is currently unused — the interpreter only stores `design_description` as a short string. Route every element-producing turn through it + `merge_brief`, and stop the generic copy loop from overwriting the dict with the interpreter's string.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_conversation_smart.py
def _capture_extractor(mapping):
    """Fake extract_design_description returning a structured dict per message."""
    async def _f(message):
        return mapping.get(message, {"summary": message})
    return _f


@pytest.mark.asyncio
async def test_describe_then_add_accumulates_brief(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ADD_ELEMENTS_MODE.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True,
                                       "design_description": {"summary": "a mountain crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("added"))
    monkeypatch.setattr(
        orch.ie, "extract_design_description",
        _capture_extractor({"add SUMMIT CO in gold": {"text_elements": ["SUMMIT CO"], "colours": ["gold"]}}),
    )
    await orch.handle_message("s1", "add SUMMIT CO in gold")
    brief = store["session"]["collected"]["design_description"]
    assert brief["summary"] == "a mountain crest"       # preserved
    assert "SUMMIT CO" in brief["text_elements"]          # accumulated
    assert "gold" in brief["colours"]


@pytest.mark.asyncio
async def test_decline_does_not_extract(monkeypatch):
    calls = []
    async def _spy(message):
        calls.append(message)
        return {"summary": message}
    store = {"session": {"id": "s1", "state": S.ASK_MORE_ELEMENTS.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True,
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    monkeypatch.setattr(orch.ie, "extract_design_description", _spy)
    await orch.handle_message("s1", "That's everything")
    assert calls == []  # a decline carries no element to extract


@pytest.mark.asyncio
async def test_refinement_add_updates_brief(monkeypatch):
    store = {"session": {"id": "s1", "state": S.DESCRIBE_CHANGES.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements_offered": True, "placement_zone": "front_panel",
                                       "design_description": {"summary": "a crest"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("updating"))
    monkeypatch.setattr(
        orch.ie, "extract_design_description",
        _capture_extractor({"add our team name in gold": {"text_elements": ["team name"], "colours": ["gold"]}}),
    )
    await orch.handle_message("s1", "add our team name in gold")
    collected = store["session"]["collected"]
    assert "team name" in collected["design_description"]["text_elements"]
    assert collected["last_change"] == "add our team name in gold"  # raw change still set
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_conversation_smart.py::test_describe_then_add_accumulates_brief -v`
Expected: FAIL — nothing calls `extract_design_description`, so `text_elements` is absent.

- [ ] **Step 3: Implement**

3a. Add the import and helper constant near the top of `orchestrator.py`:

```python
from app.services.conversation import brief
```

Add below `_DONE_ELEMENTS`:

```python
# States where a (non-declining) message contributes a design element.
_ELEMENT_STATES = frozenset(
    {
        ConversationState.DESCRIBE_DESIGN,
        ConversationState.ASK_MORE_ELEMENTS,
        ConversationState.ADD_ELEMENTS_MODE,
        ConversationState.DESCRIBE_CHANGES,
    }
)
# Bare acknowledgements that carry no element to extract on their own.
_BARE_YES = frozenset(
    {"yes", "yeah", "yep", "sure", "ok", "okay", "add text", "add a graphic", "add graphic"}
)
```

3b. Remove `"design_description"` from the generic copy loop in `_apply_fields` (the tuple at ~line 316-319). The dict is now owned exclusively by `_maybe_gather_element`:

```python
    for key in (
        "name", "purpose", "quantity", "decoration_type",
        "placement_zone", "placement_position", "remove_bg", "has_logo", "youth_flag",
    ):
        if key in fields and fields[key] is not None:
            collected[key] = fields[key]
```

3c. Add the async gather helper (module-level, e.g. after `_apply_fields`):

```python
async def _maybe_gather_element(
    state: ConversationState, fields: dict, collected: dict, message: str
) -> None:
    """Extract a design element from this turn (when there is one) and merge it
    into the canonical structured brief. Runs on the describe turn, the gather
    loop, refinement, and any out-of-order turn where the customer volunteered
    design info. Declines and bare acknowledgements contribute nothing."""
    volunteered = bool(fields.get("design_description"))
    if state not in _ELEMENT_STATES and not volunteered:
        return
    if state is ConversationState.ASK_MORE_ELEMENTS and (
        not collected.get("wants_more_elements") or message.strip().lower() in _BARE_YES
    ):
        return
    if state is ConversationState.ADD_ELEMENTS_MODE and not collected.get("add_another_element"):
        return

    incoming = await ie.extract_design_description(message)
    if incoming:
        collected["design_description"] = brief.merge_brief(
            collected.get("design_description") or {}, incoming
        )
```

3d. Call it in `handle_message`, immediately after `_apply_fields(...)` (~line 77):

```python
        _apply_fields(current, interp.get("fields") or {}, collected, message)
        await _maybe_gather_element(current, interp.get("fields") or {}, collected, message)
```

- [ ] **Step 4: Run the new tests + the describe-flow regressions**

Run: `pytest tests/test_conversation_smart.py -q`
Expected: PASS — the 3 new tests plus existing describe/has-logo tests. If any pre-existing test asserted `design_description` equals the interpreter's raw string, update it to expect the merged dict (that is the intended change).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): accumulate a structured design brief across turns and refinement"
```

---

## Task 7: Goal-leading copy for the gather states

**Files:**
- Modify: `backend/app/prompts.py` (`STATE_PROMPTS`, `CANNED_REPLIES`)
- Test: `backend/tests/test_prompts.py` (create if absent — a light assertion that both new states have copy)

**Interfaces:**
- Consumes: state slugs `"ask_more_elements"`, `"add_elements_mode"`.
- Produces: `STATE_PROMPTS` and `CANNED_REPLIES` entries for both; the canned reply for `add_elements_mode` acknowledges the element and steers toward finishing.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_prompts.py  (add to it, or create)
from app import prompts


def test_gather_states_have_copy():
    for slug in ("ask_more_elements", "add_elements_mode"):
        assert slug in prompts.CANNED_REPLIES
        assert slug in prompts.STATE_PROMPTS
    # Goal-leading: the offer names concrete element types and an exit.
    assert "text" in prompts.CANNED_REPLIES["ask_more_elements"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_prompts.py::test_gather_states_have_copy -v`
Expected: FAIL with `KeyError`/assert (slugs absent).

- [ ] **Step 3: Implement**

3a. Add to `CANNED_REPLIES` (near the `describe_design` entry):

```python
    "ask_more_elements": (
        "Anything else you'd like on the cap — some text, a slogan, extra "
        "graphics, or particular colours? Or say 'that's everything' and I'll "
        "get it generated."
    ),
    "add_elements_mode": (
        "Got it — I've added that. Anything else you'd like on there, or shall "
        "I place the design and generate it?"
    ),
```

3b. Add to `STATE_PROMPTS` (near the `describe_design` entry). These instruct the LLM to acknowledge the specific element and steer toward the goal:

```python
    "ask_more_elements": (
        "The customer has given their main design. Warmly ask if they want to "
        "add anything else — text, a slogan, extra graphics, or specific "
        "colours — making clear they can also say they're done and you'll "
        "generate it. Keep it to one or two sentences."
    ),
    "add_elements_mode": (
        "Acknowledge the element the customer just added (see the brief in "
        "context), then ask if they'd like to add anything else or are ready "
        "for you to place the design and generate it. One or two sentences."
    ),
```

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/tests/test_prompts.py
git commit -m "feat(convo): goal-leading copy for the element-gather states"
```

---

## Task 8: Post-verification acknowledgment + full-suite verification

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (`check_verification` — add the acknowledgment aside)
- Test: `backend/tests/test_conversation_smart.py`
- Docs: `CLAUDE.md` (§13 current-state note + test counts), `.superpowers/sdd/progress.md`

**Interfaces:**
- Consumes: the collapse from Task 3 (`check_verification`'s existing `while new_state in AUTO_ADVANCE_STATES` walk now lands on `OFFER_REFINE`).
- Produces: `check_verification` words that landing with an acknowledgment `aside` so the single message confirms verification + delivery AND asks the tweak question.

**Context:** After Task 3, `check_verification` already lands on `OFFER_REFINE` (no redundant taps). This task adds the one-line acknowledgment so the collapsed message still tells the customer their email is verified and the design is in their inbox, then verifies the whole feature end-to-end.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_conversation_smart.py
@pytest.mark.asyncio
async def test_verification_lands_on_offer_refine_with_ack(monkeypatch):
    store = {"session": {"id": "s1", "state": S.VERIFY_EMAIL.value,
                         "collected": {"name": "Al", "email_verified": True},
                         "upsell_count": 0, "store_id": None}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())

    captured = {}
    async def _reply(state, collected, persona, aside=None):
        captured["state"] = state
        captured["aside"] = aside
        return "worded"
    monkeypatch.setattr(orch.ie, "generate_reply", _reply)

    res = await orch.check_verification("s1")
    assert res["state"] == S.OFFER_REFINE.value       # collapsed, no redundant taps
    assert captured["state"] == S.OFFER_REFINE.value
    assert captured["aside"] and "verified" in captured["aside"].lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_conversation_smart.py::test_verification_lands_on_offer_refine_with_ack -v`
Expected: FAIL — `check_verification` currently calls `generate_reply(new_state, collected, persona)` with no `aside`, so `captured["aside"]` is `None`.

- [ ] **Step 3: Implement**

In `check_verification`, replace the reply line (currently `reply = await ie.generate_reply(new_state, collected, persona)` after the `while` collapse walk) with an acknowledgment aside:

```python
    new_state = advance_state(current, collected)
    while new_state in AUTO_ADVANCE_STATES:
        new_state = advance_state(new_state, collected)

    ack = "Your email's verified — your design's in your inbox and on-screen now."
    reply = await ie.generate_reply(new_state.value, collected, persona, aside=ack)
```

(Note: `generate_reply` takes the state *value* string — match the existing call sites.)

- [ ] **Step 4: Run the test**

Run: `pytest tests/test_conversation_smart.py::test_verification_lands_on_offer_refine_with_ack -v`
Expected: PASS.

- [ ] **Step 5: Full backend suite**

Run: `pytest -q`
Expected: PASS (all prior counts + the new tests from Tasks 1-8). Fix any residual assertion that expected the old post-verification resting states.

- [ ] **Step 6: Frontend smoke (no code change expected)**

Run: `cd frontend && npx vitest run`
Expected: the 2 pre-existing `adminQuotes` failures only (unrelated). If a chat test asserted the post-verification state was `email_verified`/`show_design`, update it to `offer_refine` and note it.

- [ ] **Step 7: Update docs**

In `CLAUDE.md` §13, update the "Smarter Studio conversation" note to mention the multi-element gather loop, and refresh the test counts. Append a completion entry to `.superpowers/sdd/progress.md`.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py CLAUDE.md .superpowers/sdd/progress.md
git commit -m "feat(convo): acknowledge verification on the collapsed post-verification turn"
```

---

## Self-Review

**Spec coverage:**
- §3.1 canonical brief + `merge_brief` → Task 1. ✅
- §3.2 gather-loop states (offer + loop, chips, booleans) → Tasks 3 (states/routing) + 5 (booleans/flag/chips). ✅
- §3.3 goal planner gather goal + GATE_STATES → Task 4. ✅
- §3.4 prompt-builder uploaded-asset enumeration → Task 2. ✅
- §3.5 post-verification collapse → Task 3 (AUTO_ADVANCE) + Task 8 (acknowledgment). ✅
- §3.6 refinement adds elements → Task 6 (`DESCRIBE_CHANGES` in `_ELEMENT_STATES`, `last_change` preserved). ✅
- §3.7 goal-leading replies → Task 7 + Task 8 aside. ✅
- §5 testing → every task is TDD; Task 8 runs the full suite + frontend. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; test bodies are concrete. ✅

**Type consistency:** `merge_brief(existing, incoming)` used identically in Tasks 1/6; `wants_more_elements` / `add_another_element` set in Task 5 and read in Task 3's `advance_state`; `elements_offered` set in Task 5 and read in Task 4; `_ELEMENT_STATES` / `_DONE_ELEMENTS` / `_BARE_YES` defined in Tasks 5-6 and used consistently; `extract_design_description(message)` matches the existing signature in `intent_extractor.py`. ✅

**Note carried for the implementer:** `extract_design_description` was dead code before this plan — Task 6 is what makes the structured brief (and therefore the prompt-builder enumeration from Task 2) actually populate. Do not skip Task 6.
