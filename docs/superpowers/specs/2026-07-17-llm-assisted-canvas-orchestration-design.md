# LLM-Assisted Canvas Orchestration (v2 step registry) — Design

**Date:** 2026-07-17
**Status:** Approved for planning
**Owner:** Backend (conversation engine)
**Supersedes:** the field-extraction + routing internals of
`2026-07-15-step-by-step-canvas-orchestrator-v2-design.md` (that spec's *flow* is
unchanged; this one changes how the flow is expressed and how turns are understood)

---

## 1. Goal

Make the v2 canvas conversation **understand the customer with the LLM** and
**route deterministically over a declared step registry**, replacing the keyword
matching and the eight parallel per-state switches in `state_machine_v2.py` /
`orchestrator_v2.py`.

Four outcomes, all requested:

1. **Robustness** — stop misreading answers.
2. **Flexibility** — absorb out-of-order and batched answers.
3. **Maintenance** — adding a step means adding one record, not editing eight switches.
4. **Naturalness** — replies react to what the customer said.

Under one constraint: **it must still follow the flow.**

## 2. Why — the evidence

Live session `e4c2f3de-5208-4418-8f89-b69230d9cb0f` (2026-07-17, local, v2 flag on)
stalled at `ask_email` with `"quantity": 0`. The customer asked three times for a
second logo and was marched to the email question instead:

| Customer said | State | Result |
|---|---|---|
| "Yes, another logo" | `ASK_ANOTHER_LOGO` | read as **no** → skipped to decor |
| "another logo" | `ASK_ADD_DECOR` | read as **no** → skipped to quantity |
| "another logo at the back" | `ASK_QUANTITY` | parsed as **quantity 0** → skipped to email |

**Root cause:** `state_machine.is_negative` matches by substring
(`any(w in m for w in _NEGATIVE)`), and the word "a**no**ther" contains `"no"`.
Verified directly against the shipped functions.

Two structural facts make this a design problem, not a typo:

- **The broken string is our own chip label.** `state_machine_v2.v2_public_data:168`
  offers `"Yes, another logo"`; `orchestrator_v2._apply_v2_fields:123` re-derives its
  meaning by grepping it. The label and its meaning were declared in two places and
  nothing forced them to agree. Via the UI the second logo is unreachable, so the logo
  loop and `MAX_LOGOS = 4` are dead code.
- **The test suite documents the bug and dodges it.** `test_orchestrator_v2.py:141`:
  *"NB: not 'another logo' — 'another' contains 'no' … a plain 'yes' avoids that false
  negative."* The test sends `"Yes"` while the UI sends `"Yes, another logo"`, so it
  stays green over a chip that cannot work.

A second, independent bug: `_parse_quantity_heuristic` returns `int` with a fallback of
`0` and never `None`, while `advance_state_v2:67` gates on `quantity not in (None, "")`.
`0` passes, so `ASK_QUANTITY` accepts any input and its re-ask branch is unreachable.

**The generalisation:** v1 is interpreter-first (`intent_extractor.interpret_turn` →
structured fields) and v2 regressed to keywords for understanding. `is_negative` is a
12-word set doing natural-language understanding. "another" is simply where it drew
blood first.

## 3. Decisions

| Question | Decision |
|---|---|
| What does "follow the flow" protect? | **Hard gates, soft middle.** `name → intro → [design] → email → FINALIZE` are immovable; inside the design segment order is free. |
| Chip taps | **Deterministic.** Exact match to a known chip → known fields. 0 LLM calls, cannot fail. |
| Free text | **LLM mandatory.** No keyword fallback. Retry, then stall — never route on a guess. |
| Reply copy | **LLM acknowledges; instructions appended verbatim** from the registry. |
| Structure | **Declare each step once, as data.** |
| Router | **A — first-unmet resolution.** LLM fills slots; the router never takes a state from the LLM. C (explicit revise/backtrack intents) is additive, later. |
| Prod migration | **None.** `CANVAS_ORCHESTRATOR_V2` is off in prod; v2 is dev-only. |

### 3.1 Why a chip tap must not go to the LLM

When the customer taps `"Yes, another logo"`, *we* generated that exact string in
`v2_public_data` and shipped it to the browser, which sent it straight back. Asking a
model what it means adds latency, cost, a failure mode, and a hallucination risk to
recover a fact we already had when we wrote the label. It is not a "keyword path" or a
second mode that can drift — it is an identity lookup on a closed set we own. The bug
exists *because* that knowledge was thrown away and the meaning re-derived by grepping.

### 3.2 Why the LLM does not choose the route

The requested flexibility — *"put my logo on the back and add text" → two steps at once*
— is the LLM **filling two slots in one turn**, not choosing a route. Reordering is an
emergent property of slot-filling plus a router that doesn't ask about filled slots. This
keeps routing exhaustively testable with plain dicts and no mocking. The pattern is
already proven in this repo: `goal_planner.next_goal` is a pure function of `collected`
returning the first unmet goal. v2 abandoned it for the `advance_state_v2` if-chain,
which is *why* v2 can only move one step per turn.

## 4. Architecture

### 4.1 `canvas_steps.py` (new) — the registry

One frozen `Step` per step; everything about that step in one literal:

```python
Step(
    id="ask_another_logo",
    ask="Locked that in. Would you like to add another logo?",
    chips=(Chip("Yes, another logo", {"another_logo": True}),
           Chip("No, that's it",     {"another_logo": False})),
    slots=("another_logo",),
    done_when=lambda c: c.get("another_logo") is not None,
    tool=None, tip=None, gate=False,
)
```

`Step` fields: `id` (matches a `ConversationState` value), `ask`, `chips`, `slots`,
`done_when`, `apply`, `tool`, `tip`, `gate`, `target_face`, `auto_open`, `show_done`.

The chip's label and the field it sets are declared **in the same literal**. There is no
matcher, so there is nothing to desync — the `"another"` bug becomes *unrepresentable*
rather than fixed.

### 4.1.1 `apply` — the effect hook

Most steps need no effect: merging the resolved fields into `collected` is the whole
update, and `apply` is `None`. Three steps need bookkeeping beyond a merge, and it lives
on the record rather than in a switch:

```python
apply: Callable[[dict, dict, dict], None] | None   # (collected, fields, session) -> mutate collected
```

The `session` row is passed because `ask_email`'s capture needs it; steps that don't
need it ignore it. This is what keeps the email capture on its step's record instead of
as a special case in the orchestrator's turn loop.

- **`ask_another_logo`** — append `pending_logo` to `logos`; if the answer was yes *and*
  `len(logos) < MAX_LOGOS`, set `pending_logo = {}` and clear `another_logo`; else
  `pending_logo = None`. This is the entire loop mechanism, declared next to the step it
  belongs to.
- **`ask_email`** — `leads.capture_lead_and_verify` (needs the session row; see §5).
- **`show_intro`** — set the `intro_shown` one-shot flag.

`apply` runs **after** slot validation and **before** routing, so a step can only ever
mutate `collected` from fields that already passed validation. It returns nothing and
must not choose a state — routing stays the router's alone.

### 4.2 `state_machine_v2.py` (rewritten, shrinks) — a generic engine

| Today | Becomes |
|---|---|
| `V2_STATES` / `V2_OWNED` | registry keys |
| `advance_state_v2` if-chain | first step where `done_when(collected)` is False |
| `_V2_PROGRESS_PATH` | registry order, filtered to asking steps |
| `v2_public_data` chips | `step.chips` |
| `v2_reply` copy | `step.ask` |
| `_TOOL_STATES` / `canvas_directive` | `step.tool` / `step.tip` |
| `_apply_v2_fields` | `step.slots` + chip lookup + `step.apply` |

### 4.3 `orchestrator_v2.py` (rewritten, shrinks)

Per turn: resolve chip *or* interpret, merge, route, assemble reply.
`is_affirmative` / `is_negative` / `_face_from` / `_is_done` are **deleted from v2's
path**. v1 keeps its own copies, untouched.

### 4.4 `prompts.py` — `V2_TURN_INTERPRETER_PROMPT`

Given only the current step's `slots` and `ask`; returns JSON filling slots. It never
names a state.

### 4.5 Loops without a loop construct

The logo loop is modelled as `logos: []` plus `pending_logo: {}` — the collection-plus-
pending shape `goal_planner` already uses for the element deep-dive.

- `ask_logo_placement.done_when` = `pending_logo is None or "face" in pending_logo`
- `logo_adjust.done_when` = `pending_logo is None or pending_logo.get("placed")`
- `ask_another_logo.done_when` = `another_logo is not None`

Answering "yes" appends `pending_logo` to `logos`, sets `pending_logo = {}` (only if
`len(logos) < MAX_LOGOS`), and clears `another_logo` — making those three steps unmet
again, so the router walks back by itself. That bookkeeping is `ask_another_logo.apply`
(§4.1.1), declared on the step it belongs to. **Looping is slot-clearing.** No
back-edges, no `wants_another_logo` / `logo_done` reset flags.

### 4.6 Gates

Gate steps carry `gate=True`. The router never returns a step positioned after an unmet
gate. This preserves the invariant the current file documents in all-caps —
`email_captured` before `FINALIZE_CANVAS` — by construction rather than by comment.

## 5. Data flow

```
message arrives
  │
  ├─ current step not in registry?  → delegate to v1 tail (unchanged)
  ├─ GREETING?                      → kickoff, don't ingest the turn
  │
  ├─ exact match to a chip on the CURRENT step?
  │     YES → fields = chip.fields          0 LLM calls, cannot fail
  │
  └─ free text
        └─ interpret_turn_v2(step.slots, step.ask, message, collected)
              ok      → fields (declared slots only)
              failure → bounded retry → stall
  │
  ├─ merge fields → collected        (validated: declared slots, enum values)
  ├─ step.apply(collected, fields, session)   (§4.1.1 — loop bookkeeping,
  │                                            email capture, one-shot flags)
  ├─ next_step = router(collected)
  ├─ reply = LLM acknowledgement  +  step.ask  +  step.tip (verbatim)
  └─ persist; return {reply, state, data:{chips, canvas directive, progress}}
```

Chip matching is exact (strip + casefold) against the **current** step's chips only. A
stale chip tapped from an older message won't match and falls through to the interpreter,
which sees it in context.

## 6. Error handling

**Slot validation is the containment boundary.** The interpreter may only write keys in
`step.slots`; enum slots are checked against allowed values (`logo_face ∈
{front,back,left,right}`). Everything else is dropped. This is
`_normalize_interpretation`'s existing discipline applied to every step rather than to
one hand-maintained list. A hallucinated field cannot reach `collected`.

**Quantity is fixed structurally.** The interpreter either fills the slot or doesn't;
`done_when = "quantity" in collected` re-asks on its own. The `"Not sure"` chip sets
`{quantity: 0, quantity_unsure: True}`, so "not sure" is no longer indistinguishable from
"never answered".

**Interpretation failure** → bounded retry with backoff → **stall**: state unchanged, an
apologetic reply, nothing guessed.

**Chip-nudge escape hatch.** An indefinite stall on a pre-email-capture session is a lost
lead. After **two consecutive** interpreter failures, re-render the current step's chips
and nudge the customer to tap one. Chips are deterministic, so a full Haiku outage
degrades the bot to a tap-through wizard instead of a wall. This does not violate the
"no keyword fallback" rule — nothing is guessed; a closed question is asked.

**Reply asymmetry.** Interpretation must be correct or we stall (a wrong field corrupts
the design). Reply prose is best-effort and falls back to `step.ask` alone if Haiku is
down (an outage makes the bot terse, not broken). The tip is concatenated from the
registry and never passes through a model.

## 7. Testing

The load-bearing test is **generated from the registry**, so it cannot go stale:

```python
@pytest.mark.parametrize("step,chip", all_chips_in_registry())
def test_every_offered_chip_is_understood(step, chip):
    collected = seed_for(step)
    fields = resolve_chip(step, chip.label)              # the exact string we ship
    assert fields == chip.fields                         # round-trips
    assert router(merge(collected, fields)) != step.id   # and makes progress
```

Every step added later is covered the moment it is declared. Contrast today's
`test_orchestrator_v2.py:141`, which hand-picked `"Yes"` to dodge the string the UI
actually sends: a test that must know about the bug to avoid it is not protecting
anything.

Also:

- **Router** — table-driven, plain dicts, no mocking/async/Supabase. Each `done_when`;
  the logo loop through the `MAX_LOGOS` cap; gate enforcement (assert no step after an
  unmet gate is ever returned).
- **Interpreter** — mocked. Hallucinated keys dropped; enum slots rejected.
- **Failure** — stall leaves state unchanged; chips re-render after two failures.
- **E2E** — `test_v2_e2e.py` updated to drive the real chip labels.

## 8. Scope

**The frontend does not change.** The response contract is preserved exactly —
`data.options` is still chip labels, the `canvas` directive keeps its shape, `progress`
keeps its shape. `Surface.tsx`, `ToolRail`, and `chatStore` are untouched. The rewrite is
backend-internal.

**Out of scope (YAGNI):** v1's orchestrator, the shared tail, approach C
(revise/backtrack intents), approach B (LLM-proposed routing).

**Flagged, not fixed:** `is_negative`'s substring bug stays alive in **v1**, which still
calls it from `advance_state`. v2 will stop using it entirely, but v1 is the retained
runtime backup and keeps the landmine. Separate ticket.

**No migration.** `CANVAS_ORCHESTRATOR_V2` is off in prod. The `collected` shape changes
(`logo_face` / `logo_done` → `logos` / `pending_logo`); in-flight dev sessions are
abandoned, which is acceptable.

## 9. Success criteria

1. Tapping `"Yes, another logo"` reaches `ASK_LOGO_PLACEMENT` with a cleared face; four
   logos are reachable; the `MAX_LOGOS` cap holds.
2. `ASK_QUANTITY` re-asks on unparseable input instead of recording `0`.
3. "logo on the back and add text" fills both slots in one turn and the router skips the
   filled step.
4. No step after an unmet gate is ever returned; `FINALIZE_CANVAS` is unreachable without
   `email_captured`.
5. Adding a step touches exactly one file and one record.
6. A chip tap makes zero LLM calls.
7. Registry-generated chip round-trip test passes for every chip of every step.
