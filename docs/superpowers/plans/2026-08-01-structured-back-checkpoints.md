# Structured Back — Checkpoint Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v2 canvas flow's derived per-slot `↩ Back` with a menu of named checkpoints that restores `collected`, the canvas and the visible chat thread to exactly how they were at that moment.

**Architecture:** Checkpoints are declared as data on the `canvas_steps.REGISTRY` (one per customer-meaningful moment; an element loop pass is one checkpoint). Entering a checkpoint's opener step writes a snapshot row to a new `session_checkpoints` table holding `collected`, the live canvas blob and a chat watermark. Restoring writes the snapshot back, carries forward the out-of-band commit flags, and marks everything after it `superseded_at` (never deletes). Which checkpoints are offerable is a pure predicate over `collected`, so the whole menu computation is unit-testable with plain dicts.

**Tech Stack:** Python 3.12 / FastAPI / supabase-py (SQL migrations, no ORM) · React 18 / Zustand / Vitest · Konva canvas.

**Spec:** `docs/superpowers/specs/2026-08-01-structured-back-checkpoints-design.md`

## Global Constraints

- **v2 canvas only.** Every change is gated on `CANVAS_ORCHESTRATOR_V2` + `flow_mode == "canvas"`. `orchestrator.py` (v1) and non-canvas flows must be byte-identical in behaviour — they never emit `can_go_back`.
- **Never delete rows.** `chat_messages` and `session_checkpoints` are marked `superseded_at`, never removed. The discarded branch must stay reconstructable server-side.
- **Restore carries forward** `CARRY_FORWARD_KEYS = {"email_captured", "email_verified", "lead_id", "quote_requested", "reference_code"}` from the live `collected` onto the restored one. Single named constant. Missing one is silent data loss.
- **Canvas ops and canvas restore are applied in the response handler in `chatStore`, never in a React effect.** An effect fires on change and re-applies on resume.
- **No PII in logs** (security rule 10): never log a name, email, or message body. Log step ids, kinds and counts only.
- **No raw string SQL in application code** (security rule 9) — all DB access via supabase-py query builders. SQL lives only in `backend/supabase/migrations/`.
- **Run backend tests with the flag explicitly set.** The repo-root `.env` defaults `CANVAS_ORCHESTRATOR_V2=true`, which flips unrelated tests red.
- Backend test command (from `backend/`):
  `CANVAS_ORCHESTRATOR_V2=false "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q`
- v2 suites (from `backend/`):
  `CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py tests/test_state_machine_v2.py tests/test_canvas_steps.py`
- Frontend test command (from the **worktree root** — the running docker stack is bind-mounted to the main checkout and cannot see these files):
  `docker compose run --rm --no-deps -T frontend npx vitest run <paths>`
- **Baseline at plan time:** backend 1213 passed (flag off), 311 passed (v2 suites, flag on); frontend 313 passed, 0 failed. Any drop is a regression.

---

## File Structure

**Backend — created**
- `backend/supabase/migrations/20260801000001_session_checkpoints.sql` — the table + `chat_messages.superseded_at`.
- `backend/app/services/conversation/checkpoints.py` — all checkpoint DB work (capture, restore, supersede). Kept out of `orchestrator_v2` so the orchestrator stays a router and the DB work has one home.
- `backend/tests/test_checkpoints.py` — service tests.

**Backend — modified**
- `canvas_steps.py` — `Checkpoint` dataclass, `Step.checkpoint` field, declarations; delete `Step.back_clears`.
- `state_machine_v2.py` — `back_targets()`; delete `last_answered_step` + `_ELEMENT_ADJUST_STEPS`; repurpose `_TERMINAL_FLAGS`.
- `orchestrator_v2.py` — capture hook, `handle_back(session_id, seq)`, `_public` emits `back_targets`; delete `_restart_element`, `_back_used`, `back_removes_element`.
- `api/routes/chat.py` — `/back` takes a body; canvas threaded on every v2 turn.
- `api/routes/sessions.py` — filter superseded chat rows.
- `models/message.py` — `BackRequest`; update the `canvas_design` docstring.
- `prompts.py` — back-menu copy; delete `V2_BACK_RESTART_ACK`.

**Frontend — modified**
- `store/canvasStore.ts` — `restoreSnapshot` (preserves `locked`, unlike `fromCanvasDesign`).
- `store/chatStore.ts` — `backTargets`, `goBackTo`, `canvas_restore`; send the canvas on every v2 turn; delete `backRemovesElement`.
- `components/CustomiseStudio/ChatColumn.tsx` — destination menu; delete the confirm dialog.
- `components/DesignStudio/Surface.tsx` — `Design for <Name>`.
- `lib/api.ts` — `sendBack(sessionId, seq)`.

---

### Task 1: Migration — `session_checkpoints` + superseded chat rows

**Files:**
- Create: `backend/supabase/migrations/20260801000001_session_checkpoints.sql`
- Modify: `backend/app/api/routes/sessions.py:387-393`
- Test: `backend/tests/test_session_supersede_filter.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `session_checkpoints` with columns `id, session_id, seq, kind, label, step_id, collected, canvas_design, chat_watermark, created_at, superseded_at`; column `chat_messages.superseded_at timestamptz`.

- [ ] **Step 1: Write the migration**

Create `backend/supabase/migrations/20260801000001_session_checkpoints.sql`:

```sql
-- =========================================================================
-- session_checkpoints — snapshot-and-restore for the v2 canvas Back menu.
-- Rows are append-only: a restore marks later rows superseded_at, never
-- deletes them, so a discarded branch stays reconstructable for audit.
-- =========================================================================
create table if not exists session_checkpoints (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references design_sessions(id) on delete cascade,
  seq            int  not null,
  kind           text not null,
  label          text not null,
  step_id        text not null,
  collected      jsonb not null,
  canvas_design  jsonb,
  chat_watermark uuid,
  created_at     timestamptz not null default now(),
  superseded_at  timestamptz
);
create unique index if not exists idx_session_checkpoints_seq
  on session_checkpoints(session_id, seq);
create index if not exists idx_session_checkpoints_live
  on session_checkpoints(session_id, seq) where superseded_at is null;

alter table session_checkpoints enable row level security;

-- Chat rows are hidden from the customer after a restore branches past them,
-- but retained for the admin/audit reader.
alter table chat_messages add column if not exists superseded_at timestamptz;
```

- [ ] **Step 2: Write the failing test for the customer-facing filter**

Create `backend/tests/test_session_supersede_filter.py`. This asserts the
customer session reader filters superseded rows and the admin reader does not.
Model it on the existing fake-Supabase pattern in `tests/test_orchestrator_v2.py`
(`_FakeTable` / `_FakeSB`), extended to record `is_` filter calls:

```python
import app.api.routes.sessions as sessions_mod


class _RecordingTable:
    def __init__(self, name, rows, calls):
        self.name, self.rows, self.calls = name, rows, calls

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def is_(self, col, val):
        self.calls.append((self.name, col, val))
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


def test_customer_session_reader_filters_superseded_chat_rows(monkeypatch):
    calls = []
    session_row = {"id": "s1", "state": "ask_name", "collected": {},
                   "share_token": "tok", "flow_mode": "canvas"}

    class _SB:
        def table(self, name):
            rows = [session_row] if name == "design_sessions" else []
            return _RecordingTable(name, rows, calls)

    monkeypatch.setattr(sessions_mod, "get_supabase", lambda: _SB())
    # ... call get_session("tok", request) via the same harness the existing
    # session tests use, then:
    assert ("chat_messages", "superseded_at", "null") in calls
```

> **Note for the implementer:** `backend/tests/` already contains session-route
> tests. Before writing this file, read the closest existing one (grep
> `tests/ -l "get_session"`) and reuse its harness rather than inventing a new
> one. The assertion above is the point of the test; the scaffolding should
> match house style.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_session_supersede_filter.py`
Expected: FAIL — no `is_("superseded_at", "null")` call is recorded.

- [ ] **Step 4: Add the filter**

In `backend/app/api/routes/sessions.py`, the `msgs` query (around line 387) becomes:

```python
    msgs = (
        sb.table("chat_messages")
        .select("role, content, state_before, state_after, created_at")
        .eq("session_id", session["id"])
        # A checkpoint restore marks every row after the restore point
        # superseded rather than deleting it (audit). The customer must see
        # the branched thread, so they are filtered HERE and deliberately not
        # in admin_diagnostics.py, which shows the full history.
        .is_("superseded_at", "null")
        .order("created_at")
        .execute()
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: same command as Step 3.
Expected: PASS.

- [ ] **Step 6: Apply the migration locally and confirm the columns exist**

```bash
cd backend && npx supabase db reset
```

Then confirm in Studio (`http://localhost:54323`) that `session_checkpoints`
exists and `chat_messages.superseded_at` is present.

> **If Supabase/Docker is unavailable:** skip this step and note it in the
> commit message. The migration is still verified by the hosted-apply step in
> Task 10, which is mandatory.

- [ ] **Step 7: Run the full backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q`
Expected: 1214 passed (1213 baseline + 1 new).

- [ ] **Step 8: Commit**

```bash
git add backend/supabase/migrations/20260801000001_session_checkpoints.sql \
        backend/app/api/routes/sessions.py \
        backend/tests/test_session_supersede_filter.py
git commit -m "feat(back): session_checkpoints table + superseded chat rows"
```

---

### Task 2: `Checkpoint` declarations on the registry (pure)

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py`
- Test: `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class Checkpoint` — frozen dataclass with fields `kind: str`, `label: Callable[[dict], str]`, `frozen_when: Callable[[dict], bool]`.
  - `Step.checkpoint: Checkpoint | None = None`.
  - `CHECKPOINT_STEP_IDS: frozenset[S]` — every step id that opens a checkpoint.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_canvas_steps.py`:

```python
def test_exactly_these_steps_open_a_checkpoint():
    """Guard test: adding a registry step forces a deliberate decision about
    whether it is a Back destination. See the spec's section 5.1."""
    assert cs.CHECKPOINT_STEP_IDS == frozenset({
        S.ASK_NAME, S.ASK_HAS_LOGO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR,
        S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE,
    })


def test_name_checkpoint_freezes_only_on_email_verification():
    cp = cs.by_id(S.ASK_NAME).checkpoint
    assert cp.frozen_when({}) is False
    assert cp.frozen_when({"decor_done": True}) is False   # design done: still editable
    assert cp.frozen_when({"email_verified": True}) is True


def test_design_checkpoints_freeze_when_the_design_is_agreed():
    for sid in (S.ASK_HAS_LOGO, S.ASK_LOGO_PLACEMENT, S.ASK_ADD_DECOR):
        cp = cs.by_id(sid).checkpoint
        assert cp.frozen_when({}) is False, sid
        assert cp.frozen_when({"decor_done": True}) is True, sid


def test_brief_checkpoints_freeze_only_when_the_design_is_confirmed():
    for sid in (S.ASK_QUANTITY, S.ASK_DECORATION, S.NEEDED_BY, S.ASK_PURPOSE):
        cp = cs.by_id(sid).checkpoint
        assert cp.frozen_when({"decor_done": True}) is False, sid
        assert cp.frozen_when({"design_confirmed": True}) is True, sid


def test_email_steps_are_never_checkpoints():
    # Verified email must not be re-askable; the verify gate freezes all input
    # anyway, so there is no window in which an unverified one is editable.
    assert cs.by_id(S.ASK_EMAIL).checkpoint is None
    assert cs.by_id(S.AWAIT_EMAIL_VERIFY).checkpoint is None


def test_labels_read_as_the_customer_s_own_answer():
    assert cs.by_id(S.ASK_NAME).checkpoint.label({"name": "Satish"}) == "Your name — Satish"
    assert cs.by_id(S.ASK_QUANTITY).checkpoint.label({"quantity": 50}) == "Quantity — 50"
    assert cs.by_id(S.ASK_HAS_LOGO).checkpoint.label({"has_logo": True}) == "Logo or image — yes"
    assert cs.by_id(S.ASK_HAS_LOGO).checkpoint.label({"has_logo": False}) == "Logo or image — no"


def test_labels_never_crash_on_a_missing_or_partial_value():
    """Labels are rendered at CAPTURE time, i.e. BEFORE the step is answered —
    so every label function must cope with its own slot being absent."""
    for sid in cs.CHECKPOINT_STEP_IDS:
        text = cs.by_id(sid).checkpoint.label({})
        assert isinstance(text, str) and text


def test_logo_label_numbers_the_pass_from_the_banked_collection():
    logo = cs.by_id(S.ASK_LOGO_PLACEMENT).checkpoint
    assert logo.label({"logos": [{"face": "front"}]}) == "Logo 2"
    assert logo.label({"logos": [], "pending_logo": {"face": "front"}}) == "Logo 1 — front"


def test_decor_label_is_not_numbered():
    """There is NO `decor` collection — ASK_ANYTHING_ELSE's apply POPS
    decor_choice/decor_face/decor_placed on each new pass, so nothing
    accumulates and a pass index cannot be derived from `collected`. The label
    describes the decoration instead of counting it."""
    decor = cs.by_id(S.ASK_ADD_DECOR).checkpoint
    assert decor.label({"decor_choice": "text", "decor_face": "left"}) == "Text — left"
    assert decor.label({}) == "Text or graphic"


def test_back_clears_is_gone():
    """Replaced by snapshots — nothing may still declare it."""
    assert not hasattr(cs.REGISTRY[0], "back_clears")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_canvas_steps.py`
Expected: FAIL — `AttributeError: module has no attribute 'CHECKPOINT_STEP_IDS'`.

- [ ] **Step 3: Add the `Checkpoint` dataclass**

In `canvas_steps.py`, above the `Step` dataclass:

```python
@dataclass(frozen=True)
class Checkpoint:
    """A customer-meaningful moment the Back menu can return to.

    Declared on the step that OPENS it, so an element loop pass is exactly one
    checkpoint — the face question, the placement and the background question
    live INSIDE it, not beside it. That is what keeps the menu readable and the
    maintenance cost at one record per checkpoint.

    `label` and `frozen_when` are pure functions of `collected`: the whole
    offerable-list computation is testable with plain dicts, no DB, no LLM.

    `label` is rendered at CAPTURE time — before the step is answered — so it
    must never assume its own slot is set.
    """
    kind: str
    label: Callable[[dict], str]
    frozen_when: Callable[[dict], bool]
```

There is deliberately **no loop key**. Capture is keyed on *entering* the step
from a different one (Task 4), which handles both loops uniformly and needs
nothing from `collected` — important, because the decor loop banks no
collection to count (see `_label_decor` below).

- [ ] **Step 4: Add the field to `Step` and delete `back_clears`**

Add to the `Step` dataclass:

```python
    # The Back destination this step opens, if any. See Checkpoint.
    checkpoint: Checkpoint | None = None
```

Delete the `back_clears` field and its whole comment block (`canvas_steps.py`,
the block ending `# See test_no_step_back_clears_email_captured_or_quote_requested.`),
and delete `back_clears=("decoration_done", "decoration_type"),` from the
`ASK_DECORATION` step. Snapshots make it moot — nothing derives what to clear
any more.

- [ ] **Step 5: Add the label/freeze helpers and the declarations**

Add above `REGISTRY`:

```python
# --- Back checkpoints -------------------------------------------------------
# Two freeze predicates cover every checkpoint, and both read a flag the
# customer sets by tapping a chip:
#   `decor_done`       — "No, that's everything" at ASK_ANYTHING_ELSE.
#   `design_confirmed` — "Looks great, send it" at REVIEW_DESIGN.
# Freezing is PER-CHECKPOINT, not a positional floor: `name` freezes on email
# verification, which happens mid-design, while the logo placed just before the
# email step stays rewindable. A floor model cannot express that.

def _frozen_on_design_agreed(c: dict) -> bool:
    return bool(c.get("decor_done"))


def _frozen_on_design_confirmed(c: dict) -> bool:
    return bool(c.get("design_confirmed"))


def _frozen_on_email_verified(c: dict) -> bool:
    return bool(c.get("email_verified"))


def _em(value: object) -> str:
    """An answer for a label, or a placeholder when the step is unanswered
    (labels render at capture time, before the answer exists)."""
    return str(value) if value not in (None, "", []) else "not set"


def _label_name(c: dict) -> str:
    return f"Your name — {_em(c.get('name'))}"


def _label_has_logo(c: dict) -> str:
    v = c.get("has_logo")
    return f"Logo or image — {'yes' if v else 'no' if v is False else 'not set'}"


def _label_logo(c: dict) -> str:
    n = len(c.get("logos") or []) + 1
    face = _pending(c).get("face")
    bits = [f"Logo {n}"]
    if face:
        bits.append(str(face))
    if _pending(c).get("bg") == "removed":
        bits.append("background removed")
    return bits[0] if len(bits) == 1 else f"{bits[0]} — {', '.join(bits[1:])}"


def _label_decor(c: dict) -> str:
    """Deliberately NOT numbered. Unlike the logo loop, which banks each placed
    logo into `logos`, the decor loop keeps only scalar slots and
    `_apply_anything_else` POPS them all on "Add something else" — so nothing
    accumulates and a pass index cannot be derived from `collected`. Describing
    the decoration is both achievable and more useful in the menu than a count.
    """
    choice = c.get("decor_choice")
    face = c.get("decor_face")
    head = str(choice).capitalize() if choice else "Text or graphic"
    return f"{head} — {face}" if face else head


def _label_quantity(c: dict) -> str:
    return f"Quantity — {_em(c.get('quantity'))}"


def _label_decoration(c: dict) -> str:
    types = c.get("decoration_types") or []
    return f"Decoration — {', '.join(str(t) for t in types) if types else 'not set'}"


def _label_needed_by(c: dict) -> str:
    return f"Needed by — {_em(c.get('needed_by'))}"


def _label_purpose(c: dict) -> str:
    return f"What it's for — {_em(c.get('purpose'))}"
```

Then attach `checkpoint=` to the eight opener steps in `REGISTRY`. For example,
on `ASK_NAME`:

```python
        checkpoint=Checkpoint(kind="name", label=_label_name,
                              frozen_when=_frozen_on_email_verified),
```

on `ASK_HAS_LOGO`:

```python
        checkpoint=Checkpoint(kind="has_logo", label=_label_has_logo,
                              frozen_when=_frozen_on_design_agreed),
```

on `ASK_LOGO_PLACEMENT`:

```python
        checkpoint=Checkpoint(kind="logo", label=_label_logo,
                              frozen_when=_frozen_on_design_agreed),
```

on `ASK_ADD_DECOR`:

```python
        checkpoint=Checkpoint(kind="decor", label=_label_decor,
                              frozen_when=_frozen_on_design_agreed),
```

on `ASK_QUANTITY`, `ASK_DECORATION`, `NEEDED_BY`, `ASK_PURPOSE` respectively:

```python
        checkpoint=Checkpoint(kind="quantity", label=_label_quantity,
                              frozen_when=_frozen_on_design_confirmed),
        checkpoint=Checkpoint(kind="decoration", label=_label_decoration,
                              frozen_when=_frozen_on_design_confirmed),
        checkpoint=Checkpoint(kind="needed_by", label=_label_needed_by,
                              frozen_when=_frozen_on_design_confirmed),
        checkpoint=Checkpoint(kind="purpose", label=_label_purpose,
                              frozen_when=_frozen_on_design_confirmed),
```

Finally, below `_BY_ID`:

```python
CHECKPOINT_STEP_IDS: frozenset[S] = frozenset(
    s.id for s in REGISTRY if s.checkpoint is not None)
```

> **Verified at plan time, do not "fix" this:** `collected["logos"]` is a real
> banked collection (the logo loop appends to it), but there is **no**
> equivalent for decorations — `_apply_anything_else` pops
> `decor_choice`/`decor_face`/`decor_placed` on every "Add something else", so
> nothing accumulates. That asymmetry is why `_label_logo` numbers its pass and
> `_label_decor` does not, and why capture keys on the step transition rather
> than a loop index (Task 4).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_canvas_steps.py`
Expected: PASS.

- [ ] **Step 7: Delete the obsolete `back_clears` guard test**

The test named in the deleted comment — `test_no_step_back_clears_email_captured_or_quote_requested`
(grep for it across `backend/tests/`) — asserts a field that no longer exists.
Delete that test. Its intent is preserved by `CARRY_FORWARD_KEYS` in Task 4.

- [ ] **Step 8: Run the v2 suites**

Run the v2 suites command from Global Constraints.
Expected: failures only in `test_state_machine_v2` / `test_orchestrator_v2` for
`last_answered_step` / `back_clears` — those are removed in Tasks 3 and 5.
Record which fail so Task 3 and Task 5 can verify they are addressed.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py backend/tests/
git commit -m "feat(back): declare Back checkpoints on the step registry"
```

---

### Task 3: `back_targets` — the offerable menu (pure)

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `cs.Checkpoint`, `cs.CHECKPOINT_STEP_IDS`, `Step.checkpoint` (Task 2).
- Produces: `back_targets(collected: dict, rows: list[dict]) -> list[dict]` returning `[{"seq": int, "label": str, "kind": str}]`, newest first. `rows` are live (non-superseded) `session_checkpoints` rows as dicts.

> **No `config` parameter, deliberately.** Every other v2 router function takes
> the store's `canvas_flow` config so it can reorder/filter the registry. This
> one does not need it: a step a store has disabled never runs, so it never
> captures a row — the rows already reflect the effective registry. Adding an
> unused parameter for symmetry would be exactly the YAGNI the review rubric
> flags.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_state_machine_v2.py`:

```python
def _rows(*specs):
    """Minimal live checkpoint rows: (seq, kind, label, step_id)."""
    return [{"seq": s, "kind": k, "label": lb, "step_id": sid}
            for s, k, lb, sid in specs]


ROWS = _rows(
    (1, "name", "Your name — Satish", S.ASK_NAME.value),
    (2, "has_logo", "Logo or image — yes", S.ASK_HAS_LOGO.value),
    (3, "logo", "Logo 1 — front", S.ASK_LOGO_PLACEMENT.value),
    (4, "quantity", "Quantity — 50", S.ASK_QUANTITY.value),
)


def test_targets_are_newest_first():
    out = v2.back_targets({}, ROWS)
    assert [t["seq"] for t in out] == [4, 3, 2, 1]
    assert out[0]["label"] == "Quantity — 50"


def test_agreeing_the_design_drops_every_design_target_but_keeps_the_brief():
    out = v2.back_targets({"decor_done": True}, ROWS)
    assert [t["seq"] for t in out] == [4]


def test_verifying_email_drops_the_name_target_but_not_the_logo():
    out = v2.back_targets({"email_verified": True}, ROWS)
    assert 1 not in [t["seq"] for t in out]
    assert 3 in [t["seq"] for t in out]


def test_confirming_the_design_empties_the_menu():
    assert v2.back_targets({"decor_done": True, "design_confirmed": True}, ROWS) == []


def test_a_submitted_quote_empties_the_menu():
    assert v2.back_targets({"quote_requested": True}, ROWS) == []


def test_a_session_with_no_rows_offers_nothing():
    """Sessions already in flight when this ships have no snapshots — Back is
    simply absent for them rather than half-working."""
    assert v2.back_targets({}, []) == []


def test_an_unknown_step_id_is_skipped_not_crashed():
    assert v2.back_targets({}, _rows((1, "gone", "Gone", "no_such_step"))) == []


def test_last_answered_step_is_gone():
    """Replaced by snapshot restore."""
    assert not hasattr(v2, "last_answered_step")
    assert not hasattr(v2, "_ELEMENT_ADJUST_STEPS")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_state_machine_v2.py`
Expected: FAIL — `back_targets` does not exist.

- [ ] **Step 3: Implement `back_targets` and delete the old machinery**

In `state_machine_v2.py`, delete `last_answered_step` (lines ~126-153) and
`_ELEMENT_ADJUST_STEPS` (lines ~35-42) entirely, and add:

```python
def back_targets(collected: dict, rows: list[dict]) -> list[dict]:
    """The Back destinations offerable right now, newest first.

    PURE: a function of (collected, rows) — the caller does the DB read, so the
    whole menu is testable with plain dicts.

    A row is offerable unless its checkpoint's own `frozen_when` says otherwise.
    Freezing is per-checkpoint rather than a positional floor, which is what
    lets `name` freeze at email verification (mid-design) while the logo placed
    just before the email step stays rewindable.

    An empty list is how "no going back" is expressed — there is no separate
    disable flag to keep in sync with this one.
    """
    if collected.get("quote_requested"):
        # Submitted: the reference is minted and sales has been emailed. Nothing
        # before it is undoable.
        return []
    out: list[dict] = []
    for row in rows:
        step = cs.by_id_value(row.get("step_id"))
        cp = step.checkpoint if step else None
        if cp is None or cp.frozen_when(collected):
            continue
        out.append({"seq": row["seq"], "label": row["label"], "kind": row["kind"]})
    out.sort(key=lambda t: t["seq"], reverse=True)
    return out
```

- [ ] **Step 4: Add the `by_id_value` lookup**

`by_id` takes a `ConversationState`; rows store the raw string. In
`canvas_steps.py`, next to `by_id`:

```python
def by_id_value(value: str | None) -> Step | None:
    """`by_id` for a raw persisted string. Returns None for an unknown value
    rather than raising, so a checkpoint row written by an older/newer build
    is skipped rather than 500-ing the whole Back menu."""
    try:
        return by_id(S(value))
    except ValueError:
        return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py \
        backend/app/services/conversation/canvas_steps.py backend/tests/
git commit -m "feat(back): back_targets menu; drop derived last_answered_step"
```

---

### Task 4: `checkpoints.py` — capture, restore, supersede

**Files:**
- Create: `backend/app/services/conversation/checkpoints.py`
- Create: `backend/tests/test_checkpoints.py`

**Interfaces:**
- Consumes: `cs.Checkpoint`, `Step.checkpoint` (Task 2).
- Produces:
  - `CARRY_FORWARD_KEYS: frozenset[str]`
  - `live_rows(sb, session_id) -> list[dict]`
  - `capture(sb, session_id, step, previous_state, collected, canvas_design) -> None` — `previous_state` is the `ConversationState` the session is leaving.
  - `restore(sb, session_id, seq, live_collected) -> dict | None` — returns the restored row, or `None` if the seq is unknown/superseded.
  - `class CheckpointUnavailable(Exception)`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_checkpoints.py`:

```python
import pytest

from app.services.conversation import canvas_steps as cs
from app.services.conversation import checkpoints as cp
from app.services.conversation.state_machine import ConversationState as S


class _FakeSB:
    """Records inserts/updates so tests can assert on what was written.
    `rows` is the session_checkpoints table; `chat` the chat_messages table."""

    def __init__(self, rows=None, chat=None, session=None):
        self.rows = rows if rows is not None else []
        self.chat = chat if chat is not None else []
        self.session = session or {"id": "s1", "collected": {}}
        self.updates = []

    def table(self, name):
        return _FakeTable(self, name)


class _FakeTable:
    def __init__(self, sb, name):
        self.sb, self.name, self.f = sb, name, {}
        self._gt = None

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self.f[col] = val
        return self

    def is_(self, col, val):
        self.f[col] = val
        return self

    def gt(self, col, val):
        self._gt = (col, val)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def insert(self, rows):
        target = self.sb.rows if self.name == "session_checkpoints" else self.sb.chat
        target.extend(rows if isinstance(rows, list) else [rows])
        return self

    def update(self, patch):
        self.sb.updates.append((self.name, dict(self.f), self._gt, patch))
        if self.name == "session_checkpoints" and self._gt:
            for r in self.sb.rows:
                if r["seq"] > self._gt[1]:
                    r.update(patch)
        if self.name == "design_sessions":
            self.sb.session.update(patch)
        return self

    def execute(self):
        if self.name == "session_checkpoints":
            data = [r for r in self.sb.rows
                    if r.get("superseded_at") is None or "superseded_at" not in self.f]
            if "seq" in self.f:
                data = [r for r in data if r["seq"] == self.f["seq"]]
            return type("R", (), {"data": data})()
        if self.name == "design_sessions":
            return type("R", (), {"data": [self.sb.session]})()
        return type("R", (), {"data": self.sb.chat})()


def test_capture_writes_one_row_with_the_rendered_label():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_NAME), S.GREETING, {"flow_mode": "canvas"}, None)
    assert len(sb.rows) == 1
    assert sb.rows[0]["kind"] == "name"
    assert sb.rows[0]["step_id"] == S.ASK_NAME.value
    assert sb.rows[0]["seq"] == 1


def test_re_rendering_the_same_step_captures_nothing():
    """A stall, a retry, a blank turn and an abuse decline all re-render the
    CURRENT step. Capture keys on ENTERING a step from a different one, so none
    of them writes a second row."""
    sb = _FakeSB()
    for _ in range(3):
        cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT),
                   S.ASK_LOGO_PLACEMENT, {"logos": []}, None)
    assert sb.rows == []


def test_a_second_loop_pass_captures_its_own_row():
    """Re-entering the same opener from elsewhere in the loop IS a new pass.
    This is why capture keys on the transition rather than on a loop index
    derived from `collected` — the decor loop banks no collection to count."""
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT), S.ASK_HAS_LOGO,
               {"logos": []}, None)
    cp.capture(sb, "s1", cs.by_id(S.ASK_LOGO_PLACEMENT), S.ASK_ANOTHER_LOGO,
               {"logos": [{"face": "front"}]}, None)
    assert [r["seq"] for r in sb.rows] == [1, 2]


def test_a_second_decor_pass_captures_its_own_row():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.ASK_ADD_DECOR), S.ASK_ANOTHER_LOGO, {}, None)
    cp.capture(sb, "s1", cs.by_id(S.ASK_ADD_DECOR), S.ASK_ANYTHING_ELSE, {}, None)
    assert [r["seq"] for r in sb.rows] == [1, 2]


def test_a_step_with_no_checkpoint_captures_nothing():
    sb = _FakeSB()
    cp.capture(sb, "s1", cs.by_id(S.LOGO_ADJUST), S.ASK_LOGO_PLACEMENT, {}, None)
    assert sb.rows == []


def test_capture_stores_the_canvas_blob_verbatim():
    sb = _FakeSB()
    design = {"colourway": "navy", "faces": {"front": [{"id": "e1"}]}}
    cp.capture(sb, "s1", cs.by_id(S.ASK_QUANTITY), S.ASK_ANYTHING_ELSE, {}, design)
    assert sb.rows[0]["canvas_design"] == design


def test_restore_replaces_collected_rather_than_merging():
    snap = {"name": "Satish", "logos": []}
    sb = _FakeSB(rows=[{"seq": 1, "kind": "name", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": snap,
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": None}])
    row = cp.restore(sb, "s1", 1, {"name": "Satish", "logos": [{"face": "front"}],
                                   "quantity": 50})
    assert row["collected"]["logos"] == []
    assert "quantity" not in row["collected"]


def test_restore_carries_forward_the_out_of_band_commit_flags():
    """The single most important correctness rule: a snapshot taken BEFORE the
    email step predates verification, and email_verified is written out of band
    by an emailed link click. A plain replacement would un-verify the customer.
    """
    snap = {"name": "Satish"}
    sb = _FakeSB(rows=[{"seq": 1, "kind": "name", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": snap,
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": None}])
    live = {"name": "Satish", "email_captured": True, "email_verified": True,
            "lead_id": "L1"}
    row = cp.restore(sb, "s1", 1, live)
    for key in ("email_captured", "email_verified", "lead_id"):
        assert row["collected"][key] == live[key], key


def test_carry_forward_keys_cover_every_out_of_band_write():
    assert cp.CARRY_FORWARD_KEYS == frozenset({
        "email_captured", "email_verified", "lead_id",
        "quote_requested", "reference_code"})


def test_restore_supersedes_later_checkpoints_without_deleting_them():
    rows = [{"seq": n, "kind": "k", "label": "L", "step_id": S.ASK_NAME.value,
             "collected": {}, "canvas_design": None, "chat_watermark": None,
             "superseded_at": None} for n in (1, 2, 3)]
    sb = _FakeSB(rows=rows)
    cp.restore(sb, "s1", 1, {})
    assert len(sb.rows) == 3                       # nothing deleted
    assert sb.rows[0]["superseded_at"] is None
    assert sb.rows[1]["superseded_at"] is not None
    assert sb.rows[2]["superseded_at"] is not None


def test_restore_supersedes_chat_rows_after_the_watermark():
    sb = _FakeSB(rows=[{"seq": 1, "kind": "k", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": {},
                        "canvas_design": None, "chat_watermark": "m7",
                        "superseded_at": None}])
    cp.restore(sb, "s1", 1, {})
    chat_updates = [u for u in sb.updates if u[0] == "chat_messages"]
    assert chat_updates, "chat rows after the watermark must be superseded"
    assert chat_updates[0][3].get("superseded_at") is not None


def test_restoring_an_unknown_seq_returns_none():
    assert cp.restore(_FakeSB(), "s1", 99, {}) is None


def test_seq_never_reuses_a_superseded_number():
    """After a restore supersedes rows 2-3, the next capture must be seq 4, not
    seq 2 — the (session_id, seq) unique index covers superseded rows too."""
    rows = [{"seq": n, "kind": "k", "label": "L", "step_id": S.ASK_NAME.value,
             "collected": {}, "canvas_design": None, "chat_watermark": None,
             "superseded_at": None} for n in (1, 2, 3)]
    sb = _FakeSB(rows=rows)
    cp.restore(sb, "s1", 1, {})
    cp.capture(sb, "s1", cs.by_id(S.ASK_QUANTITY), S.ASK_ANYTHING_ELSE, {}, None)
    assert sb.rows[-1]["seq"] == 4


def test_restoring_an_already_superseded_seq_returns_none():
    sb = _FakeSB(rows=[{"seq": 1, "kind": "k", "label": "L",
                        "step_id": S.ASK_NAME.value, "collected": {},
                        "canvas_design": None, "chat_watermark": None,
                        "superseded_at": "2026-08-01T00:00:00Z"}])
    assert cp.restore(sb, "s1", 1, {}) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_checkpoints.py`
Expected: FAIL — `No module named 'app.services.conversation.checkpoints'`.

- [ ] **Step 3: Implement the service**

Create `backend/app/services/conversation/checkpoints.py`:

```python
"""Snapshot-and-restore for the v2 canvas Back menu.

All checkpoint DB work lives here so `orchestrator_v2` stays a router. The
routing decisions (which checkpoints exist, which are offerable) are pure and
live in `canvas_steps` / `state_machine_v2`; this module only reads and writes.

Rows are append-only. A restore marks later rows `superseded_at` and never
deletes, so a discarded branch stays reconstructable for audit.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.services.conversation import canvas_steps as cs

log = structlog.get_logger(__name__)

# Values written OUTSIDE the step that a snapshot predates, which a restore must
# NOT roll back. `email_verified` is the load-bearing one: it is written out of
# band by `leads._mark_session_verified` when the customer clicks the emailed
# link, which can land at any point after a snapshot was taken. A plain
# replacement would un-verify a verified customer and re-ask for their address.
#
# ONE constant, deliberately: a key added to the commit set later and missed
# here is silent data loss with no failing test to catch it.
CARRY_FORWARD_KEYS: frozenset[str] = frozenset({
    "email_captured", "email_verified", "lead_id",
    "quote_requested", "reference_code",
})


class CheckpointUnavailable(Exception):
    """The requested seq is unknown, already superseded, or frozen."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def live_rows(sb, session_id: str) -> list[dict]:
    """Non-superseded checkpoint rows for a session, oldest first."""
    res = (sb.table("session_checkpoints")
           .select("seq, kind, label, step_id")
           .eq("session_id", session_id)
           .is_("superseded_at", "null")
           .order("seq")
           .execute())
    return list(res.data or [])


def capture(sb, session_id: str, step: cs.Step, previous_state,
            collected: dict, canvas_design: dict | None) -> None:
    """Snapshot the session on ENTRY to a checkpoint-opening step.

    Correct by construction: the turn that carries the session INTO Logo 2
    carries `collected` and the canvas as they stood at the END of Logo 1.
    Nothing is derived.

    Keyed on the TRANSITION — `previous_state is not step.id` — rather than on
    a loop index read from `collected`. Two reasons, and the second is the
    load-bearing one:

    1. It is idempotent for free. A stall, a retry, a blank turn and an abuse
       decline all re-render the CURRENT step, so previous == step and nothing
       is written.
    2. The decor loop banks NO collection to index. `_apply_anything_else`
       pops decor_choice/decor_face/decor_placed on every "Add something else",
       so a `len(collected["decor"])` key would read 0 on every pass, collide,
       and silently capture only the first decoration. The logo loop does bank
       `logos`, but keying the two differently would be two rules to keep in
       step. Re-entering an opener from elsewhere in the loop is unambiguously
       a new pass for both.

    Best-effort: a checkpoint is a convenience, and failing to write one must
    never break the customer's turn.
    """
    if step.checkpoint is None or previous_state is step.id:
        return
    cpt = step.checkpoint
    try:
        # Max over ALL rows, superseded included — `seq` is monotonic for the
        # life of the session. Counting only live rows would reissue a seq a
        # restore had just superseded, violating the (session_id, seq) unique
        # index and 500-ing the turn.
        res = (sb.table("session_checkpoints")
               .select("seq").eq("session_id", session_id)
               .order("seq").execute())
        rows = list(res.data or [])
        seq = max((r["seq"] for r in rows), default=0) + 1
        watermark = _last_chat_id(sb, session_id)
        sb.table("session_checkpoints").insert({
            "session_id": session_id,
            "seq": seq,
            "kind": cpt.kind,
            "label": cpt.label(collected),
            "step_id": step.id.value,
            "collected": collected,
            "canvas_design": canvas_design,
            "chat_watermark": watermark,
        }).execute()
    except Exception:                        # noqa: BLE001 — best effort
        log.warning("checkpoint_capture_failed", step=step.id.value)


def _last_chat_id(sb, session_id: str) -> str | None:
    res = (sb.table("chat_messages").select("id")
           .eq("session_id", session_id)
           .order("created_at", desc=True).limit(1).execute())
    rows = list(res.data or [])
    return rows[0]["id"] if rows else None


def restore(sb, session_id: str, seq: int, live_collected: dict) -> dict | None:
    """Roll the session back to checkpoint `seq`.

    Returns the checkpoint row (with `collected` already carry-forward-merged),
    or None if the seq is unknown or already superseded — which is the
    double-tap / stale-tab case the route turns into a 409.

    NOT best-effort: unlike capture, a half-done restore would leave the session
    inconsistent, so failures propagate.
    """
    res = (sb.table("session_checkpoints")
           .select("seq, kind, label, step_id, collected, canvas_design, "
                   "chat_watermark, superseded_at")
           .eq("session_id", session_id).eq("seq", seq).limit(1).execute())
    rows = list(res.data or [])
    if not rows or rows[0].get("superseded_at"):
        return None
    row = dict(rows[0])

    restored = dict(row.get("collected") or {})
    for key in CARRY_FORWARD_KEYS:
        if key in live_collected:
            restored[key] = live_collected[key]
    row["collected"] = restored

    stamp = _now()
    (sb.table("session_checkpoints").update({"superseded_at": stamp})
     .eq("session_id", session_id).gt("seq", seq).execute())
    watermark = row.get("chat_watermark")
    chat = sb.table("chat_messages").update({"superseded_at": stamp}).eq(
        "session_id", session_id)
    if watermark:
        # Rows written after the snapshot's last message. `id` is a uuid, so
        # ordering is by created_at via the watermark row's timestamp.
        chat = chat.gt("created_at", _created_at_of(sb, watermark))
    chat.execute()
    log.info("checkpoint_restored", seq=seq, kind=row.get("kind"))
    return row


def _created_at_of(sb, message_id: str) -> str:
    res = (sb.table("chat_messages").select("created_at")
           .eq("id", message_id).limit(1).execute())
    rows = list(res.data or [])
    return rows[0]["created_at"] if rows else "1970-01-01T00:00:00Z"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: same command as Step 2.
Expected: PASS. If `_FakeTable` needs another builder method (e.g. `desc=` on
`order`), add it to the fake — not to the production code.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/checkpoints.py backend/tests/test_checkpoints.py
git commit -m "feat(back): checkpoint capture/restore service"
```

---

### Task 5: Wire the orchestrator

**Files:**
- Modify: `backend/app/services/conversation/orchestrator_v2.py`
- Modify: `backend/app/prompts.py`
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: `checkpoints.capture/restore/live_rows/CARRY_FORWARD_KEYS` (Task 4), `v2.back_targets` (Task 3).
- Produces: `handle_back(session_id: str, seq: int) -> dict`; every v2 turn's `data` carries `back_targets: list[dict]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_orchestrator_v2.py`. Extend the file's existing
`_FakeTable` to serve a `session_checkpoints` table (mirror the one in
`test_checkpoints.py`) before writing these:

```python
@pytest.mark.asyncio
async def test_every_v2_turn_ships_the_back_menu(monkeypatch):
    store = _new_store()
    # ... drive the session to ASK_QUANTITY using the file's existing helper ...
    res = await o2.handle_message("s1", "Satish")
    assert isinstance(res["data"]["back_targets"], list)


@pytest.mark.asyncio
async def test_entering_a_checkpoint_step_captures_exactly_one_row(monkeypatch):
    store = _new_store()
    # drive through ASK_NAME so the session lands on a checkpoint opener
    await o2.handle_message("s1", "")            # GREETING kickoff -> ASK_NAME
    rows = store.get("checkpoints", [])
    assert len([r for r in rows if r["step_id"] == S.ASK_NAME.value]) == 1


@pytest.mark.asyncio
async def test_back_restores_collected_and_supersedes_later_rows(monkeypatch):
    # Seed two checkpoints, restore the first, assert collected is the snapshot
    # and the second row is superseded (not deleted).
    ...


@pytest.mark.asyncio
async def test_back_returns_the_canvas_snapshot_when_there_is_one(monkeypatch):
    # seq whose row has canvas_design set -> data["canvas_restore"] == that blob
    ...


@pytest.mark.asyncio
async def test_back_omits_canvas_restore_when_the_snapshot_has_none(monkeypatch):
    # the `name` checkpoint is captured before any canvas exists
    ...


@pytest.mark.asyncio
async def test_back_on_an_unknown_seq_raises_checkpoint_unavailable(monkeypatch):
    with pytest.raises(cp.CheckpointUnavailable):
        await o2.handle_back("s1", 99)


@pytest.mark.asyncio
async def test_back_carries_forward_a_verified_email(monkeypatch):
    """Restoring to a checkpoint taken before the email step must not
    un-verify the customer."""
    ...


def test_the_old_back_machinery_is_gone():
    assert not hasattr(o2, "_restart_element")
    src = __import__("inspect").getsource(o2)
    assert "_back_used" not in src
    assert "back_removes_element" not in src
```

> **Implementer note:** the four `...` bodies must be filled in, not left as
> ellipses — they are listed separately because each needs its own seeded
> fixture. Follow the seeding style already used by the neighbouring tests in
> this file. A test left as `...` passes vacuously and is a plan failure.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_orchestrator_v2.py`
Expected: FAIL.

- [ ] **Step 3: Rewrite `_public`**

```python
def _public(step: cs.Step, collected: dict, config: dict | None = None,
            *, targets: list[dict] | None = None) -> dict:
    """`v2.public_data_for` plus `back_targets` — the Back destinations
    offerable right now, newest first, already labelled and already filtered.

    Shipped on EVERY turn so the menu opens with no round trip and can never be
    stale. An empty list is how "no going back" is expressed: the frontend
    renders no Back button at all, so there is no separate disable flag to keep
    in sync.
    """
    data = v2.public_data_for(step, collected)
    data["back_targets"] = targets or []
    return data
```

Every `_public(...)` call site in the module must now pass
`targets=v2.back_targets(collected, ck.live_rows(sb, session_id))`.
Add `from app.services.conversation import checkpoints as ck` at the top.

- [ ] **Step 4: Add the capture hook in `handle_message`**

Immediately after `next_` is finally resolved (after the `next_.prepare`
re-resolution, before the `FINALIZE_CANVAS` cap check):

```python
    # Snapshot on ENTRY to a checkpoint opener — correct by construction: this
    # turn carries `collected` and the canvas as they stood at the END of the
    # previous checkpoint. `current` is the state being LEFT, which is what
    # makes this idempotent: every re-render path (stall, retry, blank turn,
    # abuse decline) has current == next_ and writes nothing.
    ck.capture(sb, session_id, next_, current, collected, canvas_design)
```

> Placement matters: this must sit **after** the `next_.prepare` re-resolution,
> so a step that satisfies its own prepare (a store with no decoration methods)
> is never captured as a checkpoint the customer can return to.

- [ ] **Step 5: Delete `_restart_element` and the `_back_used` handling**

Delete the whole `_restart_element` function, the
`collected.pop("_back_used", None)` line in `handle_message` (and its comment),
and `collected["_back_used"] = True` wherever it appears.

- [ ] **Step 6: Rewrite `handle_back`**

```python
async def handle_back(session_id: str, seq: int) -> dict:
    """Restore the session to checkpoint `seq`.

    The router needs no special casing: `collected` genuinely becomes what it
    was, so first-unmet lands on the opener step by itself. `state` is written
    explicitly so a mid-restore reload is consistent.

    Raises CheckpointUnavailable for an unknown, superseded or frozen seq — the
    double-tap and stale-tab case, which the route turns into a 409.
    """
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]
    if S(session["state"]) not in v2.V2_OWNED:
        raise ck.CheckpointUnavailable("not a v2 turn")

    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro = canvas_intro_text(store)
    colour_note = colour_disclaimer_text(store, collected.get("name") or "there")
    flow_config = ((store or {}).get("brand") or {}).get("canvas_flow")

    # Offerability is re-checked server-side: the button the customer tapped
    # was rendered from an earlier turn's data and may since have frozen.
    offerable = {t["seq"] for t in v2.back_targets(
        collected, ck.live_rows(sb, session_id))}
    if seq not in offerable:
        raise ck.CheckpointUnavailable(f"seq {seq} is not offerable")

    row = ck.restore(sb, session_id, seq, collected)
    if row is None:
        raise ck.CheckpointUnavailable(f"seq {seq} is unavailable")

    restored = row["collected"]
    step = cs.by_id_value(row["step_id"]) or cs.by_id(S.ASK_NAME)
    reply = v2.reply_for(step, restored, persona=persona, intro=intro,
                         colour_note=colour_note)
    data = _public(step, restored, flow_config,
                   targets=v2.back_targets(
                       restored, ck.live_rows(sb, session_id)))
    if row.get("canvas_design"):
        data["canvas_restore"] = row["canvas_design"]
    return await _persist(sb, session_id, restored, step, reply,
                          session["state"], step.id, user_message=None, data=data)
```

Note `user_message=None`: the customer did not type a turn, and `_persist`
already treats `None` as "assistant row only" (distinct from `""`, the GREETING
kickoff's shape).

- [ ] **Step 7: Delete the obsolete prompt**

Remove `V2_BACK_RESTART_ACK` from `backend/app/prompts.py`. Grep first to
confirm this task's edits removed its only user.

- [ ] **Step 8: Run the tests to verify they pass**

Run: same command as Step 2, then the full v2 suites command.
Expected: PASS. Any residual failure in `test_v2_e2e` / `test_v2_copy_guards`
referencing the old back behaviour must be updated here, not deferred.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py \
        backend/app/prompts.py backend/tests/
git commit -m "feat(back): orchestrator captures checkpoints and restores by seq"
```

---

### Task 6: Route + request model

**Files:**
- Modify: `backend/app/api/routes/chat.py:173-179`
- Modify: `backend/app/models/message.py`
- Test: `backend/tests/test_chat_back_route.py` (create)

**Interfaces:**
- Consumes: `handle_back(session_id, seq)` (Task 5), `CheckpointUnavailable`.
- Produces: `POST /chat/{session_id}/back` with body `{"seq": int}`; 409 on an unavailable seq; 404 on an unknown session.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chat_back_route.py`:

```python
def test_back_requires_a_seq(client):
    assert client.post("/chat/s1/back", json={}).status_code == 422


def test_back_returns_409_when_the_checkpoint_is_unavailable(client, monkeypatch):
    async def _boom(_sid, _seq):
        raise ck.CheckpointUnavailable("gone")
    monkeypatch.setattr(chat_mod, "handle_back_v2", _boom)
    assert client.post("/chat/s1/back", json={"seq": 3}).status_code == 409


def test_back_returns_404_for_an_unknown_session(client, monkeypatch):
    async def _missing(_sid, _seq):
        raise SessionNotFound("s1")
    monkeypatch.setattr(chat_mod, "handle_back_v2", _missing)
    assert client.post("/chat/s1/back", json={"seq": 1}).status_code == 404
```

> **Implementer note:** reuse the `client` fixture the existing route tests use
> (grep `backend/tests/` for `TestClient`), rather than building a new app.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q tests/test_chat_back_route.py`
Expected: FAIL.

- [ ] **Step 3: Add the request model**

In `backend/app/models/message.py`:

```python
class BackRequest(BaseModel):
    """Which checkpoint to restore. The seq comes from `data.back_targets`,
    which every v2 canvas turn ships."""
    seq: int
```

Also update the `ChatRequest.canvas_design` docstring: the blob is now sent on
**every** v2 canvas turn (it feeds the checkpoint snapshot), while the list of
turns whose blob may be **persisted** to `design_sessions.canvas_design` is
unchanged — see `chat.py::_persist_live_canvas_design`.

- [ ] **Step 4: Rewrite the route**

```python
@router.post("/chat/{session_id}/back", response_model=ChatResponse)
async def chat_back(session_id: str, body: BackRequest) -> ChatResponse:
    try:
        result = await handle_back_v2(session_id, body.seq)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    except CheckpointUnavailable as exc:
        # Already restored, superseded, or frozen since the menu was rendered
        # (double tap, stale second tab). The frontend re-renders where the
        # session actually is rather than restoring twice.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return ChatResponse(**result)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 6: Run the full backend suite**

Run the full backend command from Global Constraints, then the v2 suites command.
Expected: no failures; total ≥ 1213 + the new tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/chat.py backend/app/models/message.py backend/tests/
git commit -m "feat(back): /chat/{id}/back takes a seq; 409 on unavailable"
```

---

### Task 7: Canvas store — snapshot restore that preserves locks

**Files:**
- Modify: `frontend/src/store/canvasStore.ts`
- Test: `frontend/src/__tests__/canvasStoreRestore.test.ts` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `restoreSnapshot(design: CanvasDesign | null | undefined) => void` on the canvas store.

**Why a new action rather than reusing `fromCanvasDesign`:** that one
deliberately **strips `locked: true`** (the rework-unlock fix). A checkpoint
restore must *preserve* lock state — v2 locks each finished element, and
`lockPlaced`, `patchPendingLogo` and `observe_canvas` all anchor on "the last
**unlocked** element on a face". Unlocking everything on restore would break
that anchor and make the background-removal toggle target the wrong element.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/canvasStoreRestore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

const design = {
  colourway: 'navy',
  faces: {
    front: [{ id: 'a', type: 'image', x: 0.5, y: 0.5, locked: true } as never,
            { id: 'b', type: 'image', x: 0.2, y: 0.2, locked: false } as never],
    back: [], left: [], right: [],
  },
}

describe('restoreSnapshot', () => {
  beforeEach(() => useCanvasStore.getState().reset())

  it('preserves lock state, unlike fromCanvasDesign', () => {
    useCanvasStore.getState().restoreSnapshot(design as never)
    const front = useCanvasStore.getState().faces.front
    expect(front.map(e => e.locked)).toEqual([true, false])
  })

  it('fromCanvasDesign still unlocks everything (rework path unchanged)', () => {
    useCanvasStore.getState().fromCanvasDesign(design as never)
    expect(useCanvasStore.getState().faces.front.every(e => !e.locked)).toBe(true)
  })

  it('restores the colourway and clears the selection', () => {
    useCanvasStore.getState().restoreSnapshot(design as never)
    expect(useCanvasStore.getState().colourway).toBe('navy')
    expect(useCanvasStore.getState().selectedId).toBeNull()
  })

  it('tolerates a partial blob with missing faces', () => {
    useCanvasStore.getState().restoreSnapshot({ faces: { front: [] } } as never)
    expect(useCanvasStore.getState().faces.right).toEqual([])
  })

  it('is a no-op-safe call for null', () => {
    expect(() => useCanvasStore.getState().restoreSnapshot(null)).not.toThrow()
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from the worktree root):
`docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__/canvasStoreRestore.test.ts`
Expected: FAIL — `restoreSnapshot is not a function`.

- [ ] **Step 3: Implement `restoreSnapshot`**

Add to the store interface (next to `fromCanvasDesign`, line ~100):

```ts
  /** Roll the canvas back to a Back-checkpoint snapshot.
   *  Distinct from `fromCanvasDesign`, which STRIPS `locked` so a reworked
   *  design comes back editable. A checkpoint restore must PRESERVE locks: v2
   *  locks each finished element, and lockPlaced / patchPendingLogo /
   *  observe_canvas all anchor on "the last UNLOCKED element on a face".
   *  Unlocking everything here would re-point that anchor at an old element. */
  restoreSnapshot: (design: CanvasDesign | null | undefined) => void
```

And the implementation next to `fromCanvasDesign`:

```ts
  restoreSnapshot: design => set(() => {
    const base = { ...emptyFaces(), ...(design?.faces ?? {}) }
    const faces = { ...emptyFaces() } as Record<Face, CanvasElement[]>
    for (const f of FACES) faces[f] = (base[f] ?? []).map(e => ({ ...e }))
    return {
      faces,
      colourway: design?.colourway ?? null,
      activeFace: 'front' as Face,
      selectedId: null,
    }
  }),
```

- [ ] **Step 4: Run the test to verify it passes**

Run: same command as Step 2.
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/__tests__/canvasStoreRestore.test.ts
git commit -m "feat(back): canvasStore.restoreSnapshot preserves lock state"
```

---

### Task 8: Chat store — targets, goBackTo, canvas restore, canvas on every turn

**Files:**
- Modify: `frontend/src/store/chatStore.ts`
- Modify: `frontend/src/lib/api.ts:88-96`
- Test: `frontend/src/__tests__/chatStoreBack.test.ts` (rewrite)

**Interfaces:**
- Consumes: `restoreSnapshot` (Task 7); `data.back_targets` / `data.canvas_restore` (Task 5).
- Produces: store fields `backTargets: {seq: number; label: string; kind: string}[]`; action `goBackTo(sessionId: string, seq: number) => Promise<void>`.

- [ ] **Step 1: Write the failing tests**

Rewrite `frontend/src/__tests__/chatStoreBack.test.ts`. It currently asserts the
single-step rewind and `backRemovesElement`, both of which this work removes.

```ts
it('parses back_targets from turn data', () => {
  useChatStore.getState().applyResponse('hi', 'ask_quantity', {
    back_targets: [{ seq: 2, label: 'Logo 1 — front', kind: 'logo' }],
  })
  expect(useChatStore.getState().backTargets).toEqual(
    [{ seq: 2, label: 'Logo 1 — front', kind: 'logo' }])
})

it('defaults backTargets to an empty list when the key is absent', () => {
  useChatStore.getState().applyResponse('hi', 'ask_name', {})
  expect(useChatStore.getState().backTargets).toEqual([])
})

it('goBackTo posts the chosen seq', async () => {
  const spy = vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: {} } as never)
  await useChatStore.getState().goBackTo('s1', 3)
  expect(spy).toHaveBeenCalledWith('s1', 3)
})

it('applies canvas_restore through restoreSnapshot, not fromCanvasDesign', async () => {
  const snap = { colourway: null, faces: { front: [], back: [], left: [], right: [] } }
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: { canvas_restore: snap } } as never)
  await useChatStore.getState().goBackTo('s1', 1)
  expect(restore).toHaveBeenCalledWith(snap)
})

it('leaves the canvas alone when the snapshot carries none', async () => {
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  vi.spyOn(api, 'sendBack').mockResolvedValue(
    { reply: 'r', state: 'ask_name', data: {} } as never)
  await useChatStore.getState().goBackTo('s1', 1)
  expect(restore).not.toHaveBeenCalled()
})

it('hydrate never applies canvas_restore (a resume must not re-restore)', () => {
  const restore = vi.spyOn(useCanvasStore.getState(), 'restoreSnapshot')
  useChatStore.getState().hydrate([], 'ask_name',
    { canvas_restore: { colourway: null, faces: {} } })
  expect(restore).not.toHaveBeenCalled()
})

it('sends the live canvas on every v2 canvas turn', async () => {
  const spy = vi.spyOn(api, 'sendChat').mockResolvedValue(
    { reply: 'r', state: 'ask_logo_placement', data: {} } as never)
  useChatStore.setState({ chatState: 'ask_logo_placement' })
  await useChatStore.getState().sendMessage('s1', 'front')
  expect(spy.mock.calls[0][2]).toBeTruthy()   // canvas_design attached
})

it('drops a blank turn (existing guard, must not regress)', async () => {
  const spy = vi.spyOn(api, 'sendChat')
  await useChatStore.getState().sendMessage('s1', '   ')
  expect(spy).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__/chatStoreBack.test.ts`
Expected: FAIL.

- [ ] **Step 3: Update `api.sendBack`**

```ts
/**
 * v2 canvas Back: restore the session to a checkpoint from `data.back_targets`.
 * Dedicated endpoint (not the message endpoint), so it never reaches the
 * interpreter. 409 if the checkpoint was superseded or froze since the menu
 * was rendered.
 */
export function sendBack(sessionId: string, seq: number): Promise<ChatResponse> {
  return request<ChatResponse>(`/chat/${sessionId}/back`, {
    method: 'POST',
    body: JSON.stringify({ seq }),
  })
}
```

> Match the existing `request()` helper's convention for JSON bodies — check
> how `sendChat` passes its body and mirror it exactly (headers included).

- [ ] **Step 4: Update `parseData`, the store fields and `goBackTo`**

In `parseData` (line ~122), replace the two back lines with:

```ts
  const backTargets = Array.isArray(data.back_targets)
    ? (data.back_targets as { seq: number; label: string; kind: string }[])
    : []
```

Add `backTargets` to the returned object and to the initial state (`[]`), and
delete `canGoBack` / `backRemovesElement` everywhere they appear (interface,
`parseData`, initial state, `reset`).

Replace `goBack` with:

```ts
  goBackTo: async (sessionId: string, seq: number) => {
    if (get().sending) return
    set({ sending: true })
    try {
      const res = await sendBack(sessionId, seq)
      const data = res.data as Record<string, unknown>
      // Applied HERE, in the response handler — never in a React effect. An
      // effect fires on change and would re-apply on resume, restoring a
      // canvas the customer has since moved on from.
      const snap = data.canvas_restore
      if (snap && typeof snap === 'object') {
        useCanvasStore.getState().restoreSnapshot(snap as CanvasDesign)
      }
      get().applyResponse(res.reply, res.state, data)
    } finally {
      set({ sending: false })
    }
  },
```

- [ ] **Step 5: Send the live canvas on every v2 turn**

Replace the `liveDesign` condition (line ~224):

```ts
      // The backend snapshots the canvas into the Back checkpoint on every
      // turn, so it must see the live blob every turn — not only on the two
      // states that read it for their own logic. Which turns may PERSIST it to
      // design_sessions.canvas_design is unchanged and still enforced
      // server-side (chat.py::_persist_live_canvas_design).
      const liveDesign = useCanvasStore.getState().toCanvasDesign()
```

> If `sendMessage` is shared with non-canvas flows, gate this on the canvas
> session the same way the surrounding code does and leave non-canvas turns
> sending `undefined`. Verify by grepping `sendMessage` call sites before
> changing it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: same command as Step 2.
Expected: PASS.

- [ ] **Step 7: Typecheck**

Run: `docker compose run --rm --no-deps -T frontend npx tsc --noEmit`
Expected: zero errors. Fix every call site the removed `canGoBack` /
`backRemovesElement` / `goBack` leaves dangling.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/lib/api.ts frontend/src/__tests__/
git commit -m "feat(back): chatStore back targets, goBackTo, canvas restore"
```

---

### Task 9: The Back menu UI + the name banner

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/ChatColumn.tsx:668-699`
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:348-352`
- Test: `frontend/src/__tests__/backMenu.test.tsx` (create)

**Interfaces:**
- Consumes: `backTargets`, `goBackTo` (Task 8).
- Produces: no new exports.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/__tests__/backMenu.test.tsx`:

```tsx
it('renders no Back button when there are no targets', () => {
  useChatStore.setState({ backTargets: [] })
  render(<ChatColumn sessionId="s1" />)
  expect(screen.queryByText(/Back/)).toBeNull()
})

it('opens a list of destinations, newest first', async () => {
  useChatStore.setState({ backTargets: [
    { seq: 3, label: 'Logo 2 — back', kind: 'logo' },
    { seq: 1, label: 'Your name — Satish', kind: 'name' },
  ] })
  render(<ChatColumn sessionId="s1" />)
  await userEvent.click(screen.getByText(/Back/))
  expect(screen.getByText('Logo 2 — back')).toBeInTheDocument()
  expect(screen.getByText('Your name — Satish')).toBeInTheDocument()
})

it('picking a destination calls goBackTo with its seq', async () => {
  const spy = vi.fn()
  useChatStore.setState({ backTargets: [{ seq: 3, label: 'Logo 2 — back', kind: 'logo' }],
                          goBackTo: spy })
  render(<ChatColumn sessionId="s1" />)
  await userEvent.click(screen.getByText(/Back/))
  await userEvent.click(screen.getByText('Logo 2 — back'))
  expect(spy).toHaveBeenCalledWith('s1', 3)
})

it('Cancel closes the menu without a request', async () => {
  const spy = vi.fn()
  useChatStore.setState({ backTargets: [{ seq: 3, label: 'Logo 2 — back', kind: 'logo' }],
                          goBackTo: spy })
  render(<ChatColumn sessionId="s1" />)
  await userEvent.click(screen.getByText(/Back/))
  await userEvent.click(screen.getByText(/Cancel/))
  expect(spy).not.toHaveBeenCalled()
  expect(screen.queryByText('Logo 2 — back')).toBeNull()
})

it('hides Back at the email verification gate', () => {
  useChatStore.setState({ backTargets: [{ seq: 1, label: 'L', kind: 'name' }],
                          chatState: 'await_email_verify' })
  render(<ChatColumn sessionId="s1" />)
  expect(screen.queryByText(/Back/)).toBeNull()
})
```

And in `frontend/src/__tests__/` a Surface test:

```tsx
it('shows "Design for <Name>" once the name is captured', () => {
  useChatStore.setState({ collectedName: 'Satish' })
  render(<Surface />)
  expect(screen.getByText('Design for Satish')).toBeInTheDocument()
})

it('shows no banner before the name is captured', () => {
  useChatStore.setState({ collectedName: null })
  render(<Surface />)
  expect(screen.queryByText(/^Design for/)).toBeNull()
})
```

> **Implementer note:** `ChatColumn` and `Surface` both need their existing test
> harness (store seeding, Konva mocks). Copy the setup from
> `src/__tests__/surfaceDirective.test.tsx` and the nearest existing ChatColumn
> test rather than writing new mocks.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__/backMenu.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Replace the Back UI in `ChatColumn`**

Replace the whole block at lines 668-699:

```tsx
        {/* Structured Back: a menu of named checkpoints. The list ships on
            every turn (data.back_targets), already filtered server-side, so
            opening it costs no round trip and it can never be stale. No
            targets => no button, which is how "no going back after the design
            is agreed" is expressed — there is no separate disable flag. */}
        {sessionId && backTargets.length > 0 && !sending && !awaitingEmailVerify && (
          backMenuOpen ? (
            <div className="self-start flex flex-col gap-1.5">
              <span className="text-xs text-textMuted">
                Where would you like to go back to?
              </span>
              {backTargets.map(t => (
                <button
                  key={t.seq}
                  onClick={() => { setBackMenuOpen(false); void goBackTo(sessionId, t.seq) }}
                  className="self-start rounded-full border border-border px-3 py-1 text-xs
                             text-textPrimary hover:border-accent hover:text-accent"
                >
                  {t.label}
                </button>
              ))}
              <button
                onClick={() => setBackMenuOpen(false)}
                className="self-start text-xs text-textMuted hover:underline underline-offset-2"
              >
                Cancel — stay here
              </button>
            </div>
          ) : (
            <button
              onClick={() => setBackMenuOpen(true)}
              className="self-start text-xs text-textMuted hover:text-accent underline underline-offset-2"
            >
              ↩ Back
            </button>
          )
        )}
```

Replace the `confirmingBack` state with `const [backMenuOpen, setBackMenuOpen] = useState(false)`,
and the store reads at lines 174-176 with:

```tsx
  const backTargets = useChatStore(s => s.backTargets)
  const goBackTo = useChatStore(s => s.goBackTo)
```

Close the menu whenever the targets change (a completed restore or a forward
turn), so it never lingers over a stale list:

```tsx
  useEffect(() => { setBackMenuOpen(false) }, [backTargets])
```

- [ ] **Step 4: Add the name banner in `Surface`**

Above the `ToolRail` wrapper (line ~348):

```tsx
        {designerName && (
          <div className="px-3 pt-3 text-xs font-semibold text-textMuted truncate">
            Design for {designerName}
          </div>
        )}
```

`Surface` already subscribes to `useChatStore` (line 5, 20, 27) but the store
carries **no name field** — verified. So surface it:

In `orchestrator_v2._public`, add:

```python
    # The canvas column renders "Design for <Name>". Sourced from the turn's
    # data rather than a second fetch, so it appears the moment the name is
    # captured and needs no new endpoint.
    data["designer_name"] = collected.get("name") or None
```

In `chatStore.parseData`, add `const collectedName = typeof data.designer_name === 'string' ? data.designer_name : null`,
return it, and initialise it to `null` in the store's initial state and `reset`.

In `Surface`, read it with `const designerName = useChatStore(s => s.collectedName)`.

This is a name, so it must never reach a log line or a Sentry breadcrumb
(security rule 10) — it is display-only.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__/backMenu.test.tsx`
Expected: PASS.

- [ ] **Step 6: Full frontend suite + typecheck**

```bash
docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx
docker compose run --rm --no-deps -T frontend npx tsc --noEmit
```
Expected: ≥313 passing, 0 failing; zero type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/ frontend/src/__tests__/
git commit -m "feat(back): checkpoint menu UI + Design for <Name> banner"
```

---

### Task 10: Full verification + hosted migration + CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`
- No test file (this task verifies everything else).

- [ ] **Step 1: Full backend suite, flag off**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false "C:/Users/satis/madhats-aidesign/backend/.venv/Scripts/python.exe" -m pytest -q`
Expected: ≥1213 passing, 0 failing. Record the number.

- [ ] **Step 2: v2 suites, flag on**

Run the v2 suites command from Global Constraints.
Expected: ≥311 passing, 0 failing. Record the number.

- [ ] **Step 3: Full frontend suite + typecheck**

```bash
docker compose run --rm --no-deps -T frontend npx vitest run src/__tests__ src/components/StoreHeader.test.tsx
docker compose run --rm --no-deps -T frontend npx tsc --noEmit
```
Expected: ≥313 passing, 0 failing; zero type errors. Record the numbers.

- [ ] **Step 4: Apply the migration to the hosted Supabase**

The root `.env` points at the hosted project. Apply
`20260801000001_session_checkpoints.sql` there and **verify by querying**, not
by assuming — the 2026-07-24 batch shipped two migrations that sat unapplied and
would have PostgREST-errored every write. Confirm `session_checkpoints` exists
with all eleven columns and that `chat_messages.superseded_at` is present; a
bogus column name must still error `42703`.

- [ ] **Step 5: In-browser walk**

Start the dev stack (`docker compose up -d`, plain HTTP —
`http://localhost:5173`) with `CANVAS_ORCHESTRATOR_V2=true`, open
`http://localhost:5173/?product_id=…`, and verify:

1. Answer name → intro → "Yes, I have a logo" → pick a face → place a logo →
   Done. `↩ Back` is present.
2. Tap Back: the menu lists `Logo 1 — …`, `Logo or image — yes`,
   `Your name — …`, newest first, plus **Cancel — stay here**. Cancel closes it
   with no network request (check the Network tab).
3. Add a second logo, then Back → pick `Logo 1`. The canvas rewinds to **no
   logos**, the chat truncates to that point, and the bot re-asks the face
   question.
4. Verify the email, then Back → the `Your name` entry is **gone** and
   `Design for <Name>` is shown above the tools.
5. Answer through to "No, that's everything" → Back now lists **only** the brief
   answers (quantity / decoration / needed by / purpose).
6. Confirm at the review ("Looks great, send it") → **no Back button at all**.

> `LOGO_ADJUST` auto-opens a native file dialog, which blocks browser
> automation. Patch `HTMLInputElement.prototype.click` to no-op for
> `type=file`, then inject a `File` via `DataTransfer` into
> `input[aria-label="Upload image"]` and dispatch `change`.

- [ ] **Step 6: Update CLAUDE.md**

Add a "Current implementation state" bullet covering: the checkpoint model and
where it is declared; that `CARRY_FORWARD_KEYS` is load-bearing and why
(out-of-band `email_verified`); that `restoreSnapshot` preserves locks while
`fromCanvasDesign` strips them, and why the anchor depends on it; that the live
canvas is now sent on **every** v2 turn while the persist scoping is unchanged;
that rows are superseded not deleted; and that the 2026-07-25 element-restart
back design is retired. Record the measured test counts from Steps 1-3.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record structured Back checkpoint restore in project memory"
```

---

## Self-Review

**Spec coverage:** §5.1 checkpoint table → Task 2. §5.2 freezing → Tasks 2, 3.
§5.3 email + name banner → Tasks 2 (no email checkpoint), 9 (banner). §6.1
storage → Task 1. §6.2 capture + canvas on every turn → Tasks 5, 8. §6.3 restore
+ carry-forward → Tasks 4, 5. §6.4 409 → Tasks 4, 6. §7 frontend → Tasks 7, 8, 9.
§8 removals → Tasks 2 (`back_clears`), 3 (`last_answered_step`,
`_ELEMENT_ADJUST_STEPS`), 5 (`_restart_element`, `_back_used`,
`back_removes_element`, `V2_BACK_RESTART_ACK`). §9 rollout (no backfill) →
Task 3 test. §10 edge cases → Tasks 3, 4, 5 tests + Task 10 walk. §11 testing →
distributed. §12 files → File Structure.

**Known gaps carried deliberately:** the spec's §3 non-goal "no admin UI for the
retained audit branches" means `admin_diagnostics.py` keeps showing all rows
including superseded ones — that is intended (Task 1 Step 4 comment), and no
task surfaces the branch structure.

**Two open items from the first draft were resolved against the code rather
than left to the implementer**, and both changed the design:

1. **There is no `decor` collection.** The first draft keyed loop capture on
   `len(collected["decor"])`, which would have read 0 on every decor pass,
   collided on the same marker, and silently captured only the *first*
   decoration — a bug that would have shipped looking like "Back sometimes
   forgets a decoration". Capture now keys on the step **transition**
   (`previous_state is not step.id`), which is uniform across both loops, needs
   nothing from `collected`, and is idempotent for free.
2. **`seq` must be monotonic over superseded rows too.** Computing it from live
   rows would reissue a number a restore had just superseded and violate the
   `(session_id, seq)` unique index. Covered by
   `test_seq_never_reuses_a_superseded_number`.

**Remaining implementer latitude (bounded, and stated where it applies):** the
test scaffolding in Tasks 1, 5, 6 and 9 should reuse each file's existing
harness rather than the sketch shown — the assertions are the specification,
the setup is house style. The four `...` bodies in Task 5 Step 1 must be filled
in; a test left as `...` passes vacuously and is a plan failure.
