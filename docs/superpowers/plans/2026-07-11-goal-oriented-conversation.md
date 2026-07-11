# Goal-Oriented Conversation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the strict per-state re-ask conversation model with a goal-slot checklist that extracts everything the customer volunteers, never re-asks a filled slot, and answers side-questions inline without freezing progress — fixing the double name-ask and the form-like feel.

**Architecture:** Add a pure `goal_planner.next_goal(collected)` that returns the state of the first unmet questionnaire goal. The orchestrator applies **all** extracted fields each turn, captures the name deterministically, routes forward via `next_goal` (questionnaire) or the existing `advance_state` (downstream gates), and answers questions via an inline `aside` instead of staying and re-asking. `ConversationState`, the DB schema, the frontend contract, and all post-questionnaire machinery (generation, email verification, refine/quote/upsell) are unchanged.

**Tech Stack:** Python 3.12 / FastAPI, Supabase (supabase-py), pytest. Conversation LLM is Claude Haiku via `intent_extractor`, with a deterministic no-key fallback.

## Global Constraints

- The conversation engine MUST keep working with **no Anthropic key** (deterministic heuristics + canned replies). Every change needs a no-key path.
- **No PII (name/email/phone) in logs or Sentry.** Do not log `collected` values; log state slugs only.
- DB access via **supabase-py** only (no raw SQL, no ORM). Reuse existing `get_supabase()`.
- Reply wording for the customer NEVER comes from `STATE_PROMPTS` templates directly — those are Haiku instructions. User-facing no-key text comes from `CANNED_REPLIES`.
- Run backend tests from `backend/`: `python -m pytest -q`. Full suite must stay green (baseline: 181 passed).

---

## File Structure

- **Create** `backend/app/services/conversation/goal_planner.py` — declarative goal list + `next_goal()` + `GATE_STATES`. Pure logic, no I/O.
- **Create** `backend/tests/test_goal_planner.py` — unit tests for `next_goal`.
- **Modify** `backend/app/services/conversation/orchestrator.py` — deterministic name capture, `_route()` (next_goal vs advance_state), remove the re-ask branch, set one-shot flags, merged-placement default.
- **Modify** `backend/tests/test_conversation_smart.py` — update behaviour-changed tests, add the name regression test.
- **Modify** `backend/app/services/conversation/state_machine.py` — `_progress_path` drops the now-defaulted placement-position step.
- **Modify** `backend/tests/test_state_machine.py` — progress-path assertion (if present) / add a progress test.

---

### Task 1: `goal_planner.next_goal` (pure logic)

**Files:**
- Create: `backend/app/services/conversation/goal_planner.py`
- Test: `backend/tests/test_goal_planner.py`

**Interfaces:**
- Consumes: `app.services.conversation.state_machine.ConversationState`.
- Produces:
  - `GATE_STATES: frozenset[ConversationState]` — states routed by `advance_state`, not the planner.
  - `next_goal(collected: dict, *, upsell_count: int = 0) -> ConversationState` — first unmet questionnaire goal; returns `GENERATING` when the questionnaire is complete.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_goal_planner.py
"""Pure-logic tests for the goal-oriented conversation planner."""
from __future__ import annotations

from app.services.conversation.goal_planner import next_goal
from app.services.conversation.state_machine import ConversationState as S


def _base():
    # A fully-answered questionnaire up to (not including) placement.
    return {
        "name": "Al",
        "purpose": "staff uniforms",
        "quantity": 50,
        "decoration_type": "embroidery",
        "has_logo": False,
        "design_description": {"summary": "logo"},
    }


def test_empty_returns_name():
    assert next_goal({}) is S.ASK_NAME


def test_name_present_moves_to_purpose():
    assert next_goal({"name": "Al"}) is S.ASK_PURPOSE


def test_name_never_reasked_once_set():
    # The double-name-ask regression, at the planner level.
    out = next_goal({"name": "Al"})
    assert out is not S.ASK_NAME


def test_soft_purpose_satisfied_once_asked():
    # purpose still empty, but we've already asked -> do not ask again.
    assert next_goal({"name": "Al", "purpose_asked": True}) is S.ASK_QUANTITY


def test_youth_referral_gate_shown_once():
    c = {"name": "Al", "purpose": "school team", "youth_flag": True}
    assert next_goal(c) is S.YOUTH_REFERRAL
    c["youth_referred"] = True
    assert next_goal(c) is S.ASK_QUANTITY


def test_quantity_presence_not_truthiness():
    # "not sure" -> quantity 0 still counts as answered.
    c = {"name": "Al", "purpose_asked": True, "quantity": 0}
    assert next_goal(c) is not S.ASK_QUANTITY


def test_decoration_by_quantity():
    c = {"name": "Al", "purpose_asked": True}
    assert next_goal({**c, "quantity": 1}) is S.WARN_PRINT_SETUP
    assert next_goal({**c, "quantity": 6}) is S.RECOMMEND_DECORATION
    assert next_goal({**c, "quantity": 24}) is S.RECOMMEND_EMBROIDERY


def test_logo_branch_upload_then_removebg_then_placement():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": True}
    assert next_goal(c) is S.UPLOAD_LOGO
    c["uploaded_asset_path"] = "uploads/logo.png"
    assert next_goal(c) is S.ASK_REMOVE_BG
    c["remove_bg"] = False
    assert next_goal(c) is S.ASK_PLACEMENT_ZONE


def test_describe_branch_reaches_placement():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False,
         "design_description": {"summary": "x"}}
    assert next_goal(c) is S.ASK_PLACEMENT_ZONE


def test_placement_zone_only_then_pin_offer_then_generating():
    c = _base()
    c["placement_zone"] = "front_panel"          # position intentionally absent
    assert next_goal(c) is S.ASK_PIN_ANNOTATION   # placement satisfied by zone alone
    c["pin_offered"] = True
    assert next_goal(c) is S.GENERATING


def test_pin_offer_is_optional_never_blocks():
    c = _base()
    c["placement_zone"] = "side"
    c["pin_offered"] = True
    assert next_goal(c) is S.GENERATING
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_goal_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.conversation.goal_planner'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/conversation/goal_planner.py
"""Goal-oriented conversation planner.

Returns the state of the FIRST unmet questionnaire goal, purely from the
collected data. This replaces the old "advance one state per turn" walk: a slot
that is already filled is never returned, and a genuinely-unmet required slot is
returned no matter which state the customer is nominally on. Downstream/gate
states (pin branching, generation, email verification, refine/quote/upsell) are
NOT owned here — the orchestrator routes those through
``state_machine.advance_state``.
"""
from __future__ import annotations

from app.services.conversation.state_machine import ConversationState as S

# States routed by advance_state (branching gates + async/downstream flow), not
# by the goal planner. The planner owns the forward questionnaire only.
GATE_STATES: frozenset[S] = frozenset(
    {
        S.ASK_PIN_ANNOTATION,
        S.PIN_ANNOTATE_MODE,
        S.GENERATING,
        S.ASK_EMAIL,
        S.VERIFY_EMAIL,
        S.EMAIL_VERIFIED,
        S.SEND_PREVIEW_EMAIL,
        S.SHOW_DESIGN,
        S.OFFER_REFINE,
        S.DESCRIBE_CHANGES,
        S.REGENERATING,
        S.QUOTE_REQUESTED,
        S.UPSELL_PROMPT,
        S.SESSION_END,
    }
)


def _decoration_state(collected: dict) -> S:
    """Mirror advance_state's DECORATION_ENGINE branch: recommend by quantity."""
    qty = int(collected.get("quantity") or 0)
    if qty <= 1:
        return S.WARN_PRINT_SETUP
    if qty < 12:
        return S.RECOMMEND_DECORATION
    return S.RECOMMEND_EMBROIDERY


def next_goal(collected: dict, *, upsell_count: int = 0) -> S:
    """Return the state for the first unmet forward-questionnaire goal.

    Pure function of ``collected``. When every goal is met, returns GENERATING
    (where the email is captured inline).
    """
    # 1. name (required)
    if not collected.get("name"):
        return S.ASK_NAME

    # 2. purpose (soft: satisfied once given OR once asked)
    if not collected.get("purpose") and not collected.get("purpose_asked"):
        return S.ASK_PURPOSE

    # youth referral (one-shot statement gate, derived from purpose)
    if collected.get("youth_flag") and not collected.get("youth_referred"):
        return S.YOUTH_REFERRAL

    # 3. quantity (required; presence, not truthiness — "not sure" -> 0 counts)
    if "quantity" not in collected:
        return S.ASK_QUANTITY

    # 4. decoration type (required)
    if not collected.get("decoration_type"):
        return _decoration_state(collected)

    # 5. design source (required) + branch
    if "has_logo" not in collected:
        return S.ASK_HAS_LOGO
    if collected.get("has_logo"):
        if not collected.get("uploaded_asset_path"):
            return S.UPLOAD_LOGO
        if "remove_bg" not in collected:
            return S.ASK_REMOVE_BG
    else:
        if not collected.get("design_description"):
            return S.DESCRIBE_DESIGN

    # 6. placement (required; zone only — position defaults to centre elsewhere)
    if not collected.get("placement_zone"):
        return S.ASK_PLACEMENT_ZONE

    # 7. pin annotation (optional, offered exactly once)
    if not collected.get("pin_offered"):
        return S.ASK_PIN_ANNOTATION

    # 8. email is captured inline at GENERATING
    return S.GENERATING
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_goal_planner.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/goal_planner.py backend/tests/test_goal_planner.py
git commit -m "feat(convo): add goal-oriented planner (next_goal)"
```

---

### Task 2: Wire the orchestrator to the planner

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py`
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `goal_planner.next_goal`, `goal_planner.GATE_STATES`, existing `advance_state`, `AUTO_ADVANCE_STATES`.
- Produces: unchanged `handle_message` return shape `{"reply", "state", "data"}`.

Behaviour changes in this task:
1. **Deterministic name capture** so a bare "Satish" always fills `name` (kills the double-ask at the source).
2. **`_route()`**: questionnaire states → `next_goal`; gate states → `advance_state`.
3. **Delete the "ask_question/chitchat → stay & re-ask" branch.** Questions become an inline `aside`; routing still runs so filled slots advance and only genuinely-unmet slots "stay".
4. **One-shot flags** (`purpose_asked`, `youth_referred`, `pin_offered`) set when about to ask that state.

- [ ] **Step 1: Update the behaviour-changed tests and add the name regression test**

Replace the three seeded-`collected` tests so prior slots are filled (goal-oriented routing asks the *first unmet* slot, so tests must seed everything before the slot under test), and add the name regression test. Edit `backend/tests/test_conversation_smart.py`:

```python
@pytest.mark.asyncio
async def test_bare_name_advances_and_is_not_reasked(monkeypatch):
    # Regression: a bare first name must be captured and the flow must move to
    # purpose — never ask the name a second time.
    store = {"session": {"id": "s1", "state": S.ASK_NAME.value, "collected": {}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    # Interpreter misclassifies the bare word as chitchat with no fields.
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "chitchat", "fields": {}}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("what are they for?"))
    res = await orch.handle_message("s1", "Satish")
    assert store["session"]["collected"]["name"] == "Satish"
    assert res["state"] == S.ASK_PURPOSE.value


@pytest.mark.asyncio
async def test_side_question_does_not_advance(monkeypatch):
    # A pure question at an unmet slot is answered but stays on that slot.
    store = {"session": {"id": "s1", "state": S.ASK_QUANTITY.value,
                         "collected": {"name": "Al", "purpose": "gifts"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "Embroidery lasts longer."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("re-ask"))
    res = await orch.handle_message("s1", "which lasts longer?")
    assert res["state"] == S.ASK_QUANTITY.value  # quantity still unmet -> stays


@pytest.mark.asyncio
async def test_upload_logo_chip_advances_even_if_misclassified(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "ask_question", "fields": {}, "question_answer": "..."}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("upload please"))
    res = await orch.handle_message("s1", "Upload logo")
    assert res["state"] == S.UPLOAD_LOGO.value


@pytest.mark.asyncio
async def test_describe_chip_routes_to_describe(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("describe please"))
    res = await orch.handle_message("s1", "Describe what I want")
    assert res["state"] == S.DESCRIBE_DESIGN.value


@pytest.mark.asyncio
async def test_typed_have_a_logo_reaches_upload(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_HAS_LOGO.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery"}, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("ok"))
    res = await orch.handle_message("s1", "yes I have a logo ready")
    assert res["state"] == S.UPLOAD_LOGO.value
```

(The existing `test_upload_logo_chip_advances_even_if_misclassified`, `test_describe_chip_routes_to_describe`, `test_typed_have_a_logo_reaches_upload`, and `test_side_question_does_not_advance` are replaced by the versions above.)

- [ ] **Step 2: Run the tests to verify the new/changed ones fail**

Run: `cd backend && python -m pytest tests/test_conversation_smart.py -q`
Expected: FAIL — `test_bare_name_advances_and_is_not_reasked` fails (name not captured / state stays `ask_name`), and the seeded-collected tests may fail on backward routing until the orchestrator uses `next_goal`.

- [ ] **Step 3: Add the import and name capture in `orchestrator.py`**

Add the planner import near the other conversation imports (after line 27 `from app.services.conversation import intent_extractor as ie`):

```python
from app.services.conversation import goal_planner
```

In `_apply_fields`, add deterministic name capture as the first block inside the function body (right after `low = message.lower()`), so a bare first name is always captured even when the interpreter misclassifies the turn:

```python
    # Deterministic name capture: a bare first name must fill `name` no matter
    # how the interpreter classified the turn (fixes the double name-ask). Skip
    # obvious non-answers (questions).
    if state is S.ASK_NAME and not collected.get("name"):
        candidate = message.strip().split("\n")[0][:60]
        if candidate and "?" not in candidate:
            collected["name"] = candidate
```

(Note: the existing `for key in (...)` loop that copies interpreter `fields` runs after this and will overwrite `name` with the interpreter's value when present — that is fine, the interpreter's value is preferred; this block only fills the gap when the interpreter gave nothing.)

- [ ] **Step 4: Replace the routing block in `handle_message`**

Replace the block from `intent = interp["intent"]` through the `reply = await ie.generate_reply(new_state.value, collected, persona)` line inside the `else:` branch (currently lines ~95-134) with:

```python
        intent = interp["intent"]
        # A tapped option chip (or a message exactly matching one) is a
        # DEFINITIVE answer — never a side-question. The interpreter occasionally
        # misclassifies a terse decision reply as ask_question/chitchat.
        _opts = _public_data(current, collected)
        _chip_values = [o.lower() for o in (_opts.get("options", []) + _opts.get("options2", []))]
        if message.strip().lower() in _chip_values and intent in ("ask_question", "chitchat"):
            intent = "answer"

        # Questions / chit-chat are answered INLINE (aside) and never freeze the
        # flow: routing still runs, so filled slots advance and only a genuinely
        # unmet slot "stays". This is what removes the old re-ask loop.
        aside = interp.get("question_answer") or None if intent in ("ask_question", "chitchat") else None

        if intent in ("revise", "backtrack"):
            target = interp.get("revise_target") or interp.get("backtrack_target")
            new_state = ConversationState(target) if target else _route(current, collected, upsell_count)
            if target:
                log.info("backtrack", session_id=session_id, frm=state_before, to=new_state.value)
        elif current is ConversationState.OFFER_REFINE and collected.get("wants_changes"):
            if _can_edit(session_id):
                new_state = ConversationState.DESCRIBE_CHANGES
            else:
                collected["edit_cap_reached"] = True
                new_state = ConversationState.QUOTE_REQUESTED
        else:
            new_state = _route(current, collected, upsell_count)

        if new_state is ConversationState.UPSELL_PROMPT and collected.get("wants_upsell"):
            upsell_count += 1
        # auto-advance through any routing-only states advance_state may return
        while new_state in AUTO_ADVANCE_STATES:
            new_state = advance_state(new_state, collected, upsell_count=upsell_count)

        # One-shot flags: mark soft/optional goals as offered so they are never
        # nagged on a later turn.
        if new_state is ConversationState.ASK_PURPOSE:
            collected["purpose_asked"] = True
        elif new_state is ConversationState.YOUTH_REFERRAL:
            collected["youth_referred"] = True
        elif new_state is ConversationState.ASK_PIN_ANNOTATION:
            collected["pin_offered"] = True

        reply = await ie.generate_reply(new_state.value, collected, persona, aside=aside)
```

- [ ] **Step 5: Add the `_route` helper**

Add this module-level helper (place it just above `_apply_fields`):

```python
def _route(
    current: ConversationState, collected: dict, upsell_count: int
) -> ConversationState:
    """Forward routing: the goal planner owns the questionnaire; advance_state
    owns the downstream/branching gates."""
    if current in goal_planner.GATE_STATES:
        return advance_state(current, collected, upsell_count=upsell_count)
    return goal_planner.next_goal(collected, upsell_count=upsell_count)
```

Remove the now-unused `advance_and_skip` from the import list on lines 28-38 (leave `advance_state`, `allowed_backtracks`, `is_affirmative`, `is_negative`, `progress`, `AUTO_ADVANCE_STATES`, `ConversationState`, `QUESTION_FIELD` — verify each is still referenced; `QUESTION_FIELD` may now be unused, drop it if so).

- [ ] **Step 6: Run the conversation tests**

Run: `cd backend && python -m pytest tests/test_conversation_smart.py -q`
Expected: PASS (all, including `test_bare_name_advances_and_is_not_reasked`)

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS. If a downstream test regresses, confirm the failing state is in `GATE_STATES` (should route via `advance_state`); adjust `GATE_STATES` membership, not the test.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): route via goal planner; capture name deterministically; answer questions inline"
```

---

### Task 3: Merged placement (default position = centre)

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (`_apply_fields`)
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `next_goal` placement rule (satisfied by `placement_zone` alone).
- Produces: `collected["placement_position"]` defaulted to `"centre"` when a zone is given without a position, so `ASK_PLACEMENT_POSITION` is never a mandatory separate turn.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_placement_zone_defaults_position_and_skips_position_turn(monkeypatch):
    store = {"session": {"id": "s1", "state": S.ASK_PLACEMENT_ZONE.value,
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "design_description": {"summary": "x"}},
                         "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(
        orch.ie, "interpret_turn",
        _fixed_interpret({"intent": "answer", "fields": {"placement_zone": "front_panel"}}),
    )
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("pin?"))
    res = await orch.handle_message("s1", "front panel")
    assert store["session"]["collected"]["placement_position"] == "centre"
    # position turn skipped -> next is the pin offer, not ASK_PLACEMENT_POSITION
    assert res["state"] == S.ASK_PIN_ANNOTATION.value
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_conversation_smart.py::test_placement_zone_defaults_position_and_skips_position_turn -q`
Expected: FAIL — `placement_position` not set (KeyError) / state is `ask_placement_position`.

- [ ] **Step 3: Add the default in `_apply_fields`**

In `orchestrator.py` `_apply_fields`, after the `for key in (...)` field-copy loop (which may set `placement_zone`), add:

```python
    # Merged placement: a zone is enough. Default the position to centre so we
    # never spend a separate turn asking for it (the customer can fine-tune via
    # the pin tool). An explicitly-provided position is preserved.
    if collected.get("placement_zone") and not collected.get("placement_position"):
        collected["placement_position"] = "centre"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_conversation_smart.py::test_placement_zone_defaults_position_and_skips_position_turn -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): merge placement into one question, default position to centre"
```

---

### Task 4: Progress indicator reflects the merged path

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (`_progress_path`)
- Test: `backend/tests/test_state_machine.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `progress(state, collected)` total no longer counts `ASK_PLACEMENT_POSITION` (it is defaulted, never its own turn).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_state_machine.py`:

```python
from app.services.conversation.state_machine import progress


def test_progress_path_excludes_defaulted_position():
    # describe branch: name, purpose, quantity, decoration, has_logo,
    # describe_design, placement_zone, email = 8 steps (position is defaulted).
    collected = {"has_logo": False}
    total = progress(S.ASK_NAME, collected)["total"]
    assert total == 8


def test_progress_counts_logo_branch():
    # logo branch adds upload + remove_bg, drops describe:
    # name, purpose, quantity, decoration, has_logo, upload, remove_bg,
    # placement_zone, email = 9 steps.
    collected = {"has_logo": True}
    assert progress(S.ASK_NAME, collected)["total"] == 9
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && python -m pytest tests/test_state_machine.py -k progress -q`
Expected: FAIL — totals are 9 (describe) / 10 (logo) because `ASK_PLACEMENT_POSITION` is still counted.

- [ ] **Step 3: Remove the position step from `_progress_path`**

In `state_machine.py` `_progress_path`, change the tail line:

```python
    path += [S.ASK_PLACEMENT_ZONE, S.ASK_PLACEMENT_POSITION, S.ASK_EMAIL]
```

to:

```python
    path += [S.ASK_PLACEMENT_ZONE, S.ASK_EMAIL]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd backend && python -m pytest tests/test_state_machine.py -k progress -q`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `cd backend && python -m pytest -q`
Expected: PASS (all green)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine.py
git commit -m "feat(convo): progress counter reflects merged placement step"
```

---

## Self-Review Notes

- **Spec coverage:** goal checklist → Task 1 `next_goal`; extract-all/skip-filled + no re-ask + answer-inline → Task 2; deterministic name fix → Task 2; soft purpose / youth one-shot / pin one-shot flags → Tasks 1+2; merged placement + default centre → Tasks 1+3; auto-recommend decoration (single turn) → Task 1 (`_decoration_state` returns the recommend state directly; the old auto-advanced `DECORATION_ENGINE`/`CONFIRM_DECORATION` turns are simply never targeted); no-key fallback → preserved (planner is pure; `interpret_turn` heuristic path unchanged); progress indicator → Task 4; downstream untouched → `GATE_STATES` routes them via `advance_state`.
- **No-key path:** `next_goal` is pure and key-agnostic; the heuristic extractor still fills the current slot, so the planner advances one question at a time without looping.
- **Type consistency:** `next_goal(collected, *, upsell_count=0) -> ConversationState` and `GATE_STATES` names are used identically in Tasks 1 and 2. `_route` and `_apply_fields` signatures match their call sites.
- **Enum/schema stability:** no `ConversationState` values added/removed; `ASK_PLACEMENT_POSITION` and `CONFIRM_DECORATION`/`DECORATION_ENGINE` remain valid states (reachable via revise/backtrack), just not on the forward path.
