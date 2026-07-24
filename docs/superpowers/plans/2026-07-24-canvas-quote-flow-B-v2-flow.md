# Workstream B — v2 Conversation Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one registry-driven "When do you need these by?" step to the v2 canvas flow, inserted immediately before `ASK_PURPOSE`, so sales captures a delivery timeframe on every canvas quote.

**Architecture:** The v2 canvas orchestrator is registry-driven — `canvas_steps.REGISTRY` is the single source of truth and `state_machine_v2.next_step` routes by pure first-unmet resolution over the tuple order. Adding a step means adding a `Step` record plus its standard wiring (a `ConversationState` enum member, a `_SLOT_DOCS` entry, a `_PROGRESS_PATH` position); no per-state switch and no orchestrator change. Because the step carries chips, chip taps resolve deterministically (0 model calls) and a typed custom date flows through the Haiku interpreter into the `needed_by` slot.

**Tech Stack:** Python 3.12, FastAPI, pytest, Haiku interpreter

## Global Constraints
- v2 flow is registry-driven; routing is pure first-unmet — never add a per-state switch.
- The interpreter fills slots only, never names a state; new slot must be in `WRITABLE_SLOTS` via the step's `slots`.
- Chips carry BOTH label and the fields that label means, in the same literal.
- Baseline `CANVAS_ORCHESTRATOR_V2=false pytest -q` stays green.
- **All `pytest` commands in this plan run from `backend/`** (`cd backend` first) — the suite has no `conftest.py` and imports `from tests.canvas_step_helpers import …` and `from app.…`, which only resolve when the working directory is `backend/`. The v2 unit/e2e tests here call `orchestrator_v2.handle_message` / pure router functions directly, so they are independent of the `CANVAS_ORCHESTRATOR_V2` env flag (the flag is only read in `chat.py::_dispatch`, not in `orchestrator_v2`); they pass under either flag value. The baseline flag-off full-suite run is the final gate.
- The registry, progress path, `_SLOT_DOCS`, and the `satisfy` test helper are **coupled declaration sites** guarded by existing tests (`test_registry_declares_the_v2_flow_in_order`, `test_every_writable_slot_is_documented_for_the_interpreter`, `test_every_asking_step_has_a_progress_position`, `test_router_walks_every_step_in_declared_order`). A half-wired step turns the suite red on purpose — each task below leaves every touched test file green before committing.
- **Before starting:** branch off `master` — `git checkout -b feat/canvas-quote-flow-B-needed-by`.

---

## File Structure

Source (modify):
- `backend/app/services/conversation/state_machine.py` — new `ConversationState.NEEDED_BY` enum member.
- `backend/app/services/conversation/state_machine_v2.py` — `S.NEEDED_BY` added to `_PROGRESS_PATH`.
- `backend/app/services/conversation/canvas_steps.py` — new `Step(id=S.NEEDED_BY, …)` record in `REGISTRY`, inserted before the `ASK_PURPOSE` record.
- `backend/app/services/conversation/intent_extractor.py` — new `_SLOT_DOCS["needed_by"]` entry.

Tests / helpers (modify):
- `backend/tests/canvas_step_helpers.py` — `satisfy()` gains a `NEEDED_BY` branch.
- `backend/tests/test_state_machine_v2.py` — new routing/progress tests; one seed updated.
- `backend/tests/test_canvas_steps.py` — new step-shape tests; the registry-order test updated.
- `backend/tests/test_intent_extractor_v2.py` — new free-text `validate_fields` test.
- `backend/tests/test_v2_e2e.py` — chip-label walk extended through the new step; new free-text (voice-path) e2e test.
- `backend/tests/test_orchestrator_v2.py` — four coupled assertions/seeds updated.

No `prompts.py` change: the step's `ask` copy lives inline on the `Step`, exactly like `ASK_QUANTITY` ("How many caps are you after?") and `ASK_HAS_LOGO`.

---

## Task 1: Add the `NEEDED_BY` ConversationState enum member

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (v2 additive block, ~line 51, after `ASK_DECORATION_MIX`)
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Produces: `ConversationState.NEEDED_BY` with value `"needed_by"` (imported as `S.NEEDED_BY` throughout the v2 modules).

Rationale for ordering: Tasks 2 and 3 reference `S.NEEDED_BY` at import/collection time, so the enum member must exist first.

- [x] **Step 1 (failing test):** Add an enum-existence test to `backend/tests/test_state_machine_v2.py`:

```python
def test_needed_by_enum_member_exists():
    assert S.NEEDED_BY.value == "needed_by"
```

- [x] **Step 2 (run → FAIL):** `pytest tests/test_state_machine_v2.py::test_needed_by_enum_member_exists -v`
  - Expected: `FAILED` — collection/attribute error `AttributeError: NEEDED_BY` (the member does not exist yet).

- [x] **Step 3 (implement):** In `backend/app/services/conversation/state_machine.py`, add the member inside the v2 additive block, immediately after the `ASK_DECORATION_MIX` line:

```python
    ASK_DECORATION_MIX = "ask_decoration_mix"   # v2 only; v1 never routes here
    NEEDED_BY = "needed_by"                      # v2 only: "when do you want it by?" (before purpose)
```

- [x] **Step 4 (run → PASS):** `pytest tests/test_state_machine_v2.py::test_needed_by_enum_member_exists -v`
  - Expected: `1 passed`.

- [x] **Step 5 (commit):**
```bash
git add backend/app/services/conversation/state_machine.py backend/tests/test_state_machine_v2.py
git commit -m "$(cat <<'EOF'
feat(v2): add NEEDED_BY conversation state enum member

Groundwork for the "when do you need these by?" step (Workstream B/B1).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Give `NEEDED_BY` a progress position (before purpose)

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (`_PROGRESS_PATH`, ~lines 75–78)
- Test: `backend/tests/test_state_machine_v2.py`
- Modify (coupled): `backend/tests/test_orchestrator_v2.py` (~line 187 — the v2 progress `total`)

**Interfaces:**
- Consumes: `state_machine_v2._PROGRESS_PATH: list[S]`, `progress_for(step) -> {"step": int, "total": int}` where `total = len(_PROGRESS_PATH)`.
- Produces: `_PROGRESS_PATH` length grows 8 → 9; `S.NEEDED_BY` sits immediately before `S.ASK_PURPOSE`.

Why this is its own task: `progress_for`'s `total` is `len(_PROGRESS_PATH)`, so appending `S.NEEDED_BY` bumps the v2 flow total to 9 the instant the path changes — independent of whether the `Step` record exists yet. Exactly one existing assertion pins that total (`test_orchestrator_v2.py:187`); it is updated here so this task lands green.

- [x] **Step 1 (failing test):** Add a progress-position test to `backend/tests/test_state_machine_v2.py`:

```python
def test_needed_by_has_a_progress_slot_immediately_before_purpose():
    path = v2._PROGRESS_PATH
    assert S.NEEDED_BY in path
    assert path.index(S.NEEDED_BY) == path.index(S.ASK_PURPOSE) - 1
    assert len(path) == 9
```

- [x] **Step 2 (run → FAIL):** `pytest tests/test_state_machine_v2.py::test_needed_by_has_a_progress_slot_immediately_before_purpose -v`
  - Expected: `FAILED` — `assert S.NEEDED_BY in path` is False; `len(path) == 8`.

- [x] **Step 3 (implement):** In `backend/app/services/conversation/state_machine_v2.py`, insert `S.NEEDED_BY` immediately before `S.ASK_PURPOSE` in `_PROGRESS_PATH`:

```python
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_DECORATION, S.ASK_EMAIL, S.NEEDED_BY, S.ASK_PURPOSE,
]
```

- [x] **Step 4 (update the one coupled assertion):** In `backend/tests/test_orchestrator_v2.py`, in `test_a_volunteered_answer_is_banked_and_its_step_skipped` (~line 187), bump the v2 flow total:

```python
    assert res["data"]["progress"]["total"] == 9
```

  (Leave the V1 totals untouched — `test_progress.py:24`, `test_state_machine.py:86`, and `test_state_machine.py` `advance_state` use the separate V1 `progress()` and are unaffected by `_PROGRESS_PATH`.)

- [x] **Step 5 (run → PASS):** run the new test, the existing v2 progress guards, and the coupled orchestrator test together:
```bash
pytest tests/test_state_machine_v2.py::test_needed_by_has_a_progress_slot_immediately_before_purpose \
       tests/test_state_machine_v2.py::test_progress_collapses_loop_steps_onto_their_anchor \
       tests/test_state_machine_v2.py::test_progress_v2_is_state_keyed_and_survives_a_tail_state \
       tests/test_canvas_steps.py::test_every_asking_step_has_a_progress_position \
       tests/test_orchestrator_v2.py::test_a_volunteered_answer_is_banked_and_its_step_skipped -v
```
  - Expected: `5 passed`. (`test_every_asking_step_has_a_progress_position` iterates `cs.REGISTRY`, which does not yet contain `NEEDED_BY`, so it stays green; `ASK_PURPOSE`'s anchor is still in the path.)

- [x] **Step 6 (commit):**
```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py backend/tests/test_orchestrator_v2.py
git commit -m "$(cat <<'EOF'
feat(v2): reserve a progress slot for NEEDED_BY before purpose

v2 "Step X of N" counter grows 8 -> 9 for the new needed-by step.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Add the `needed_by` Step to the registry (+ slot docs, test helper, coupled test updates)

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py` (`REGISTRY`, insert before the `Step(id=S.ASK_PURPOSE, …)` record, ~line 576)
- Modify: `backend/app/services/conversation/intent_extractor.py` (`_SLOT_DOCS`, ~line 624)
- Modify: `backend/tests/canvas_step_helpers.py` (`satisfy()`, add a branch, ~line 55)
- Test (new): `backend/tests/test_canvas_steps.py`, `backend/tests/test_state_machine_v2.py`
- Modify (coupled): `backend/tests/test_canvas_steps.py` (`test_registry_declares_the_v2_flow_in_order`), `backend/tests/test_state_machine_v2.py` (`test_finalize_reached_when_everything_done`), `backend/tests/test_orchestrator_v2.py` (three assertions/seeds), `backend/tests/test_v2_e2e.py` (`test_full_v2_walk_using_the_exact_chip_labels`)

**Interfaces:**
- Consumes: `Step`, `Chip` dataclasses; `state_machine_v2.next_step(collected) -> Step`; `resolve_chip(step, message, collected) -> dict | None`.
- Produces: `cs.by_id(S.NEEDED_BY) -> Step`; `"needed_by"` present in `cs.WRITABLE_SLOTS` (auto-derived from the step's `slots`); routing `ASK_EMAIL -> NEEDED_BY -> ASK_PURPOSE`. No `SLOT_ENUMS` entry (the slot is free text: a chip bucket OR a custom date). No `apply`/`direct_answer`: the chips carry the buckets, the interpreter parses typed dates, and the value lives in `collected["needed_by"]` for Workstream C to surface in the sales quote summary.

- [x] **Step 1 (failing tests — routing + shape):** Add to `backend/tests/test_state_machine_v2.py`:

```python
def test_needed_by_is_asked_after_email_and_before_purpose():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True,
              decor_done=True, quantity=50, decoration_done=True,
              email_captured=True)
    assert v2.next_step(c).id is S.NEEDED_BY
    c["needed_by"] = "ASAP"
    assert v2.next_step(c).id is S.ASK_PURPOSE
```

  Add to `backend/tests/test_canvas_steps.py`:

```python
def test_needed_by_step_shape():
    step = cs.by_id(S.NEEDED_BY)
    assert step is not None
    assert step.slots == ("needed_by",)
    assert "needed_by" in cs.WRITABLE_SLOTS
    assert "needed_by" not in cs.SLOT_ENUMS      # free text: a bucket OR a date
    assert step.apply is None and step.direct_answer is None
    assert step.done_when({"needed_by": "ASAP"})
    assert not step.done_when({})
    labels = [ch.label for ch in step.chips]
    assert labels == ["ASAP", "2–4 weeks", "1–2 months", "Just exploring"]
    for ch in step.chips:
        assert set(ch.fields) == {"needed_by"}


def test_needed_by_sits_immediately_before_purpose_in_the_registry():
    ids = [s.id for s in cs.REGISTRY]
    assert ids[ids.index(S.NEEDED_BY) + 1] is S.ASK_PURPOSE


def test_a_defer_answer_still_satisfies_needed_by():
    """"Just exploring" (no firm date) is a valid answer — any non-empty value
    satisfies the step."""
    step = cs.by_id(S.NEEDED_BY)
    fields = v2.resolve_chip(step, "Just exploring", {})
    assert fields == {"needed_by": "Just exploring"}
    assert step.done_when(fields)
```

- [x] **Step 2 (run → FAIL):**
```bash
pytest tests/test_state_machine_v2.py::test_needed_by_is_asked_after_email_and_before_purpose \
       tests/test_canvas_steps.py::test_needed_by_step_shape \
       tests/test_canvas_steps.py::test_needed_by_sits_immediately_before_purpose_in_the_registry \
       tests/test_canvas_steps.py::test_a_defer_answer_still_satisfies_needed_by -v
```
  - Expected: all `FAILED` — `cs.by_id(S.NEEDED_BY)` is `None` (no registry record), so `.slots`/`.done_when` raise `AttributeError`; routing returns `ASK_PURPOSE`, not `NEEDED_BY`.

- [x] **Step 3 (implement the Step record):** In `backend/app/services/conversation/canvas_steps.py`, insert this record into the `REGISTRY` tuple immediately **before** the existing `Step(id=S.ASK_PURPOSE, …)` record (and after the `Step(id=S.ASK_EMAIL, …)` record):

```python
    Step(
        id=S.NEEDED_BY,
        ask="When do you need these by?",
        # Each label carries its own meaning field — a chip cannot disagree with
        # itself (see the module docstring). The value stored is the bucket
        # itself; a typed custom date arrives instead via the interpreter filling
        # the `needed_by` slot (no chip tapped).
        chips=(Chip("ASAP", {"needed_by": "ASAP"}),
               Chip("2–4 weeks", {"needed_by": "2–4 weeks"}),
               Chip("1–2 months", {"needed_by": "1–2 months"}),
               Chip("Just exploring", {"needed_by": "Just exploring"})),
        slots=("needed_by",),
        # Any non-empty answer satisfies it — including the "Just exploring" defer
        # chip. No apply/direct_answer: chips carry the buckets, the interpreter
        # parses typed dates, and the value lives in collected["needed_by"] for
        # Workstream C to surface in the sales quote summary. Free text, so no
        # SLOT_ENUMS entry (a custom date must pass validate_fields untouched).
        done_when=lambda c: "needed_by" in c,
    ),
```

- [x] **Step 4 (implement the slot doc):** In `backend/app/services/conversation/intent_extractor.py`, add a `_SLOT_DOCS` entry so the interpreter can fill `needed_by` from free text (place it after the `"quantity"` entry, before `"decoration_types"`):

```python
    "needed_by": "needed_by (string) — when the customer needs the caps by; a rough timeframe (e.g. 'ASAP', '2-4 weeks', '1-2 months') or a specific date they give. Use 'Just exploring' when there is no firm date",
```

- [x] **Step 5 (implement the test helper):** In `backend/tests/canvas_step_helpers.py`, add a `NEEDED_BY` branch to `satisfy()` immediately **before** the `S.ASK_PURPOSE` branch (so the registry walk and every `seed_for(...)` past this step stay valid):

```python
    elif step.id is S.NEEDED_BY:
        c["needed_by"] = "2-4 weeks"
```

- [x] **Step 6 (run new tests → PASS):**
```bash
pytest tests/test_state_machine_v2.py::test_needed_by_is_asked_after_email_and_before_purpose \
       tests/test_canvas_steps.py::test_needed_by_step_shape \
       tests/test_canvas_steps.py::test_needed_by_sits_immediately_before_purpose_in_the_registry \
       tests/test_canvas_steps.py::test_a_defer_answer_still_satisfies_needed_by -v
```
  - Expected: `4 passed`.

- [x] **Step 7 (surface the coupled failures):** run the full touched files to see which existing tests the insertion broke:
```bash
pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py -q
```
  - Expected: `FAILED` in exactly these (the coupled declaration sites and position-dependent flows):
    - `test_canvas_steps.py::test_registry_declares_the_v2_flow_in_order` — hardcoded order list is stale.
    - `test_state_machine_v2.py::test_finalize_reached_when_everything_done` — seed lacks `needed_by`, so first-unmet returns `NEEDED_BY`, not `FINALIZE_CANVAS`.
    - `test_orchestrator_v2.py::test_ask_email_tells_the_customer_a_verification_link_was_sent` — next state after email is now `NEEDED_BY`, not `ASK_PURPOSE`.
    - `test_orchestrator_v2.py::test_ask_email_survives_an_outage_via_regex` — same next-state change.
    - `test_orchestrator_v2.py::test_daily_cap_reroutes_to_the_quote_ask` — seed starts at `ASK_PURPOSE` without `needed_by`, so answering purpose routes to `NEEDED_BY` instead of the capped `FINALIZE`/quote handoff.
    - `test_v2_e2e.py::test_full_v2_walk_using_the_exact_chip_labels` — the walk's email→purpose transition now lands on `NEEDED_BY`.
    - (`test_router_walks_every_step_in_declared_order` and the parametrized `test_every_offered_chip_*` tests should already be GREEN — the `satisfy` helper branch and the auto-enumerated chips cover them.)

- [x] **Step 8 (update coupled test — registry order):** In `backend/tests/test_canvas_steps.py`, `test_registry_declares_the_v2_flow_in_order`, change the final row of the expected list to insert `S.NEEDED_BY` before `S.ASK_PURPOSE`:

```python
        S.ASK_EMAIL, S.NEEDED_BY, S.ASK_PURPOSE, S.FINALIZE_CANVAS,
```

- [x] **Step 9 (update coupled test — v2 finalize seed):** In `backend/tests/test_state_machine_v2.py`, `test_finalize_reached_when_everything_done`, add `needed_by="ASAP"` to the seed so `FINALIZE_CANVAS` is reachable:

```python
def test_finalize_reached_when_everything_done():
    c = _seed(name="Sam", intro_ack=True, has_logo=True, logos_done=True, decor_done=True,
              quantity=50, decoration_done=True, email_captured=True, needed_by="ASAP",
              purpose="team caps")
    assert v2.next_step(c).id is S.FINALIZE_CANVAS
```

- [x] **Step 10 (update coupled tests — orchestrator_v2 next-state + capped seed):** In `backend/tests/test_orchestrator_v2.py`:

  In `test_ask_email_tells_the_customer_a_verification_link_was_sent` (~line 208):
```python
    assert res["state"] == S.NEEDED_BY.value
```

  In `test_ask_email_survives_an_outage_via_regex` (~line 335):
```python
    assert res["state"] == S.NEEDED_BY.value
```

  In `test_daily_cap_reroutes_to_the_quote_ask`, add `"needed_by"` to the seeded `collected` (~lines 252–256) so answering purpose reaches the capped `FINALIZE`:
```python
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True, "has_logo": True,
        "logos_done": True, "decor_done": True, "quantity": 50,
        "needed_by": "ASAP", "email_captured": True,
    }
```

- [x] **Step 11 (update coupled test — e2e chip-label walk):** In `backend/tests/test_v2_e2e.py`, `test_full_v2_walk_using_the_exact_chip_labels`, replace the tail of the `walk` list so the email answer lands on `NEEDED_BY`, then a chip tap advances to `ASK_PURPOSE`:

```python
        ("50-99",                   S.ASK_DECORATION),
        ("Embroidery",              S.ASK_EMAIL),          # single-select
        ("sam@example.com",         S.NEEDED_BY),
        ("ASAP",                    S.ASK_PURPOSE),
        ("for the team",            S.FINALIZE_CANVAS),
    ]
```

  And add one assertion to the final `collected` checks at the end of that test:

```python
    assert c["needed_by"] == "ASAP"
```

- [x] **Step 12 (run → PASS):** re-run every touched file:
```bash
pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py -q
```
  - Expected: all pass (0 failed).

- [x] **Step 13 (commit):**
```bash
git add backend/app/services/conversation/canvas_steps.py \
        backend/app/services/conversation/intent_extractor.py \
        backend/tests/canvas_step_helpers.py \
        backend/tests/test_canvas_steps.py \
        backend/tests/test_state_machine_v2.py \
        backend/tests/test_orchestrator_v2.py \
        backend/tests/test_v2_e2e.py
git commit -m "$(cat <<'EOF'
feat(v2): add "when do you need these by?" step before purpose (B1)

Registry-driven needed_by step: ASAP / 2-4 weeks / 1-2 months / Just
exploring chips plus a free-text custom date via the interpreter. Routes
ASK_EMAIL -> NEEDED_BY -> ASK_PURPOSE by first-unmet; value banked in
collected["needed_by"] for the sales quote summary (Workstream C).

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Free-text (voice-path) coverage + interpreter validation + verification checklist (B3)

**Files:**
- Test (new): `backend/tests/test_intent_extractor_v2.py`, `backend/tests/test_v2_e2e.py`
- Verification only (no code): manual voice pass through the v2 canvas flow

**Interfaces:**
- Consumes: `intent_extractor.validate_fields(raw) -> dict`; `orchestrator_v2.handle_message(session_id, message)`; `intent_extractor.interpret_turn_v2` (monkeypatched in the e2e test).
- Produces: proof that a dictated/transcribed custom date (free text, no chip) fills `needed_by` and advances the flow.

B3 is a verification obligation, not a new mechanism: voice answers become text that flows through the interpreter into slots, and chip labels are matched from transcribed text (already covered by Task 3's chip walk). This task adds the free-text half and records the manual voice result.

- [ ] **Step 1 (failing test — interpreter passes a free-text date):** Add to `backend/tests/test_intent_extractor_v2.py`:

```python
def test_validate_passes_a_free_text_needed_by():
    # needed_by is NOT in SLOT_ENUMS (a custom date is valid), so a free-text
    # value must pass validate_fields untouched — that is how a dictated date
    # reaches collected.
    assert ie.validate_fields({"needed_by": "the 15th of March"}) == {
        "needed_by": "the 15th of March"
    }
```

- [ ] **Step 2 (run → PASS immediately):** `pytest tests/test_intent_extractor_v2.py::test_validate_passes_a_free_text_needed_by -v`
  - Expected: `1 passed`. (This test only fails if `needed_by` was never added to `WRITABLE_SLOTS` in Task 3 — running it here is the guard that the slot is genuinely interpreter-writable, not enum-locked.)

- [ ] **Step 3 (failing test — free-text/voice e2e walk):** Add to `backend/tests/test_v2_e2e.py`:

```python
@pytest.mark.asyncio
async def test_needed_by_accepts_a_free_text_date_voice_path(monkeypatch):
    """B3 voice path: a dictated/transcribed custom date is free text, so it
    flows through the interpreter into the needed_by slot — no chip tapped — and
    advances ASK_PURPOSE. Chip labels from transcribed text are already covered
    by test_full_v2_walk_using_the_exact_chip_labels."""
    store = _new_store()
    store["session"]["state"] = S.NEEDED_BY.value
    store["session"]["collected"].update({
        "name": "Sam", "intro_ack": True, "has_logo": False, "logos_done": True,
        "pending_logo": None, "decor_done": True, "quantity": 12,
        "decoration_done": True, "email_captured": True,
    })
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _fill(step, message, collected):
        assert step.id is S.NEEDED_BY
        return {"needed_by": "the 15th of next month"}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _fill)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "I'd need them by the 15th of next month")
    assert res["state"] == S.ASK_PURPOSE.value
    assert store["session"]["collected"]["needed_by"] == "the 15th of next month"
```

- [ ] **Step 4 (run → PASS):** `pytest tests/test_v2_e2e.py::test_needed_by_accepts_a_free_text_date_voice_path -v`
  - Expected: `1 passed`. (Fails only if the `Step` or slot wiring from Task 3 is incomplete — `merge_fields` keeps `needed_by` because it is the current step's own slot, and `next_step` then advances to `ASK_PURPOSE`.)

- [ ] **Step 5 (full-file confirmation):**
```bash
pytest tests/test_intent_extractor_v2.py tests/test_v2_e2e.py -q
```
  - Expected: all pass.

- [ ] **Step 6 (baseline gate — flag off, full suite):** confirm nothing else regressed under the baseline configuration:
```bash
CANVAS_ORCHESTRATOR_V2=false pytest -q
```
  - Expected: the whole backend suite green (0 failed).

- [ ] **Step 7 (baseline gate — flag on):** the repo-root `.env` defaults `CANVAS_ORCHESTRATOR_V2=true`; run the v2-owning files under it to confirm parity:
```bash
pytest tests/test_canvas_steps.py tests/test_state_machine_v2.py tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_intent_extractor_v2.py -q
```
  - Expected: all pass.

- [ ] **Step 8 (manual voice pass — no code):** Run a live canvas session (`?mode=blank` or `?product_id=…`) with `CANVAS_ORCHESTRATOR_V2=true` and a valid `ANTHROPIC_API_KEY`. Walk to the "When do you need these by?" step and verify, using voice-dictated (speech-to-text) input:
  - Tapping a chip ("ASAP" / "2–4 weeks" / "1–2 months" / "Just exploring") advances to the purpose question and banks `needed_by`.
  - Dictating a custom date ("I need them by the end of March") is transcribed to text, fills `needed_by`, and advances.
  - The "Step X of N" counter reads one higher than before this change (9 total) and stays steady across the step.
  - Record the outcome (pass/fail + notes) in the PR description. This is a checklist item, not an automated test.

- [ ] **Step 9 (commit):**
```bash
git add backend/tests/test_intent_extractor_v2.py backend/tests/test_v2_e2e.py
git commit -m "$(cat <<'EOF'
test(v2): cover free-text/voice needed_by path (B3)

validate_fields passes a free-text date; e2e walk fills needed_by via the
interpreter (no chip). Chip-label voice matching is covered by the existing
exact-label walk. Manual voice pass recorded in the PR.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
EOF
)"
```

---

## Done criteria
- `cd backend && CANVAS_ORCHESTRATOR_V2=false pytest -q` is green.
- The v2 canvas flow asks "When do you need these by?" immediately before the purpose question; chip taps and typed dates both fill `collected["needed_by"]`.
- The "Step X of N" total is 9.
- The manual voice pass result is recorded.
- No `frontend/`, `docker-compose*.yml`, Railway, or `CLAUDE.md` changes (Workstream B is backend-only).
