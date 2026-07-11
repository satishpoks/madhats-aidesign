# Conversational Per-Element Deep-Dive (InkyBay-parity) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each thing a customer adds a first-class typed **element** the bot interrogates one attribute at a time (font/size/colour/style/placement, all deferrable) before moving on — attributes bound per element, placement per element — and generate the preview from that structured element list.

**Architecture:** Backend-first rework of the conversation gather loop. A structured `collected["elements"]` list replaces the flat `design_description` brief. A new pure `element_planner` decides the next attribute to ask per element; a new `ELEMENT_DEEPDIVE` state loops on that; `ASK_MORE_ELEMENTS` becomes the type chooser. The prompt builder enumerates one block per element at its own placement. Supersedes the flat-brief gather loop + global placement from the wider-brief work (same unmerged branch).

**Tech Stack:** Python 3.12, FastAPI, pytest/pytest-asyncio. No new deps. Frontend: chip-only additions (no new components).

## Global Constraints

- Python target **3.12**; no new dependencies.
- No PII (name/email/phone) in logs or LLM contexts — reuse `_safe_collected`; never log raw messages.
- Engine must keep working with **no `ANTHROPIC_API_KEY`** (deterministic heuristics + canned per-attribute questions); degraded structure is acceptable, nothing may crash.
- The LLM never decides routing — routing stays in `state_machine` / `goal_planner` / `element_planner`.
- Composite onto the real product reference photo — never regenerate the cap. The `IMAGE_GEN_PROMPT` cap-fidelity lock, no-collage rules, and the uploaded-logo SECOND-image directive must stay intact and asserted.
- **Only `content` is required** per element; every other attribute is deferrable ("you choose"/"whatever looks good"/"the team decides") → recorded in the element's `deferred` list and skipped.
- TDD: failing test first, watch it fail, minimal implementation, watch it pass, commit.
- Backend tests: `pytest -q` from `backend/` with the project venv.

### Shared data shapes (used across tasks — copy verbatim)

Element dict:
```
{ "type": "text"|"graphic"|"logo"|"note", "content": str,
  "font": str|None, "size": str|None, "colour": str|None, "style": str|None,
  "placement_zone": str|None, "placement_position": str|None,
  "remove_bg": bool|None, "asset_path": str|None, "deferred": [str] }
```
- `collected["elements"]`: list of completed element dicts.
- `collected["pending_element"]`: the element being built (or absent/None).

Attribute order per type (authoritative — `element_planner.ATTRIBUTE_ORDER`):
```
text:    ["content","font","size","colour","style","placement_zone","placement_position"]
graphic: ["content","style","size","colour","placement_zone","placement_position"]
logo:    ["remove_bg","size","placement_zone","placement_position"]
note:    ["content"]
```

---

## Task 1: `element_planner` — next-attribute + completion (pure)

**Files:**
- Create: `backend/app/services/conversation/element_planner.py`
- Test: `backend/tests/test_element_planner.py`

**Interfaces:**
- Produces: `ATTRIBUTE_ORDER: dict[str, list[str]]`; `next_attribute(element: dict) -> str | None` (first attribute in the type's order that is unset — `None`/`""` — and not in `element["deferred"]`; `None` = complete); `is_complete(element) -> bool`; `defer_remaining(element) -> None` (adds every unset, non-`content` attribute to `deferred`, in place).

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_element_planner.py
"""element_planner — per-element attribute sequencing (pure functions)."""
from __future__ import annotations

from app.services.conversation import element_planner as ep


def test_text_asks_content_first_then_font():
    assert ep.next_attribute({"type": "text", "deferred": []}) == "content"
    assert ep.next_attribute({"type": "text", "content": "TEAM", "deferred": []}) == "font"


def test_deferred_attribute_is_skipped():
    el = {"type": "text", "content": "TEAM", "deferred": ["font"]}
    assert ep.next_attribute(el) == "size"


def test_set_attribute_is_skipped_bool_false_counts_as_set():
    el = {"type": "logo", "remove_bg": False, "deferred": []}
    assert ep.next_attribute(el) == "size"  # remove_bg=False is a real answer


def test_complete_when_all_set_or_deferred():
    el = {"type": "note", "content": "leave room on the back", "deferred": []}
    assert ep.next_attribute(el) is None
    assert ep.is_complete(el) is True


def test_defer_remaining_defers_non_content_only():
    el = {"type": "text", "content": "TEAM", "deferred": []}
    ep.defer_remaining(el)
    assert "content" not in el["deferred"]
    assert set(el["deferred"]) == {"font", "size", "colour", "style",
                                   "placement_zone", "placement_position"}
    assert ep.is_complete(el) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_element_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.conversation.element_planner`

- [ ] **Step 3: Implement**

```python
# backend/app/services/conversation/element_planner.py
"""Per-element attribute sequencing for the deep-dive.

Pure functions of one element dict. The deterministic state machine asks for
`next_attribute`; the customer may defer any non-content attribute.
"""
from __future__ import annotations

ATTRIBUTE_ORDER: dict[str, list[str]] = {
    "text": ["content", "font", "size", "colour", "style",
             "placement_zone", "placement_position"],
    "graphic": ["content", "style", "size", "colour",
                "placement_zone", "placement_position"],
    "logo": ["remove_bg", "size", "placement_zone", "placement_position"],
    "note": ["content"],
}

# The only attribute that can never be deferred.
_REQUIRED = "content"


def _unset(element: dict, attr: str) -> bool:
    val = element.get(attr)
    return val is None or val == ""


def next_attribute(element: dict) -> str | None:
    order = ATTRIBUTE_ORDER.get(element.get("type"), [])
    deferred = set(element.get("deferred") or [])
    for attr in order:
        if attr in deferred:
            continue
        if _unset(element, attr):
            return attr
    return None


def is_complete(element: dict) -> bool:
    return next_attribute(element) is None


def defer_remaining(element: dict) -> None:
    """Mark every still-unset, non-content attribute as designer's-choice."""
    deferred = element.setdefault("deferred", [])
    for attr in ATTRIBUTE_ORDER.get(element.get("type"), []):
        if attr == _REQUIRED:
            continue
        if _unset(element, attr) and attr not in deferred:
            deferred.append(attr)
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_element_planner.py -v` → PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/element_planner.py backend/tests/test_element_planner.py
git commit -m "feat(convo): element_planner sequences per-element attributes"
```

---

## Task 2: State machine — `ELEMENT_DEEPDIVE`, retire global placement

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py`
- Test: `backend/tests/test_state_machine.py`

**Interfaces:**
- Produces: new `ConversationState.ELEMENT_DEEPDIVE = "element_deepdive"`. `advance_state` routing:
  - `ASK_MORE_ELEMENTS` → `ELEMENT_DEEPDIVE` if `collected.get("pending_element")`, else `ASK_PIN_ANNOTATION` if not `pin_offered`, else `GENERATING`.
  - `ELEMENT_DEEPDIVE` → `ELEMENT_DEEPDIVE` if `collected.get("pending_element")` (still building), else `ASK_MORE_ELEMENTS`.
  - `UPLOAD_LOGO` → `ELEMENT_DEEPDIVE`; `DESCRIBE_DESIGN` → `ELEMENT_DEEPDIVE`.
- Consumes: `collected["pending_element"]` (set by the orchestrator, Task 5), `pin_offered`.

**Context:** The old `ADD_ELEMENTS_MODE` and the global `ASK_REMOVE_BG`/`ASK_PLACEMENT_ZONE`/`ASK_PLACEMENT_POSITION` forward transitions are superseded. Keep those enum members (backtrack targets / legacy tests may reference them) but they are no longer on the forward path. `AUTO_ADVANCE_STATES` (the post-verification collapse) is unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_state_machine.py
def test_deepdive_entered_when_pending_element():
    assert advance_state(S.ASK_MORE_ELEMENTS, {"pending_element": {"type": "text"}}) is S.ELEMENT_DEEPDIVE


def test_deepdive_loops_until_element_complete():
    assert advance_state(S.ELEMENT_DEEPDIVE, {"pending_element": {"type": "text"}}) is S.ELEMENT_DEEPDIVE
    # pending cleared (element completed by orchestrator) -> back to the offer
    assert advance_state(S.ELEMENT_DEEPDIVE, {}) is S.ASK_MORE_ELEMENTS


def test_more_elements_exit_offers_pins_then_generates():
    # no pending element, pins not yet offered -> pin offer
    assert advance_state(S.ASK_MORE_ELEMENTS, {}) is S.ASK_PIN_ANNOTATION
    assert advance_state(S.ASK_MORE_ELEMENTS, {"pin_offered": True}) is S.GENERATING


def test_design_sources_funnel_into_deepdive():
    assert advance_state(S.UPLOAD_LOGO, {}) is S.ELEMENT_DEEPDIVE
    assert advance_state(S.DESCRIBE_DESIGN, {}) is S.ELEMENT_DEEPDIVE


def test_progress_steady_during_deepdive_and_placement_retired():
    # Global placement is off the path; the deep-dive holds the counter at the
    # design-source step for both branches.
    describe = {"has_logo": False}
    assert progress(S.ELEMENT_DEEPDIVE, describe) == progress(S.DESCRIBE_DESIGN, describe)
    assert progress(S.ASK_MORE_ELEMENTS, describe) == progress(S.DESCRIBE_DESIGN, describe)
    logo = {"has_logo": True}
    assert progress(S.ELEMENT_DEEPDIVE, logo) == progress(S.ASK_REMOVE_BG, logo)
    # describe branch total drops by one now that ASK_PLACEMENT_ZONE is gone: 7
    assert progress(S.ASK_NAME, describe)["total"] == 7
```

(`progress` is already imported at the top of `test_state_machine.py`.)

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_state_machine.py::test_deepdive_entered_when_pending_element -v` → FAIL (`AttributeError: ELEMENT_DEEPDIVE`).

- [ ] **Step 3: Implement**

3a. Add the enum member after `ADD_ELEMENTS_MODE`:
```python
    ADD_ELEMENTS_MODE = "add_elements_mode"
    ELEMENT_DEEPDIVE = "element_deepdive"
```

3b. In `TRANSITIONS`, repoint the design-source successors and add the deep-dive:
```python
    S.UPLOAD_LOGO: [S.ELEMENT_DEEPDIVE],
    S.ASK_REMOVE_BG: [S.ELEMENT_DEEPDIVE],
    S.DESCRIBE_DESIGN: [S.ELEMENT_DEEPDIVE],
    S.ASK_MORE_ELEMENTS: [S.ELEMENT_DEEPDIVE, S.ASK_PIN_ANNOTATION, S.GENERATING],
    S.ELEMENT_DEEPDIVE: [S.ELEMENT_DEEPDIVE, S.ASK_MORE_ELEMENTS],
```

3c. In `advance_state`, REPLACE the old `ASK_MORE_ELEMENTS`/`ADD_ELEMENTS_MODE` branches with:
```python
    # --- Per-element deep-dive ---
    if current is S.ASK_MORE_ELEMENTS:
        if collected.get("pending_element"):
            return S.ELEMENT_DEEPDIVE
        if not collected.get("pin_offered"):
            return S.ASK_PIN_ANNOTATION
        return S.GENERATING

    if current is S.ELEMENT_DEEPDIVE:
        return S.ELEMENT_DEEPDIVE if collected.get("pending_element") else S.ASK_MORE_ELEMENTS
```
(Delete the two old `wants_more_elements`/`add_another_element` branches for these states. Leave `ADD_ELEMENTS_MODE` with no forward branch — it falls through to the default successor; it is off the forward path.)

3d. Add `S.UPLOAD_LOGO` and `S.DESCRIBE_DESIGN` forward branches so the design sources reach the deep-dive. Since `advance_state` uses the default-successor for states with no special branch, and 3b set their `TRANSITIONS[0]` to `ELEMENT_DEEPDIVE`, no extra code is needed — the default branch returns `nexts[0]`. (Verify `ASK_REMOVE_BG` similarly.)

3e. In `ALLOWED_BACKTRACKS`, add:
```python
    S.ELEMENT_DEEPDIVE: [S.ASK_MORE_ELEMENTS],
    S.ASK_MORE_ELEMENTS: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.UPLOAD_LOGO],
```

3f. Fix the `progress()` counter (global placement is retired; the deep-dive must not reset it to "Step 1"):
- In `_progress_path`, **remove** `S.ASK_PLACEMENT_ZONE` from the tail so the path ends `[..., <design-source step>, S.ASK_EMAIL]` (describe branch total becomes 7, logo branch 8).
- In `progress()`, extend the existing `ASK_PLACEMENT_POSITION` normalization branch so `S.ASK_MORE_ELEMENTS`, `S.ELEMENT_DEEPDIVE` (and the now-legacy `S.ASK_PLACEMENT_ZONE`/`S.ASK_PLACEMENT_POSITION`) normalize to the branch's design-source step present in `_progress_path` — i.e. `S.ASK_REMOVE_BG if collected.get("has_logo") else S.DESCRIBE_DESIGN`. This keeps "Step X of N" steady while the customer builds elements. The new test `test_progress_steady_during_deepdive_and_placement_retired` pins this.

- [ ] **Step 4: Run tests** — `pytest tests/test_state_machine.py -v`, then `pytest -q`. Some pre-existing tests referencing the old `ASK_MORE_ELEMENTS`→`ASK_PLACEMENT_ZONE` / `ADD_ELEMENTS_MODE` forward transitions will fail; update them to the new routing (deep-dive / pin exit). Update `test_design_source_paths_reach_more_elements` (from the prior feature) to expect `ELEMENT_DEEPDIVE`. Note every updated test in the report.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(convo): ELEMENT_DEEPDIVE state; retire global placement from forward flow"
```

---

## Task 3: Goal planner — element-model design source, drop global placement

**Files:**
- Modify: `backend/app/services/conversation/goal_planner.py`
- Test: `backend/tests/test_goal_planner.py`

**Interfaces:**
- Consumes: `collected["elements"]`, `collected["pending_element"]`, `elements_offered`, `pin_offered`.
- Produces: `next_goal` returns the design-source state until at least one element exists or is pending; offers `ASK_MORE_ELEMENTS` once; then pins; then `GENERATING`. The global placement goal is removed. `GATE_STATES` gains `ELEMENT_DEEPDIVE`.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_goal_planner.py
def test_no_elements_yet_asks_design_source():
    c = {"name":"Al","purpose":"p","purpose_asked":True,"quantity":24,
         "decoration_type":"embroidery","has_logo":False}
    assert goal_planner.next_goal(c) is S.DESCRIBE_DESIGN


def test_with_an_element_offers_more_then_pins_then_generating():
    base = {"name":"Al","purpose":"p","purpose_asked":True,"quantity":24,
            "decoration_type":"embroidery","has_logo":False,
            "elements":[{"type":"text","content":"TEAM"}]}
    assert goal_planner.next_goal(base) is S.ASK_MORE_ELEMENTS
    assert goal_planner.next_goal({**base,"elements_offered":True}) is S.ASK_PIN_ANNOTATION
    assert goal_planner.next_goal({**base,"elements_offered":True,"pin_offered":True}) is S.GENERATING


def test_deepdive_is_a_gate():
    assert S.ELEMENT_DEEPDIVE in goal_planner.GATE_STATES
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_goal_planner.py::test_with_an_element_offers_more_then_pins_then_generating -v` → FAIL (still returns global-placement path / wrong order).

- [ ] **Step 3: Implement**

3a. Add `S.ELEMENT_DEEPDIVE` to `GATE_STATES` (after `S.ADD_ELEMENTS_MODE`).

3b. Replace the design-source block (current lines 75-93) with the element-model version:
```python
    # 5. design source (required): at least one element must exist or be pending
    if "has_logo" not in collected:
        return S.ASK_HAS_LOGO
    if not collected.get("elements") and not collected.get("pending_element"):
        if collected.get("has_logo"):
            if not collected.get("uploaded_asset_path"):
                return S.UPLOAD_LOGO
        else:
            return S.DESCRIBE_DESIGN

    # 5b. additional elements (optional, offered exactly once)
    if not collected.get("elements_offered"):
        return S.ASK_MORE_ELEMENTS

    # 6. pin annotation (optional, offered exactly once) — placement is per-element
    if not collected.get("pin_offered"):
        return S.ASK_PIN_ANNOTATION

    # 7. email is captured inline at GENERATING
    return S.GENERATING
```
(Delete the old `remove_bg` goal and the `ASK_PLACEMENT_ZONE` goal — both are handled inside the deep-dive now.)

- [ ] **Step 4: Run** — `pytest tests/test_goal_planner.py -v`, then `pytest -q`; update any pre-existing goal-planner test that assumed the flat `design_description`/global-placement ordering (note them).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/goal_planner.py backend/tests/test_goal_planner.py
git commit -m "feat(convo): goal planner uses the element model; drops global placement"
```

---

## Task 4: Intent extractor — attribute extraction + dynamic reply

**Files:**
- Modify: `backend/app/services/conversation/intent_extractor.py`, `backend/app/prompts.py`
- Test: `backend/tests/test_conversation_smart.py` (extractor tests live alongside the others)

**Interfaces:**
- Produces:
  - `async extract_element_attributes(el_type: str, message: str) -> dict` — returns a dict of any recognised attributes among `content,font,size,colour,style,placement_zone,placement_position,remove_bg` plus `defer: bool`. No key → deterministic heuristics; key → Haiku via `prompts.ELEMENT_ATTRIBUTE_PROMPT`.
  - `generate_reply(..., ask_for: str | None = None)` — when `ask_for` is set, the reply asks for that attribute (LLM instruction, or `prompts.ATTRIBUTE_QUESTIONS[ask_for]` canned), acknowledging context.
  - `prompts.ATTRIBUTE_QUESTIONS: dict[str,str]`, `prompts.DEFER_WORDS`, `prompts.ELEMENT_ATTRIBUTE_PROMPT`.

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_conversation_smart.py
import pytest
from app.services.conversation import intent_extractor as ie2


@pytest.mark.asyncio
async def test_extract_attributes_no_key_detects_defer_and_zone(monkeypatch):
    monkeypatch.setattr(ie2, "_has_llm", False)
    out = await ie2.extract_element_attributes("text", "you choose the font")
    assert out.get("defer") is True
    out2 = await ie2.extract_element_attributes("graphic", "put it on the left side")
    assert out2.get("placement_zone") == "side"


@pytest.mark.asyncio
async def test_generate_reply_ask_for_no_key_uses_attribute_question(monkeypatch):
    monkeypatch.setattr(ie2, "_has_llm", False)
    reply = await ie2.generate_reply("element_deepdive", {"pending_element": {"type": "text"}},
                                     "Ricardo", ask_for="font")
    assert "font" in reply.lower()
```

- [ ] **Step 2: Run to verify failure** — FAIL (`AttributeError: extract_element_attributes` / `ask_for`).

- [ ] **Step 3: Implement**

3a. In `prompts.py` add:
```python
DEFER_WORDS = ("you choose", "your choice", "whatever", "you decide", "team decide",
               "surprise me", "no preference", "don't mind", "dont mind", "any", "up to you")

ATTRIBUTE_QUESTIONS = {
    "content": "What would you like it to say?",
    "font": "What font feel would you like — bold, classic, handwritten? (or say 'you choose')",
    "size": "Roughly how big — small, medium or large? (or 'you choose')",
    "colour": "What colour should it be? (or 'you choose')",
    "style": "Any special styling — an outline, a shadow, or curved text? (or 'none')",
    "placement_zone": "Where on the cap should this go — front, side, back, or under the brim?",
    "placement_position": "Whereabouts there — left, centre or right?",
    "remove_bg": "Should I clean up / remove the background of your artwork? (yes/no)",
}

ELEMENT_ATTRIBUTE_PROMPT = """The customer is describing ONE decoration element of type "{el_type}" for a cap.
Message: "{message}"
Extract ONLY attributes they actually gave. Respond with ONLY a JSON object with any of:
{{"content": "...", "font": "...", "size": "small|medium|large", "colour": "...",
  "style": "...", "placement_zone": "front_panel|side|back|under_brim",
  "placement_position": "left|centre|right", "remove_bg": true, "defer": true}}
Set "defer": true if they said to leave it to you (e.g. "you choose"). Omit anything not mentioned."""
```

3b. In `intent_extractor.py` add the heuristic + public function (place near `extract_design_description`):
```python
_SIZE_WORDS = {"small": "small", "tiny": "small", "little": "small",
               "medium": "medium", "mid": "medium",
               "large": "large", "big": "large", "huge": "large"}


def _extract_attrs_heuristic(el_type: str, message: str) -> dict:
    low = message.lower()
    out: dict = {}
    if any(w in low for w in prompts.DEFER_WORDS):
        out["defer"] = True
        return out
    zone = _zone_from_text(message)
    if zone:
        out["placement_zone"] = zone
    for w, val in _SIZE_WORDS.items():
        if w in low:
            out["size"] = val
            break
    if "left" in low:
        out["placement_position"] = "left"
    elif "right" in low:
        out["placement_position"] = "right"
    elif "centre" in low or "center" in low or "middle" in low:
        out["placement_position"] = "centre"
    return out


async def extract_element_attributes(el_type: str, message: str) -> dict:
    if not _has_llm:
        return _extract_attrs_heuristic(el_type, message)
    prompt = prompts.ELEMENT_ATTRIBUTE_PROMPT.format(el_type=el_type, message=message)
    data = _parse_json(await _complete(prompt, max_tokens=200))
    return data if isinstance(data, dict) else {}
```

3c. Extend `generate_reply` signature with `ask_for: str | None = None`. No-key path:
```python
    if not _has_llm:
        if ask_for:
            base = prompts.ATTRIBUTE_QUESTIONS.get(ask_for, "Tell me a bit more.")
        else:
            base = _generate_reply_canned(state, collected, persona_name)
        return f"{aside} {base}" if aside else base
```
Key path: when `ask_for` is set, build the instruction from `ATTRIBUTE_QUESTIONS[ask_for]` wrapped in the "acknowledge then ask, allow 'you choose'" wording, and skip the `STATE_PROMPTS` lookup. Keep `_safe_collected` redaction.

- [ ] **Step 4: Run** — `pytest tests/test_conversation_smart.py -k "attributes or ask_for" -v` → PASS; `pytest -q` green.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/intent_extractor.py backend/app/prompts.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): per-attribute extraction + ask_for reply wording"
```

---

## Task 5: Orchestrator — element lifecycle + deep-dive routing

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `element_planner` (Task 1), `ie.extract_element_attributes` / `generate_reply(ask_for=)` (Task 4), the new states (Task 2).
- Produces: type choice at `ASK_MORE_ELEMENTS` sets `collected["pending_element"] = {"type": <t>, "deferred": []}`; `UPLOAD_LOGO` seeds `{"type":"logo","asset_path":...}`; `DESCRIBE_DESIGN` seeds an inferred text/graphic element with `content`. In `ELEMENT_DEEPDIVE`, extracted attributes merge into `pending_element`; a defer marks the current `ask_for` attribute deferred; a per-element done signal calls `element_planner.defer_remaining`; when `element_planner.is_complete`, the element is appended to `collected["elements"]` and `pending_element` cleared. The reply passes `ask_for = element_planner.next_attribute(pending_element)`.

**Context:** This is the behavioural core. Remove the old `_maybe_gather_element` flat-brief path and the `wants_more_elements`/`add_another_element` derivations for these states (Task 6 removes the now-dead `merge_brief` usage; here, stop populating the flat brief for the gather path). Element-type detection at `ASK_MORE_ELEMENTS`: chip/text → `text`|`graphic`|`note` via keywords ("text"/"words"/"slogan"→text; "graphic"/"logo"/"icon"/"image"/"picture"→graphic; "note"→note).

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_conversation_smart.py
@pytest.mark.asyncio
async def test_add_graphic_records_graphic_type_not_text(monkeypatch):
    store = {"session": {"id":"s1","state": S.ASK_MORE_ELEMENTS.value,
        "collected":{"name":"Al","purpose":"p","quantity":24,"decoration_type":"embroidery",
                     "has_logo":False,"elements":[{"type":"text","content":"TEAM"}],
                     "elements_offered":True}, "upsell_count":0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent":"answer","fields":{}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("describe the graphic"))
    res = await orch.handle_message("s1", "Add a graphic")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
    assert store["session"]["collected"]["pending_element"]["type"] == "graphic"


@pytest.mark.asyncio
async def test_deepdive_captures_then_completes_and_appends(monkeypatch):
    pend = {"type":"text","content":"TEAM","font":"bold","size":"large","colour":"gold",
            "style":"none","placement_zone":"front_panel","deferred":[]}
    store = {"session": {"id":"s1","state": S.ELEMENT_DEEPDIVE.value,
        "collected":{"name":"Al","quantity":24,"decoration_type":"embroidery","has_logo":False,
                     "elements":[],"elements_offered":True,"pending_element":pend},
        "upsell_count":0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent":"answer","fields":{}}))
    async def _attrs(t,m): return {"placement_position":"centre"}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("anything else?"))
    res = await orch.handle_message("s1", "centre")
    c = store["session"]["collected"]
    assert c["elements"][-1]["content"] == "TEAM"        # completed element pushed
    assert "pending_element" not in c or not c["pending_element"]
    assert res["state"] == S.ASK_MORE_ELEMENTS.value


@pytest.mark.asyncio
async def test_defer_marks_attribute_and_moves_on(monkeypatch):
    pend = {"type":"text","content":"TEAM","deferred":[]}
    store = {"session": {"id":"s1","state": S.ELEMENT_DEEPDIVE.value,
        "collected":{"name":"Al","quantity":24,"decoration_type":"embroidery","has_logo":False,
                     "elements":[],"elements_offered":True,"pending_element":pend,
                     "deepdive_ask_for":"font"}, "upsell_count":0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent":"answer","fields":{}}))
    async def _attrs(t,m): return {"defer": True}
    monkeypatch.setattr(orch.ie, "extract_element_attributes", _attrs)
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("size?"))
    await orch.handle_message("s1", "you choose")
    assert "font" in store["session"]["collected"]["pending_element"]["deferred"]
```

- [ ] **Step 2: Run to verify failure** — FAIL (no element lifecycle yet).

- [ ] **Step 3: Implement**

3a. Add imports + constants near the top:
```python
from app.services.conversation import element_planner as ep

_ELEMENT_TYPE_WORDS = (
    ("note", "note"),
    ("graphic", "graphic"), ("logo", "graphic"), ("icon", "graphic"),
    ("image", "graphic"), ("picture", "graphic"), ("pic", "graphic"),
    ("text", "text"), ("word", "text"), ("slogan", "text"), ("name", "text"),
    ("wording", "text"), ("say", "text"),
)


def _element_type_from(message: str) -> str | None:
    low = message.lower()
    for word, etype in _ELEMENT_TYPE_WORDS:
        if word in low:
            return etype
    return None
```

3b. In `handle_message`, after `_apply_fields` + before routing, add the element lifecycle (a new helper `_advance_elements` called for the two gather states):
```python
        _apply_fields(current, interp.get("fields") or {}, collected, message)
        await _advance_elements(current, collected, message)
```

3c. Add `_advance_elements`:
```python
async def _advance_elements(state, collected, message) -> None:
    """Own the pending_element lifecycle for the type chooser + deep-dive."""
    S = ConversationState
    low = message.strip().lower()

    if state is S.ASK_MORE_ELEMENTS and not collected.get("pending_element"):
        if is_negative(message) or bool(_DONE_ELEMENTS_RE.search(low)):
            return  # declined -> exit handled by advance_state (no pending)
        etype = _element_type_from(message)
        if etype:
            collected["pending_element"] = {"type": etype, "deferred": []}
        return

    if state is S.ELEMENT_DEEPDIVE and collected.get("pending_element"):
        el = collected["pending_element"]
        ask_for = collected.get("deepdive_ask_for")
        # per-element done signal -> defer everything remaining
        if bool(_DONE_ELEMENTS_RE.search(low)):
            ep.defer_remaining(el)
        else:
            attrs = await ie.extract_element_attributes(el.get("type"), message)
            if attrs.pop("defer", False) and ask_for and ask_for != "content":
                if ask_for not in el["deferred"]:
                    el["deferred"].append(ask_for)
            for k, v in attrs.items():
                if v not in (None, ""):
                    el[k] = v
            # a plain answer with no structured field fills the attribute we asked
            if ask_for and ask_for not in el and not attrs and ask_for in ("content", "font", "colour", "style"):
                el[ask_for] = message.strip()[:120]
        if ep.is_complete(el):
            collected.setdefault("elements", []).append(el)
            collected["pending_element"] = None
            collected.pop("deepdive_ask_for", None)
```

3d. Seed elements at the design source. In `handle_message` where the upload/describe are handled (or in `_advance_elements`), add:
```python
    if state is S.UPLOAD_LOGO and collected.get("uploaded_asset_path") and not collected.get("pending_element"):
        collected["pending_element"] = {"type": "logo",
            "asset_path": collected["uploaded_asset_path"], "content": "uploaded logo", "deferred": []}
    if state is S.DESCRIBE_DESIGN and not collected.get("pending_element"):
        etype = "text" if _looks_like_text(message) else "graphic"
        collected["pending_element"] = {"type": etype, "content": message.strip()[:200], "deferred": []}
```
with `_looks_like_text(message)` = the message is short and quoted/alnum wording (define: `len(message.split()) <= 5 and any(c.isalpha() for c in message)`). Place these seed calls in `_advance_elements` under the matching `state is` guards (before the deep-dive block does nothing because there is no pending yet — the seed then lets the NEXT turn deep-dive; on the SAME turn, after seeding, also run one extraction pass so a rich describe fills attributes: call `extract_element_attributes` and merge as in 3c).

3e. Set `deepdive_ask_for` when wording the reply. In `handle_message` where `reply = await ie.generate_reply(...)` is built, add for the deep-dive:
```python
        ask_for = None
        if new_state is ConversationState.ELEMENT_DEEPDIVE and collected.get("pending_element"):
            ask_for = ep.next_attribute(collected["pending_element"])
            collected["deepdive_ask_for"] = ask_for
        reply = await ie.generate_reply(new_state.value, collected, persona, aside=aside, ask_for=ask_for)
```

3f. Remove the old `ASK_MORE_ELEMENTS`/`ADD_ELEMENTS_MODE` branches from `_apply_fields` (the `wants_more_elements`/`add_another_element` derivations) — the lifecycle now owns these states. Keep the pin/upsell/refine branches.

- [ ] **Step 4: Run** — the three new tests, then `pytest -q`; update pre-existing gather-loop tests from the wider-brief feature that asserted `wants_more_elements`/`ADD_ELEMENTS_MODE` behaviour to the new lifecycle, noting each.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): per-element lifecycle + deep-dive routing in the orchestrator"
```

---

## Task 6: Orchestrator `_public_data` chips + retire flat-brief gather

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Produces: `_public_data(ASK_MORE_ELEMENTS)` → `{"options": ["Add text","Add a graphic","Add a note","That's everything"]}`; `_public_data(ELEMENT_DEEPDIVE, collected)` → attribute-appropriate chips based on `collected.get("deepdive_ask_for")`, always including a `"You choose"` chip (except for `content`); `placement_zone` → the four zones, `placement_position` → left/centre/right, `size` → Small/Medium/Large, `remove_bg` → Yes/No.
- Removes: the now-dead `_maybe_gather_element` flat-brief merge for the gather path and its `_ELEMENT_STATES`/`_BARE_YES`/`merge_brief` usage IF no longer referenced (keep `DESCRIBE_CHANGES` refinement merge only if still needed — see note).

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_conversation_smart.py
def test_more_elements_offers_all_types():
    opts = orch._public_data(S.ASK_MORE_ELEMENTS, {})["options"]
    assert opts == ["Add text", "Add a graphic", "Add a note", "That's everything"]


def test_deepdive_placement_chips_include_you_choose():
    data = orch._public_data(S.ELEMENT_DEEPDIVE, {"deepdive_ask_for": "placement_zone"})
    assert "Front panel" in data["options"]
    assert "You choose" in data["options"]


def test_deepdive_content_has_no_you_choose():
    data = orch._public_data(S.ELEMENT_DEEPDIVE, {"deepdive_ask_for": "content"})
    assert data.get("options", []) == []  # free text only; content is required
```

- [ ] **Step 2: Run to verify failure** — FAIL.

- [ ] **Step 3: Implement**

3a. In `_public_data`, replace the `ASK_MORE_ELEMENTS`/`ADD_ELEMENTS_MODE` entries with:
```python
    if state is S.ASK_MORE_ELEMENTS:
        return {"options": ["Add text", "Add a graphic", "Add a note", "That's everything"]}
    if state is S.ELEMENT_DEEPDIVE:
        ask = collected.get("deepdive_ask_for")
        chips = {
            "placement_zone": ["Front panel", "Side", "Back", "Under-brim"],
            "placement_position": ["Left", "Centre", "Right"],
            "size": ["Small", "Medium", "Large"],
            "remove_bg": ["Yes, remove it", "No, keep as-is"],
        }.get(ask, [])
        if ask and ask != "content":
            chips = chips + ["You choose"]
        return {"options": chips} if chips else {}
```

3b. Retire the flat-brief gather path: remove `_maybe_gather_element`'s handling of `ASK_MORE_ELEMENTS`/`ADD_ELEMENTS_MODE` (those states no longer produce a flat brief). Keep ONLY the `DESCRIBE_CHANGES` refinement merge if refinement still relies on `design_description`; otherwise, if Task 7's prompt builder no longer reads `design_description`, delete `_maybe_gather_element`, `merge_brief` import, `_ELEMENT_STATES`, `_BARE_YES`, and `brief.py` + `test_brief.py`. Decide based on Task 7. (If unsure, leave `brief.py` and only stop calling it for the gather states; note it for the final review.)

- [ ] **Step 4: Run** — new tests + `pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): deep-dive attribute chips; retire flat-brief gather path"
```

---

## Task 7: Prompt builder — per-element enumeration + per-element placement

**Files:**
- Modify: `backend/app/services/prompt_builder.py`, `backend/app/prompts.py` (`IMAGE_GEN_PROMPT`)
- Test: `backend/tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: `collected["elements"]` (list of element dicts). Falls back to the legacy `design_description` shape only if `elements` is absent (back-compat for any un-migrated caller).
- Produces: `_design_block` enumerates one line-group per element with its attributes AND its placement; `note` elements become a "Customer note to the team" line; the `logo` element keeps the SECOND-image directive; `IMAGE_GEN_PROMPT` no longer has a single global `PLACEMENT:` section — placement is per element inside `{design_block}`.

**Context:** Highest-risk change. The cap-fidelity lock, no-collage rules, and SECOND-image directive MUST stay. Existing `test_prompt_builder.py` tests use the flat `design_description` + global placement — they must be rewritten for the `elements` model (Flow A described-design, Flow B logo, decoration style, pins, collage locks all re-expressed against `elements`).

- [ ] **Step 1: Write the failing tests** (rewrite the file's design/placement tests for the element model)

```python
# replace the Flow-A / Flow-B / placement tests in test_prompt_builder.py with element-model versions:
def test_elements_enumerated_with_per_element_placement():
    collected = {"elements": [
        {"type":"text","content":"TEAM SPIRIT","font":"bold","size":"large","colour":"gold",
         "placement_zone":"front_panel","placement_position":"centre","deferred":[]},
        {"type":"graphic","content":"a star","style":"minimalist","colour":"navy",
         "placement_zone":"side","deferred":["size"]},
    ]}
    prompt = _build(collected)
    assert "TEAM SPIRIT" in prompt and "gold" in prompt and "front panel" in prompt
    assert "star" in prompt and "navy" in prompt and "side" in prompt


def test_note_element_is_team_context_not_render():
    prompt = _build({"elements":[{"type":"note","content":"match our jersey blue","deferred":[]}]})
    assert "note to the team" in prompt.lower()
    assert "match our jersey blue" in prompt


def test_logo_element_keeps_second_image_directive():
    prompt = _build({"elements":[{"type":"logo","content":"uploaded logo",
        "asset_path":"uploads/logo.png","placement_zone":"front_panel","deferred":[]}],
        "uploaded_asset_path":"uploads/logo.png"})
    assert "SECOND image" in prompt
    assert "onto the cap" in prompt.lower()


def test_deferred_and_empty_attributes_skipped():
    prompt = _build({"elements":[{"type":"text","content":"HI","deferred":["colour","font"]}]})
    assert "Design colours" not in prompt and "font" not in prompt.lower()


def test_cap_lock_and_no_collage_still_present():
    prompt = _build({"elements":[{"type":"text","content":"HI","deferred":[]}]}).lower()
    assert "reproduce the cap exactly" in prompt
    assert "collage" in prompt and "side-by-side" in prompt
```

- [ ] **Step 2: Run to verify failure** — FAIL (builder still reads flat `design_description`).

- [ ] **Step 3: Implement**

3a. `IMAGE_GEN_PROMPT` (prompts.py): remove the standalone `PLACEMENT:` block's `{placement_zone}/{placement_position}` and fold placement into the per-element description. Replace lines 320-329 region with:
```
DECORATION(S) TO ADD (each placed exactly as noted):
{design_block}

DECORATION STYLE:
{decoration_style}
{pin_block}
```
(Keep everything else — ROLE, PRIMARY DIRECTIVE, OUTPUT/no-collage — unchanged.)

3b. `prompt_builder.py`: replace `_element_lines`/`_design_block` with element enumeration:
```python
_ZONE_LABEL = {"front_panel":"front panel","side":"side","back":"back","under_brim":"under the brim"}


def _placement_phrase(el: dict) -> str:
    zone = el.get("placement_zone")
    if not zone:
        return ""
    label = _ZONE_LABEL.get(zone, zone.replace("_", " "))
    pos = el.get("placement_position")
    return f" on the {label}" + (f" ({pos})" if pos else "")


def _element_line(el: dict) -> str:
    etype = el.get("type")
    if etype == "note":
        return f"Customer note to the team (do not render): {el.get('content','')}"
    if etype == "logo":
        base = prompts.UPLOADED_ASSET_DESIGN_BLOCK
        parts = []
        if el.get("size"): parts.append(f"sized {el['size']}")
        place = _placement_phrase(el)
        tail = (", ".join(parts) + place).strip()
        return base + (f"\nPlace the artwork{place}." if place else "")
    # text / graphic
    bits = []
    content = el.get("content", "")
    if etype == "text":
        bits.append(f'Text reading "{content}" (render exactly as written)')
    else:
        bits.append(f"A graphic: {content}")
    if el.get("font"): bits.append(f"{el['font']} font")
    if el.get("style"): bits.append(f"{el['style']} style")
    if el.get("size"): bits.append(f"{el['size']} size")
    if el.get("colour"): bits.append(f"in {el['colour']}")
    line = ", ".join(bits) + _placement_phrase(el) + "."
    return line


def _design_block(collected: dict) -> str:
    elements = collected.get("elements")
    if not elements:
        # legacy fallback: single described design / uploaded asset
        if collected.get("uploaded_asset_path"):
            return prompts.UPLOADED_ASSET_DESIGN_BLOCK
        return prompts.FALLBACK_DESIGN_BLOCK
    lines = [_element_line(el) for el in elements if el.get("type") != "logo"]
    logo_lines = [_element_line(el) for el in elements if el.get("type") == "logo"]
    all_lines = logo_lines + [f"- {ln}" for ln in lines]
    return "\n".join(all_lines) if all_lines else prompts.FALLBACK_DESIGN_BLOCK
```

3c. `build_prompt`: drop the `placement_zone`/`placement_position` kwargs from the `IMAGE_GEN_PROMPT.format(...)` call (they are no longer in the template). Keep `decoration_kind`, `design_block`, `decoration_style`, `pin_block`, and the `change_request` append.

- [ ] **Step 4: Run** — `pytest tests/test_prompt_builder.py -v` (rewritten + kept fidelity tests), then `pytest -q`. Confirm the cap-lock and no-collage assertions pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/prompt_builder.py backend/app/prompts.py backend/tests/test_prompt_builder.py
git commit -m "feat(prompt): enumerate elements with per-element placement"
```

---

## Task 8: `build_params` + generate.py element compatibility

**Files:**
- Modify: `backend/app/services/prompt_builder.py` (`build_params`), `backend/app/api/routes/generate.py`
- Test: `backend/tests/test_prompt_builder.py`, existing generate tests

**Interfaces:**
- Produces: `build_params` derives its single-value fields (`placement_zone`, `placement_position`, `remove_bg`, `decoration_type`) from the FIRST element that has them (falling back to defaults) so `GenerationParams` stays valid; the prompt text itself is per-element. Regeneration (`generate.py`) still layers `last_change` via `change_request`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_prompt_builder.py
def test_build_params_reads_first_element_placement():
    params = prompt_builder.build_params(
        {"elements":[{"type":"text","content":"HI","placement_zone":"back",
                      "placement_position":"left","remove_bg":True}]}, "preview")
    assert params.placement_zone == "back"
    assert params.placement_position == "left"
    assert params.remove_bg is True
```

- [ ] **Step 2: Run to verify failure** — FAIL (reads top-level `placement_zone`).

- [ ] **Step 3: Implement**

```python
def _first_with(elements: list, key: str, default):
    for el in elements or []:
        if el.get(key) not in (None, ""):
            return el[key]
    return default


def build_params(collected: dict, tier: str) -> GenerationParams:
    elements = collected.get("elements") or []
    return GenerationParams(
        tier=tier,
        placement_zone=_first_with(elements, "placement_zone", collected.get("placement_zone", "front_panel")),
        placement_position=_first_with(elements, "placement_position", collected.get("placement_position", "centre")),
        decoration_type=collected.get("decoration_type", "print"),
        remove_bg=bool(_first_with(elements, "remove_bg", collected.get("remove_bg", False))),
        pin_annotations=collected.get("pin_annotations", []) or [],
        resolution="2k" if tier == "final" else "standard",
    )
```

- [ ] **Step 4: Run** — new test + `-k generation` + `pytest -q`. Update any generate test that assumed top-level placement.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/prompt_builder.py backend/app/api/routes/generate.py backend/tests/test_prompt_builder.py
git commit -m "feat(prompt): build_params derives single-value fields from elements"
```

---

## Task 9: Copy, no-key questions, full verification + docs

**Files:**
- Modify: `backend/app/prompts.py` (`STATE_PROMPTS`, `CANNED_REPLIES` for `ask_more_elements`/`element_deepdive`), `CLAUDE.md`
- Test: `backend/tests/test_prompts.py`; full backend + frontend suites
- Frontend: verify only

**Interfaces:**
- Produces: `CANNED_REPLIES`/`STATE_PROMPTS` entries for `element_deepdive` (goal-leading: acknowledge the element, ask for the next attribute) and updated `ask_more_elements` copy (offers text/graphic/note). `ATTRIBUTE_QUESTIONS` (Task 4) supplies the per-attribute canned text.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_prompts.py
def test_deepdive_states_have_copy():
    for slug in ("ask_more_elements", "element_deepdive"):
        assert slug in prompts.CANNED_REPLIES
        assert slug in prompts.STATE_PROMPTS
    assert "graphic" in prompts.CANNED_REPLIES["ask_more_elements"].lower()
```

- [ ] **Step 2: Run to verify failure** — FAIL (`element_deepdive` absent).

- [ ] **Step 3: Implement** — add to `CANNED_REPLIES`:
```python
    "ask_more_elements": (
        "Anything to add — some text, a graphic, or a note for our team? "
        "Or say 'that's everything' and I'll put it together."
    ),
    "element_deepdive": "Great — let's nail down the details of that one.",
```
and to `STATE_PROMPTS`:
```python
    "ask_more_elements": (
        "Ask whether the customer wants to add another element — text, a graphic, "
        "or a note for the team — making clear they can also say they're done. "
        "One or two sentences."
    ),
    "element_deepdive": (
        "You are taking a custom order like a helpful salesperson. Acknowledge what "
        "the customer just gave for the current element, then ask ONLY for the next "
        "detail (provided to you), making clear they can say 'you choose'. One or two "
        "sentences, warm and specific."
    ),
```

- [ ] **Step 4: Full verification**
- `pytest -q` (backend). Fix any residual test still on the old flat/global model.
- Frontend: from `frontend/`, run `npx vitest run` in the FOREGROUND (do not background it). Expect only the 2 pre-existing `adminQuotes` failures; if a chat test asserted an old gather state, update it. Verify the `ChatPanel` renders the new `ASK_MORE_ELEMENTS`/`ELEMENT_DEEPDIVE` chips incl. "You choose" (chips are generic `options`, so no component change is expected — confirm by reading the option-render path).
- `CLAUDE.md` §13: update the "Smarter Studio conversation" bullet to describe the per-element deep-dive (typed elements, per-element attributes + placement, deferrable, InkyBay-parity capture) and refresh the backend test count.

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/tests/test_prompts.py CLAUDE.md
git commit -m "feat(convo): deep-dive copy; docs + full-suite verification"
```

---

## Self-Review

**Spec coverage:**
- §3.1 element list → data shape used in Tasks 5-8. ✅
- §3.2 attribute plans → Task 1. ✅
- §3.3 states (ELEMENT_DEEPDIVE, retire global placement, logo/describe funnel) → Tasks 2, 5. ✅
- §3.4 dynamic reply (`ask_for`) → Tasks 4, 5. ✅
- §3.5 no-key extraction → Task 4. ✅
- §3.6 prompt builder per-element + IMAGE_GEN_PROMPT rework → Tasks 7, 8. ✅
- §3.7 goal planner → Task 3. ✅
- §3.8 progress steady → Task 2, Step 3f + `test_progress_steady_during_deepdive_and_placement_retired`. ✅
- §4 frontend chips incl. "You choose" → Task 6 (`_public_data`) + Task 9 (verify). ✅
- §5 testing → each task TDD; Task 9 full suite. ✅

**Placeholder scan:** every step has concrete code/tests. The Task 6 "keep-or-delete `brief.py`" decision is explicitly conditioned on Task 7's outcome with a safe default (leave it, stop calling it) — not a placeholder.

**Type consistency:** element dict shape identical across Tasks 1/5/6/7/8; `pending_element`, `deferred`, `deepdive_ask_for` used consistently; `element_planner.next_attribute/is_complete/defer_remaining` names match; `extract_element_attributes(el_type, message)` and `generate_reply(..., ask_for=)` signatures match between Tasks 4 and 5.

**Note for implementers:** this rework supersedes the wider-brief flat brief + global placement — several pre-existing tests from that feature WILL need updating to the element model. That is expected; update them to assert the new behaviour (never weaken to hide a real regression) and note each in the task report.
