# Studio Review Gate + Orchestrator Correctness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a free-text turn from silently skipping the design review, stop the ack model breaking character, fix mojibake chips, and put a watermarked all-views confirm gate, a production-grade focus cue, and per-message attribution into the canvas studio.

**Architecture:** Four independent workstreams on one branch. A is pure-function backend guards in the v2 registry engine (no LLM, no DB — testable with plain dicts). B adds one boolean to the existing turn payload and one DOM overlay + one modal on the frontend; the watermark is a DOM sibling of the Konva stage, so it is structurally incapable of entering `stage.toDataURL()`. C and D are presentational changes in two components. Nothing new is introduced into the routing engine, and v1 (`orchestrator.py`) is untouched throughout.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React 18 / TypeScript / Zustand / react-konva / Tailwind / vitest (frontend).

## Global Constraints

- Branch is `feat/studio-review-gate-and-orchestrator-fixes`, already created off `master` at `698ba15`.
- Backend tests run **flag-off** by default: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`. **This project has no `backend/.venv`** — use the container instead: `MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q`.
- The five v2 suites must also be run **flag-on**: `CANVAS_ORCHESTRATOR_V2=true ... pytest -q tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py`.
- Frontend tests run **inside the container** — host `npx vitest` is broken on this Windows machine (missing `@vitest/utils`, the documented per-platform `node_modules` gotcha): `docker compose exec -T frontend npx vitest run <path>`.
- Baselines to hold. Backend numbers were **measured on this branch at `9b7c9a8`** during Task 1 (by stashing), superseding the stale CLAUDE.md figures of 1259/330: backend flag-off **1283**, v2 suites flag-on **348**. Frontend is **not yet re-measured** — CLAUDE.md says `src/__tests__` + `src/components/StoreHeader.test.tsx` = 330, so the first frontend task must stash-measure it and correct this line. `docker compose exec -T frontend npx tsc --noEmit` **clean**.
- **`backend/tests` is NOT bind-mounted into the running `backend` container**, and the image lacks dev deps. Run backend tests with an explicit mount instead of editing `docker-compose.yml`: `MSYS_NO_PATHCONV=1 docker compose run --rm -v "$PWD/backend/tests:/app/tests" -e CANVAS_ORCHESTRATOR_V2=false backend sh -c "pip install -q pytest pytest-asyncio && python -m pytest -q"`. (Discovered in Task 1; see the SDD ledger.)
- Security rule 10: no customer name/email in logs or Sentry breadcrumbs. `log.*(err=type(exc).__name__)`, never `str(exc)`, on any path whose prompt carried customer text.
- v2 copy is guarded by `backend/tests/test_v2_copy_guards.py`: no casual register (`_CASUAL` word-boundary list), and no v2 string may contain "under the cap". Any new customer-facing string must pass it.
- Do **not** reintroduce client-side background-removal processing, and do not let customer copy promise processing or a wait (CLAUDE.md, background-removal entry).
- Commit after every task. Never `--no-verify`.

---

## File Structure

**Backend — modified**

| File | Responsibility after this plan |
|---|---|
| `backend/app/services/conversation/state_machine_v2.py` | Adds `_STEP_OWNED_FLAGS` (renamed from `_TERMINAL_FLAGS`, 3 new members) and a `watermark` key in `public_data_for`. |
| `backend/app/services/conversation/intent_extractor.py` | `write_ack` stops inheriting the persona system prompt; adds pure `_ack_is_sane`. |
| `backend/app/api/routes/storefront.py` | Returns the global `watermark_text` app setting. |
| `backend/app/prompts.py` | Adds `ACK_SYSTEM_PROMPT` (minimal, instruction-free). |

**Backend — tests**

`backend/tests/test_state_machine_v2.py`, `backend/tests/test_intent_extractor_v2.py`, `backend/tests/test_storefront.py` (create if absent).

**Frontend — created**

| File | Responsibility |
|---|---|
| `frontend/src/components/DesignStudio/Watermark.tsx` | A DOM overlay of repeating diagonal text. Used over the canvas and over each review image. Knows nothing about state. |
| `frontend/src/components/DesignStudio/FaceStage.tsx` | The static per-face Konva mini-render, extracted from `FaceThumbnails` and parameterised by size, so a 64px thumbnail and a 320px review image share one renderer. |
| `frontend/src/components/DesignStudio/ReviewDialog.tsx` | The all-views confirm modal. Composes `FaceStage` + `Watermark`; mirrors the two review chips. |
| `frontend/src/components/CustomiseStudio/ColumnHeader.tsx` | The per-column header strip (resting name / active accent-filled instruction). |

**Frontend — modified**

| File | Change |
|---|---|
| `frontend/src/components/DesignStudio/FaceThumbnails.tsx` | Keeps the rail; delegates rendering to `FaceStage`. |
| `frontend/src/components/DesignStudio/Surface.tsx` | Mounts `<Watermark>` over the stage wrapper; mounts `<ReviewDialog>`. |
| `frontend/src/components/CustomiseStudio/index.tsx` | Header-on-lifted-cards focus cue; `FocusPill` removed. |
| `frontend/src/components/CustomiseStudio/ChatColumn.tsx` | Attribution lanes + grouped name lines. |
| `frontend/src/store/chatStore.ts` | Parses `data.watermark`. |
| `frontend/src/store/brandStore.ts`, `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts` | Carry `watermark_text` from `/storefront`. |

---

## Interfaces produced by this plan

Later tasks depend on these exact names. They are listed once here so an implementer reading a single task can look them up.

```python
# state_machine_v2.py
_STEP_OWNED_FLAGS: frozenset[str]
def merge_fields(step: Step, collected: dict, fields: dict) -> dict          # unchanged signature
def watermark_for(step: Step) -> bool                                        # NEW
def public_data_for(step: Step, collected: dict) -> dict                     # gains data["watermark"]: bool

# intent_extractor.py
def _ack_is_sane(text: str) -> bool                                          # NEW, pure
async def write_ack(persona: str, fields: dict) -> str                       # unchanged signature
```

```ts
// Watermark.tsx
export function Watermark({ text }: { text: string }): JSX.Element

// FaceStage.tsx
export function FaceStage({ face, size, fontsTick }: { face: Face; size: number; fontsTick: number }): JSX.Element

// ReviewDialog.tsx
export function ReviewDialog({ open, onConfirm, onRework, onClose }: {
  open: boolean; onConfirm: () => void; onRework: () => void; onClose: () => void
}): JSX.Element | null

// ColumnHeader.tsx
export function ColumnHeader({ name, instruction, active }: {
  name: string; instruction: string; active: boolean
}): JSX.Element

// chatStore state
watermark: boolean            // from data.watermark
// brandStore state
watermarkText: string         // from /storefront, default 'MADHATS PREVIEW'
```

---

# WORKSTREAM A — Orchestrator correctness

## Task 1: Gate flags may only be written by their owning step

The live defect: at `NEEDED_BY` a free-text "go back to quantity" made the interpreter fill `design_rework: true`. `merge_fields` banked it (unset→truthy is allowed), routing did not move, so nothing looked wrong — and two turns later `REVIEW_DESIGN.done_when` (`design_confirmed or design_rework`) was already satisfied, so first-unmet skipped the review and landed on `REWORK_CANVAS`.

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py:29-71`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_STEP_OWNED_FLAGS: frozenset[str]` (replaces `_TERMINAL_FLAGS`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_state_machine_v2.py`:

```python
def test_design_rework_is_dropped_when_written_off_step():
    """Live session bb62d05a: a free-text 'go back to quantity' at NEEDED_BY made
    the interpreter fill design_rework:true. It banked, routing didn't move, and
    two turns later REVIEW_DESIGN's done_when was already satisfied — so the
    review was skipped and the customer landed in the rework loop unasked."""
    step = cs.by_id(S.NEEDED_BY)
    fields = v2.merge_fields(step, {}, {"needed_by": "2-4 weeks", "design_rework": True})
    assert fields == {"needed_by": "2-4 weeks"}


def test_design_rework_is_kept_on_the_step_that_owns_it():
    step = cs.by_id(S.REVIEW_DESIGN)
    fields = v2.merge_fields(step, {}, {"design_rework": True})
    assert fields == {"design_rework": True}


def test_rework_canvas_may_still_clear_design_rework():
    """REWORK_CANVAS declares design_rework as its own slot; clearing it is how
    'Done' is expressed, so the falsy write must survive both guards."""
    step = cs.by_id(S.REWORK_CANVAS)
    fields = v2.merge_fields(step, {"design_rework": True}, {"design_rework": False})
    assert fields == {"design_rework": False}


def test_design_confirmed_is_dropped_when_written_off_step():
    step = cs.by_id(S.ASK_PURPOSE)
    fields = v2.merge_fields(step, {}, {"purpose": "staff caps", "design_confirmed": True})
    assert fields == {"purpose": "staff caps"}


def test_final_notes_done_is_dropped_when_written_off_step():
    """Skipping ASK_FINAL_NOTES would deny the customer the colour-disclaimer copy."""
    step = cs.by_id(S.ASK_QUANTITY)
    fields = v2.merge_fields(step, {}, {"quantity": 45, "final_notes_done": True})
    assert fields == {"quantity": 45}


def test_loop_control_slots_stay_volunteerable():
    """decor_done et al must still be fillable from an earlier turn — that is the
    slot-filling flexibility the whole registry design rests on."""
    step = cs.by_id(S.ASK_QUANTITY)
    fields = v2.merge_fields(step, {}, {"quantity": 45, "decor_done": True})
    assert fields == {"quantity": 45, "decor_done": True}


def test_the_live_bb62d05a_sequence_lands_on_review_not_rework():
    """End-to-end over the pure router: quantity -> the back-request turn ->
    purpose must reach REVIEW_DESIGN. Fails on master (lands on rework_canvas)."""
    collected = {
        "name": "Satish", "intro_ack": True, "has_logo": True, "logos_done": True,
        "logo_face": "front", "logo_placed": True, "logo_bg": "removed",
        "another_logo": False, "pending_logo": None, "decor_done": True,
        "email_captured": True, "email_verified": True, "quantity": 45,
        "decoration_options": [], "decoration_done": True,
    }
    # The back-request turn at NEEDED_BY: the interpreter returned design_rework.
    step = cs.by_id(S.NEEDED_BY)
    collected.update(v2.merge_fields(step, collected, {"design_rework": True}))
    collected["needed_by"] = "2-4 weeks"
    collected["purpose"] = "dont say"
    assert v2.next_step(collected, None).id is S.REVIEW_DESIGN
```

- [ ] **Step 2: Run them and verify they fail**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q \
  tests/test_state_machine_v2.py -k "design_rework or design_confirmed or final_notes_done or bb62d05a or loop_control"
```

Expected: the three off-step tests and `test_the_live_bb62d05a_sequence_lands_on_review_not_rework` FAIL. `test_design_rework_is_kept_on_the_step_that_owns_it`, `test_rework_canvas_may_still_clear_design_rework` and `test_loop_control_slots_stay_volunteerable` already PASS — they pin behaviour that must not regress.

- [ ] **Step 3: Rename the constant and extend it**

Replace `state_machine_v2.py:29-38` with:

```python
# Flags that RECORD something rather than describe a preference: a lead
# captured, a quote submitted, a design confirmed or sent back for rework, the
# final-notes step answered. Each is made true by its owning step's `apply` (or
# its chip), and each satisfies a done_when. `merge_fields` is the only reader.
#
# The interpreter sees every WRITABLE_SLOT on every turn, so free text at ANY
# step can set one of these — and because a truthy write is normally always
# banked, that makes first-unmet SKIP the owning step, and its apply never runs.
# Two live regressions: session 766b8361 ("that's it let's go" at
# ASK_FINAL_NOTES -> quote_requested, so no MH-XXXXXX reference, no customer
# email, no sales notification) and session bb62d05a ("i need to go back to How
# many caps" at NEEDED_BY -> design_rework, so the design review was skipped
# entirely and the customer was dropped into the rework loop unasked).
#
# Deliberately NOT `checkpoints.CARRY_FORWARD_KEYS`, which is a wider set
# (lead_id, email_verified, reference_code) serving a different concern: what a
# Back restore must not roll back. Conflating them would let the interpreter
# write, say, reference_code off-step. Two concepts, two constants.
#
# Deliberately NOT extended to the loop-control slots (decor_done, has_logo,
# another_logo, more_decor, logo_placed, decor_placed): those are MEANT to be
# volunteerable from an earlier turn — "no, text only" satisfying ASK_HAS_LOGO
# is the slot-filling flexibility the registry design rests on.
_STEP_OWNED_FLAGS: frozenset[str] = frozenset({
    "email_captured", "quote_requested",
    "design_rework", "design_confirmed", "final_notes_done",
})
```

- [ ] **Step 4: Point `merge_fields` at the new name**

In `merge_fields`, change the return expression's second clause:

```python
    own = set(step.slots)
    return {k: v for k, v in fields.items()
            if (k in own or v or not collected.get(k))
            and (k not in _STEP_OWNED_FLAGS or k in own)}
```

And in its docstring, replace the paragraph beginning `A `_TERMINAL_FLAG` is the one exception` with:

```
    A `_STEP_OWNED_FLAG` is the one exception in the OTHER direction: a truthy
    write is normally always banked, but volunteering one from free text at an
    earlier step makes first-unmet SKIP the owning step, so its apply never
    runs. Such a flag may only be set on the step that OWNS it (its chip, or
    the interpreter while that step is current), which is exactly where the
    apply runs too. See the constant for the two live regressions.
```

- [ ] **Step 5: Verify no other reader of the old name survives**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend sh -c "grep -rn '_TERMINAL_FLAGS' /app/app /app/tests || echo CLEAN"
```

Expected: `CLEAN`. If a test referenced the old name, rename it there too.

- [ ] **Step 6: Run the tests and verify they pass**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_state_machine_v2.py
```

Expected: all PASS.

- [ ] **Step 7: Prove the guard is load-bearing**

Temporarily delete `and (k not in _STEP_OWNED_FLAGS or k in own)`, re-run the four off-step tests, confirm they FAIL, then restore the line. Do not commit the deletion.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "fix(canvas-v2): a gate flag may only be written by the step that owns it

Live session bb62d05a: a free-text 'i need to go back to How many caps do you
need?' at NEEDED_BY made the interpreter fill design_rework:true. merge_fields
banked it (unset->truthy is allowed) and routing did not move, so nothing
looked wrong. Two turns later REVIEW_DESIGN.done_when (design_confirmed or
design_rework) was already satisfied and first-unmet skipped the review
outright, dropping the customer into the rework loop without ever asking if
they were happy with the design.

Same class as 240b7f9, one slot over. _TERMINAL_FLAGS becomes _STEP_OWNED_FLAGS
and gains design_rework, design_confirmed and final_notes_done. The
loop-control slots are deliberately left volunteerable.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: The ack cannot leak the system prompt or break its own rules

At `ASK_PURPOSE` the customer typed "dont say". `write_ack` renders `We understood: {"purpose": "dont say"}` into `V2_ACK_PROMPT` and calls `_complete`, which passes `RICARDO_SYSTEM_PROMPT` as the system prompt by default. Haiku read "dont say" as an operator instruction and answered the *system prompt*, shipping this to the customer:

> "I appreciate you clarifying the setup, but I should let you know I'm ready to greet an actual customer now—I don't need a practice run. Once a customer arrives, I'll acknowledge them warmly in my first message only…"

**Files:**
- Modify: `backend/app/prompts.py` (add `ACK_SYSTEM_PROMPT` next to `V2_ACK_PROMPT`, around line 1273)
- Modify: `backend/app/services/conversation/intent_extractor.py` (`write_ack`, and a new `_ack_is_sane` above it)
- Test: `backend/tests/test_intent_extractor_v2.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `_ack_is_sane(text: str) -> bool`, `prompts.ACK_SYSTEM_PROMPT`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_intent_extractor_v2.py`:

```python
from app.services.conversation.intent_extractor import _ack_is_sane


# Captured verbatim from Haiku on 2026-08-01 with fields={"purpose": "dont say"}.
LIVE_LEAKS = [
    "I'm Ricardo, your design assistant at MadHats. What brings you in today?",
    "I appreciate you sharing that context, but I'm ready to help customers "
    "design caps whenever they arrive.",
    "I appreciate you clarifying the setup, but I should let you know I'm ready "
    "to greet an actual customer now—I don't need a practice run.\n\nOnce a "
    "customer arrives, I'll acknowledge them warmly in my first message only, "
    "keep it brief and human, and guide them through their cap design naturally.",
]


@pytest.mark.parametrize("text", LIVE_LEAKS)
def test_live_ack_leaks_are_rejected(text):
    assert _ack_is_sane(text) is False


@pytest.mark.parametrize("text", [
    "Got it — 45 caps noted.",
    "Thank you, that's recorded.",
    "Noted, we'll use two to four weeks.",
    "Understood.",
])
def test_normal_acks_are_accepted(text):
    assert _ack_is_sane(text) is True


def test_an_empty_ack_is_not_sane():
    assert _ack_is_sane("") is False
    assert _ack_is_sane("   ") is False


def test_a_question_is_rejected_even_if_short():
    """V2_ACK_PROMPT forbids questions; an ack that asks one steals the step's
    own question and confuses the turn."""
    assert _ack_is_sane("Noted. What size did you want?") is False


def test_a_greeting_is_rejected():
    """RICARDO_SYSTEM_PROMPT forbids greeting after the first message; a greeting
    here reads as the bot restarting the conversation mid-flow."""
    assert _ack_is_sane("Hello Satish, that's noted.") is False


def test_an_overlong_ack_is_rejected():
    assert _ack_is_sane(" ".join(["word"] * 25)) is False
```

- [ ] **Step 2: Run them and verify they fail**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_intent_extractor_v2.py -k ack
```

Expected: FAIL — `ImportError: cannot import name '_ack_is_sane'`.

- [ ] **Step 3: Add the minimal system prompt**

In `backend/app/prompts.py`, immediately after `V2_ACK_PROMPT`:

```python
# The ack call is a one-line transform over a JSON field dump, NOT a
# conversational turn. Handing it RICARDO_SYSTEM_PROMPT (a behavioural brief
# full of hard rules) is what let Haiku answer the BRIEF instead of the
# customer: at ASK_PURPOSE the field {"purpose": "dont say"} read as an
# operator instruction and the reply paraphrased the system prompt's own rules
# back into the customer's chat ("I'll acknowledge them warmly in my first
# message only…"). This prompt states the role and nothing a model could
# mistake for an instruction to comply with.
ACK_SYSTEM_PROMPT = (
    "You rewrite structured data into a single short sentence of plain English. "
    "You never ask questions and never introduce yourself."
)
```

- [ ] **Step 4: Add the sanity guard**

In `intent_extractor.py`, immediately above `async def write_ack`:

```python
#: An ack is one short courteous sentence (V2_ACK_PROMPT). Anything else is the
#: model having answered something other than the field dump, and it is
#: concatenated straight into the customer's bubble — so it is checked, not
#: trusted. Pure: no network, no state, exhaustively unit-testable.
_ACK_MAX_WORDS = 20
_ACK_SELF_REFERENCE = re.compile(
    r"\b(customer|customers|ricardo|assistant|i'm ready|im ready|practice run)\b",
    re.IGNORECASE,
)


def _ack_is_sane(text: str) -> bool:
    """True if `text` is usable as an ack.

    Rejects the four ways the model has actually gone wrong: asking a question,
    greeting mid-conversation, running long or multi-paragraph, and talking
    ABOUT the customer/itself rather than to them. Any rejection degrades to
    "" — the same terse-but-correct reply an outage produces — never to a
    leaked meta message.
    """
    body = (text or "").strip()
    if not body:
        return False
    if "?" in body:
        return False
    if len(body.split()) > _ACK_MAX_WORDS:
        return False
    if "\n\n" in body:
        return False
    if _ACK_SELF_REFERENCE.search(body):
        return False
    first = re.sub(r"[^a-z']", "", body.split()[0].casefold())
    return first not in _GREETING_TOKENS
```

Confirm `import re` is already at the top of `intent_extractor.py`; add it if not. `_GREETING_TOKENS` is already defined in this module — if it is defined **below** this insertion point, move `_ack_is_sane` to sit after it (module-level names are resolved at call time, so this is style, not correctness; keep it readable).

- [ ] **Step 5: Wire both into `write_ack`**

Replace the body of `write_ack` from the `try:` onward with:

```python
    try:
        text = await _complete(
            prompts.V2_ACK_PROMPT.format(persona=persona, fields=json.dumps(safe)),
            system=prompts.ACK_SYSTEM_PROMPT,
            max_tokens=80,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("v2_ack_failed", err=type(exc).__name__)
        return ""
    ack = _strip_meta_preamble(repair_mojibake(text)).strip()
    if not _ack_is_sane(ack):
        # Never log the ack itself: it can carry the customer's own words back.
        log.warning("v2_ack_rejected", words=len(ack.split()))
        return ""
    return ack
```

- [ ] **Step 6: Run the tests and verify they pass**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_intent_extractor_v2.py
```

Expected: all PASS.

- [ ] **Step 7: Run the v2 suites flag-on to catch an ack-dependent assertion**

```
MSYS_NO_PATHCONV=1 docker compose exec -T -e CANVAS_ORCHESTRATOR_V2=true backend python -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py \
  tests/test_state_machine_v2.py tests/test_canvas_steps.py
```

Expected: PASS. If a test stubs `write_ack` to return a long string that the guard now rejects, fix the **stub** (make it a realistic short ack), not the guard.

- [ ] **Step 8: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/intent_extractor.py backend/tests/test_intent_extractor_v2.py
git commit -m "fix(canvas-v2): the ack can no longer answer the system prompt

Live session bb62d05a: at ASK_PURPOSE the customer typed 'dont say'.
write_ack renders that into V2_ACK_PROMPT as 'We understood: {\"purpose\":
\"dont say\"}' and calls _complete, which passes RICARDO_SYSTEM_PROMPT by
default. Haiku read the field as an operator instruction and answered the
SYSTEM PROMPT, paraphrasing its hard rules into the customer's chat; one of
three sampled runs emitted a fresh greeting mid-flow, which that same system
prompt forbids. The customer replied 'whay message is this???'.

Two changes. The ack call now gets ACK_SYSTEM_PROMPT — a minimal prompt with
no behavioural rules to comply with — removing the source. And _ack_is_sane
validates the result before it is concatenated into the bubble, rejecting
questions, greetings, over-long or multi-paragraph replies, and text that
talks about the customer rather than to them. Rejection degrades to '', the
same terse reply an outage already produces.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Mojibake chips resolve, and never reach the sales email

`collected["needed_by"]` stored as `2â€“4 weeks` (`U+00E2 U+20AC U+201C`), and the **user chat row carries the same mojibake** — the browser posted the mangled label. The registry source is clean UTF-8 (`E2 80 93`, verified with `od -c`). So `resolve_chip`'s exact match misses, the turn burns an interpreter call, and corrupted text lands in `needed_by` → `brief_notes` → the sales email.

**The corrupting hop is not yet identified.** Assistant message content containing em-dashes round-trips correctly, so it is not a blanket response-decoding fault. This task is investigation first, then two defence-in-depth changes that stand on their own.

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (`_norm`)
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `repair_mojibake` from `intent_extractor` (already exists, unchanged).
- Produces: no new public names — `_norm` gains a repair step.

- [ ] **Step 1: Investigate the corrupting hop (timebox: 45 minutes)**

Run each probe and record the exact bytes. Stop as soon as one hop shows clean-in / mangled-out.

```bash
# 1. Does the backend SEND it clean? (chips come from public_data_for -> data.options)
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -c "
import sys; sys.path.insert(0,'/app')
from app.services.conversation import canvas_steps as cs, state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S
d = v2.public_data_for(cs.by_id(S.NEEDED_BY), {})
lbl = [o for o in d['options'] if 'weeks' in o][0]
print(repr(lbl), [hex(ord(c)) for c in lbl])
"

# 2. Does it survive the HTTP layer? (raw bytes on the wire, no client decoding)
curl -s -H "X-Store-Key: mh_pk_madhats_local" http://localhost:8000/openapi.json -o /dev/null -w "%{http_code}\n"
# then hit a real chat turn that renders NEEDED_BY and inspect the raw body:
#   curl -s ... | od -c | grep -A1 weeks
```

If step 1 prints `0xe2 0x20ac 0x201c` the corruption is **server-side** (a source-encoding or template issue). If step 1 is clean (`0x2013`) and the wire bytes are clean, the corruption is in the browser — check `frontend/src/lib/api.ts`'s response handling for a `TextDecoder`/`latin1` path or a `Response.text()` used where `.json()` is expected.

Record the finding in the commit message. **If the timebox expires without a conclusion, proceed to Step 2 anyway** — the remaining steps fix the customer-visible symptom regardless, and the investigation becomes a follow-up ticket.

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_state_machine_v2.py`:

```python
# The exact bytes the browser posted back in live session bb62d05a: an en-dash
# (U+2013) mis-decoded as CP1252 becomes "â€“" (U+00E2 U+20AC U+201C).
MANGLED_NEEDED_BY = "2â€“4 weeks"


def test_a_mojibake_chip_label_still_resolves_as_a_chip():
    """Live session bb62d05a: the browser posted the en-dash label back mangled,
    so the exact-label match missed, the turn burned an interpreter call, and
    the corrupted string was stored in needed_by -> brief_notes -> sales email."""
    step = cs.by_id(S.NEEDED_BY)
    fields = v2.resolve_chip(step, MANGLED_NEEDED_BY, {})
    assert fields == {"needed_by": "2–4 weeks"}


def test_a_clean_chip_label_still_resolves():
    step = cs.by_id(S.NEEDED_BY)
    assert v2.resolve_chip(step, "2–4 weeks", {}) == {"needed_by": "2–4 weeks"}


def test_free_text_still_falls_through_to_the_interpreter():
    step = cs.by_id(S.NEEDED_BY)
    assert v2.resolve_chip(step, "sometime next month I think", {}) is None
```

Note the asserted value: the chip's **own clean payload**, not the mangled input. Matching a mangled label must still store clean text.

- [ ] **Step 3: Run it and verify it fails**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_state_machine_v2.py -k mojibake
```

Expected: FAIL — `assert None == {'needed_by': '2–4 weeks'}`.

- [ ] **Step 4: Repair both sides in `_norm`**

`_norm` is the single comparison point for both `resolve_chip` and `_resolve_multi`, so one change covers every chip in the registry. Replace `state_machine_v2.py:255-256`:

```python
def _norm(s: str) -> str:
    """Casefolded comparison key for a chip label.

    `repair_mojibake` is applied because a chip label round-trips through the
    browser and can come back CP1252-mangled — live session bb62d05a posted
    "2â€“4 weeks" for the en-dash chip "2–4 weeks". Without the repair the
    exact-label match misses, so a chip tap (designed as a 0-LLM identity
    lookup on a set we own) burns an interpreter call AND the mangled text is
    what gets stored, reaching brief_notes and the sales email. Repairing the
    KEY rather than the value means a matched chip still banks its own clean
    payload. `repair_mojibake` is a no-op on clean text, so nothing else moves.
    """
    return repair_mojibake(s or "").strip().casefold()
```

Add the import at the top of `state_machine_v2.py`:

```python
from app.services.conversation.intent_extractor import repair_mojibake
```

- [ ] **Step 5: Check for an import cycle**

`intent_extractor` imports `canvas_steps` lazily inside `interpret_turn_v2` (`# noqa: PLC0415 cycle`), and `state_machine_v2` imports `canvas_steps` at module scope. Verify the new top-level import does not close a cycle:

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -c "import sys; sys.path.insert(0,'/app'); from app.services.conversation import state_machine_v2; print('OK')"
```

Expected: `OK`. If it raises `ImportError`, move the import inside `_norm` with the same `# noqa: PLC0415 cycle` comment the codebase already uses.

- [ ] **Step 6: Run the tests and verify they pass**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_state_machine_v2.py
```

Expected: all PASS.

- [ ] **Step 7: Apply whatever the investigation found**

If Step 1 identified the corrupting hop, fix it now in the same commit and add a test at that layer. If it did not, add this to the plan's follow-ups and say so explicitly in the commit message — do not imply it was found.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "fix(canvas-v2): a CP1252-mangled chip label still resolves as a chip

Live session bb62d05a stored needed_by as '2â€“4 weeks' (U+00E2 U+20AC U+201C),
and the user chat row carries the same mojibake — the browser posted the label
back mangled. The registry source is clean UTF-8 (verified with od -c), so
resolve_chip's exact match missed: the tap burned an interpreter call instead
of being the 0-LLM identity lookup it is designed to be, and the corrupted
string was stored, reaching brief_notes and the sales email.

_norm is the single comparison point for resolve_chip and _resolve_multi, so
repairing the KEY there covers every chip in the registry — and because only
the key is repaired, a matched chip still banks its own clean payload.
repair_mojibake is a no-op on clean text.

Rewriting the en-dashes to ASCII was rejected: it would hide the fault and it
will resurface on any other non-ASCII copy, of which v2 has plenty.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# WORKSTREAM B — Review gate

## Task 4: The backend says when the canvas is watermarked

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (new `watermark_for`, and `public_data_for`)
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `watermark_for(step: Step) -> bool`; `public_data_for` gains `data["watermark"]: bool`.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_canvas_is_watermarked_from_the_review_onward():
    for state in (S.REVIEW_DESIGN, S.ASK_FINAL_NOTES, S.REQUEST_QUOTE, S.FINALIZE_CANVAS):
        assert v2.watermark_for(cs.by_id(state)) is True, state


def test_the_canvas_is_clean_while_they_are_still_designing():
    for state in (S.ASK_NAME, S.ASK_HAS_LOGO, S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST,
                  S.ASK_LOGO_BG, S.ASK_EMAIL, S.AWAIT_EMAIL_VERIFY, S.ASK_ADD_DECOR,
                  S.DECOR_ADJUST, S.ASK_QUANTITY, S.NEEDED_BY, S.ASK_PURPOSE):
        assert v2.watermark_for(cs.by_id(state)) is False, state


def test_rework_lifts_the_watermark():
    """Reworking is editing. A customer must not drag a logo around under a
    diagonal watermark — that reads as a broken app."""
    assert v2.watermark_for(cs.by_id(S.REWORK_CANVAS)) is False


def test_public_data_carries_the_watermark_flag():
    data = v2.public_data_for(cs.by_id(S.REVIEW_DESIGN), {})
    assert data["watermark"] is True
    data = v2.public_data_for(cs.by_id(S.ASK_QUANTITY), {})
    assert data["watermark"] is False
```

- [ ] **Step 2: Run and verify failure**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_state_machine_v2.py -k watermark
```

Expected: FAIL — `AttributeError: module ... has no attribute 'watermark_for'`.

- [ ] **Step 3: Implement**

Add above `public_data_for` in `state_machine_v2.py`:

```python
# Once the design is finished it is only ever DISPLAYED, never edited — so from
# the review onward every pixel on screen carries a watermark. REWORK_CANVAS is
# the deliberate hole: reworking IS editing, and dragging a logo around under a
# diagonal watermark reads as a broken app.
#
# A shared-tail state (generating / verify / refine / quote) has no registry
# step, so `canvas_directive` returns None there and the frontend falls back to
# its own default — which is `true`. That is correct and intentional: the design
# is finished in every one of those states.
_WATERMARKED_STEPS: frozenset[S] = frozenset({
    S.REVIEW_DESIGN, S.ASK_FINAL_NOTES, S.REQUEST_QUOTE, S.FINALIZE_CANVAS,
})


def watermark_for(step: Step) -> bool:
    """True when the canvas must render its watermark overlay."""
    return step.id in _WATERMARKED_STEPS
```

In `public_data_for`, after the `data["progress"]` line:

```python
    data["watermark"] = watermark_for(step)
```

- [ ] **Step 4: Run and verify passing**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_state_machine_v2.py
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(canvas-v2): ship a watermark flag on every v2 turn

On from REVIEW_DESIGN through FINALIZE_CANVAS, off during REWORK_CANVAS and
everything earlier. Backend-owned so it is resume-safe and there is no frontend
state list to drift — the same reason canvas_directive already lives here.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: The watermark text reaches the browser

`watermark_text` is a **global app setting** (`app_settings` via `settings_service`), not a per-store brand field. It is therefore returned top-level from `/storefront`, **not** through `public_brand` — which filters `stores.brand` keys and would be the wrong home. (This refines §B4 of the spec, which said `public_brand`; the observable result is identical.)

**Files:**
- Modify: `backend/app/api/routes/storefront.py`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/store/brandStore.ts`
- Test: `backend/tests/test_storefront.py` (create if absent)

**Interfaces:**
- Consumes: `settings_service.get_settings().watermark_text` (exists).
- Produces: `/storefront` → `watermark_text: str`; `useBrandStore().watermarkText: string`.

- [ ] **Step 1: Write the failing backend test**

Create or append `backend/tests/test_storefront.py`:

```python
def test_storefront_returns_the_watermark_text(client, store_headers):
    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    assert isinstance(res.json()["watermark_text"], str)
    assert res.json()["watermark_text"]        # never empty — the overlay needs something to draw


def test_storefront_never_leaks_the_watermark_asset(client, store_headers):
    """public_brand's allow-list must still hold: the internal asset URL is not
    a customer-facing field, and adding a watermark key must not smuggle it out."""
    res = client.get("/storefront", headers=store_headers)
    assert res.status_code == 200
    assert "watermark_asset_url" not in res.text
```

Match the existing fixtures in `backend/tests/` — inspect a neighbouring route test (e.g. `test_products.py` or `test_admin_stores.py`) for the real `client` / store-header fixture names and use those, rather than inventing them.

- [ ] **Step 2: Run and verify failure**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_storefront.py
```

Expected: FAIL — `KeyError: 'watermark_text'`.

- [ ] **Step 3: Implement the backend**

In `backend/app/api/routes/storefront.py`, add the import and the field:

```python
from app.services import settings_service
```

```python
@router.get("/storefront")
async def get_storefront(request: Request, store: dict = Depends(require_store)) -> dict:
    return {
        "name": store.get("name") or "",
        "persona_name": store.get("persona_name") or settings.chatbot_persona_name,
        "brand": public_brand(store.get("brand"), str(request.base_url)),
        # Global app setting (app_settings), not a per-store brand field — so it
        # is returned top-level rather than through public_brand's brand
        # allow-list. The canvas draws this over the design from the review
        # onward; delivery.py already burns the same string into the emailed
        # previews server-side, so both surfaces stay in step.
        "watermark_text": settings_service.get_settings().watermark_text,
    }
```

- [ ] **Step 4: Run and verify passing**

```
MSYS_NO_PATHCONV=1 docker compose exec -T backend python -m pytest -q tests/test_storefront.py
```

Expected: PASS.

- [ ] **Step 5: Carry it into the frontend store**

In `frontend/src/lib/types.ts`, the storefront response type is the interface carrying `persona_name` (line ~141). Add `watermark_text?: string` to it — optional, so a backend deployed behind the frontend still typechecks.

In `frontend/src/store/brandStore.ts`, the store already carries `personaName` (line 66/74/81) and is set in one place from the `/storefront` response (line 81). Add `watermarkText` alongside it in the state interface and the initialiser:

```ts
  watermarkText: 'MADHATS PREVIEW',
```

and extend the existing single `set(...)` at line 81 rather than adding a second one:

```ts
      set({
        brand: sf.brand || {}, storeName: sf.name, personaName: sf.persona_name,
        // Falls back to the same literal services/watermark.py uses as its
        // default (_DEFAULT_TEXT), so an unconfigured store looks identical on
        // the canvas and in the emailed preview.
        watermarkText: sf.watermark_text || 'MADHATS PREVIEW',
        loaded: true,
      })
```

- [ ] **Step 6: Typecheck**

```
docker compose exec -T frontend npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/storefront.py backend/tests/test_storefront.py frontend/src/lib/types.ts frontend/src/store/brandStore.ts
git commit -m "feat(storefront): expose the configured watermark text to the widget

watermark_text is a global app_settings value, not a stores.brand field, so it
is returned top-level rather than through public_brand's brand allow-list —
which stays exactly as narrow as it was (watermark_asset_url is still internal,
pinned by a test). The canvas overlay and delivery.py's server-side burn now
read the same admin-configured string.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: The watermark overlay, and proof it can never reach an export

**Files:**
- Create: `frontend/src/components/DesignStudio/Watermark.tsx`
- Modify: `frontend/src/store/chatStore.ts` (`parseData`, state, initial value, `hydrate`)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx` (the `canvas-stage-wrap` div)
- Test: `frontend/src/__tests__/watermark.test.tsx`

**Interfaces:**
- Consumes: `data.watermark` (Task 4), `useBrandStore().watermarkText` (Task 5).
- Produces: `<Watermark text={string} />`; `useChatStore().watermark: boolean`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/watermark.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Watermark } from '../components/DesignStudio/Watermark'
import { useChatStore } from '../store/chatStore'

describe('Watermark overlay', () => {
  it('renders the configured text and is inert', () => {
    render(<Watermark text="MADHATS PREVIEW" />)
    const el = screen.getByTestId('canvas-watermark')
    // aria-hidden: it is decoration over content the customer can already read.
    expect(el).toHaveAttribute('aria-hidden', 'true')
    // pointer-events-none: it sits over the Konva stage; without this it would
    // swallow every drag, click and transform on the canvas beneath it.
    expect(el.className).toContain('pointer-events-none')
  })

  it('chatStore parses the backend watermark flag', () => {
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'review_design', { watermark: true })
    expect(useChatStore.getState().watermark).toBe(true)
  })

  it('defaults to watermarked when the backend sends no flag', () => {
    // A shared-tail state (generating / verify / refine / quote) has no registry
    // step, so no flag is sent — and the design IS finished in all of them.
    useChatStore.setState({ watermark: false })
    useChatStore.getState().applyResponse('hi', 'generating', {})
    expect(useChatStore.getState().watermark).toBe(true)
  })
})
```

- [ ] **Step 2: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/watermark.test.tsx
```

Expected: FAIL — cannot resolve `../components/DesignStudio/Watermark`.

- [ ] **Step 3: Write the component**

Create `frontend/src/components/DesignStudio/Watermark.tsx`:

```tsx
/**
 * A repeating diagonal watermark drawn OVER a design.
 *
 * Deliberately a DOM sibling of the Konva stage, never a Konva layer. A DOM
 * node cannot appear in `stage.toDataURL()`, which makes two failure modes
 * impossible by construction rather than by discipline:
 *
 *  - the decorations-only layout guide (canvasFlatten.flattenStage) stays
 *    clean, so the image model never renders a watermark onto the cap;
 *  - the WYSIWYG preview (flattenFull) is never double-stamped, because
 *    delivery.py already burns the same text into the emailed copy server-side.
 *
 * That is also why there is no EXPORT_HIDE_NAME tagging here — there is
 * nothing for an export to hide.
 *
 * `text` comes from the admin-configured `watermark_text` app setting via
 * /storefront, so the canvas and the email always agree.
 */
export function Watermark({ text }: { text: string }) {
  const tile = 220
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${tile}" height="${tile}">
      <text x="50%" y="50%" transform="rotate(-30 ${tile / 2} ${tile / 2})"
            text-anchor="middle" dominant-baseline="middle"
            font-family="Helvetica, Arial, sans-serif" font-size="17"
            font-weight="700" letter-spacing="1.5"
            fill="rgb(255 255 255 / 0.42)">${text}</text>
    </svg>`
  return (
    <div
      data-testid="canvas-watermark"
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 z-10 mix-blend-overlay"
      style={{
        backgroundImage: `url("data:image/svg+xml;utf8,${encodeURIComponent(svg)}")`,
        backgroundRepeat: 'repeat',
      }}
    />
  )
}
```

- [ ] **Step 4: Parse the flag in `chatStore`**

In `parseData` (`chatStore.ts:100-140`), add before the `return`:

```ts
  // Absent on a shared-tail turn (no registry step, so the backend sends no
  // flag) — and the design is finished in every one of those states, so the
  // safe default is watermarked. Only an explicit `false` clears it.
  const watermark = data.watermark !== false
```

Add `watermark` to the returned object, to `ChatStoreState`, and to the initial state (`watermark: false` — nothing is designed yet at mount).

In `hydrate`, set `watermark` from the same parse so a resumed session at `review_design` comes back watermarked.

- [ ] **Step 5: Mount it over the stage**

In `Surface.tsx`, add the imports:

```tsx
import { Watermark } from './Watermark'
import { useBrandStore } from '../../store/brandStore'
```

Read the two values alongside the other store reads near the top of the component:

```tsx
  const watermark = useChatStore(s => s.watermark)
  const watermarkText = useBrandStore(s => s.watermarkText)
```

Replace the stage wrapper (currently `<div data-testid="canvas-stage-wrap" className="w-full shrink-0 flex justify-center">`) with:

```tsx
          <div data-testid="canvas-stage-wrap" className="w-full shrink-0 flex justify-center">
            {/* `relative` scopes the watermark's `absolute inset-0` to exactly
                the stage box. It must wrap ONLY the stage — on the outer column
                it would tile over the Adjust panel and the Done button too. */}
            <div className="relative">
              <CanvasStage stageRef={stageRef} locked={stageLocked} />
              {watermark && <Watermark text={watermarkText} />}
            </div>
          </div>
```

- [ ] **Step 6: Prove the overlay is absent from both exports**

Append to `frontend/src/__tests__/watermark.test.tsx`:

```tsx
import Konva from 'konva'
import { flattenFull, flattenStage } from '../lib/canvasFlatten'

it('is structurally absent from both flatten paths', () => {
  // The guarantee is that a DOM node cannot enter stage.toDataURL(). Assert it
  // against a real Konva stage rather than trusting the argument: a future
  // refactor that moved the watermark INTO the Konva tree would silently start
  // baking it into the layout guide the image model consumes.
  const container = document.createElement('div')
  document.body.appendChild(container)
  const stage = new Konva.Stage({ container, width: 480, height: 480 })
  stage.add(new Konva.Layer())

  const overlay = document.createElement('div')
  overlay.setAttribute('data-testid', 'canvas-watermark')
  container.appendChild(overlay)

  expect(() => flattenStage(stage)).not.toThrow()
  expect(() => flattenFull(stage)).not.toThrow()
  expect(stage.find((n: Konva.Node) => n.getAttr('data-testid') === 'canvas-watermark')).toHaveLength(0)
  stage.destroy()
  container.remove()
})
```

- [ ] **Step 7: Run and verify passing**

```
docker compose exec -T frontend npx vitest run src/__tests__/watermark.test.tsx src/__tests__/chatStore.test.ts src/__tests__/canvasFlattenExportSize.test.ts
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/DesignStudio/Watermark.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/store/chatStore.ts frontend/src/__tests__/watermark.test.tsx
git commit -m "feat(canvas): watermark the design from the review onward

A DOM sibling of the Konva stage, never a Konva layer — so it cannot enter
stage.toDataURL(), which makes two failure modes impossible by construction:
the decorations-only layout guide stays clean (a watermark in it would be
RENDERED onto the cap by the image model), and the WYSIWYG preview is never
double-stamped, since delivery.py already burns the same text server-side.

The absence is asserted against a real Konva stage rather than assumed, so a
later refactor that moved it into the Konva tree fails loudly.

Text comes from the admin-configured watermark_text. Visibility comes from the
backend flag; a turn with no flag defaults to watermarked, which is correct for
the shared-tail states where the design is already finished.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: One face renderer, two sizes

`FaceThumbnails.tsx` hardcodes `TW = TH = 64` and `SCALE = TW / STAGE_W` at module scope, so `ElementThumb` and `FaceThumbStage` can only draw a 64px thumbnail. The review dialog needs the same render at ~320px. Extract and parameterise — do **not** copy the renderer, or the two will drift and the dialog will stop matching the rail.

**Files:**
- Create: `frontend/src/components/DesignStudio/FaceStage.tsx`
- Modify: `frontend/src/components/DesignStudio/FaceThumbnails.tsx`
- Test: `frontend/src/__tests__/faceStage.test.tsx`

**Interfaces:**
- Consumes: `useCanvasStore`, `canvasGeometry` helpers, `STAGE_W` (all existing).
- Produces: `export function FaceStage({ face, size, fontsTick })`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/faceStage.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { FaceStage } from '../components/DesignStudio/FaceStage'
import { useCanvasStore } from '../store/canvasStore'

describe('FaceStage', () => {
  it('renders at the requested size', () => {
    useCanvasStore.setState({ activeFace: 'front' })
    const { container } = render(<FaceStage face="front" size={320} fontsTick={0} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).not.toBeNull()
    expect(canvas!.getAttribute('width')).toBe('320')
  })

  it('renders at thumbnail size too, from the same component', () => {
    const { container } = render(<FaceStage face="front" size={64} fontsTick={0} />)
    expect(container.querySelector('canvas')!.getAttribute('width')).toBe('64')
  })
})
```

- [ ] **Step 2: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/faceStage.test.tsx
```

Expected: FAIL — cannot resolve `FaceStage`.

- [ ] **Step 3: Extract**

Create `frontend/src/components/DesignStudio/FaceStage.tsx` by moving `useThumbImage`, `ElementThumb` and `FaceThumbStage` out of `FaceThumbnails.tsx`, replacing every module-scope `TW`, `TH` and `SCALE` with values derived from a `size` prop:

- `ElementThumb` takes `{ el, size }`; inside it, `const TW = size, TH = size, SCALE = size / STAGE_W`.
- `FaceThumbStage` is renamed `FaceStage` and takes `{ face, size, fontsTick }`; every `TW`/`TH` becomes `size`, and it passes `size` down to each `<ElementThumb>`.
- Export `FaceStage`; keep `useThumbImage` and `ElementThumb` module-private.

Every other line — the `centerPosition` / `offsetX` / `offsetY` centring, the `estimateTextBox` fallback, the `multiply` colourway `Rect`, the `key={fontsTick}` redraw, `listening={false}` — is moved **verbatim**. The centring mirrors `nodes.tsx` exactly and a rotated element diverges visibly if it is altered.

- [ ] **Step 4: Rewire the rail**

In `FaceThumbnails.tsx`, delete the moved code, `import { FaceStage } from './FaceStage'`, and replace the `<FaceThumbStage face={f} fontsTick={fontsTick} />` call with:

```tsx
              <FaceStage face={f} size={64} fontsTick={fontsTick} />
```

Keep `TW`/`TH` only if other code in the file still reads them; otherwise delete them.

- [ ] **Step 5: Run the tests and verify nothing regressed**

```
docker compose exec -T frontend npx vitest run src/__tests__/faceStage.test.tsx src/__tests__/designStudioCenterPivotSmoke.test.tsx src/__tests__/surfaceDirective.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```

Expected: PASS, and zero type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/FaceStage.tsx frontend/src/components/DesignStudio/FaceThumbnails.tsx frontend/src/__tests__/faceStage.test.tsx
git commit -m "refactor(canvas): extract FaceStage so one renderer serves both sizes

FaceThumbnails hardcoded TW/TH/SCALE at module scope, so its static per-face
render could only ever be 64px. The review dialog needs the same render large.
Copying it would let the two drift and the dialog would stop matching the rail,
so the renderer is extracted and parameterised by size instead. The centring
maths is moved verbatim — it mirrors nodes.tsx, and a rotated element visibly
diverges if it is altered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: The all-views confirm dialog

**Files:**
- Create: `frontend/src/components/DesignStudio/ReviewDialog.tsx`
- Modify: `frontend/src/components/DesignStudio/Surface.tsx`
- Test: `frontend/src/__tests__/reviewDialog.test.tsx`

**Interfaces:**
- Consumes: `FaceStage` (Task 7), `Watermark` (Task 6), `useChatStore().chatState`, `useCanvasStore().faces`.
- Produces: `<ReviewDialog open onConfirm onRework onClose />`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/reviewDialog.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ReviewDialog } from '../components/DesignStudio/ReviewDialog'
import { useCanvasStore } from '../store/canvasStore'

function seedTwoDecoratedFaces() {
  useCanvasStore.setState({
    faces: {
      front: [{ id: 'a', type: 'text', content: 'MADHATS', x: 0.3, y: 0.3,
                width: 0.3, height: 0.1, rotation: 0, zIndex: 0 }],
      back:  [{ id: 'b', type: 'text', content: 'EST 1998', x: 0.3, y: 0.3,
                width: 0.3, height: 0.1, rotation: 0, zIndex: 0 }],
      left: [], right: [],
    } as never,
  })
}

describe('ReviewDialog', () => {
  it('renders nothing when closed', () => {
    const { container } = render(
      <ReviewDialog open={false} onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows only the decorated faces, each watermarked', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    expect(screen.getByText('Front')).toBeInTheDocument()
    expect(screen.getByText('Back')).toBeInTheDocument()
    // An undecorated face is just the blank product photo — nothing to review.
    expect(screen.queryByText('Left')).not.toBeInTheDocument()
    expect(screen.getAllByTestId('canvas-watermark')).toHaveLength(2)
  })

  it('is an accessible modal', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    const dlg = screen.getByRole('dialog')
    expect(dlg).toHaveAttribute('aria-modal', 'true')
    expect(dlg).toHaveAccessibleName()
  })

  it('mirrors the two review chips', () => {
    seedTwoDecoratedFaces()
    const onConfirm = vi.fn(); const onRework = vi.fn()
    render(<ReviewDialog open onConfirm={onConfirm} onRework={onRework} onClose={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Looks great, send it' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: "I'd like to rework it" }))
    expect(onRework).toHaveBeenCalledTimes(1)
  })

  it('closes on Escape', () => {
    seedTwoDecoratedFaces()
    const onClose = vi.fn()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={onClose} />)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})
```

The chip labels are **exact literals** — `state_machine_v2.resolve_chip` matches them by identity (`canvas_steps.REVIEW_DESIGN.chips`). A typo here means the dialog's buttons send a message the backend reads as free text and hands to the interpreter.

- [ ] **Step 2: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/reviewDialog.test.tsx
```

Expected: FAIL — cannot resolve `ReviewDialog`.

- [ ] **Step 3: Implement**

Create `frontend/src/components/DesignStudio/ReviewDialog.tsx`:

```tsx
import { useEffect, useRef } from 'react'
import { FACES, useCanvasStore, type Face } from '../../store/canvasStore'
import { useBrandStore } from '../../store/brandStore'
import { FaceStage } from './FaceStage'
import { Watermark } from './Watermark'

const LABELS: Record<Face, string> = { front: 'Front', back: 'Back', left: 'Left', right: 'Right' }
const VIEW_PX = 300

/** Exact chip labels from canvas_steps.REVIEW_DESIGN. resolve_chip matches them
 *  by identity, so a typo here becomes free text the interpreter has to guess
 *  at — which is the whole class of bug Workstream A exists to remove. */
const CONFIRM_LABEL = 'Looks great, send it'
const REWORK_LABEL = "I'd like to rework it"

/**
 * The pre-submit confirm gate: every decorated face, watermarked, in one place.
 *
 * It renders from `canvasStore` through the same `FaceStage` the face rail
 * uses, so it needs no flatten, no upload and no new endpoint, and it can never
 * show something the canvas doesn't.
 *
 * Closable on purpose: the canvas behind it is watermarked in this state
 * (state_machine_v2._WATERMARKED_STEPS), so letting the customer look at it
 * costs nothing, and trapping them in a modal to look at their own design is
 * hostile.
 */
export function ReviewDialog({ open, onConfirm, onRework, onClose }: {
  open: boolean
  onConfirm: () => void
  onRework: () => void
  onClose: () => void
}) {
  const faces = useCanvasStore(s => s.faces)
  const watermarkText = useBrandStore(s => s.watermarkText)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
      if (e.key !== 'Tab' || !panelRef.current) return
      // Focus trap: a modal that lets Tab escape to the page behind it is not
      // a modal for a keyboard or screen-reader user.
      const f = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
      if (f.length === 0) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    panelRef.current?.querySelector<HTMLElement>('button')?.focus()
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  const decorated = (FACES as Face[]).filter(f => faces[f].length > 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-0 md:p-6">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-dialog-title"
        className="flex h-full w-full flex-col overflow-hidden bg-surface md:h-auto md:max-h-[90vh] md:max-w-3xl md:rounded-2xl"
      >
        <div className="flex-none border-b border-border px-5 py-4">
          <h2 id="review-dialog-title" className="text-base font-semibold text-textPrimary">
            Review your design
          </h2>
          <p className="mt-1 text-sm text-textMuted">
            Here is every view you have decorated. Check each one before we send it to our team.
          </p>
        </div>

        {/* Stacked and scrollable on a phone; a grid once there is room. */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {decorated.map(f => (
              <figure key={f} className="m-0">
                <div className="relative mx-auto w-fit overflow-hidden rounded-xl border border-border">
                  <FaceStage face={f} size={VIEW_PX} fontsTick={0} />
                  <Watermark text={watermarkText} />
                </div>
                <figcaption className="mt-2 text-center text-sm font-medium text-textPrimary">
                  {LABELS[f]}
                </figcaption>
              </figure>
            ))}
          </div>
        </div>

        <div className="flex flex-none flex-col gap-2 border-t border-border px-5 py-4 sm:flex-row sm:justify-end">
          <button onClick={onRework}
            className="rounded-full border border-border px-5 py-2 text-sm font-medium text-textPrimary hover:bg-surfaceAlt">
            {REWORK_LABEL}
          </button>
          <button onClick={onConfirm}
            className="rounded-full bg-canvasAccent px-5 py-2 text-sm font-semibold text-white hover:bg-canvasAccentHover">
            {CONFIRM_LABEL}
          </button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Mount it in `Surface.tsx`**

Add the import and a local open flag driven by chat state, then render it at the end of the component's JSX (as a sibling of `<GraphicsPicker …/>`):

```tsx
import { ReviewDialog } from './ReviewDialog'
```

```tsx
  const chatState = useChatStore(s => s.chatState)
  const [reviewOpen, setReviewOpen] = useState(false)
  // Open on ARRIVAL at the review, not on every render while there — otherwise
  // dismissing it would immediately re-open. Leaving the state resets the latch.
  const wasReviewing = useRef(false)
  useEffect(() => {
    const reviewing = chatState === 'review_design'
    if (reviewing && !wasReviewing.current) setReviewOpen(true)
    if (!reviewing) setReviewOpen(false)
    wasReviewing.current = reviewing
  }, [chatState])

  function sendReview(label: string) {
    setReviewOpen(false)
    const sid = useSessionStore.getState().sessionId
    if (sid) void useChatStore.getState().sendMessage(sid, label)
  }
```

```tsx
      <ReviewDialog
        open={reviewOpen}
        onConfirm={() => sendReview('Looks great, send it')}
        onRework={() => sendReview("I'd like to rework it")}
        onClose={() => setReviewOpen(false)}
      />
```

- [ ] **Step 5: Run the tests and verify passing**

```
docker compose exec -T frontend npx vitest run src/__tests__/reviewDialog.test.tsx src/__tests__/surfaceDirective.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```

Expected: PASS, zero type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/ReviewDialog.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/reviewDialog.test.tsx
git commit -m "feat(canvas): all-views confirm dialog at the review step

Every decorated face, watermarked, in one modal — so the customer confirms
what they actually designed rather than whichever face happened to be active.

It renders from canvasStore through the same FaceStage the face rail uses, so
it needs no flatten, no upload and no new endpoint, and it cannot show
something the canvas doesn't. Undecorated faces are omitted: those are just the
blank product photo.

The two buttons send the EXACT chip labels canvas_steps.REVIEW_DESIGN ships, so
they resolve by identity with no interpreter call. Closable on purpose — the
canvas behind it is watermarked in this state.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# WORKSTREAM C — Focus cue

## Task 9: Filled column headers on lifted cards

Replaces `ring-2 ring-canvasAccent` + `shadow-[0_0_18px_-4px_…]` + blanket `opacity-60`. The blanket opacity is the main offender: it fades live text to grey, so the resting half reads as *disabled* rather than *not your turn*.

**Files:**
- Create: `frontend/src/components/CustomiseStudio/ColumnHeader.tsx`
- Modify: `frontend/src/components/CustomiseStudio/index.tsx`
- Test: `frontend/src/__tests__/customiseStudioFocus.test.tsx` (exists — update)

**Interfaces:**
- Consumes: `useActiveSurface()` (unchanged).
- Produces: `<ColumnHeader name instruction active />`.

- [ ] **Step 1: Read the existing test and note what it pins**

```
docker compose exec -T frontend cat src/__tests__/customiseStudioFocus.test.tsx
```

Assertions on `ring-2`, `opacity-60` or the `▶` pill are being deliberately replaced. Assertions on `data-active`, `role="status"` and the **absence** of `pointer-events-none` are invariants — keep them.

- [ ] **Step 2: Rewrite the test for the new cue**

Replace the class-name assertions in `customiseStudioFocus.test.tsx` with:

```tsx
  it('fills the active column header and leaves the resting one quiet', () => {
    renderStudioWithChatActive()   // reuse the file's existing helper
    const chat = screen.getByTestId('chat-column-wrap')
    const canvas = screen.getByTestId('canvas-column')
    expect(chat).toHaveAttribute('data-active', 'true')
    expect(canvas).toHaveAttribute('data-active', 'false')
    // The active header states the turn; the resting one just names its half.
    expect(screen.getByText('Your turn — answer here')).toBeInTheDocument()
    expect(screen.getByText('Your design')).toBeInTheDocument()
  })

  it('announces the active surface without relying on colour', () => {
    renderStudioWithChatActive()
    expect(screen.getByRole('status')).toHaveTextContent('Your turn — answer here')
  })

  it('never blocks pointer events on the resting column', () => {
    // Dimming is a cue, not a lock — real locking is per-affordance. Blocking
    // events here would stop the customer scrolling back through the thread or
    // re-reading the cap, which they must always be able to do.
    renderStudioWithChatActive()
    expect(screen.getByTestId('canvas-column').className).not.toContain('pointer-events-none')
  })

  it('does not dim the resting column wholesale', () => {
    // opacity-60 on the container faded live text to grey, so the resting half
    // read as disabled or mid-error. Only its CONTENT softens now.
    renderStudioWithChatActive()
    expect(screen.getByTestId('canvas-column').className).not.toContain('opacity-60')
  })
```

- [ ] **Step 3: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/customiseStudioFocus.test.tsx
```

Expected: FAIL — the header text does not exist yet.

- [ ] **Step 4: Write `ColumnHeader`**

Create `frontend/src/components/CustomiseStudio/ColumnHeader.tsx`:

```tsx
/**
 * The permanent header strip on each half of the split screen.
 *
 * Active: filled with the canvas accent, white text, stating the turn.
 * Resting: a quiet grey label naming the half.
 *
 * A fixed NAME (not a status word) when resting, because it teaches a
 * first-time customer what the two halves are — the accent fill already
 * carries the whose-turn signal, so the label doesn't have to.
 *
 * `role="status"` only when active: the cue must be announced, and must never
 * be colour-only, but two live status regions would announce on every flip.
 */
export function ColumnHeader({ name, instruction, active }: {
  name: string
  instruction: string
  active: boolean
}) {
  return (
    <div
      {...(active ? { role: 'status' } : {})}
      className={`flex h-8 flex-none items-center gap-2 px-4 text-xs font-semibold transition-colors duration-300 ${
        active
          ? 'bg-canvasAccent text-white'
          : 'border-b border-border bg-surfaceAlt text-textMuted'
      }`}
    >
      <span
        aria-hidden="true"
        className={`h-1.5 w-1.5 flex-none rounded-full ${
          active ? 'animate-pulse bg-white' : 'bg-border'
        }`}
      />
      {active ? instruction : name}
    </div>
  )
}
```

- [ ] **Step 5: Rework `CustomiseStudio/index.tsx`**

Delete `FocusPill`, `ACTIVE_CLASSES` and `INACTIVE_CLASSES`. Replace them with:

```tsx
/** The active card lifts off the desk. No outline and no outward glow: a ring
 *  around a whole column is a developer's cue, and the glow bled into the
 *  neighbouring panel. */
const ACTIVE_CARD = 'shadow-[0_10px_24px_-10px_rgba(28,25,23,0.30),0_2px_6px_-2px_rgba(28,25,23,0.10)] border-borderStrong'
const RESTING_CARD = 'bg-surfaceAlt/40'
/** Applied to the resting column's CONTENT, never its container. The old
 *  blanket `opacity-60` faded live text to grey, so the half read as disabled
 *  rather than "not your turn". */
const RESTING_CONTENT = 'opacity-50 transition-opacity duration-300'
```

Rewrite the two column wrappers:

```tsx
      <div className="flex min-h-0 flex-1 flex-col gap-2 bg-base p-2 md:flex-row">
        <div
          data-testid="canvas-column"
          data-active={String(canvasActive)}
          className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 ${canvasActive ? ACTIVE_CARD : RESTING_CARD}`}
        >
          <ColumnHeader name="Your design" instruction="Your turn — design here" active={canvasActive} />
          <div className={`flex min-h-0 min-w-0 flex-1 ${canvasActive ? '' : RESTING_CONTENT}`}>
            <DesignStudioSurface />
          </div>
        </div>

        <div
          data-testid="chat-column-wrap"
          data-active={String(!canvasActive)}
          className={`flex h-[45vh] w-full min-h-0 flex-none flex-col overflow-hidden rounded-xl border border-border bg-surface transition-shadow duration-300 md:h-auto md:w-[360px] lg:w-[420px] xl:w-[480px] 2xl:w-[560px] ${!canvasActive ? ACTIVE_CARD : RESTING_CARD}`}
        >
          <ColumnHeader
            name={personaName}
            instruction="Your turn — answer here"
            active={!canvasActive && chatAnswerable}
          />
          <div className={`flex min-h-0 flex-1 flex-col ${!canvasActive ? '' : RESTING_CONTENT}`}>
            <ChatColumn />
          </div>
        </div>
      </div>
```

Add the import and the persona read at the top of the component:

```tsx
import { ColumnHeader } from './ColumnHeader'
import { useBrandStore } from '../../store/brandStore'
```

```tsx
  const personaName = useBrandStore(s => s.personaName) || 'Ricardo'
```

`personaName` already exists in `brandStore.ts` (declared line 66, initialised `''` line 74, set from `sf.persona_name` line 81) — nothing to add. The `|| 'Ricardo'` covers only the pre-fetch window, since the initial value is the empty string. Do not hardcode the persona: it is per-store.

Note `chatAnswerable` is already computed in this file from `CHAT_UNANSWERABLE_STATES`; passing it into `active` is what keeps `await_email_verify` / `generating` from claiming the turn while the input is dead.

If `borderStrong` is not in `tailwind.config.js`, use `border-border` and drop the token rather than adding one for a single use.

- [ ] **Step 6: Run and verify passing**

```
docker compose exec -T frontend npx vitest run src/__tests__/customiseStudioFocus.test.tsx src/__tests__/CustomiseStudio.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```

Expected: PASS, zero type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CustomiseStudio/ColumnHeader.tsx frontend/src/components/CustomiseStudio/index.tsx frontend/src/__tests__/customiseStudioFocus.test.tsx
git commit -m "feat(studio): production-grade focus cue — filled headers on lifted cards

The old cue was a 2px accent ring round a whole column, an 18px outward glow
that bled into the neighbouring panel, and a blanket opacity-60. The opacity
was the real problem: it faded live text to grey, so the resting half read as
disabled or mid-error rather than simply not-your-turn.

Now each half is a card with a permanent header. The active card lifts with a
layered shadow and its header fills with the canvas accent, stating the turn;
the resting card names itself in grey and softens only its CONTENT, so headers
and structure stay at full contrast. This also works on a phone, where the
halves stack and a ring around a column you can only half see said nothing.

useActiveSurface is untouched, role=status moves onto the active header (so the
cue is still announced and never colour-only), and pointer-events are still
never blocked — dimming is a cue, real locking stays per-affordance.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# WORKSTREAM D — Message attribution

## Task 10: A lane on every message, a name on speaker change

Today attribution is bubble side + colour only (`ChatColumn.tsx:451-465`).

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:451-465`
- Test: `frontend/src/__tests__/chatAttribution.test.tsx`

**Interfaces:**
- Consumes: `useBrandStore().personaName` (Task 9).
- Produces: nothing consumed later.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/chatAttribution.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChatColumn } from '../components/CustomiseStudio/ChatColumn'
import { useChatStore } from '../store/chatStore'

function seed(msgs: { role: 'user' | 'assistant'; text: string }[]) {
  useChatStore.setState({
    messages: msgs.map((m, i) => ({ id: String(i), role: m.role, text: m.text })),
    chatState: 'ask_quantity', options: [], sending: false,
  })
}

describe('chat attribution', () => {
  it('gives every message a lane', () => {
    seed([
      { role: 'assistant', text: 'How many caps do you need?' },
      { role: 'user', text: '45' },
      { role: 'assistant', text: 'When do you need these by?' },
      { role: 'assistant', text: 'Select an option below.' },
    ])
    render(<ChatColumn />)
    expect(screen.getAllByTestId('msg-lane')).toHaveLength(4)
  })

  it('names the speaker only when the speaker changes', () => {
    seed([
      { role: 'assistant', text: 'When do you need these by?' },
      { role: 'assistant', text: 'Select an option below.' },
      { role: 'user', text: '2 weeks' },
      { role: 'assistant', text: 'Noted.' },
    ])
    render(<ChatColumn />)
    // Two assistant runs -> two assistant name lines, not three.
    expect(screen.getAllByText(/Design assistant/)).toHaveLength(2)
    expect(screen.getAllByText('You')).toHaveLength(1)
  })

  it('labels the customer "You", never their captured name', () => {
    // The name is PII and this element repeats on every run of their messages.
    useChatStore.setState({ collectedName: 'Satish' })
    seed([{ role: 'user', text: '45' }])
    render(<ChatColumn />)
    expect(screen.getByText('You')).toBeInTheDocument()
    expect(screen.queryByText(/Satish/)).not.toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/chatAttribution.test.tsx
```

Expected: FAIL — no `msg-lane` testids.

- [ ] **Step 3: Implement**

Replace `ChatColumn.tsx:451-465` with:

```tsx
        {messages.map((msg, i) => {
          const mine = msg.role === 'user'
          // The LANE is on every message — it is the per-message identifier.
          // The NAME only when the speaker changes: v2 routinely emits several
          // assistant bubbles per turn (data.extra_replies, plus the
          // reply/instruction split), and repeating an identical header on
          // consecutive bubbles reads as padding, especially on a phone.
          const startsRun = i === 0 || messages[i - 1].role !== msg.role
          return (
            <div key={msg.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div
                data-testid="msg-lane"
                className={`flex max-w-[88%] flex-col gap-1 md:max-w-md ${
                  mine
                    ? 'items-end border-r-2 border-chatUserBubble pr-2'
                    : 'items-start border-l-2 border-canvasAccent pl-2'
                }`}
              >
                {startsRun && (
                  <span className="text-[11px] font-semibold leading-none text-textMuted">
                    {mine ? 'You' : (
                      <>
                        {personaName}
                        <span className="font-normal text-textMuted/70"> · Design assistant</span>
                      </>
                    )}
                  </span>
                )}
                <div
                  className={`whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
                    mine
                      ? 'rounded-br-sm bg-chatUserBubble text-white'
                      : 'rounded-bl-sm border border-border bg-surface text-textPrimary shadow-sm'
                  }`}
                >
                  {linkify(msg.text)}
                </div>
              </div>
            </div>
          )
        })}
```

Add near the component's other store reads:

```tsx
  const personaName = useBrandStore(s => s.personaName) || 'Ricardo'
```

with `import { useBrandStore } from '../../store/brandStore'`.

Note `max-w-[80%]` becomes `max-w-[88%]`: there is no avatar column, so the lane provides the offset and the bubble can use the width.

- [ ] **Step 4: Run and verify passing**

```
docker compose exec -T frontend npx vitest run src/__tests__/chatAttribution.test.tsx src/__tests__/ChatColumn.test.tsx
docker compose exec -T frontend npx tsc --noEmit
```

Expected: PASS, zero type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomiseStudio/ChatColumn.tsx frontend/src/__tests__/chatAttribution.test.tsx
git commit -m "feat(chat): attribute every message with a lane, name on speaker change

Attribution was bubble side + colour only, which a non-technical customer has
no reason to read as 'who said this'. Every message now carries a coloured
lane — accent for the assistant, the user-bubble colour for the customer — and
that lane is the per-message identifier.

The NAME line renders only when the speaker changes, because v2 routinely emits
several assistant bubbles per turn (extra_replies, plus the reply/instruction
split) and an identical repeated header reads as padding on a phone.

The customer's label is the literal 'You', never their captured name: this
element repeats on every run of their messages and the name is PII.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

# Mobile + verification

## Task 11: Phone layout

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/index.tsx` (the chat split)
- Modify: `frontend/src/components/DesignStudio/Surface.tsx` (Adjust-panel clamp)
- Test: `frontend/src/__tests__/mobileLayout.test.tsx`

**Interfaces:** consumes Tasks 8–10; produces nothing.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/mobileLayout.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { CustomiseStudio } from '../components/CustomiseStudio'

// jsdom performs NO layout, so these pin class names, not pixels. That is the
// honest limit of what can be checked here — see the plan's verification note.
describe('phone layout', () => {
  it('gives the chat a flexible share, not a hard 45vh', () => {
    render(<CustomiseStudio />)
    const chat = screen.getByTestId('chat-column-wrap')
    expect(chat.className).toContain('basis-[45vh]')
    expect(chat.className).toContain('min-h-0')
    expect(chat.className).not.toMatch(/(^|\s)h-\[45vh\]/)
  })

  it('stacks the two halves on a phone and rows them from md', () => {
    render(<CustomiseStudio />)
    const row = screen.getByTestId('canvas-column').parentElement!
    expect(row.className).toContain('flex-col')
    expect(row.className).toContain('md:flex-row')
  })
})
```

And in `reviewDialog.test.tsx`, append the full-bleed assertion — a shrunken
desktop modal on a 360px screen leaves the views unreadable:

```tsx
  it('is full-bleed on a phone and a centred panel from md', () => {
    seedTwoDecoratedFaces()
    render(<ReviewDialog open onConfirm={vi.fn()} onRework={vi.fn()} onClose={vi.fn()} />)
    const panel = screen.getByRole('dialog')
    expect(panel.className).toContain('h-full')
    expect(panel.className).toContain('w-full')
    expect(panel.className).toContain('md:h-auto')
    expect(panel.className).toContain('md:max-w-3xl')
  })
```

- [ ] **Step 2: Run and verify failure**

```
docker compose exec -T frontend npx vitest run src/__tests__/mobileLayout.test.tsx
```

Expected: FAIL on the `basis-[45vh]` assertion.

- [ ] **Step 3: Make the chat split flexible**

In `CustomiseStudio/index.tsx`, change the chat wrapper's mobile sizing from `h-[45vh] flex-none` to:

```
basis-[45vh] grow-0 shrink min-h-0 md:basis-auto
```

Rationale to keep in a comment: a hard `h-[45vh]` reserves the same height whether the thread is two bubbles or twenty; `basis` + `shrink` lets it give height back to the canvas when the chat is short, which matters most on the phone where both halves are on one screen.

- [ ] **Step 4: Budget the new headers into the Adjust clamp**

The `SelectedToolbar` stacked variant clamps to `max-h-[9rem]` below `md` (CLAUDE.md: `vh` measures the viewport, not the column, so a flat `45vh` cap would let the sticky panel hide the cap). Two 32px column headers now sit in that column. Reduce the mobile clamp to `max-h-[7.5rem]` and leave `md:max-h-[45vh]` unchanged.

- [ ] **Step 5: Widen the bubbles**

Already done in Task 10 (`max-w-[88%]`). Verify no other `max-w-[80%]` remains in `ChatColumn.tsx`:

```
docker compose exec -T frontend sh -c "grep -n 'max-w-\[80%\]' src/components/CustomiseStudio/ChatColumn.tsx || echo CLEAN"
```

Expected: `CLEAN`.

- [ ] **Step 6: Run and verify passing**

```
docker compose exec -T frontend npx vitest run src/__tests__/mobileLayout.test.tsx src/__tests__/adjustPanelPlacement.test.tsx src/__tests__/selectedToolbarPlacement.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CustomiseStudio/index.tsx frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/mobileLayout.test.tsx
git commit -m "feat(studio): phone layout for the new headers and dialog

The chat's hard h-[45vh] reserved the same height whether the thread was two
bubbles or twenty; basis + shrink lets it hand height back to the canvas, which
matters most on a phone where both halves share one screen. The two new column
headers are budgeted into the sub-md Adjust-panel clamp (7.5rem, was 9rem)
rather than being allowed to push the cap off the bottom. Bubbles widen to 88%
now that the attribution lane provides the offset instead of an avatar column.

NOT VERIFIED IN A BROWSER: sub-768px has never been observed on this project —
resize_window is a no-op in this environment and devtools MCP cannot attach.
These tests pin class names; jsdom performs no layout. Needs a real phone.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: Full verification and project memory

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Backend, flag off**

```
MSYS_NO_PATHCONV=1 docker compose exec -T -e CANVAS_ORCHESTRATOR_V2=false backend python -m pytest -q
```

Record the number. Expected ≥ 1259 + the new tests, with **0 failures**.

- [ ] **Step 2: The five v2 suites, flag on**

```
MSYS_NO_PATHCONV=1 docker compose exec -T -e CANVAS_ORCHESTRATOR_V2=true backend python -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py \
  tests/test_state_machine_v2.py tests/test_canvas_steps.py
```

Record the number. Expected ≥ 330 + new, 0 failures.

- [ ] **Step 3: Frontend**

```
docker compose exec -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx
docker compose exec -T frontend npx vitest run src/admin
docker compose exec -T frontend npx tsc --noEmit
```

Record the numbers. Zero type errors.

- [ ] **Step 4: Drive it in a real browser**

Start the stack (`docker compose up -d`), open `http://localhost:5173/?product_id=<id>` with `CANVAS_ORCHESTRATOR_V2=true`, and confirm each of these by observation, not inference:

1. At `ask_name` the chat card is lifted with an accent-filled header reading "Your turn — answer here"; the canvas card shows a grey "Your design" header and is NOT wholesale faded.
2. Messages show a lane on each bubble, with the name line only at the start of each speaker's run.
3. At `logo_adjust` the cue flips to the canvas. **`LOGO_ADJUST` auto-opens a native file dialog, which blocks the automation channel** — patch `HTMLInputElement.prototype.click` to a no-op for `type=file`, then inject a `File` via `DataTransfer` into `input[aria-label="Upload image"]` and dispatch `change`.
4. No watermark is visible during the design phase.
5. On reaching `review_design` the dialog opens showing every decorated face, each watermarked, and the canvas behind it is watermarked too.
6. "I'd like to rework it" closes the dialog and the watermark **disappears** while editing.
7. Pressing Done returns to the review and the watermark returns.
8. Export integrity: with the watermark visible, run `doRender`'s flatten in the console and confirm the produced PNG has no watermark. This is the one that matters most — a watermark in the layout guide would be rendered onto the cap by the image model.

- [ ] **Step 5: Update CLAUDE.md**

Add a dated entry under "Current implementation state" covering: `_STEP_OWNED_FLAGS` and why the loop-control slots are excluded; `ACK_SYSTEM_PROMPT` + `_ack_is_sane` and the leak they fix; `_norm`'s mojibake repair and that the corrupting hop was/was not found; the backend `watermark` flag and the DOM-overlay-not-Konva-layer rule with its export rationale; `FaceStage` as the single face renderer; the focus-cue and attribution changes. Record the measured test numbers from Steps 1–3, and state plainly that mobile is **not** browser-verified.

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the review-gate + orchestrator-correctness batch in project memory

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Follow-ups (not in this plan)

- Free-text Back ("take me back to quantity"). Task 1 makes the request harmless; making it *work* is a discoverability decision. The structured Back menu already offers the destination.
- Server-rendered watermarked dialog images — offered during design, declined in favour of the no-round-trip client overlay. Revisit if a stripped watermark is ever observed.
- The mojibake root cause, if Task 3 Step 1's timebox expires without a conclusion.
- Real-device mobile verification (Task 11).
