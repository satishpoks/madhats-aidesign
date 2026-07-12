# Early Email Capture + Hide Pin Placement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Ricardo's email ask to right after the design source (framed as "saves your progress", non-blocking), and hide the pin-placement step from the flow without deleting its code.

**Architecture:** A new goal-planner-routed state `SAVE_PROGRESS_EMAIL` is inserted the moment a design source exists; it captures the email (reusing `capture_lead_and_verify`) and falls back into the per-element deep-dive. Pin routing is removed from the two places that reach it (`goal_planner` step 6, `advance_state`'s `ASK_MORE_ELEMENTS` branch). Because `GENERATING` no longer asks for the email, a new `advance_after_generation` backend function + frontend poll (mirroring the existing regeneration pattern) advances `GENERATING` once generation settles.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend), React 18 / Zustand / Vitest (frontend). No new dependencies.

## Global Constraints

- No secrets in code; no PII (name/email) in logs — unchanged here.
- The email/verification mechanism is unchanged: capturing an email sends the existing verification link; delivery stays gated on **verified email AND completed generation**.
- Generation still runs at the end (full design captured first) — only the email *ask* moves.
- Pin code stays in the repo, just unreached (reversible).
- Backend tests: `cd backend && pytest -q`. Frontend tests: `cd frontend && npx vitest run`.
- Follow existing patterns in `services/conversation/` and `store/`. Match surrounding comment density.

---

### Task 1: Scaffolding — new `SAVE_PROGRESS_EMAIL` state, prompts, reworded `GENERATING` copy

Purely additive: declare the state and its copy, and stop `GENERATING` asking for the email. No routing reaches the new state yet, so the suite stays green.

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (enum, `TRANSITIONS`, `ALLOWED_BACKTRACKS`)
- Modify: `backend/app/prompts.py` (`STATE_PROMPTS`, `CANNED_REPLIES`)
- Test: `backend/tests/test_prompts_flow.py` (create)

**Interfaces:**
- Produces: `ConversationState.SAVE_PROGRESS_EMAIL` (value `"save_progress_email"`); `CANNED_REPLIES["save_progress_email"]`, `STATE_PROMPTS["save_progress_email"]`; reworded `CANNED_REPLIES["generating"]` / `STATE_PROMPTS["generating"]` that no longer ask for an email.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompts_flow.py`:

```python
"""Copy + enum guards for the early-email / hidden-pin flow changes."""
from app.prompts import CANNED_REPLIES, STATE_PROMPTS
from app.services.conversation.state_machine import ConversationState as S


def test_save_progress_email_state_exists():
    assert S.SAVE_PROGRESS_EMAIL.value == "save_progress_email"


def test_save_progress_email_copy_mentions_progress():
    canned = CANNED_REPLIES["save_progress_email"].lower()
    assert "progress" in canned
    assert "email" in canned or "@" in canned
    assert "save_progress_email" in STATE_PROMPTS


def test_generating_copy_no_longer_asks_for_email():
    # Email is captured earlier now; the generating line must not ask for it.
    canned = CANNED_REPLIES["generating"].lower()
    assert "email" not in canned
    assert "putting" in canned or "together" in canned
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_prompts_flow.py -q`
Expected: FAIL — `AttributeError: SAVE_PROGRESS_EMAIL` / `KeyError: 'save_progress_email'`.

- [ ] **Step 3: Add the enum member**

In `backend/app/services/conversation/state_machine.py`, add the member immediately after `ASK_EMAIL = "ask_email"` (around line 36):

```python
    ASK_EMAIL = "ask_email"
    SAVE_PROGRESS_EMAIL = "save_progress_email"
```

- [ ] **Step 4: Add TRANSITIONS + ALLOWED_BACKTRACKS entries**

In the same file, add to `TRANSITIONS` (place it right after the `S.DESCRIBE_DESIGN` entry, ~line 68). The early-email edge from the design source is resolved by the goal planner (Task 2), so this entry only documents the forward successor used by `advance_and_skip`/the default fallback:

```python
    S.SAVE_PROGRESS_EMAIL: [S.ELEMENT_DEEPDIVE],
```

Add to `ALLOWED_BACKTRACKS` (after the `S.DESCRIBE_DESIGN` entry, ~line 109):

```python
    S.SAVE_PROGRESS_EMAIL: [S.ASK_HAS_LOGO, S.DESCRIBE_DESIGN, S.UPLOAD_LOGO],
```

- [ ] **Step 5: Add prompts + reword generating**

In `backend/app/prompts.py`, add to `STATE_PROMPTS` (after the `"describe_design"` entry, ~line 58):

```python
    "save_progress_email": (
        "Ask for the customer's email, explaining it saves their progress so they "
        "can return to this design anytime and lets you send the finished design "
        "when it's ready. One or two warm sentences — not pushy."
    ),
```

Replace the `"generating"` entry in `STATE_PROMPTS` (~line 82) with:

```python
    "generating": "Tell them you're putting the design together now and it'll be in "
    "their inbox and on-screen the moment it's ready. Do NOT ask for their email.",
```

Add to `CANNED_REPLIES` (after the `"describe_design"` entry, ~line 267):

```python
    "save_progress_email": (
        "What's the best email for you? I'll save your progress so you can pick this "
        "design back up anytime — and send the finished design across once it's ready."
    ),
```

Replace the `"generating"` entry in `CANNED_REPLIES` (~line 290) with:

```python
    "generating": (
        "Putting your design together now — I'll pop it in your inbox and "
        "on-screen the moment it's ready."
    ),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/test_prompts_flow.py -q`
Expected: PASS (3 passed).

- [ ] **Step 7: Run the full backend suite (nothing else should break)**

Run: `cd backend && pytest -q`
Expected: PASS — no regressions (routing unchanged so far).

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/app/prompts.py backend/tests/test_prompts_flow.py
git commit -m "feat(convo): add SAVE_PROGRESS_EMAIL state + copy; drop email ask from generating

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: Reroute — hide pin + early-email goal in `goal_planner` and `advance_state`

Insert the early-email checkpoint in the goal planner and remove the two pin entry points. Because `SAVE_PROGRESS_EMAIL` now routes and would otherwise loop, add its one-shot flag in the orchestrator's flag block. Update every pure-logic and orchestrator test that the reroute changes.

**Files:**
- Modify: `backend/app/services/conversation/goal_planner.py:76-99` (add early-email gate; remove step-6 pin block)
- Modify: `backend/app/services/conversation/state_machine.py` (`advance_state` `ASK_MORE_ELEMENTS` branch, ~line 180)
- Modify: `backend/app/services/conversation/orchestrator.py` (one-shot flag block, ~line 200)
- Test: `backend/tests/test_goal_planner.py`, `backend/tests/test_state_machine.py`, `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `ConversationState.SAVE_PROGRESS_EMAIL` (Task 1).
- Produces: `goal_planner.next_goal` returns `SAVE_PROGRESS_EMAIL` once `pending_element`/`elements` exists and `email_prompt_shown` is unset; `advance_state(ASK_MORE_ELEMENTS, ...)` returns `GENERATING` (no pin) when there's no pending element; orchestrator sets `collected["email_prompt_shown"] = True` when it lands on `SAVE_PROGRESS_EMAIL`.

- [ ] **Step 1: Write/adjust the failing pure-logic tests**

In `backend/tests/test_goal_planner.py`, replace the pin-era tests. Replace `test_logo_branch_upload_then_more_elements_then_pin` (lines ~59-68) with:

```python
def test_logo_branch_upload_then_email_then_more_elements():
    # Once the logo is uploaded, the design source is met; the early-email
    # checkpoint fires next (once), then the elements offer.
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": True}
    assert next_goal(c) is S.UPLOAD_LOGO
    c["uploaded_asset_path"] = "uploads/logo.png"
    c["elements"] = [{"type": "logo", "content": "uploaded logo"}]
    assert next_goal(c) is S.SAVE_PROGRESS_EMAIL
    c["email_prompt_shown"] = True
    assert next_goal(c) is S.ASK_MORE_ELEMENTS
    c["elements_offered"] = True
    assert next_goal(c) is S.GENERATING
```

Replace `test_describe_branch_reaches_pin` (lines ~71-75) with:

```python
def test_describe_branch_reaches_generating():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False,
         "elements": [{"type": "text", "content": "x"}], "elements_offered": True,
         "email_prompt_shown": True}
    assert next_goal(c) is S.GENERATING
```

Replace `test_elements_offered_then_pin_offer_then_generating` and `test_pin_offer_is_optional_never_blocks` (lines ~78-90) with:

```python
def test_elements_offered_then_generating():
    c = _base()
    c["email_prompt_shown"] = True
    c["elements_offered"] = True
    assert next_goal(c) is S.GENERATING
```

Update `test_gather_goal_skipped_once_offered` (lines ~98-100) — expected becomes `GENERATING`:

```python
def test_gather_goal_skipped_once_offered():
    collected = {**_base(), "email_prompt_shown": True, "elements_offered": True}
    assert next_goal(collected) is S.GENERATING
```

Update `test_with_an_element_offers_more_then_pins_then_generating` (lines ~115-121) with:

```python
def test_with_an_element_offers_email_then_more_then_generating():
    base = {"name":"Al","purpose":"p","purpose_asked":True,"quantity":24,
            "decoration_type":"embroidery","has_logo":False,
            "elements":[{"type":"text","content":"TEAM"}]}
    assert next_goal(base) is S.SAVE_PROGRESS_EMAIL
    base["email_prompt_shown"] = True
    assert next_goal(base) is S.ASK_MORE_ELEMENTS
    assert next_goal({**base,"elements_offered":True}) is S.GENERATING
```

Update `test_gather_goal_offered_once_before_pin` (lines ~93-95) — `_base()` has `elements` but no `email_prompt_shown`, so the email gate now fires first:

```python
def test_email_checkpoint_before_gather_offer():
    collected = _base()
    assert next_goal(collected) is S.SAVE_PROGRESS_EMAIL
    collected["email_prompt_shown"] = True
    assert next_goal(collected) is S.ASK_MORE_ELEMENTS
```

Add a dedicated early-email test at the end of the file:

```python
def test_early_email_fires_once_then_deepdive():
    # A mid-build element (pending_element) triggers the email checkpoint once,
    # then falls through to the deep-dive.
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False,
         "pending_element": {"type": "text", "content": "TEAM", "deferred": []}}
    assert next_goal(c) is S.SAVE_PROGRESS_EMAIL
    c["email_prompt_shown"] = True
    assert next_goal(c) is S.ELEMENT_DEEPDIVE


def test_early_email_not_reoffered_without_design_source():
    # No element yet -> no early email; normal design-source questions first.
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False}
    assert next_goal(c) is S.DESCRIBE_DESIGN
```

Note: `test_pending_element_routes_to_deepdive_regardless_of_elements_offered` (lines ~129-140) passes `pending_element` **without** `email_prompt_shown`, so it must now set it. Update both dict literals to include `"email_prompt_shown": True`:

```python
def test_pending_element_routes_to_deepdive_regardless_of_elements_offered():
    c = {"name": "Al", "purpose_asked": True, "quantity": 24,
         "decoration_type": "embroidery", "has_logo": False, "email_prompt_shown": True,
         "pending_element": {"type": "text", "content": "TEAM", "deferred": []}}
    assert next_goal(c) is S.ELEMENT_DEEPDIVE
    c["elements_offered"] = True
    assert next_goal(c) is S.ELEMENT_DEEPDIVE
```

In `backend/tests/test_state_machine.py`, replace `test_more_elements_exit_offers_pins_then_generates` (lines ~140-143) with:

```python
def test_more_elements_exit_generates_pin_hidden():
    # Pin placement is hidden: no pending element -> straight to generation.
    assert advance_state(S.ASK_MORE_ELEMENTS, {}) is S.GENERATING
    assert advance_state(S.ASK_MORE_ELEMENTS, {"pin_offered": True}) is S.GENERATING
```

(Leave `test_pin_branch` at lines ~30-32 as-is — `advance_state(ASK_PIN_ANNOTATION, …)` logic is intentionally kept intact, just unreached.)

- [ ] **Step 2: Run the pure-logic tests to verify they fail**

Run: `cd backend && pytest tests/test_goal_planner.py tests/test_state_machine.py -q`
Expected: FAIL — new/renamed tests error (email gate + pin removal not implemented).

- [ ] **Step 3: Add the early-email gate + remove the pin block in goal_planner**

In `backend/app/services/conversation/goal_planner.py`, insert the gate immediately after the decoration-type check (after line 74, before the `pending_element` check at line 76-78):

```python
    # 4. decoration type (required)
    if not collected.get("decoration_type"):
        return _decoration_state(collected)

    # 4b. early email checkpoint — the moment a design source exists (a
    # described element or an uploaded logo has seeded one), capture the email
    # once, framed as "saves your progress", BEFORE the per-element deep-dive.
    # Non-blocking: once offered (email_prompt_shown), fall through whether or
    # not a usable email was given.
    if (collected.get("pending_element") or collected.get("elements")) \
            and not collected.get("email_prompt_shown"):
        return S.SAVE_PROGRESS_EMAIL

    # an element is mid-build -> the per-element deep-dive owns it
    if collected.get("pending_element"):
        return S.ELEMENT_DEEPDIVE
```

Then remove the step-6 pin block (lines ~94-96) so it reads:

```python
    # 5b. additional elements (optional, offered exactly once)
    if not collected.get("elements_offered"):
        return S.ASK_MORE_ELEMENTS

    # 6. email is captured earlier (SAVE_PROGRESS_EMAIL); generation is the last step.
    # Pin placement is hidden for now.
    return S.GENERATING
```

- [ ] **Step 4: Remove the pin entry point in advance_state**

In `backend/app/services/conversation/state_machine.py`, change the `ASK_MORE_ELEMENTS` branch of `advance_state` (~lines 180-185) to:

```python
    # --- Per-element deep-dive ---
    if current is S.ASK_MORE_ELEMENTS:
        if collected.get("pending_element"):
            return S.ELEMENT_DEEPDIVE
        # Pin placement is hidden for now — go straight to generation.
        return S.GENERATING
```

- [ ] **Step 5: Add the SAVE_PROGRESS_EMAIL one-shot flag in the orchestrator**

In `backend/app/services/conversation/orchestrator.py`, in the one-shot flag block (~lines 196-204), add a branch:

```python
        if new_state is ConversationState.ASK_PURPOSE:
            collected["purpose_asked"] = True
        elif new_state is ConversationState.YOUTH_REFERRAL:
            collected["youth_referred"] = True
        elif new_state is ConversationState.SAVE_PROGRESS_EMAIL:
            collected["email_prompt_shown"] = True
        elif new_state is ConversationState.ASK_MORE_ELEMENTS:
            collected["elements_offered"] = True
        elif new_state is ConversationState.ASK_PIN_ANNOTATION:
            collected["pin_offered"] = True
```

- [ ] **Step 6: Fix the orchestrator tests broken by the reroute**

In `backend/tests/test_conversation_smart.py`:

Update `test_placement_zone_defaults_position_and_skips_position_turn` (lines ~208-226): add `"email_prompt_shown": True` to `collected` and change the final assertion from `S.ASK_PIN_ANNOTATION` to `S.GENERATING`:

```python
                         "collected": {"name": "Al", "purpose": "gifts", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "elements": [{"type": "text", "content": "x"}],
                                       "elements_offered": True, "email_prompt_shown": True},
```
```python
    # position turn skipped -> pin is hidden, so next is generation
    assert res["state"] == S.GENERATING.value
```

Update `test_more_elements_decline_goes_to_placement` (lines ~248-264) — rename and change the assertion to `S.GENERATING`:

```python
async def test_more_elements_decline_goes_to_generating(monkeypatch):
    # Pin placement is hidden: a decline at ASK_MORE_ELEMENTS with no pending
    # element goes straight to generation.
    ...  # (body unchanged except the final assertion)
    res = await orch.handle_message("s1", "That's everything")
    assert res["state"] == S.GENERATING.value
    assert "pending_element" not in store["session"]["collected"] or not store["session"]["collected"]["pending_element"]
```

Update `test_describe_design_first_turn_enters_deepdive` (lines ~707-728): the email checkpoint now fires before the deep-dive on the describe turn, so seed `email_prompt_shown` so the deep-dive is still reached:

```python
    store = {"session": {"id": "s1", "state": S.DESCRIBE_DESIGN.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "email_prompt_shown": True},
                         "upsell_count": 0}}
```

(The two assertions — `res["state"] == S.ELEMENT_DEEPDIVE.value` and the seeded `pending_element` — stay.)

- [ ] **Step 7: Run the affected suites to verify they pass**

Run: `cd backend && pytest tests/test_goal_planner.py tests/test_state_machine.py tests/test_conversation_smart.py -q`
Expected: PASS.

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS (progress tests still green — Task 5 refines them; nothing there asserts pin routing).

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/ backend/tests/test_goal_planner.py backend/tests/test_state_machine.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): early-email goal + hide pin routing

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: Capture the email at `SAVE_PROGRESS_EMAIL` (non-blocking)

Make the early state actually save the email (send the verification link) and prove the flow continues into the deep-dive on the next turn.

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py:150-158` (inline email-capture condition)
- Test: `backend/tests/test_conversation_smart.py`

**Interfaces:**
- Consumes: `leads_service.extract_email`, `leads_service.capture_lead_and_verify` (existing); `ConversationState.SAVE_PROGRESS_EMAIL`.
- Produces: at `SAVE_PROGRESS_EMAIL`, a usable email sets `collected["email_captured"] = True` (+ `lead_id`) and sends verification; the turn then routes onward to `ELEMENT_DEEPDIVE`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_conversation_smart.py`:

```python
@pytest.mark.asyncio
async def test_save_progress_email_captures_and_continues(monkeypatch):
    # A valid email at SAVE_PROGRESS_EMAIL is captured (verification sent) and
    # the flow continues into the deep-dive — non-blocking.
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.SAVE_PROGRESS_EMAIL.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "pending_element": pend, "email_prompt_shown": True},
                         "store_id": None, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("great, saved!"))
    monkeypatch.setattr(orch.leads_service, "extract_email", lambda m: "al@example.com")
    captured = {}
    def _cap(session, collected, email):
        captured["email"] = email
        return "lead-123"
    monkeypatch.setattr(orch.leads_service, "capture_lead_and_verify", _cap)

    res = await orch.handle_message("s1", "al@example.com")
    c = store["session"]["collected"]
    assert captured["email"] == "al@example.com"
    assert c["email_captured"] is True
    assert c["lead_id"] == "lead-123"
    # non-blocking: continues into the deep-dive (pending element still building)
    assert res["state"] == S.ELEMENT_DEEPDIVE.value


@pytest.mark.asyncio
async def test_save_progress_email_no_email_still_continues(monkeypatch):
    # A non-email reply doesn't dead-end: email_prompt_shown stays set and the
    # flow proceeds to the deep-dive without capturing.
    pend = {"type": "text", "content": "TEAM", "deferred": []}
    store = {"session": {"id": "s1", "state": S.SAVE_PROGRESS_EMAIL.value,
                         "collected": {"name": "Al", "purpose": "p", "quantity": 24,
                                       "decoration_type": "embroidery", "has_logo": False,
                                       "pending_element": pend, "email_prompt_shown": True},
                         "store_id": None, "upsell_count": 0}}
    monkeypatch.setattr(orch, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(orch.settings_service, "get_settings", _fake_settings())
    monkeypatch.setattr(orch.ie, "interpret_turn", _fixed_interpret({"intent": "answer", "fields": {}}))
    monkeypatch.setattr(orch.ie, "generate_reply", _fixed_reply("no worries"))
    monkeypatch.setattr(orch.leads_service, "extract_email", lambda m: None)

    res = await orch.handle_message("s1", "maybe later")
    c = store["session"]["collected"]
    assert not c.get("email_captured")
    assert res["state"] == S.ELEMENT_DEEPDIVE.value
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_conversation_smart.py -k save_progress_email -q`
Expected: FAIL — email not captured (condition doesn't include `SAVE_PROGRESS_EMAIL`).

- [ ] **Step 3: Extend the inline capture condition**

In `backend/app/services/conversation/orchestrator.py`, change the guard (~line 150):

```python
        if current in (
            ConversationState.GENERATING,
            ConversationState.ASK_EMAIL,
            ConversationState.SAVE_PROGRESS_EMAIL,
        ) and not collected.get("email_captured"):
            email = leads_service.extract_email(message)
            if email:
                lead_id = leads_service.capture_lead_and_verify(session, collected, email)
                collected["email_captured"] = True
                if lead_id:
                    collected["lead_id"] = lead_id
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && pytest tests/test_conversation_smart.py -k save_progress_email -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/tests/test_conversation_smart.py
git commit -m "feat(convo): capture email at SAVE_PROGRESS_EMAIL, non-blocking

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: `advance_after_generation` — move `GENERATING` forward once generation settles

`GENERATING` no longer has a user email turn to advance it. Add a one-shot advance (mirrors `advance_after_regeneration`) that the frontend calls after generation settles.

**Files:**
- Modify: `backend/app/services/conversation/orchestrator.py` (add `advance_after_generation`)
- Modify: `backend/app/api/routes/chat.py` (add route + import)
- Test: `backend/tests/test_generation_advance.py` (create)

**Interfaces:**
- Consumes: `advance_state`, `AUTO_ADVANCE_STATES`, `_public_data`, `progress`, `ie.generate_reply` (existing); `RegenerationPollResponse` (existing model, reused).
- Produces: `orchestrator.advance_after_generation(session_id) -> dict` (`{"reply": str|None, "state": str, "data": dict}`); route `GET /chat/{session_id}/generation-advance`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_generation_advance.py` (reuse the fake-Supabase pattern from `test_verification_poll.py`):

```python
"""advance_after_generation() — moves GENERATING forward after generation settles.

Email is captured earlier now (SAVE_PROGRESS_EMAIL), so GENERATING has no user
email turn to advance it. The frontend calls this once, after startGeneration
settles, and it advances GENERATING -> VERIFY_EMAIL (or collapses to
OFFER_REFINE if already verified, or -> ASK_EMAIL if no email was captured).
"""
from __future__ import annotations

import asyncio

from app.services.conversation import orchestrator


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows, sink):
        self._rows = rows
        self._sink = sink

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def update(self, payload):
        self._sink.setdefault("updates", []).append(payload)
        return self

    def insert(self, payload):
        self._sink.setdefault("inserts", []).append(payload)
        return self

    def execute(self):
        return _Result(self._rows)


class _FakeSB:
    def __init__(self, session_row):
        self._session_row = session_row
        self.sink: dict = {}

    def table(self, name):
        rows = [self._session_row] if name == "design_sessions" else []
        return _Query(rows, self.sink)


def _patch(monkeypatch, session_row):
    fake = _FakeSB(session_row)
    monkeypatch.setattr(orchestrator, "get_supabase", lambda: fake)
    monkeypatch.setattr(orchestrator, "get_store", lambda _sid: None)

    async def _reply(state, collected, persona, aside=None):
        return f"[{state}] aside={aside}"

    monkeypatch.setattr(orchestrator.ie, "generate_reply", _reply)
    return fake


def test_advances_to_verify_when_captured_not_verified(monkeypatch):
    session = {"id": "s1", "state": "generating",
               "collected": {"email_captured": True}, "store_id": None}
    fake = _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s1"))
    assert result["state"] == "verify_email"
    assert result["reply"].startswith("[verify_email]")
    inserts = fake.sink.get("inserts", [])
    assert len(inserts) == 1 and inserts[0]["role"] == "assistant"


def test_collapses_to_offer_refine_when_already_verified(monkeypatch):
    session = {"id": "s2", "state": "generating",
               "collected": {"email_captured": True, "email_verified": True}, "store_id": None}
    _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s2"))
    assert result["state"] == "offer_refine"
    assert "verified" in result["reply"].lower()
    assert result["data"]["options"] == ["Request changes", "Looks good"]


def test_falls_back_to_ask_email_when_no_email(monkeypatch):
    session = {"id": "s3", "state": "generating", "collected": {}, "store_id": None}
    _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s3"))
    assert result["state"] == "ask_email"


def test_noop_when_not_generating(monkeypatch):
    session = {"id": "s4", "state": "offer_refine",
               "collected": {"email_captured": True}, "store_id": None}
    fake = _patch(monkeypatch, session)
    result = asyncio.run(orchestrator.advance_after_generation("s4"))
    assert result["reply"] is None
    assert result["state"] == "offer_refine"
    assert fake.sink.get("inserts") is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && pytest tests/test_generation_advance.py -q`
Expected: FAIL — `AttributeError: module 'orchestrator' has no attribute 'advance_after_generation'`.

- [ ] **Step 3: Implement `advance_after_generation`**

In `backend/app/services/conversation/orchestrator.py`, add after `advance_after_regeneration` (~line 361):

```python
async def advance_after_generation(session_id: str) -> dict:
    """One-shot advance used by the chat right after preview generation settles.

    The email is captured earlier now (SAVE_PROGRESS_EMAIL), so GENERATING has
    no user email turn to move it forward. The frontend calls this once, after
    startGeneration(sessionId) settles (success or failure), to advance:
      - email captured + already verified (clicked the link during the
        deep-dive) -> collapse straight through to OFFER_REFINE;
      - email captured, not yet verified -> rest at VERIFY_EMAIL (the verify
        poll finishes it);
      - no email captured -> ASK_EMAIL (terminal fallback ask).
    No-op (reply=None) if the session isn't at GENERATING.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}

    if current is not ConversationState.GENERATING:
        data = _public_data(current, collected)
        data["progress"] = progress(current, collected)
        return {"reply": None, "state": current.value, "data": data}

    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name

    new_state = advance_state(current, collected)  # VERIFY_EMAIL or ASK_EMAIL
    aside = None
    if new_state is ConversationState.VERIFY_EMAIL and collected.get("email_verified"):
        # Verified during the deep-dive — collapse through the post-verification
        # statement states to OFFER_REFINE (same landing as check_verification).
        new_state = advance_state(new_state, collected)  # EMAIL_VERIFIED
        while new_state in AUTO_ADVANCE_STATES:
            new_state = advance_state(new_state, collected)
        aside = "Your email's verified — your design's in your inbox and on-screen now."

    reply = await ie.generate_reply(new_state.value, collected, persona, aside=aside)

    sb.table("design_sessions").update(
        {"state": new_state.value, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert(
        {
            "session_id": session_id,
            "role": "assistant",
            "content": reply,
            "state_before": current.value,
            "state_after": new_state.value,
        }
    ).execute()

    data = _public_data(new_state, collected)
    data["progress"] = progress(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}
```

- [ ] **Step 4: Add the route**

In `backend/app/api/routes/chat.py`, add `advance_after_generation` to the import (line 12-17):

```python
from app.services.conversation.orchestrator import (
    SessionNotFound,
    advance_after_generation,
    advance_after_regeneration,
    check_verification,
    handle_message,
)
```

Add the endpoint after `poll_regeneration`:

```python
@router.get("/chat/{session_id}/generation-advance", response_model=RegenerationPollResponse)
async def poll_generation_advance(session_id: str) -> RegenerationPollResponse:
    """One-shot advance used by the chat right after preview generation settles.

    Called exactly once by the frontend after startGeneration(sessionId) resolves
    (success or failure). Advances GENERATING -> VERIFY_EMAIL (or collapses to
    OFFER_REFINE if already verified, or -> ASK_EMAIL if no email was captured);
    a no-op if the session isn't at GENERATING.
    """
    try:
        result = await advance_after_generation(session_id)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return RegenerationPollResponse(**result)
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd backend && pytest tests/test_generation_advance.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/conversation/orchestrator.py backend/app/api/routes/chat.py backend/tests/test_generation_advance.py
git commit -m "feat(convo): advance_after_generation to move generating forward

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 5: Progress counter — email step reflects the new position

`_progress_path` ends at `ASK_EMAIL`; rename that slot to `SAVE_PROGRESS_EMAIL` (email is now the early step), and make the terminal `ASK_EMAIL` fallback count as post-question.

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (`_progress_path`, `_POST_QUESTION_STATES`)
- Test: `backend/tests/test_progress.py`

**Interfaces:**
- Produces: `progress(SAVE_PROGRESS_EMAIL, collected)` returns the email step (`step == total`); `progress(ASK_EMAIL, …)` returns `step == total` (post-question fallback). Totals unchanged (7 describe / 8 upload).

- [ ] **Step 1: Write/adjust the failing test**

Append to `backend/tests/test_progress.py`:

```python
def test_progress_early_email_is_the_email_step():
    # SAVE_PROGRESS_EMAIL is the email step in both branches (last counted step).
    p = progress(S.SAVE_PROGRESS_EMAIL, {"has_logo": False})
    assert p["step"] == p["total"] == 7


def test_progress_terminal_ask_email_fallback_is_complete():
    # The rare terminal fallback ask must not drop back to step 1.
    p = progress(S.ASK_EMAIL, {"has_logo": False})
    assert p["step"] == p["total"]
```

Also update the stale comment in `test_progress_pin_annotation_does_not_reset` (lines ~43-48) to note pins are hidden but still count as post-question (assertions unchanged):

```python
def test_progress_pin_annotation_still_post_question():
    # Pin states are hidden from the flow but remain post-questionnaire, so if
    # ever reached they read as complete (step == total), never step 1.
    for st in (S.ASK_PIN_ANNOTATION, S.PIN_ANNOTATE_MODE):
        p = progress(st, {"has_logo": False})
        assert p["step"] == p["total"], st
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_progress.py -q`
Expected: FAIL — `SAVE_PROGRESS_EMAIL` not in path (falls to the step-1 fallback); `ASK_EMAIL` returns step 1.

- [ ] **Step 3: Update `_progress_path` and `_POST_QUESTION_STATES`**

In `backend/app/services/conversation/state_machine.py`, change the last line of `_progress_path` (~line 286) from:

```python
    path += [S.ASK_EMAIL]
```
to:
```python
    path += [S.SAVE_PROGRESS_EMAIL]
```

Add `ASK_EMAIL` to `_POST_QUESTION_STATES` (the frozenset ~lines 291-307) so the terminal fallback counts as complete:

```python
        ConversationState.ASK_PIN_ANNOTATION,
        ConversationState.PIN_ANNOTATE_MODE,
        ConversationState.ASK_EMAIL,
        ConversationState.GENERATING,
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_progress.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_progress.py
git commit -m "feat(convo): progress counter reflects early email step

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 6: Frontend — advance `generating` after generation settles

Wire the new backend endpoint into the store and chain it after `startGeneration` settles, mirroring the regeneration pattern.

**Files:**
- Modify: `frontend/src/lib/api.ts` (add `pollGenerationAdvance`)
- Modify: `frontend/src/store/chatStore.ts` (add `advanceGeneration` action)
- Modify: `frontend/src/components/ChatPanel/index.tsx` (chain after `startGeneration`)
- Test: `frontend/src/__tests__/chatStore.test.ts` (create)

**Interfaces:**
- Consumes: `pollGenerationAdvance(sessionId) -> Promise<VerificationPollResponse>`; `useGenerationStore.startGeneration` (returns a settled `Promise<void>`).
- Produces: `chatStore.advanceGeneration(sessionId)` appends Ricardo's reply and updates chat state when the reply is non-null.

- [ ] **Step 1: Write the failing store test**

Create `frontend/src/__tests__/chatStore.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { useChatStore } from '../store/chatStore'
import { pollGenerationAdvance } from '../lib/api'

beforeEach(() => {
  useChatStore.getState().reset()
  vi.clearAllMocks()
})

describe('advanceGeneration', () => {
  it('appends the reply and advances state when reply is non-null', async () => {
    vi.mocked(pollGenerationAdvance).mockResolvedValue({
      reply: "Putting your design together now.",
      state: 'verify_email',
      data: { progress: { step: 7, total: 7 } },
    })
    await useChatStore.getState().advanceGeneration('sess-1')
    const s = useChatStore.getState()
    expect(s.chatState).toBe('verify_email')
    expect(s.messages.at(-1)?.text).toBe('Putting your design together now.')
  })

  it('is a no-op when reply is null (not at generating)', async () => {
    vi.mocked(pollGenerationAdvance).mockResolvedValue({
      reply: null,
      state: 'generating',
      data: {},
    })
    const before = useChatStore.getState().messages.length
    await useChatStore.getState().advanceGeneration('sess-1')
    expect(useChatStore.getState().messages.length).toBe(before)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/chatStore.test.ts`
Expected: FAIL — `advanceGeneration` is not a function / `pollGenerationAdvance` not exported.

- [ ] **Step 3: Add the api helper**

In `frontend/src/lib/api.ts`, add after `pollRegeneration` (~line 100):

```typescript
/**
 * One-shot advance of the chat after preview generation settles. Called exactly
 * once by the frontend right after startGeneration(sessionId) resolves (success
 * or failure). `reply` is null if the session wasn't at generating; otherwise it
 * carries Ricardo's reply and `state` has advanced.
 */
export function pollGenerationAdvance(sessionId: string): Promise<VerificationPollResponse> {
  return request<VerificationPollResponse>(`/chat/${sessionId}/generation-advance`)
}
```

- [ ] **Step 4: Add the store action**

In `frontend/src/store/chatStore.ts`, update the import (line 2):

```typescript
import { sendChat, pollVerification, pollRegeneration, pollGenerationAdvance } from '../lib/api'
```

Add to the interface (after `advanceRegeneration`, ~line 37):

```typescript
  /** One-shot advance from generating -> verify/offer_refine, after generation settles. */
  advanceGeneration: (sessionId: string) => Promise<void>
```

Add the implementation after `advanceRegeneration` (~line 209), mirroring it:

```typescript
  advanceGeneration: async (sessionId: string) => {
    try {
      const res = await pollGenerationAdvance(sessionId)
      if (res.reply == null) return // not at generating (already advanced, or n/a)
      const { options, options2, triggerGeneration, triggerRegeneration, continuable, progress } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          { id: uid(), role: 'assistant', text: res.reply as string },
        ],
        chatState: res.state,
        options,
        options2,
        triggerGeneration,
        triggerRegeneration,
        continuable,
        progress,
      }))
    } catch {
      // Best-effort — a transient failure leaves the thread as-is; the verify
      // poll / backfill still delivers the design.
    }
  },
```

- [ ] **Step 5: Chain it in ChatPanel**

In `frontend/src/components/ChatPanel/index.tsx`, add the store selector near the other chat-store selectors (~line 347):

```typescript
  const advanceGeneration = useChatStore(s => s.advanceGeneration)
```

Update the generation effect (~lines 392-396) to chain the advance after `startGeneration` settles:

```typescript
  // Trigger async generation when the flow reaches the generating state, then
  // advance the chat once it settles (success or failure) so the customer is
  // never stranded at 'generating'. startGeneration() is once-guarded per session.
  useEffect(() => {
    if (sessionId && (triggerGeneration || chatState === 'generating')) {
      void startGeneration(sessionId).then(
        () => advanceGeneration(sessionId),
        () => advanceGeneration(sessionId),
      )
    }
  }, [sessionId, triggerGeneration, chatState, startGeneration, advanceGeneration])
```

- [ ] **Step 6: Add `advanceGeneration` to the store `reset` if needed**

No change — `reset` only resets data fields, not actions. Skip.

- [ ] **Step 7: Run the store test to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/chatStore.test.ts`
Expected: PASS (2 passed).

- [ ] **Step 8: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS — the 2 pre-existing `adminQuotes` failures (missing Router context, unrelated) may remain; no NEW failures. Confirm `ChatPanel.test.tsx` still passes.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/store/chatStore.ts frontend/src/components/ChatPanel/index.tsx frontend/src/__tests__/chatStore.test.ts
git commit -m "feat(chat): advance generating after generation settles

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 7: Full-suite verification + docs

**Files:**
- Modify: `CLAUDE.md` (Current implementation state — one line)

- [ ] **Step 1: Run both suites**

Run: `cd backend && pytest -q` — Expected: PASS.
Run: `cd frontend && npx vitest run` — Expected: PASS (only the 2 known unrelated `adminQuotes` failures, if still present).

- [ ] **Step 2: Update CLAUDE.md**

In `CLAUDE.md` §13 "Current implementation state", update the Smarter Studio bullet to note: the email is now captured **early** (right after the design source, framed as "saves your progress", non-blocking via `SAVE_PROGRESS_EMAIL`); pin-placement is **hidden** from the flow (code retained, unreached); `advance_after_generation` (`GET /chat/{id}/generation-advance`) moves `GENERATING` forward once generation settles.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: early email + hidden pin in current implementation state

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Spec §4.1 (hide pin, reversible) → Task 2 (routing removed; enum/component/route kept). ✓
- Spec §4.2 (new `SAVE_PROGRESS_EMAIL`, goal-routed, one-shot, capture, non-blocking, copy, `_public_data` free-text) → Tasks 1 (state+copy), 2 (routing+one-shot), 3 (capture). `_public_data` needs no branch — the default `return {}` already yields a free-text state. ✓
- Spec §4.3 (`advance_after_generation` + route + frontend poll + chain; verified/not-verified/no-email branches) → Tasks 4 (backend+route), 6 (frontend). ✓
- Spec §4.4 (`GENERATING` copy no longer asks email) → Task 1. ✓
- Spec §5 edge cases: verified-during-deepdive collapse → Task 4 test `test_collapses_to_offer_refine_when_already_verified`; no-email → Task 3 `test_save_progress_email_no_email_still_continues` + Task 4 `test_falls_back_to_ask_email_when_no_email`; resume (`email_prompt_shown` persisted in `collected`) → covered by existing persistence; progress → Task 5. ✓
- Spec §7 test impact → Tasks 2–6 update/add the listed tests. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `advance_after_generation` returns `{"reply", "state", "data"}` consumed by `RegenerationPollResponse` (reused, same shape as the regeneration poll). Frontend `pollGenerationAdvance` returns `VerificationPollResponse` (identical shape to the regeneration helper it mirrors). `advanceGeneration` matches `advanceRegeneration`'s signature. `email_prompt_shown` / `email_captured` / `lead_id` keys are consistent across Tasks 2–4. ✓

**Known limitation (noted, out of scope):** the early verification link's 15-minute TTL may expire during a long deep-dive; re-sending on expiry is not handled here. Delivery backfill and the terminal fallback still cover eventual delivery.
