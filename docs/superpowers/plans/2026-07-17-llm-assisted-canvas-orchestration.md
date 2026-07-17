# LLM-Assisted Canvas Orchestration (v2 step registry) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace v2's keyword matching and eight parallel per-state switches with a declared step registry, an LLM that fills slots, and a deterministic first-unmet router.

**Architecture:** One `Step` record per step declares its copy, chips (label *and* the fields that label means, in the same literal), slots, done-condition, effect hook, and canvas tool. `state_machine_v2` becomes a generic engine reading that registry; `orchestrator_v2` resolves a chip deterministically or calls Haiku for free text, then asks the router for the first step whose `done_when(collected)` is False. The LLM never names a state.

**Tech Stack:** Python 3.12, FastAPI, pytest/pytest-asyncio, Claude Haiku (`settings.claude_haiku_model`), Supabase.

**Spec:** `docs/superpowers/specs/2026-07-17-llm-assisted-canvas-orchestration-design.md`

## Global Constraints

- **No PII in logs.** Never log `name`, `email`, or `purpose`. Reuse `intent_extractor._safe_collected` when passing `collected` to a model or a log.
- **Chip taps make zero LLM calls.** Exact match (strip + casefold) against the current step's chips only.
- **Free text has no keyword fallback.** Interpret via Haiku; on failure retry then stall. Never guess.
- **Tool tips are concatenated verbatim** from `prompts.V2_TOOL_TIPS`. They never pass through a model.
- **v1 is untouched.** `orchestrator.py`, `state_machine.py`, `goal_planner.py` are not modified. v2 must stop *calling* `is_affirmative`/`is_negative`, but must not delete or change them — v1 still uses them.
- **The response contract is frozen.** `{"reply", "state", "data": {...}}` where `data` may carry `options`, `continuable`, `canvas`, `progress`, `trigger_finalize`. The frontend must not need a change.
- **`MAX_LOGOS = 4`.**
- **Env flag unchanged:** `settings.canvas_orchestrator_v2` + `flow_mode == "canvas"` still selects v2 in `chat.py::_dispatch`.
- **A name must stay plausible.** `_plausible_name` / `_NAME_FILLER` (committed in `44e8eda`) exist because *"ok" became a customer's name* in a live session. The interpreter proposes `name`; a deterministic guard must still reject filler. Do not drop this — see Task 4.
- **Run tests from `backend/`:** `cd backend && CANVAS_ORCHESTRATOR_V2=false pytest -q`.
  **The env override is required.** The repo-root `.env` sets `CANVAS_ORCHESTRATOR_V2=true` for local dev, which makes three *pre-existing* tests fail (`test_config_v2_flag.py::test_flag_defaults_false`, `test_canvas_routes.py::test_finalize_routes_to_decoration`, `test_chat_route.py::test_chat_post_resolves_body_not_422`) — they assert flag-default-off and flag-off routing. With the override: **562 passed** at `44e8eda`. That is the baseline; do not "fix" those three.

## Deviation from the spec (read before Task 1)

The spec's §4.6 `gate=True` mechanism is **not implemented**, because planning the router proved it is a no-op. A first-unmet router never returns *any* step positioned after *any* unmet step, so "never return a step after an unmet gate" is already true for every step. Building `gate` would ship dead configuration that reads as if it were load-bearing.

The invariant it was meant to protect — **`FINALIZE_CANVAS` unreachable without `email_captured`** — is preserved by construction and proven by test instead: `ask_email` precedes `finalize_canvas` in registry order, and `ask_email.done_when` reads `email_captured`, which **only** `_apply_email` sets after a real `capture_lead_and_verify`. The interpreter cannot set it (see Task 5: `email_captured` is not a writable slot). Task 2 asserts this directly.

## File Structure

| File | Responsibility |
|---|---|
| **Create** `backend/app/services/conversation/canvas_steps.py` | `Chip`/`Step` records, the `REGISTRY`, `apply` hooks, `WRITABLE_SLOTS`, `SLOT_ENUMS`. The only file you touch to add a step. |
| **Rewrite** `backend/app/services/conversation/state_machine_v2.py` | Generic engine over the registry: `next_step`, `resolve_chip`, `directive_for`, `public_data_for`, `progress_for`, `reply_for`. |
| **Rewrite** `backend/app/services/conversation/orchestrator_v2.py` | Per-turn loop: chip-or-interpret → validate → apply → route → reply → persist. |
| **Modify** `backend/app/prompts.py` | `V2_TURN_INTERPRETER_PROMPT`, `V2_ACK_PROMPT`, `V2_STALL_REPLY`, `V2_NUDGE_REPLY`. |
| **Modify** `backend/app/services/conversation/intent_extractor.py` | Add `interpret_turn_v2`, `write_ack`. |
| **Create** `backend/tests/test_canvas_steps.py` | Registry invariants + the chip round-trip regression test. |
| **Rewrite** `backend/tests/test_state_machine_v2.py` | Router, loop, UI surface. |
| **Rewrite** `backend/tests/test_orchestrator_v2.py` | Turn loop, stall, nudge. |
| **Modify** `backend/tests/test_v2_e2e.py` | Drive the real chip labels. |

**Slot vocabulary** (used across tasks — names are fixed here):

| Slot | Type | Set by | Read by |
|---|---|---|---|
| `name` | str | interpreter | `ask_name.done_when` |
| `intro_ack` | bool | `_apply_intro` | `show_intro.done_when` |
| `logo_face` | enum front/back/left/right | chip or interpreter | `_apply_logo_face` |
| `logo_placed` | bool | chip or interpreter | `_apply_logo_placed` |
| `another_logo` | bool | chip or interpreter | `_apply_another_logo` |
| `decor_choice` | enum text/shape | chip or interpreter | `ask_add_decor.done_when` |
| `decor_placed` | bool | chip or interpreter | `decor_adjust.done_when` |
| `more_decor` | bool | chip or interpreter | `_apply_anything_else` |
| `decor_done` | bool | chip | `ask_add_decor.done_when` |
| `quantity` | int | chip or interpreter | `ask_quantity.done_when` |
| `quantity_unsure` | bool | chip | (sales signal only) |
| `email` | str | interpreter | `_apply_email` |
| `purpose` | str | interpreter | `ask_purpose.done_when` |

**Internal, NOT writable by the interpreter:** `logos`, `pending_logo`, `logos_done`, `email_captured`, `lead_id`, `_asked`, `_fail_count`.

---

### Task 1: Step registry records and data

**Files:**
- Create: `backend/app/services/conversation/canvas_steps.py`
- Test: `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: `app.prompts.V2_TOOL_TIPS`, `V2_ASK_NAME`, `V2_ASK_NAME_RETRY`; `ConversationState`.
- Produces: `Chip(label: str, fields: dict)`; `Step(...)`; `REGISTRY: tuple[Step, ...]`; `MAX_LOGOS: int`; `by_id(state) -> Step | None`; `WRITABLE_SLOTS: frozenset[str]`; `SLOT_ENUMS: dict[str, frozenset]`. Apply hooks land in Task 4 — `apply=None` everywhere for now.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_canvas_steps.py
from app.services.conversation import canvas_steps as cs
from app.services.conversation.state_machine import ConversationState as S


def test_registry_ids_are_unique_and_are_conversation_states():
    ids = [s.id for s in cs.REGISTRY]
    assert len(ids) == len(set(ids))
    assert all(isinstance(i, S) for i in ids)


def test_registry_declares_the_v2_flow_in_order():
    assert [s.id for s in cs.REGISTRY] == [
        S.ASK_NAME, S.SHOW_INTRO,
        S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO,
        S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE,
        S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE, S.FINALIZE_CANVAS,
    ]


def test_ask_email_precedes_finalize():
    ids = [s.id for s in cs.REGISTRY]
    assert ids.index(S.ASK_EMAIL) < ids.index(S.FINALIZE_CANVAS)


def test_chips_may_set_slots_plus_trusted_flags_the_llm_cannot():
    # Chips are trusted (we authored the label AND its fields), so they may set
    # terminal/annotation flags that are deliberately NOT in the interpreter's
    # writable set — the model must never be able to declare the decor loop over
    # or fake a "not sure".
    allowed = cs.WRITABLE_SLOTS | {"decor_done", "quantity_unsure"}
    for step in cs.REGISTRY:
        for chip in step.chips:
            assert set(chip.fields) <= allowed, f"{step.id}: {chip.label}"


def test_terminal_flags_are_not_interpreter_writable():
    assert "decor_done" not in cs.WRITABLE_SLOTS
    assert "quantity_unsure" not in cs.WRITABLE_SLOTS
    assert "email_captured" not in cs.WRITABLE_SLOTS


def test_tool_steps_carry_a_tip_and_tipless_steps_carry_no_tool():
    for step in cs.REGISTRY:
        assert bool(step.tool) == bool(step.tip), step.id


def test_by_id_round_trips():
    assert cs.by_id(S.ASK_ANOTHER_LOGO).id is S.ASK_ANOTHER_LOGO
    assert cs.by_id(S.OFFER_REFINE) is None      # a shared-tail state v2 doesn't own
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.conversation.canvas_steps'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/conversation/canvas_steps.py
"""The v2 canvas step registry — the single source of truth for the flow.

Each Step declares everything about one step in one literal: its question copy,
its chips (the label AND the fields that label means, together), the slots the
interpreter fills, when the step is satisfied, any effect it needs, and the
canvas tool it hands over.

Declaring a chip's label next to its fields is the point: the old code declared
the label in `v2_public_data` and re-derived its meaning by grepping the string
in `_apply_v2_fields`, and the two silently disagreed ("Yes, another logo" read
as a decline, because "another" contains "no"). Here a chip cannot disagree with
itself.

Adding a step = adding one record here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app import prompts
from app.services.conversation.state_machine import ConversationState as S

MAX_LOGOS = 4

FACES: frozenset[str] = frozenset({"front", "back", "left", "right"})


@dataclass(frozen=True)
class Chip:
    """An offered button: the exact label we ship, and what tapping it means."""
    label: str
    fields: dict


@dataclass(frozen=True)
class Step:
    id: S
    ask: str                                   # format string; ctx = name/persona/intro
    done_when: Callable[[dict], bool]
    ask_retry: str | None = None               # shorter copy when re-asked
    chips: tuple[Chip, ...] = ()
    slots: tuple[str, ...] = ()                # what THIS step asks for; () = ack-only
    apply: Callable[[dict, dict, dict], None] | None = None   # (collected, fields, session)
    tool: str | None = None
    tip: str | None = None
    continuable: bool = False
    auto_open: str | None = None
    show_done: bool = False
    face_target: bool = False                  # directive should carry the logo face


# --- loop helpers -----------------------------------------------------------
# The logo loop is a collection plus a pending item (the shape goal_planner
# already uses for the element deep-dive). Looping is slot-clearing: clearing
# `another_logo` and re-seeding `pending_logo` makes the three logo steps unmet
# again, so the router walks back to them by itself. No back-edges.

def _pending(c: dict) -> dict:
    return c.get("pending_logo") or {}


def _logos_open(c: dict) -> bool:
    return not c.get("logos_done")


REGISTRY: tuple[Step, ...] = (
    Step(
        id=S.ASK_NAME,
        ask=prompts.V2_ASK_NAME,
        ask_retry=prompts.V2_ASK_NAME_RETRY,
        slots=("name",),
        # Task 4 wires apply=_apply_name here (rejects filler — "ok" is not a name).
        done_when=lambda c: bool(c.get("name")),
    ),
    Step(
        id=S.SHOW_INTRO,
        ask="{intro}\n\nReady? Tap continue when you are.",
        continuable=True,
        slots=(),                              # ack-only: any reply satisfies it
        done_when=lambda c: bool(c.get("intro_ack")),
    ),
    Step(
        id=S.ASK_LOGO_PLACEMENT,
        ask=("Great, {name}! Let's add your logo. Which part of the cap should "
             "it go on — front, back, left or right?"),
        chips=(Chip("Front", {"logo_face": "front"}),
               Chip("Back", {"logo_face": "back"}),
               Chip("Left", {"logo_face": "left"}),
               Chip("Right", {"logo_face": "right"})),
        slots=("logo_face",),
        done_when=lambda c: not _logos_open(c) or "face" in _pending(c),
        tool="upload",
        tip=prompts.V2_TOOL_TIPS["upload"],
        # auto_open stays None: the file dialog must not open before the face is
        # answered, or the logo lands on whatever face is already active.
        auto_open=None,
        face_target=True,
    ),
    Step(
        id=S.LOGO_ADJUST,
        ask=("Pop your logo on there — I've opened the picker for you. Once "
             "it's on, drag to move it, pull a corner to resize, or rotate it. "
             "There's a background-removal toggle in the toolbar if you need "
             "it. Press Done when the placement looks right."),
        chips=(Chip("Done", {"logo_placed": True}),),
        slots=("logo_placed",),
        done_when=lambda c: not _logos_open(c) or bool(_pending(c).get("placed")),
        tool="upload",
        tip=prompts.V2_TOOL_TIPS["upload"],
        auto_open="upload",
        show_done=True,
        face_target=True,
    ),
    Step(
        id=S.ASK_ANOTHER_LOGO,
        ask="Locked that in. Would you like to add another logo?",
        chips=(Chip("Yes, another logo", {"another_logo": True}),
               Chip("No, that's it", {"another_logo": False})),
        slots=("another_logo",),
        done_when=lambda c: not _logos_open(c) or c.get("another_logo") is not None,
    ),
    Step(
        id=S.ASK_ADD_DECOR,
        ask="Would you like to add any text or a shape to your design?",
        chips=(Chip("Add text", {"decor_choice": "text"}),
               Chip("Add a shape", {"decor_choice": "shape"}),
               Chip("No, nothing else", {"decor_done": True})),
        slots=("decor_choice",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("decor_choice")),
    ),
    Step(
        id=S.DECOR_ADJUST,
        # reply_for prepends the tip for the tool actually chosen (text vs
        # shape), which is why this copy is only the tail of the sentence.
        ask="Press Done when you're happy with it.",
        chips=(Chip("Done", {"decor_placed": True}),),
        slots=("decor_placed",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("decor_placed")),
        tool="text",                           # overridden per decor_choice in Task 6
        tip=prompts.V2_TOOL_TIPS["text"],
        auto_open="text",
        show_done=True,
        face_target=True,
    ),
    Step(
        id=S.ASK_ANYTHING_ELSE,
        ask="Is that everything, or would you like to add anything else?",
        chips=(Chip("Add something else", {"more_decor": True}),
               Chip("No, that's everything", {"decor_done": True})),
        slots=("more_decor",),
        done_when=lambda c: bool(c.get("decor_done")) or bool(c.get("more_decor")),
    ),
    Step(
        id=S.ASK_QUANTITY,
        ask="How many caps are you after?",
        chips=(Chip("1", {"quantity": 1}),
               Chip("2-11", {"quantity": 2}),
               Chip("12-49", {"quantity": 12}),
               Chip("50-99", {"quantity": 50}),
               Chip("100+", {"quantity": 100}),
               Chip("Not sure", {"quantity": 0, "quantity_unsure": True})),
        slots=("quantity",),
        # Presence, not truthiness: "Not sure" -> 0 is a real answer. The old
        # code gated on `quantity not in (None, "")` while the parser fell back
        # to 0, so ANY input advanced and the re-ask branch was dead code.
        done_when=lambda c: "quantity" in c,
    ),
    Step(
        id=S.ASK_EMAIL,
        ask="What's the best email to send your design preview to?",
        slots=("email",),
        # `email_captured` is set ONLY by _apply_email after a real
        # capture_lead_and_verify, and is not a writable slot — so the
        # interpreter cannot fake it and FINALIZE_CANVAS cannot be reached
        # without a captured lead.
        done_when=lambda c: bool(c.get("email_captured")),
    ),
    Step(
        id=S.ASK_PURPOSE,
        ask="Last thing — if you don't mind me asking, what's the hat for?",
        slots=("purpose",),
        done_when=lambda c: bool(c.get("purpose")),
    ),
    Step(
        id=S.FINALIZE_CANVAS,
        ask="Perfect — putting your design together now…",
        # Terminal: never satisfied, so the router returns it once every earlier
        # step is done. The finalize route (-> GENERATING) resolves it.
        done_when=lambda c: False,
    ),
)

_BY_ID: dict[S, Step] = {s.id: s for s in REGISTRY}


def by_id(state: S) -> Step | None:
    """The Step for a state, or None for a shared-tail state v2 doesn't own."""
    return _BY_ID.get(state)


# Every slot any step asks for. This is the interpreter's writable set: it may
# fill the current step's slot AND any other slot the customer volunteers
# ("logo on the back and 50 caps"), which is where reordering comes from.
# Internal bookkeeping (logos/pending_logo/logos_done/email_captured/_asked) is
# deliberately absent — the interpreter must never write it.
WRITABLE_SLOTS: frozenset[str] = frozenset(
    s for step in REGISTRY for s in step.slots
)

SLOT_ENUMS: dict[str, frozenset[str]] = {
    "logo_face": FACES,
    "decor_choice": frozenset({"text", "shape"}),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/tests/test_canvas_steps.py
git commit -m "feat(canvas-v2): declare the step registry as data"
```

---

### Task 2: The first-unmet router

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Create: `backend/tests/canvas_step_helpers.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `canvas_steps.REGISTRY`, `by_id`, `MAX_LOGOS`.
- Produces: `next_step(collected: dict) -> Step`; `V2_OWNED: frozenset[ConversationState]`;
  `progress_for(step: Step) -> dict`; `progress_v2(state: ConversationState, collected: dict) -> dict`.
- Produces (test helper, imported by Task 4 too — do NOT duplicate it there):
  `canvas_step_helpers.satisfy(collected, step) -> None`,
  `canvas_step_helpers.seed_for(step) -> dict`.

**Third consumer — `sessions.py` (found at Task 2 execution, plan gap):**
`app/api/routes/sessions.py:269` imports `progress_v2` and calls it as
`progress_v2(S.GENERATING, collected)` inside the v2-gated `canvas-finalize`
branch. `GENERATING` is a shared-tail state with **no registry step**. Progress
therefore ships in THIS task (not Task 6) so that route never breaks, and
`progress_v2` keeps its exact current signature — **`sessions.py` needs no
change**.

Replace the whole file's routing section. Keep `V2_OWNED` exported — `orchestrator_v2` and `chat.py` read it.

The backend has **no `conftest.py`** and tests use inline fakes; a plain helper
module imported by both test files matches that convention.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/canvas_step_helpers.py  (NEW — shared by test_state_machine_v2
# and test_canvas_steps; the registry walk is needed by both, so it lives once)
from app.services.conversation import canvas_steps as cs
from app.services.conversation.state_machine import ConversationState as S


def satisfy(c: dict, step) -> None:
    """Minimal mutation to make one step done, mirroring the apply hooks.

    Walks the LONGEST path (one logo, one decoration) so that every step in the
    registry becomes first-unmet in turn — hence decor_choice/decor_placed here
    rather than the decor_done shortcut, which would skip DECOR_ADJUST and
    ASK_ANYTHING_ELSE entirely.
    """
    if step.id is S.ASK_NAME:
        c["name"] = "Sam"
    elif step.id is S.SHOW_INTRO:
        c["intro_ack"] = True
    elif step.id is S.ASK_LOGO_PLACEMENT:
        c["pending_logo"] = {"face": "front"}
    elif step.id is S.LOGO_ADJUST:
        c.setdefault("pending_logo", {})["placed"] = True
    elif step.id is S.ASK_ANOTHER_LOGO:
        c["logos_done"] = True
        c["pending_logo"] = None
    elif step.id is S.ASK_ADD_DECOR:
        c["decor_choice"] = "text"
    elif step.id is S.DECOR_ADJUST:
        c["decor_placed"] = True
    elif step.id is S.ASK_ANYTHING_ELSE:
        c["decor_done"] = True
    elif step.id is S.ASK_QUANTITY:
        c["quantity"] = 12
    elif step.id is S.ASK_EMAIL:
        c["email_captured"] = True
    elif step.id is S.ASK_PURPOSE:
        c["purpose"] = "team caps"


def seed_for(step) -> dict:
    """A collected where `step` is the first unmet step."""
    c = {"flow_mode": "canvas"}
    for s in cs.REGISTRY:
        if s.id is step.id:
            return c
        satisfy(c, s)
    raise AssertionError(f"unreachable step {step.id}")
```

```python
# backend/tests/test_state_machine_v2.py  (replace the routing tests)
import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S
from tests.canvas_step_helpers import satisfy


def _seed(**over):
    c = {"flow_mode": "canvas"}
    c.update(over)
    return c


def test_empty_session_asks_name():
    assert v2.next_step(_seed()).id is S.ASK_NAME


def test_name_then_intro_then_logo_face():
    assert v2.next_step(_seed(name="Sam")).id is S.SHOW_INTRO
    assert v2.next_step(_seed(name="Sam", intro_ack=True)).id is S.ASK_LOGO_PLACEMENT


def test_face_answered_moves_to_adjust():
    c = _seed(name="Sam", intro_ack=True, pending_logo={"face": "back"})
    assert v2.next_step(c).id is S.LOGO_ADJUST


def test_placed_moves_to_another_logo():
    c = _seed(name="Sam", intro_ack=True, pending_logo={"face": "back", "placed": True})
    assert v2.next_step(c).id is S.ASK_ANOTHER_LOGO


def test_logo_loop_reopens_placement_when_another_wanted():
    # "yes" clears another_logo and re-seeds pending_logo (Task 4's apply);
    # the router must walk BACK to the face question on its own.
    c = _seed(name="Sam", intro_ack=True, logos=[{"face": "back", "placed": True}],
              pending_logo={})
    assert v2.next_step(c).id is S.ASK_LOGO_PLACEMENT


def test_logos_done_falls_through_to_decor():
    c = _seed(name="Sam", intro_ack=True, logos=[{"face": "back", "placed": True}],
              pending_logo=None, logos_done=True)
    assert v2.next_step(c).id is S.ASK_ADD_DECOR


def test_quantity_zero_counts_as_answered():
    # "Not sure" -> 0 is a real answer; presence, not truthiness.
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True, quantity=0)
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_missing_quantity_re_asks():
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True)
    assert v2.next_step(c).id is S.ASK_QUANTITY


def test_finalize_unreachable_without_email_captured():
    # The load-bearing invariant. Every earlier slot filled, email not captured.
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True,
              quantity=50, purpose="team caps", email="sam@example.com")
    assert v2.next_step(c).id is S.ASK_EMAIL


def test_finalize_reached_when_everything_done():
    c = _seed(name="Sam", intro_ack=True, logos_done=True, decor_done=True,
              quantity=50, email_captured=True, purpose="team caps")
    assert v2.next_step(c).id is S.FINALIZE_CANVAS


def test_router_walks_every_step_in_declared_order():
    # Exhaustive order guarantee: satisfying each step in turn must yield the
    # next one, and never a step positioned after an unmet one.
    c = _seed()
    for step in cs.REGISTRY:
        assert v2.next_step(c).id is step.id, f"expected {step.id}"
        satisfy(c, step)


def test_v2_owned_is_the_registry_plus_greeting():
    assert v2.V2_OWNED == frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}
    assert S.OFFER_REFINE not in v2.V2_OWNED     # shared tail stays v1's


def test_progress_collapses_loop_steps_onto_their_anchor():
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    for sid in (S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 3, "total": total}
    for sid in (S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        assert v2.progress_for(cs.by_id(sid)) == {"step": 4, "total": total}
    assert v2.progress_for(cs.by_id(S.FINALIZE_CANVAS)) == {"step": total, "total": total}


def test_progress_v2_is_state_keyed_and_survives_a_tail_state():
    # sessions.py's canvas-finalize route calls this with GENERATING, which has
    # NO registry step. It must report "complete", not explode.
    total = v2.progress_for(cs.by_id(S.ASK_NAME))["total"]
    assert v2.progress_v2(S.GENERATING, {}) == {"step": total, "total": total}
    assert v2.progress_v2(S.ASK_QUANTITY, {}) == {"step": 5, "total": total}
```

Note: `test_router_never_returns_a_step_after_an_unmet_one` skips `DECOR_ADJUST` and `ASK_ANYTHING_ELSE` via `_satisfy` setting `decor_done` at `ASK_ADD_DECOR` — that is correct, it mirrors the "No, nothing else" path.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: FAIL — `AttributeError: module 'app.services.conversation.state_machine_v2' has no attribute 'next_step'`

- [ ] **Step 3: Write minimal implementation**

Replace `state_machine_v2.py` top-to-bottom with this (the rest of the module's
functions arrive in Task 6):

```python
# backend/app/services/conversation/state_machine_v2.py
"""v2 canvas routing — a generic engine over the canvas_steps registry.

Routing is first-unmet resolution: return the first step whose done_when(collected)
is False. That is a pure function of `collected`, so it is exhaustively testable
with plain dicts and needs no LLM, no mocking and no Supabase.

Flexibility comes from slot-filling, not from anyone choosing a route: if the
interpreter banks a volunteered answer ("logo on the back and 50 caps"), the
step that asks for it is already done, so the router simply doesn't return it.

Order is enforced inherently — the router never returns any step positioned
after an unmet one — which is why there is no separate "gate" concept. The
load-bearing invariant (no FINALIZE_CANVAS without email_captured) holds because
ask_email precedes finalize_canvas and its done_when reads `email_captured`,
which only _apply_email sets and the interpreter cannot write.
"""
from __future__ import annotations

from app.services.conversation import canvas_steps as cs
from app.services.conversation.canvas_steps import MAX_LOGOS, Step  # noqa: F401 re-export
from app.services.conversation.state_machine import ConversationState as S

# Every state a v2 turn may rest on. GREETING is the kickoff (no registry step:
# it greets and advances without ingesting the turn). Anything NOT here is a
# shared tail state v1 owns — orchestrator_v2 delegates those turns to v1.
V2_OWNED: frozenset[S] = frozenset({s.id for s in cs.REGISTRY}) | {S.GREETING}


def next_step(collected: dict) -> Step:
    """The first step whose done_when is False. FINALIZE_CANVAS is terminal
    (done_when is always False), so this always returns a Step."""
    for step in cs.REGISTRY:
        if not step.done_when(collected):
            return step
    return cs.REGISTRY[-1]


# The customer-facing question steps, in order — the loop/adjust steps collapse
# onto their loop's anchor so "Step X of N" stays steady during a deep-dive.
_PROGRESS_ANCHORS: dict[S, S] = {
    S.LOGO_ADJUST: S.ASK_LOGO_PLACEMENT,
    S.ASK_ANOTHER_LOGO: S.ASK_LOGO_PLACEMENT,
    S.DECOR_ADJUST: S.ASK_ADD_DECOR,
    S.ASK_ANYTHING_ELSE: S.ASK_ADD_DECOR,
}
_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
    S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE,
]


def progress_for(step: Step) -> dict:
    total = len(_PROGRESS_PATH)
    anchor = _PROGRESS_ANCHORS.get(step.id, step.id)
    if anchor in _PROGRESS_PATH:
        return {"step": _PROGRESS_PATH.index(anchor) + 1, "total": total}
    return {"step": total, "total": total}      # finalize + tail -> complete


def progress_v2(state: S, collected: dict | None = None) -> dict:
    """State-keyed wrapper, kept at its original signature for
    `sessions.py`'s canvas-finalize route — which calls it with GENERATING, a
    shared-tail state that has no registry step (-> "complete")."""
    step = cs.by_id(state)
    if step is None:
        total = len(_PROGRESS_PATH)
        return {"step": total, "total": total}
    return progress_for(step)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): route by first-unmet resolution over the registry"
```

---

### Task 3: Deterministic chip resolution + the round-trip regression test

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: `canvas_steps.REGISTRY`, `state_machine_v2.next_step`.
- Produces: `resolve_chip(step: Step, message: str) -> dict | None` — the chip's fields (a copy), or `None` if the message isn't one of this step's chips.

This task ships the regression test for the live bug.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_canvas_steps.py  (append)
import pytest

from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


def _all_chips():
    return [(s, ch) for s in cs.REGISTRY for ch in s.chips]


@pytest.mark.parametrize(
    "step,chip", _all_chips(), ids=lambda v: getattr(v, "label", getattr(v, "id", ""))
)
def test_every_offered_chip_is_understood(step, chip):
    """THE regression test for the live bug.

    "Yes, another logo" is a string WE generated in the chip list and shipped to
    the browser, which handed it straight back — and the old code grepped it to
    find out what we had meant, reading "another" as "no". Enumerated from the
    registry, so a step added later is covered the moment it is declared.
    """
    fields = v2.resolve_chip(step, chip.label)
    assert fields == chip.fields, f"{step.id}: {chip.label!r} did not round-trip"


def test_the_exact_bug_yes_another_logo_is_not_a_decline():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "Yes, another logo") == {"another_logo": True}
    assert v2.resolve_chip(step, "No, that's it") == {"another_logo": False}


def test_chip_match_is_case_and_whitespace_insensitive():
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)
    assert v2.resolve_chip(step, "  front  ") == {"logo_face": "front"}


def test_free_text_is_not_a_chip():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "yeah go on then") is None


def test_a_stale_chip_from_another_step_does_not_match():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    assert v2.resolve_chip(step, "Add text") is None


def test_resolve_chip_returns_a_copy_not_the_registry_dict():
    step = cs.by_id(S.ASK_ANOTHER_LOGO)
    got = v2.resolve_chip(step, "Yes, another logo")
    got["another_logo"] = "mutated"
    assert step.chips[0].fields == {"another_logo": True}
```

The companion assertion — that a chip also *advances* the flow — needs Task 4's
`apply` hooks to exist, so it lands in Task 4 rather than being faked with an
xfail here.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'resolve_chip'`

- [ ] **Step 3: Write minimal implementation**

Append to `state_machine_v2.py`:

```python
def _norm(s: str) -> str:
    return (s or "").strip().casefold()


def resolve_chip(step: Step, message: str) -> dict | None:
    """The fields for an offered chip, or None if `message` isn't one of them.

    A chip tap is not natural language: we generated the label in this registry
    and shipped it to the browser, which sent it straight back. Matching it is an
    identity lookup on a closed set we own — no model, no latency, no failure
    mode. Only the CURRENT step's chips match; a stale chip tapped on an older
    message falls through to the interpreter, which reads it in context.
    """
    target = _norm(message)
    for chip in step.chips:
        if _norm(chip.label) == target:
            return dict(chip.fields)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: PASS — every chip in the registry round-trips

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_canvas_steps.py
git commit -m "feat(canvas-v2): resolve chips deterministically + registry round-trip test

Regression test for the live bug: 'Yes, another logo' read as a decline
because is_negative substring-matches and 'another' contains 'no'. The test
enumerates the registry, so a chip added later is covered when declared."
```

---

### Task 4: The `apply` effect hooks

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py`
- Test: `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: `leads.capture_lead_and_verify(session: dict, collected: dict, email: str) -> tuple[str | None, bool]`.
- Produces: module-level `_apply_name`, `_apply_intro`, `_apply_logo_face`, `_apply_logo_placed`, `_apply_another_logo`, `_apply_anything_else`, `_apply_email`, each `(collected, fields, session) -> None`; wired onto their `Step`s. Plus `_plausible_name` / `_NAME_FILLER`, ported from `orchestrator_v2` at `44e8eda`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_canvas_steps.py  (append)

# Shared with test_state_machine_v2 — created in Task 2, do NOT re-declare here.
from tests.canvas_step_helpers import seed_for


@pytest.mark.parametrize(
    "step,chip", _all_chips(), ids=lambda v: getattr(v, "label", getattr(v, "id", ""))
)
def test_every_offered_chip_makes_progress(step, chip):
    """Understanding a chip is not enough — it must also move the flow. This is
    the half of the round-trip test that needs the apply hooks."""
    c = seed_for(step)
    assert v2.next_step(c).id is step.id          # precondition: we're on it
    fields = v2.resolve_chip(step, chip.label)
    c.update(fields)
    if step.apply:
        step.apply(c, dict(fields), {})
    assert v2.next_step(c).id is not step.id, f"{step.id}: {chip.label!r} did not advance"


@pytest.mark.parametrize("filler", ["ok", "Okay", "yes", "hi there", "sure", "!!", "done"])
def test_filler_never_becomes_a_name(filler):
    """Regression (44e8eda): "ok" became a customer's name in a live session.
    The interpreter proposes; this deterministic guard disposes."""
    c = {"name": filler}                      # as the pre-apply merge leaves it
    cs.by_id(S.ASK_NAME).apply(c, {"name": filler}, {})
    assert "name" not in c
    assert not cs.by_id(S.ASK_NAME).done_when(c)      # -> re-asks


@pytest.mark.parametrize("real", ["Sam", "satish", "Mary-Jane", "Jo Smith"])
def test_a_real_name_is_kept(real):
    c = {"name": real}
    cs.by_id(S.ASK_NAME).apply(c, {"name": real}, {})
    assert c["name"] == real
    assert cs.by_id(S.ASK_NAME).done_when(c)


def test_a_name_is_trimmed_to_first_line_and_60_chars():
    c = {}
    cs.by_id(S.ASK_NAME).apply(c, {"name": "Sam\nsecond line"}, {})
    assert c["name"] == "Sam"


def test_intro_ack_is_set_by_any_reply():
    c = {}
    cs.by_id(S.SHOW_INTRO).apply(c, {}, {})
    assert c["intro_ack"] is True


def test_logo_face_lands_on_the_pending_logo():
    c = {}
    cs.by_id(S.ASK_LOGO_PLACEMENT).apply(c, {"logo_face": "back"}, {})
    assert c["pending_logo"] == {"face": "back"}


def test_another_logo_yes_banks_the_logo_and_reopens_the_loop():
    c = {"pending_logo": {"face": "back", "placed": True}, "another_logo": True}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": True}, {})
    assert c["logos"] == [{"face": "back", "placed": True}]
    assert c["pending_logo"] == {}
    assert "another_logo" not in c            # cleared -> the loop re-asks
    assert not c.get("logos_done")
    assert v2.next_step(c | {"name": "Sam", "intro_ack": True}).id is S.ASK_LOGO_PLACEMENT


def test_another_logo_no_banks_the_logo_and_closes_the_loop():
    c = {"pending_logo": {"face": "back", "placed": True}, "another_logo": False}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": False}, {})
    assert c["logos"] == [{"face": "back", "placed": True}]
    assert c["pending_logo"] is None
    assert c["logos_done"] is True


def test_logo_loop_stops_at_max_logos_even_when_more_are_wanted():
    c = {"logos": [{"face": f} for f in ("front", "back", "left")],
         "pending_logo": {"face": "right", "placed": True}}
    cs.by_id(S.ASK_ANOTHER_LOGO).apply(c, {"another_logo": True}, {})
    assert len(c["logos"]) == cs.MAX_LOGOS
    assert c["logos_done"] is True             # capped
    assert c["pending_logo"] is None


def test_anything_else_yes_clears_the_decor_slots():
    c = {"decor_choice": "text", "decor_placed": True, "more_decor": True}
    cs.by_id(S.ASK_ANYTHING_ELSE).apply(c, {"more_decor": True}, {})
    assert "decor_choice" not in c and "decor_placed" not in c and "more_decor" not in c


def test_email_apply_captures_the_lead(monkeypatch):
    seen = {}

    def _fake(session, collected, email):
        seen.update(session=session, email=email)
        return "lead-1", True

    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify", _fake)
    c = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "sam@example.com"}, {"id": "s1"})
    assert c["email_captured"] is True and c["lead_id"] == "lead-1"
    assert seen["email"] == "sam@example.com"


def test_email_apply_does_not_capture_when_verification_fails(monkeypatch):
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: (None, False))
    c = {}
    cs.by_id(S.ASK_EMAIL).apply(c, {"email": "sam@example.com"}, {"id": "s1"})
    assert not c.get("email_captured")         # -> ask_email re-asks itself
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: FAIL — `TypeError: 'NoneType' object is not callable` on
`cs.by_id(S.SHOW_INTRO).apply(...)` (every `apply` is still `None`)

- [ ] **Step 3: Write minimal implementation**

Add to `canvas_steps.py` above `REGISTRY`:

```python
from app.services import leads as leads_service
from app.services.conversation import intent_extractor as ie

# Replies that are plainly not a name. Ported verbatim from orchestrator_v2
# (commit 44e8eda): the old ASK_NAME step took the customer's first message
# verbatim, so "ok" became their name and the bot said "Great, ok! Let's add
# your logo." The interpreter is better at this than the old keyword ingest was,
# but it is still a model — this deterministic guard is what GUARANTEES the bug
# cannot come back. The model proposes; the guard disposes; done_when re-asks.
_NAME_FILLER = frozenset({
    "ok", "okay", "k", "yes", "yeah", "yep", "yup", "no", "nope", "nah",
    "sure", "hi", "hello", "hey", "hiya", "thanks", "ta", "cool", "great",
    "continue", "next", "done", "start", "go", "ready", "please",
})


def _plausible_name(candidate: str) -> bool:
    if not candidate or "?" in candidate:
        return False
    if ie._is_greeting_only(candidate):
        return False
    if not any(ch.isalpha() for ch in candidate):
        return False
    return candidate.lower().strip(" .!,'\"") not in _NAME_FILLER


def _apply_name(c: dict, f: dict, s: dict) -> None:
    name = (f.get("name") or "").strip().split("\n")[0][:60]
    if _plausible_name(name):
        c["name"] = name
    else:
        c.pop("name", None)      # never let filler satisfy done_when


def _apply_intro(c: dict, f: dict, s: dict) -> None:
    # Any reply to the intro is an acknowledgement — there is nothing to parse,
    # which is why show_intro declares no slots and never calls the model.
    c["intro_ack"] = True


def _apply_logo_face(c: dict, f: dict, s: dict) -> None:
    face = f.get("logo_face")
    if not face:
        return
    if c.get("pending_logo") is None:
        c["pending_logo"] = {}
    c["pending_logo"]["face"] = face


def _apply_logo_placed(c: dict, f: dict, s: dict) -> None:
    if f.get("logo_placed") and c.get("pending_logo") is not None:
        c["pending_logo"]["placed"] = True


def _apply_another_logo(c: dict, f: dict, s: dict) -> None:
    """The entire loop mechanism, declared next to the step it belongs to.

    Bank the finished logo, then either re-seed a pending one (which makes the
    three logo steps unmet again, so the router walks back by itself) or close
    the loop. Looping is slot-clearing.
    """
    logos = c.setdefault("logos", [])
    pending = c.get("pending_logo")
    if pending:
        logos.append(pending)
    if f.get("another_logo") and len(logos) < MAX_LOGOS:
        c["pending_logo"] = {}
        c.pop("another_logo", None)
    else:
        c["pending_logo"] = None
        c["logos_done"] = True


def _apply_anything_else(c: dict, f: dict, s: dict) -> None:
    if f.get("more_decor"):
        for k in ("decor_choice", "decor_placed", "more_decor"):
            c.pop(k, None)


def _apply_email(c: dict, f: dict, s: dict) -> None:
    """Double opt-in capture. `email_captured` is set ONLY here, and only after a
    real capture — which is what makes FINALIZE_CANVAS unreachable without a
    lead. On failure nothing is set, so ask_email re-asks itself."""
    email = f.get("email")
    if not email:
        return
    lead_id, ok = leads_service.capture_lead_and_verify(s, c, email)
    if lead_id:
        c["lead_id"] = lead_id
    if ok:
        c["email_captured"] = True
```

Then wire them onto the records: `apply=_apply_name` on `ASK_NAME`,
`_apply_intro` on `SHOW_INTRO`, `_apply_logo_face` on `ASK_LOGO_PLACEMENT`,
`_apply_logo_placed` on `LOGO_ADJUST`, `_apply_another_logo` on
`ASK_ANOTHER_LOGO`, `_apply_anything_else` on `ASK_ANYTHING_ELSE`,
`_apply_email` on `ASK_EMAIL`.

`orchestrator_v2` does `collected.update(fields)` **before** calling `apply`, so
`_apply_name` must actively `pop` an implausible name rather than merely decline
to set it — the merge will already have written it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_canvas_steps.py -q`
Expected: PASS — all chips now round-trip *and* progress, no xfails

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/tests/test_canvas_steps.py
git commit -m "feat(canvas-v2): add apply hooks (logo loop, email capture, intro ack)"
```

---

### Task 5: Slot validation + the LLM interpreter

**Files:**
- Modify: `backend/app/prompts.py`
- Modify: `backend/app/services/conversation/intent_extractor.py`
- Test: `backend/tests/test_intent_extractor_v2.py` (create)

**Interfaces:**
- Consumes: `_complete`, `_parse_json`, `_safe_collected`, `_has_llm`; `canvas_steps.WRITABLE_SLOTS`, `SLOT_ENUMS`.
- Produces: `validate_fields(raw: dict) -> dict`; `async interpret_turn_v2(step, message: str, collected: dict) -> dict`; `LLMUnavailable(Exception)`.

`interpret_turn_v2` raises `LLMUnavailable` when there is no key or the call fails — it never falls back to keywords (Task 8 turns that into a stall).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_intent_extractor_v2.py
import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation.state_machine import ConversationState as S


def test_validate_drops_undeclared_slots():
    got = ie.validate_fields({"name": "Sam", "email_captured": True, "logos": ["x"]})
    assert got == {"name": "Sam"}          # internal keys are not writable


def test_validate_enforces_enums():
    assert ie.validate_fields({"logo_face": "back"}) == {"logo_face": "back"}
    assert ie.validate_fields({"logo_face": "brim"}) == {}
    assert ie.validate_fields({"decor_choice": "sticker"}) == {}


def test_validate_coerces_quantity_to_int_or_drops_it():
    assert ie.validate_fields({"quantity": 50}) == {"quantity": 50}
    assert ie.validate_fields({"quantity": "50"}) == {"quantity": 50}
    assert ie.validate_fields({"quantity": "loads"}) == {}


@pytest.mark.asyncio
async def test_interpret_raises_when_no_key(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", False)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "go on then", {})


@pytest.mark.asyncio
async def test_interpret_raises_when_the_call_fails(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def _boom(*a, **k):
        raise RuntimeError("429")

    monkeypatch.setattr(ie, "_complete", _boom)
    with pytest.raises(ie.LLMUnavailable):
        await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "go on then", {})


@pytest.mark.asyncio
async def test_interpret_returns_validated_fields(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)

    async def _ok(*a, **k):
        return '{"fields": {"another_logo": true, "quantity": 50, "logos": ["x"]}}'

    monkeypatch.setattr(ie, "_complete", _ok)
    got = await ie.interpret_turn_v2(cs.by_id(S.ASK_ANOTHER_LOGO), "yeah and 50 caps", {})
    # Volunteered quantity is banked (that is where reordering comes from);
    # the internal `logos` key is dropped.
    assert got == {"another_logo": True, "quantity": 50}


@pytest.mark.asyncio
async def test_interpret_never_sends_pii(monkeypatch):
    monkeypatch.setattr(ie, "_has_llm", True)
    seen = {}

    async def _spy(prompt, **k):
        seen["prompt"] = prompt
        return '{"fields": {}}'

    monkeypatch.setattr(ie, "_complete", _spy)
    await ie.interpret_turn_v2(cs.by_id(S.ASK_QUANTITY), "50",
                               {"name": "Sam", "email": "sam@example.com"})
    assert "sam@example.com" not in seen["prompt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_intent_extractor_v2.py -q`
Expected: FAIL — `AttributeError: module 'app.services.conversation.intent_extractor' has no attribute 'validate_fields'`

- [ ] **Step 3: Write minimal implementation**

Append to `prompts.py`:

```python
V2_TURN_INTERPRETER_PROMPT = """You read ONE customer message in a guided cap-design chat and turn it into structured fields. You do NOT decide what happens next.

We just asked the customer:
{ask}

The answer to that question belongs in: {asked_slots}

Fields you may fill (fill ONLY what the customer clearly says — never guess):
{slot_docs}

Rules:
- The customer's answer to our question goes in {asked_slots}.
- If they ALSO volunteer something else (e.g. "logo on the back and 50 caps"), fill those fields too.
- Omit any field the customer did not clearly express. Omitting is always correct when unsure.
- Never invent a quantity. "not sure" means quantity 0.

Reply with JSON only: {{"fields": {{...}}}}

Customer message:
{message}
"""

V2_STALL_REPLY = (
    "Sorry — I didn't quite catch that. Could you say it once more?"
)

V2_NUDGE_REPLY = (
    "Sorry, I'm having trouble reading that one. Tap one of the buttons below "
    "and we'll keep moving."
)

V2_ACK_PROMPT = """You are {persona}, a friendly cap-design assistant.

Write ONE short, warm sentence acknowledging what the customer just said. Then stop.

Do NOT ask a question. Do NOT give instructions. Do NOT mention buttons or tools — that copy is added separately.

Customer said: {message}
We understood: {fields}

Reply with the sentence only.
"""
```

Append to `intent_extractor.py`:

```python
class LLMUnavailable(RuntimeError):
    """Haiku is unreachable (no key, or the call failed).

    v2 has no keyword fallback by design: a wrong field corrupts the design, so
    the turn stalls rather than guessing. See orchestrator_v2.
    """


def validate_fields(raw: dict) -> dict:
    """Keep only declared, well-typed slots. The containment boundary: a
    hallucinated or internal key can never reach `collected`."""
    from app.services.conversation import canvas_steps as cs  # noqa: PLC0415 cycle

    out: dict = {}
    for key, val in (raw or {}).items():
        if key not in cs.WRITABLE_SLOTS:
            continue
        allowed = cs.SLOT_ENUMS.get(key)
        if allowed is not None:
            if isinstance(val, str) and val.lower() in allowed:
                out[key] = val.lower()
            continue
        if key == "quantity":
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                pass
            continue
        out[key] = val
    return out


_SLOT_DOCS: dict[str, str] = {
    "name": "name (string) — the customer's first name",
    "intro_ack": "intro_ack (bool)",
    "logo_face": "logo_face (one of: front, back, left, right)",
    "logo_placed": "logo_placed (bool) — true when they say the logo looks right / they're done",
    "another_logo": "another_logo (bool) — true if they want to add ANOTHER logo",
    "decor_choice": "decor_choice (one of: text, shape)",
    "decor_placed": "decor_placed (bool) — true when they're happy with it",
    "more_decor": "more_decor (bool) — true if they want to add something else",
    "quantity": "quantity (integer) — how many caps; 0 means not sure",
    "email": "email (string)",
    "purpose": "purpose (string) — what the hat is for",
}


async def interpret_turn_v2(step, message: str, collected: dict) -> dict:
    """Structured fields from one free-text turn. Raises LLMUnavailable rather
    than guessing — v2 stalls instead of falling back to keywords."""
    from app.services.conversation import canvas_steps as cs  # noqa: PLC0415 cycle

    if not _has_llm:
        raise LLMUnavailable("no anthropic api key")
    prompt = prompts.V2_TURN_INTERPRETER_PROMPT.format(
        ask=step.ask,
        asked_slots=", ".join(step.slots) or "(nothing)",
        slot_docs="\n".join(f"- {_SLOT_DOCS[s]}" for s in sorted(cs.WRITABLE_SLOTS)
                            if s in _SLOT_DOCS),
        message=message,
    )
    try:
        raw = await _complete(prompt, max_tokens=300)
    except Exception as exc:  # noqa: BLE001 — any SDK error is "unavailable"
        log.warning("v2_interpret_failed", err=str(exc))
        raise LLMUnavailable(str(exc)) from exc
    return validate_fields(_parse_json(raw).get("fields") or {})


async def write_ack(persona: str, message: str, fields: dict) -> str:
    """One warm sentence acknowledging the turn, or "" if unavailable.

    Best-effort by design: the instructions are concatenated from the registry
    afterwards, so an outage makes the bot terse, never uninstructive."""
    if not _has_llm:
        return ""
    try:
        text = await _complete(
            prompts.V2_ACK_PROMPT.format(
                persona=persona, message=message, fields=json.dumps(fields)
            ),
            max_tokens=80,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("v2_ack_failed", err=str(exc))
        return ""
    return _strip_meta_preamble(repair_mojibake(text)).strip()
```

Note the prompt is built from `step.ask` + `message` + slot docs only — `collected` is never interpolated, which is why the PII test passes.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_intent_extractor_v2.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/intent_extractor.py backend/tests/test_intent_extractor_v2.py
git commit -m "feat(canvas-v2): LLM slot interpreter with validation, no keyword fallback"
```

---

### Task 6: UI surface derived from the registry

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `progress_for` (already shipped in Task 2 — do NOT re-implement it).
- Produces: `directive_for(step, collected) -> dict`; `public_data_for(step, collected) -> dict`; `canvas_directive(state, collected) -> dict | None` (kept for `chat.py`/tests that pass a state).

The response contract is frozen — the frontend must not change.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_state_machine_v2.py  (append)

def test_tool_steps_hand_over_exactly_one_tool():
    d = v2.directive_for(cs.by_id(S.LOGO_ADJUST), {"pending_logo": {"face": "back"}})
    assert d["allowed_tools"] == ["upload"]
    assert d["target_face"] == "back"
    assert d["auto_open"] == "upload"
    assert d["show_done"] is True


def test_face_question_enables_upload_but_does_not_auto_open_it():
    # Conflating these was a shipped bug: the file dialog opened before the face
    # was answered, so the logo landed on whatever face was already active.
    d = v2.directive_for(cs.by_id(S.ASK_LOGO_PLACEMENT), {})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] is None
    assert d["target_face"] == "front"          # default until answered


def test_every_other_owned_step_locks_all_tools():
    # A null directive means "not a v2 turn" and makes the frontend fall back to
    # v1's whole-rail gating + status strip, which showed "Design locked in —
    # finishing up" MID-design. Every owned step must emit a directive.
    for step in cs.REGISTRY:
        d = v2.directive_for(step, {})
        assert d is not None, step.id
        if step.tool is None:
            assert d["allowed_tools"] == [], step.id


def test_decor_directive_follows_the_chosen_tool():
    assert v2.directive_for(cs.by_id(S.DECOR_ADJUST), {"decor_choice": "shape"})["allowed_tools"] == ["shape"]
    assert v2.directive_for(cs.by_id(S.DECOR_ADJUST), {"decor_choice": "text"})["allowed_tools"] == ["text"]


def test_canvas_directive_is_none_for_a_shared_tail_state():
    assert v2.canvas_directive(S.OFFER_REFINE, {}) is None


def test_public_data_chips_come_from_the_registry():
    d = v2.public_data_for(cs.by_id(S.ASK_ANOTHER_LOGO), {})
    assert d["options"] == ["Yes, another logo", "No, that's it"]


def test_public_data_marks_the_intro_continuable_and_finalize_triggering():
    assert v2.public_data_for(cs.by_id(S.SHOW_INTRO), {})["continuable"] is True
    assert v2.public_data_for(cs.by_id(S.FINALIZE_CANVAS), {})["trigger_finalize"] is True


def test_public_data_carries_progress():
    # progress_for itself is covered in Task 2; this asserts it is wired in.
    assert v2.public_data_for(cs.by_id(S.ASK_QUANTITY), {})["progress"]["step"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'directive_for'`

- [ ] **Step 3: Write minimal implementation**

Append to `state_machine_v2.py` (`_PROGRESS_PATH` / `_PROGRESS_ANCHORS` /
`progress_for` already exist from Task 2 — do not redeclare them):

```python
from app import prompts


def _face(collected: dict) -> str:
    face = (collected.get("pending_logo") or {}).get("face")
    return face if face in cs.FACES else "front"


def _decor_tool(collected: dict) -> str:
    return "shape" if collected.get("decor_choice") == "shape" else "text"


def directive_for(step: Step, collected: dict) -> dict:
    """The canvas-control blob for a step. EVERY owned step returns one: the
    tool steps hand over their single tool, every other step locks all tools
    explicitly. A null directive means "not a v2 turn" and makes the frontend
    fall back to v1's whole-rail gating + status strip — which showed "Design
    locked in — finishing up" mid-design."""
    if step.tool is None:
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False}
    tool = _decor_tool(collected) if step.id is S.DECOR_ADJUST else step.tool
    return {
        "allowed_tools": [tool],
        "target_face": _face(collected) if step.face_target else None,
        "auto_open": tool if step.auto_open else None,
        "instructions": prompts.V2_TOOL_TIPS[tool],
        "show_done": step.show_done,
    }


def canvas_directive(state: S, collected: dict) -> dict | None:
    """State-keyed wrapper: None for a shared-tail state v2 doesn't own."""
    step = cs.by_id(state)
    return directive_for(step, collected) if step else None


def public_data_for(step: Step, collected: dict) -> dict:
    data: dict = {}
    if step.chips:
        data["options"] = [c.label for c in step.chips]
    if step.continuable:
        data["continuable"] = True
    if step.id is S.FINALIZE_CANVAS:
        data["trigger_finalize"] = True
    data["canvas"] = directive_for(step, collected)
    data["progress"] = progress_for(step)
    return data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: PASS (20 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): derive directive, chips and progress from the registry"
```

---

### Task 7: Reply assembly

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Produces: `reply_for(step, collected, *, persona: str, intro: str, ack: str = "") -> str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_state_machine_v2.py  (append)

def _reply(step_id, collected=None, **kw):
    kw.setdefault("persona", "Ricardo")
    kw.setdefault("intro", "Welcome!")
    return v2.reply_for(cs.by_id(step_id), collected or {}, **kw)


def test_reply_appends_the_tool_tip_verbatim():
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"})
    assert prompts.V2_TOOL_TIPS["upload"] in out


def test_the_ack_can_never_paraphrase_the_tip_away():
    out = _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"},
                 ack="Nice — the back's a great spot.")
    assert out.startswith("Nice — the back's a great spot.")
    assert prompts.V2_TOOL_TIPS["upload"] in out       # concatenated, not generated


def test_reply_falls_back_to_bare_copy_without_an_ack():
    out = _reply(S.ASK_QUANTITY)
    assert out == "How many caps are you after?"


def test_reply_interpolates_name_persona_and_intro():
    assert "Sam" in _reply(S.ASK_LOGO_PLACEMENT, {"name": "Sam"})
    assert "Ricardo" in _reply(S.ASK_NAME, persona="Ricardo")
    assert "Welcome!" in _reply(S.SHOW_INTRO, intro="Welcome!")


def test_reply_uses_retry_copy_once_the_step_has_been_asked():
    first = _reply(S.ASK_NAME)
    again = _reply(S.ASK_NAME, {"_asked": ["ask_name"]})
    assert first != again
    assert again == prompts.V2_ASK_NAME_RETRY


def test_decor_adjust_reply_uses_the_chosen_tool_tip():
    out = _reply(S.DECOR_ADJUST, {"decor_choice": "shape"})
    assert prompts.V2_TOOL_TIPS["shape"] in out
    assert prompts.V2_TOOL_TIPS["text"] not in out


def test_reply_defaults_the_name_when_unknown():
    assert "there" in _reply(S.ASK_LOGO_PLACEMENT, {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: FAIL — `AttributeError: ... has no attribute 'reply_for'`

- [ ] **Step 3: Write minimal implementation**

Append to `state_machine_v2.py`:

```python
def reply_for(step: Step, collected: dict, *, persona: str, intro: str,
              ack: str = "") -> str:
    """ack (LLM, best-effort) + the step's copy + its tool tip (verbatim).

    The tip is concatenated from the registry and never passes through a model,
    so a warm paraphrase cannot drop "tap the highlighted button" and leave the
    customer stuck. Without an ack the reply is simply the scripted copy."""
    if step.id is S.DECOR_ADJUST:
        body = f"{prompts.V2_TOOL_TIPS[_decor_tool(collected)]} Press Done when you're happy with it."
    else:
        asked = step.ask_retry and step.id.value in (collected.get("_asked") or [])
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
        )
        if step.tip and step.id is not S.LOGO_ADJUST:
            body = f"{body} {step.tip}"
    return f"{ack} {body}".strip() if ack else body
```

`LOGO_ADJUST`'s `ask` already contains its instructions, so it is excluded from
the tip append to avoid duplicating them.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: PASS (27 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): assemble replies as ack + copy + verbatim tip"
```

---

### Task 8: The orchestrator turn loop

**Files:**
- Rewrite: `backend/app/services/conversation/orchestrator_v2.py`
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: everything above; `_v1.handle_message`, `SessionNotFound`, `_can_start_design`, `get_store`, `canvas_intro_text`.
- Produces: `async handle_message(session_id: str, message: str) -> dict`.

Keep `_FakeSB`/`_FakeTable`/`_new_store` from the existing test file.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_orchestrator_v2.py  (keep the fakes; replace the tests)
import pytest

from app import prompts
from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


def _no_llm(monkeypatch):
    async def _boom(*a, **k):
        raise ie.LLMUnavailable("no key")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


def _llm_returns(monkeypatch, fields):
    async def _ok(*a, **k):
        return dict(fields)
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _ok)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)


@pytest.mark.asyncio
async def test_kickoff_greets_and_advances_to_ask_name(monkeypatch):
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "")
    assert res["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_the_live_bug_yes_another_logo_reopens_the_logo_loop(monkeypatch):
    """Regression: the customer tapped the chip three times and was marched to
    the email question, because "another" contains "no"."""
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "pending_logo": {"face": "front", "placed": True},
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)                       # a chip must not need the LLM
    res = await o2.handle_message("s1", "Yes, another logo")
    assert res["state"] == S.ASK_LOGO_PLACEMENT.value
    assert store["session"]["collected"]["logos"] == [{"face": "front", "placed": True}]


@pytest.mark.asyncio
async def test_a_chip_tap_makes_zero_llm_calls(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_QUANTITY.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "logos_done": True,
                                     "decor_done": True}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    calls = []

    async def _spy(*a, **k):
        calls.append(1)
        raise AssertionError("chip taps must not call the model")

    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _spy)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)

    res = await o2.handle_message("s1", "50-99")
    assert calls == []
    assert store["session"]["collected"]["quantity"] == 50
    assert res["state"] == S.ASK_EMAIL.value


@pytest.mark.asyncio
async def test_free_text_stalls_when_the_model_is_unavailable(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "go on then")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value        # unchanged: nothing guessed
    assert res["reply"] == prompts.V2_STALL_REPLY
    assert store["session"]["collected"]["_fail_count"] == 1


@pytest.mark.asyncio
async def test_two_failures_nudge_toward_the_chips(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "_fail_count": 1,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "go on then")
    assert res["reply"] == prompts.V2_NUDGE_REPLY
    assert res["data"]["options"] == ["Yes, another logo", "No, that's it"]


@pytest.mark.asyncio
async def test_a_successful_turn_clears_the_fail_count(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "_fail_count": 1,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"another_logo": False})
    await o2.handle_message("s1", "nah I'm good")
    assert store["session"]["collected"].get("_fail_count", 0) == 0


@pytest.mark.asyncio
async def test_a_volunteered_answer_is_banked_and_its_step_skipped(monkeypatch):
    """Reordering: filling a later slot early means the router never asks it."""
    store = _new_store()
    store["session"]["state"] = S.ASK_ANOTHER_LOGO.value
    store["session"]["collected"] = {"flow_mode": "canvas", "name": "Sam",
                                     "intro_ack": True, "decor_done": True,
                                     "pending_logo": {"face": "front", "placed": True}}
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"another_logo": False, "quantity": 50})
    res = await o2.handle_message("s1", "no thanks, and I need 50 caps")
    assert store["session"]["collected"]["quantity"] == 50
    assert res["state"] == S.ASK_EMAIL.value        # ask_quantity skipped
    assert res["data"]["progress"]["total"] == 7


@pytest.mark.asyncio
async def test_a_shared_tail_state_delegates_to_v1(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.OFFER_REFINE.value
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    called = {}

    async def _v1(sid, msg):
        called["hit"] = (sid, msg)
        return {"reply": "v1", "state": S.OFFER_REFINE.value, "data": {}}

    monkeypatch.setattr(o2._v1, "handle_message", _v1)
    res = await o2.handle_message("s1", "tweak it")
    assert called["hit"] == ("s1", "tweak it")
    assert res["reply"] == "v1"


@pytest.mark.asyncio
async def test_daily_cap_reroutes_to_the_quote_ask(monkeypatch):
    store = _new_store()
    store["session"]["state"] = S.ASK_PURPOSE.value
    store["session"]["collected"] = {
        "flow_mode": "canvas", "name": "Sam", "intro_ack": True,
        "logos_done": True, "decor_done": True, "quantity": 50,
        "email_captured": True,
    }
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    monkeypatch.setattr(o2, "_can_start_design", lambda _sid: False)
    _llm_returns(monkeypatch, {"purpose": "team caps"})
    res = await o2.handle_message("s1", "for the team")
    assert res["state"] == S.QUOTE_REQUESTED.value
    assert res["data"]["options"] == ["Yes, request a quote", "No, I'm all set"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_orchestrator_v2.py -q`
Expected: FAIL — the old keyword implementation misroutes `"Yes, another logo"` to `ask_add_decor`

- [ ] **Step 3: Write minimal implementation**

Replace `orchestrator_v2.py` entirely:

```python
"""v2 step-by-step canvas orchestrator (parallel to orchestrator.py).

Per turn: resolve a chip deterministically OR interpret free text with Haiku,
validate into declared slots, run the step's effect, ask the router for the
first unmet step, assemble the reply, persist.

The LLM reads the customer; it never routes. Chips never reach the LLM: we
generated the label in canvas_steps and shipped it to the browser, so matching
it back is an identity lookup on a closed set we own.

Selected only when settings.canvas_orchestrator_v2 and flow_mode == "canvas".
Any state outside V2_OWNED is a shared tail state v1 owns — delegated, so a
canvas session is never stranded post-design.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import prompts
from app.config import settings
from app.db import get_supabase
from app.services.branding import canvas_intro_text
from app.services.stores import get_store
from app.services.conversation import canvas_steps as cs
from app.services.conversation import intent_extractor as ie
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation import orchestrator as _v1
from app.services.conversation.orchestrator import SessionNotFound, _can_start_design
from app.services.conversation.state_machine import ConversationState as S

_NUDGE_AFTER = 2


async def handle_message(session_id: str, message: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    current = S(session["state"])

    if current not in v2.V2_OWNED:
        return await _v1.handle_message(session_id, message)

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)
    state_before = current.value

    if current is S.GREETING:
        # Kickoff: greet and advance without ingesting the opening turn.
        # Deliberately does NOT mark ask_name as asked — this turn must get the
        # FULL greeting; only a re-ask gets the shorter retry copy. The main loop
        # below marks it when the customer actually answers.
        step = cs.by_id(S.ASK_NAME)
        reply = v2.reply_for(step, collected, persona=persona, intro=intro)
        return await _persist(sb, session_id, collected, step, reply,
                              state_before, S.ASK_NAME, user_message="")

    step = cs.by_id(current)
    ack = ""

    fields = v2.resolve_chip(step, message)
    if fields is None and step.slots:
        # Free text on a step that asks for something: the model reads it, or we
        # stall. No keyword fallback — a wrong field corrupts the design.
        try:
            fields = await ie.interpret_turn_v2(step, message, collected)
        except ie.LLMUnavailable:
            return await _stall(sb, session_id, collected, step, state_before,
                                message)
        ack = await ie.write_ack(persona, message, fields)
    elif fields is None:
        fields = {}                       # ack-only step (show_intro)

    collected.pop("_fail_count", None)
    collected.update(fields)
    if step.apply:
        step.apply(collected, fields, session)

    asked = collected.setdefault("_asked", [])
    if step.id.value not in asked:
        asked.append(step.id.value)

    next_ = v2.next_step(collected)

    if next_.id is S.FINALIZE_CANVAS and not _can_start_design(session_id):
        # Honesty gate: the customer is capped, so pose the quote ask instead of
        # promising a render. QUOTE_REQUESTED is a shared tail state, so the NEXT
        # turn delegates to v1 — but THIS turn must speak, and v2 has no copy
        # for it.
        collected["generation_blocked"] = "daily_limit"
        reply = f"{prompts.GENERATION_BLOCKED_ASIDE} {prompts.CANVAS_QUOTE_ASK}"
        data = {"options": ["Yes, request a quote", "No, I'm all set"],
                "progress": v2.progress_for(cs.by_id(S.FINALIZE_CANVAS))}
        return await _persist(sb, session_id, collected, None, reply, state_before,
                              S.QUOTE_REQUESTED, user_message=message, data=data)

    reply = v2.reply_for(next_, collected, persona=persona, intro=intro, ack=ack)
    return await _persist(sb, session_id, collected, next_, reply, state_before,
                          next_.id, user_message=message)


async def _stall(sb, session_id, collected, step, state_before, message) -> dict:
    """Retry exhausted: leave the state untouched and guess nothing.

    After two consecutive failures, re-render the chips and nudge — chips are
    deterministic, so a full outage degrades the bot to a tap-through wizard
    instead of stranding a pre-email-capture session (a lost lead). Nothing is
    guessed; a closed question is asked.
    """
    fails = int(collected.get("_fail_count") or 0) + 1
    collected["_fail_count"] = fails
    nudge = fails >= _NUDGE_AFTER and step.chips
    reply = prompts.V2_NUDGE_REPLY if nudge else prompts.V2_STALL_REPLY
    return await _persist(sb, session_id, collected, step, reply, state_before,
                          step.id, user_message=message)


async def _persist(sb, session_id, collected, step, reply, state_before, new_state,
                   *, user_message: str = "", data: dict | None = None) -> dict:
    """Write the state + both chat rows, and shape the response.

    `step` is the step the session now RESTS on (None only for the capped
    QUOTE_REQUESTED handoff, which supplies its own `data`).
    """
    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()
    sb.table("chat_messages").insert([
        {"session_id": session_id, "role": "user", "content": user_message,
         "state_before": state_before, "state_after": state_before},
        {"session_id": session_id, "role": "assistant", "content": reply,
         "state_before": state_before, "state_after": new_state.value},
    ]).execute()
    if data is None:
        data = v2.public_data_for(step, collected) if step else {}
    return {"reply": reply, "state": new_state.value, "data": data}
```

Note `_stall` returns `public_data_for(step, ...)` via `_persist`, which re-renders the
step's chips — that is what makes the nudge actionable rather than just apologetic.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_orchestrator_v2.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py backend/tests/test_orchestrator_v2.py
git commit -m "feat(canvas-v2): rewrite the turn loop on the registry + LLM interpreter

Fixes the live bug: 'Yes, another logo' now reopens the logo loop instead of
being read as a decline. Chips resolve without the model; free text stalls
rather than guessing."
```

---

### Task 9: Remove the dead keyword path, update e2e, document

**Files:**
- Modify: `backend/tests/test_v2_e2e.py`
- Modify: `CLAUDE.md`
- Verify: `backend/app/services/conversation/orchestrator_v2.py` (no keyword helpers remain)

**Interfaces:** none new.

`_DONE_WORDS`, `_DONE_WORDS_RE`, `_is_done`, `_NAME_FILLER`, `_plausible_name`,
`_face_from`, `_apply_v2_fields`, `_V2_OWNED` and the `is_affirmative`/`is_negative`
imports were all dropped in Task 8's rewrite. This task proves it and updates the
e2e walk to drive the **real chip labels**.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_v2_e2e.py  (replace the walk)
import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


def test_v2_no_longer_uses_the_shared_keyword_matchers():
    """v1 keeps is_affirmative/is_negative (it still routes on them); v2 must
    not import them. `is_negative` matches by substring, so "another" reads as
    "no" — that is what broke the logo loop."""
    src = (o2.__file__)
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    for banned in ("is_affirmative", "is_negative", "_apply_v2_fields",
                   "_is_done", "_face_from"):
        assert banned not in text, f"{banned} still referenced in orchestrator_v2"


@pytest.mark.asyncio
async def test_full_v2_walk_using_the_exact_chip_labels(monkeypatch):
    """Drives the strings the UI actually ships. The old e2e hand-picked "yes"
    to dodge the broken chip and stayed green over it."""
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    async def _boom(*a, **k):
        raise o2.ie.LLMUnavailable("chips must not need the model")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom)

    async def _ack(*a, **k):
        return ""
    monkeypatch.setattr(o2.ie, "write_ack", _ack)
    monkeypatch.setattr(cs.leads_service, "capture_lead_and_verify",
                        lambda s, c, e: ("lead-1", True))

    await o2.handle_message("s1", "")                       # -> ASK_NAME

    # Name and purpose are free text; feed them through a stubbed interpreter.
    async def _interp(step, msg, collected):
        return {"name": "Sam"} if step.id is S.ASK_NAME else {"purpose": "team caps"}
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _interp)
    res = await o2.handle_message("s1", "Sam")
    assert res["state"] == S.SHOW_INTRO.value

    async def _boom2(*a, **k):
        raise o2.ie.LLMUnavailable("chips must not need the model")
    monkeypatch.setattr(o2.ie, "interpret_turn_v2", _boom2)

    walk = [
        ("ok",                  S.ASK_LOGO_PLACEMENT),   # intro ack (no slots)
        ("Front",               S.LOGO_ADJUST),
        ("Done",                S.ASK_ANOTHER_LOGO),
        ("Yes, another logo",   S.ASK_LOGO_PLACEMENT),   # THE bug
        ("Back",                S.LOGO_ADJUST),
        ("Done",                S.ASK_ANOTHER_LOGO),
        ("No, that's it",       S.ASK_ADD_DECOR),
        ("Add text",            S.DECOR_ADJUST),
        ("Done",                S.ASK_ANYTHING_ELSE),
        ("No, that's everything", S.ASK_QUANTITY),
        ("50-99",               S.ASK_EMAIL),
    ]
    for msg, expected in walk:
        res = await o2.handle_message("s1", msg)
        assert res["state"] == expected.value, f"{msg!r} -> {res['state']}"

    monkeypatch.setattr(o2.ie, "interpret_turn_v2",
                        lambda step, msg, c: _aio({"email": "sam@example.com"}))
    res = await o2.handle_message("s1", "sam@example.com")
    assert res["state"] == S.ASK_PURPOSE.value

    monkeypatch.setattr(o2.ie, "interpret_turn_v2",
                        lambda step, msg, c: _aio({"purpose": "team caps"}))
    res = await o2.handle_message("s1", "for the team")
    assert res["state"] == S.FINALIZE_CANVAS.value
    assert res["data"]["trigger_finalize"] is True

    c = store["session"]["collected"]
    assert len(c["logos"]) == 2
    assert [l["face"] for l in c["logos"]] == ["front", "back"]
    assert c["quantity"] == 50


async def _aio(val):
    return val
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_v2_e2e.py -q`
Expected: FAIL if any banned helper survived Task 8, else PASS

- [ ] **Step 3: Write minimal implementation**

If the guard test fails, delete the named symbols from `orchestrator_v2.py`. Then
add to `CLAUDE.md` §13 "Current implementation state", replacing the sentence
"Each v2 state drives the canvas directly via a `canvas` directive blob…" — keep
that sentence and append after the v2 bullet:

```markdown
  **v2 is registry-driven (2026-07-17).** The flow is declared once as data in
  `services/conversation/canvas_steps.py`: one `Step` per step holding its copy,
  chips (**label AND the fields that label means, in the same literal**), slots,
  `done_when`, `apply` effect, and canvas tool. `state_machine_v2` is a generic
  engine over it — routing is **first-unmet resolution** (`next_step` = the first
  step whose `done_when(collected)` is False), a pure function of `collected`,
  testable with plain dicts. **Adding a step = adding one record**; the eight
  parallel per-state switches are gone. Understanding is split: a **chip tap
  resolves deterministically** by exact label match (0 LLM calls — we generated
  the label and shipped it, so matching it back is an identity lookup), while
  **free text goes to Haiku** (`intent_extractor.interpret_turn_v2`) which fills
  *slots only and never names a state*; validation (`validate_fields`) drops
  anything outside `WRITABLE_SLOTS` so internal flags like `email_captured` can
  never be model-written. **There is no keyword fallback** — on `LLMUnavailable`
  the turn **stalls** (state unchanged, nothing guessed) and after 2 consecutive
  failures re-renders the chips to nudge a tap, so an outage degrades to a
  tap-through wizard rather than stranding a pre-email session. Replies are
  **LLM ack + scripted copy + tool tip concatenated verbatim** (the tip never
  passes through a model). Flexibility comes from **slot-filling, not routing**:
  a volunteered answer ("no thanks, and I need 50 caps") fills a later slot, and
  the router simply never asks that step. **Loops are slot-clearing** — the logo
  loop is `logos` + `pending_logo`, and `_apply_another_logo` re-seeds
  `pending_logo`/clears `another_logo` so the router walks back on its own; no
  back-edges, `MAX_LOGOS`=4. There is **no gate concept**: first-unmet already
  never returns a step after an unmet one, and `FINALIZE_CANVAS` is unreachable
  without `email_captured` because `ask_email` precedes it and only
  `_apply_email` sets that flag. **Known landmine:** `state_machine.is_negative`
  still matches by **substring** ("a**no**ther" contains "no") and **v1 still
  routes on it** — v2 no longer calls it. Spec/plan:
  `docs/superpowers/{specs,plans}/2026-07-17-llm-assisted-canvas-orchestration*`.
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && pytest -q`
Expected: PASS. Baseline before this work was **562 passed** (with the CANVAS_ORCHESTRATOR_V2=false override). The
count will differ — the v2 tests were rewritten — but there must be **zero
failures** and no v1/tail test may regress.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_v2_e2e.py CLAUDE.md
git commit -m "test(canvas-v2): e2e on real chip labels; document the registry engine"
```

---

## Follow-up tickets (do NOT do in this plan)

1. **`is_negative` substring bug in v1.** `state_machine.py:167` matches by substring, so "another"/"know"/"now"/"note" read as "no". v1 still routes on it from `advance_state`. Needs word-boundary matching (v1 already has the pattern in `_DONE_ELEMENTS_RE`) plus a v1 regression sweep.
2. **Approach C** — explicit `revise`/`backtrack`/`restart` intents (v1 has `revise_target`/`backtrack_target` in `interpret_turn`). Additive on top of the registry.
3. **Interpreter retry/backoff tuning** — Task 8 treats any `LLMUnavailable` as one failure; a 429 vs a timeout may warrant different retry counts.
