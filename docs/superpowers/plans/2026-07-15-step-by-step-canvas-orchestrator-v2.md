# Step-by-Step Canvas Orchestrator (v2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parallel "v2" chat orchestrator that leads canvas Design Studio customers through the canvas one tool at a time (unlock → highlight → instruct → place/adjust → lock), selectable by a global env flag, keeping today's orchestrator as an untouched runtime backup.

**Architecture:** A new `orchestrator_v2` + `state_machine_v2` own the *front half* (name → admin intro → ≤4-logo loop → text/shape loop → quantity → email → purpose). Each v2 state emits a `canvas` directive in its `data` payload that drives which frontend tool is enabled/highlighted, which face is shown, and instruction copy. After purpose, v2 hands off to the **existing shared tail** (generate → verify → deliver → refine). The `/chat` route dispatches to v2 only when `CANVAS_ORCHESTRATOR_V2` is on **and** the session's `flow_mode == "canvas"`.

**Tech Stack:** Python 3.12 / FastAPI / pydantic-settings / supabase-py (backend), React 18 / Zustand / react-konva / Vitest (frontend), pytest (backend tests).

## Global Constraints

- New states are **added to the existing `ConversationState` enum** (additive only — v1 routing must never return them; v1 behaviour stays byte-identical).
- v1 modules (`orchestrator.py`, `state_machine.py` routing, existing tail states) are **not modified** except for the additive enum members and the shared tail (which is reused, not changed).
- Selection: env `CANVAS_ORCHESTRATOR_V2` (bool, default `false`); scope = canvas sessions only.
- No secrets in code; the flag is read only in `app/config.py` via pydantic-settings.
- The admin-set intro is stored in the existing `stores.brand` jsonb; PATCH must **read-merge** brand (never wipe existing keys). Crash-safe MadHats default when unset.
- Per-tool usage tips are **canned copy in code** (frontend constants), not admin-editable.
- Canvas control is **data-directive driven**: the state machine is the single source of truth; the frontend only reacts to the `canvas` directive.
- Backend tests: `cd backend && pytest -q`. Frontend tests: `cd frontend && npx vitest run`.
- Commit after each task.

---

## File Structure

**Backend (new):**
- `backend/app/services/conversation/state_machine_v2.py` — v2 forward routing + progress + directive builder.
- `backend/app/services/conversation/orchestrator_v2.py` — v2 `handle_message` (front half + tail handoff).
- `backend/tests/test_state_machine_v2.py`, `backend/tests/test_orchestrator_v2.py`.

**Backend (modified):**
- `backend/app/config.py` — add `canvas_orchestrator_v2` flag.
- `backend/app/services/conversation/state_machine.py` — add new enum members only.
- `backend/app/api/routes/chat.py` — dispatch to v2.
- `backend/app/api/routes/sessions.py` — `finalize_canvas` v2 branch (→ GENERATING).
- `backend/app/services/branding.py` + admin stores route — `canvas_intro` field.
- `.env.example` — document the flag.

**Frontend (new):**
- `frontend/src/components/DesignStudio/toolInstructions.ts` — canned per-tool tips.
- `frontend/src/__tests__/orchestratorV2Canvas.test.tsx` (directive → surface reactions), plus additions to existing `ToolRail.test.tsx`.

**Frontend (modified):**
- `frontend/src/store/canvasStore.ts` — per-element `locked` + `lockAll`/`unlockAll`.
- `frontend/src/components/DesignStudio/nodes.tsx` — respect `el.locked`.
- `frontend/src/components/DesignStudio/ToolRail.tsx` — `allowedTools` gating + `highlightTool`.
- `frontend/src/store/chatStore.ts` — parse `canvas` directive + `trigger_finalize`.
- `frontend/src/components/DesignStudio/Surface.tsx` — react to the directive; post `"done"`; run finalize on `trigger_finalize`.

---

## Backend

### Task 1: Env flag `CANVAS_ORCHESTRATOR_V2`

**Files:**
- Modify: `backend/app/config.py` (Settings class, after the `--App--` block ~line 72)
- Modify: `.env.example`
- Test: `backend/tests/test_config_v2_flag.py` (create)

**Interfaces:**
- Produces: `settings.canvas_orchestrator_v2: bool` (default `False`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config_v2_flag.py
from app.config import Settings


def test_flag_defaults_false():
    s = Settings()  # type: ignore[call-arg]
    assert s.canvas_orchestrator_v2 is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("CANVAS_ORCHESTRATOR_V2", "true")
    s = Settings()  # type: ignore[call-arg]
    assert s.canvas_orchestrator_v2 is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_config_v2_flag.py -q`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'canvas_orchestrator_v2'`).

- [ ] **Step 3: Add the setting**

In `backend/app/config.py`, inside the `--- App ---` group (after `chatbot_persona_name`):

```python
    # --- Orchestrator selection ---
    # When true, canvas sessions (flow_mode == "canvas") are handled by the
    # step-by-step v2 orchestrator. Every other session and the false case use
    # the v1 orchestrator, unchanged. Global flag; canvas-only in scope.
    canvas_orchestrator_v2: bool = False
```

- [ ] **Step 4: Document in `.env.example`**

Add near the other app flags:

```dotenv
# Step-by-step canvas orchestrator (v2). "true" routes canvas sessions through
# the new tool-by-tool flow; unset/false keeps the current orchestrator.
CANVAS_ORCHESTRATOR_V2=false
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_config_v2_flag.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py .env.example backend/tests/test_config_v2_flag.py
git commit -m "feat(config): add CANVAS_ORCHESTRATOR_V2 flag"
```

---

### Task 2: New enum members + `state_machine_v2` routing

**Files:**
- Modify: `backend/app/services/conversation/state_machine.py` (enum only, ~line 37-42)
- Create: `backend/app/services/conversation/state_machine_v2.py`
- Test: `backend/tests/test_state_machine_v2.py`

**Interfaces:**
- Consumes: `ConversationState` (shared enum), `is_affirmative`, `is_negative` from `state_machine`.
- Produces:
  - New enum members: `SHOW_INTRO="show_intro"`, `ASK_LOGO_PLACEMENT="ask_logo_placement"`, `LOGO_ADJUST="logo_adjust"`, `ASK_ANOTHER_LOGO="ask_another_logo"`, `ASK_ADD_DECOR="ask_add_decor"`, `DECOR_ADJUST="decor_adjust"`, `ASK_ANYTHING_ELSE="ask_anything_else"`, `FINALIZE_CANVAS="finalize_canvas"`.
  - `MAX_LOGOS: int = 4`
  - `advance_state_v2(current: ConversationState, collected: dict) -> ConversationState`
  - `progress_v2(state: ConversationState, collected: dict) -> dict` returning `{"step": int, "total": int}`
  - `V2_STATES: frozenset[ConversationState]` — the front-half states v2 owns.

- [ ] **Step 1: Add enum members**

In `state_machine.py`, inside `class ConversationState`, after `CANVAS_DESIGN = "canvas_design"`:

```python
    # --- v2 step-by-step canvas orchestrator (additive; v1 never routes here) ---
    SHOW_INTRO = "show_intro"
    ASK_LOGO_PLACEMENT = "ask_logo_placement"
    LOGO_ADJUST = "logo_adjust"
    ASK_ANOTHER_LOGO = "ask_another_logo"
    ASK_ADD_DECOR = "ask_add_decor"
    DECOR_ADJUST = "decor_adjust"
    ASK_ANYTHING_ELSE = "ask_anything_else"
    FINALIZE_CANVAS = "finalize_canvas"
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_state_machine_v2.py
from app.services.conversation.state_machine import ConversationState as S
from app.services.conversation import state_machine_v2 as v2


def test_intro_then_first_logo_placement():
    assert v2.advance_state_v2(S.ASK_NAME, {}) is S.SHOW_INTRO
    assert v2.advance_state_v2(S.SHOW_INTRO, {}) is S.ASK_LOGO_PLACEMENT


def test_placement_to_adjust_then_another():
    c = {"logo_face": "front"}
    assert v2.advance_state_v2(S.ASK_LOGO_PLACEMENT, c) is S.LOGO_ADJUST
    c["logo_done"] = True
    assert v2.advance_state_v2(S.LOGO_ADJUST, c) is S.ASK_ANOTHER_LOGO


def test_another_logo_yes_loops_until_cap():
    c = {"logo_count": 1, "wants_another_logo": True}
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, c) is S.ASK_LOGO_PLACEMENT
    c = {"logo_count": 4, "wants_another_logo": True}
    # At the cap, no more logos — advance to the decor loop.
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, c) is S.ASK_ADD_DECOR


def test_another_logo_no_goes_to_decor():
    assert v2.advance_state_v2(S.ASK_ANOTHER_LOGO, {"wants_another_logo": False}) is S.ASK_ADD_DECOR


def test_decor_loop():
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {"decor_choice": "text"}) is S.DECOR_ADJUST
    assert v2.advance_state_v2(S.ASK_ADD_DECOR, {"decor_choice": None}) is S.ASK_QUANTITY
    assert v2.advance_state_v2(S.DECOR_ADJUST, {"decor_done": True}) is S.ASK_ANYTHING_ELSE
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": True}) is S.ASK_ADD_DECOR
    assert v2.advance_state_v2(S.ASK_ANYTHING_ELSE, {"wants_more_decor": False}) is S.ASK_QUANTITY


def test_tail_reorder_quantity_email_purpose_then_finalize():
    assert v2.advance_state_v2(S.ASK_QUANTITY, {"quantity": 12}) is S.ASK_EMAIL
    assert v2.advance_state_v2(S.ASK_EMAIL, {"email_captured": True}) is S.ASK_PURPOSE
    assert v2.advance_state_v2(S.ASK_PURPOSE, {"purpose": "team"}) is S.FINALIZE_CANVAS


def test_progress_counts_v2_path():
    p = v2.progress_v2(S.ASK_NAME, {})
    assert p["step"] == 1
    assert p["total"] >= 6
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: FAIL (`ModuleNotFoundError: state_machine_v2`).

- [ ] **Step 4: Implement `state_machine_v2.py`**

```python
# backend/app/services/conversation/state_machine_v2.py
"""v2 step-by-step canvas orchestrator routing.

Linear front half with two loops (logos ≤4, then text/shape), then the
quantity/email/purpose reorder, then a finalize handoff into the shared tail.
The orchestrator sets the branch flags on `collected`; this module only maps
(state, collected) -> next state. Downstream of FINALIZE_CANVAS the shared v1
tail (advance_state) takes over.
"""
from __future__ import annotations

from app.services.conversation.state_machine import ConversationState as S

MAX_LOGOS = 4

# The front-half states v2 owns (everything before the shared tail).
V2_STATES: frozenset[S] = frozenset({
    S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT, S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO,
    S.ASK_ADD_DECOR, S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE, S.FINALIZE_CANVAS,
})


def advance_state_v2(current: S, collected: dict) -> S:
    if current is S.ASK_NAME:
        return S.SHOW_INTRO
    if current is S.SHOW_INTRO:
        return S.ASK_LOGO_PLACEMENT
    if current is S.ASK_LOGO_PLACEMENT:
        return S.LOGO_ADJUST
    if current is S.LOGO_ADJUST:
        return S.ASK_ANOTHER_LOGO if collected.get("logo_done") else S.LOGO_ADJUST
    if current is S.ASK_ANOTHER_LOGO:
        if collected.get("wants_another_logo") and int(collected.get("logo_count") or 0) < MAX_LOGOS:
            return S.ASK_LOGO_PLACEMENT
        return S.ASK_ADD_DECOR
    if current is S.ASK_ADD_DECOR:
        return S.DECOR_ADJUST if collected.get("decor_choice") else S.ASK_QUANTITY
    if current is S.DECOR_ADJUST:
        return S.ASK_ANYTHING_ELSE if collected.get("decor_done") else S.DECOR_ADJUST
    if current is S.ASK_ANYTHING_ELSE:
        return S.ASK_ADD_DECOR if collected.get("wants_more_decor") else S.ASK_QUANTITY
    if current is S.ASK_QUANTITY:
        return S.ASK_EMAIL if collected.get("quantity") not in (None, "") else S.ASK_QUANTITY
    if current is S.ASK_EMAIL:
        return S.ASK_PURPOSE if collected.get("email_captured") else S.ASK_EMAIL
    if current is S.ASK_PURPOSE:
        return S.FINALIZE_CANVAS if collected.get("purpose") not in (None, "") else S.ASK_PURPOSE
    # FINALIZE_CANVAS is resolved by the finalize route (-> GENERATING), not here.
    return current


# "Step X of N" — the ordered customer-facing question states for v2.
_V2_PROGRESS_PATH: list[S] = [
    S.ASK_NAME, S.SHOW_INTRO, S.ASK_LOGO_PLACEMENT,
    S.ASK_ADD_DECOR, S.ASK_QUANTITY, S.ASK_EMAIL, S.ASK_PURPOSE,
]


def progress_v2(state: S, collected: dict) -> dict:
    total = len(_V2_PROGRESS_PATH)
    # Loop/adjust states collapse onto their loop's anchor question.
    norm = state
    if state in (S.LOGO_ADJUST, S.ASK_ANOTHER_LOGO):
        norm = S.ASK_LOGO_PLACEMENT
    elif state in (S.DECOR_ADJUST, S.ASK_ANYTHING_ELSE):
        norm = S.ASK_ADD_DECOR
    if norm in _V2_PROGRESS_PATH:
        return {"step": _V2_PROGRESS_PATH.index(norm) + 1, "total": total}
    # Past the questionnaire (finalize + tail) -> complete.
    return {"step": total, "total": total}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine.py backend/app/services/conversation/state_machine_v2.py backend/tests/test_state_machine_v2.py
git commit -m "feat(conv): v2 canvas state machine routing + enum members"
```

---

### Task 3: v2 reply copy + `canvas` directive builder

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py` (add `canvas_directive` + `v2_public_data`)
- Modify: `backend/app/prompts.py` (add `V2_CANNED_REPLIES` dict + per-tool intro fallback)
- Test: `backend/tests/test_state_machine_v2.py` (extend)

**Interfaces:**
- Consumes: `ConversationState`, `collected` dict; `store` brand dict for the intro text.
- Produces:
  - `canvas_directive(state: ConversationState, collected: dict) -> dict | None` — the `{allowed_tools, target_face, auto_open, instructions, show_done}` blob (or `None` when the state drives no canvas change).
  - `v2_public_data(state: ConversationState, collected: dict) -> dict` — merges options/continuable/directive/trigger flags for the frontend.
  - `v2_reply(state, collected, persona, intro_text) -> str` — deterministic reply copy per v2 state.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_state_machine_v2.py
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.state_machine import ConversationState as S


def test_directive_logo_placement_unlocks_upload_only():
    d = v2.canvas_directive(S.ASK_LOGO_PLACEMENT, {})
    assert d["allowed_tools"] == ["upload"]
    assert d["auto_open"] == "upload"
    assert d["show_done"] is False


def test_directive_logo_adjust_shows_done_and_keeps_upload():
    d = v2.canvas_directive(S.LOGO_ADJUST, {"logo_face": "back"})
    assert d["show_done"] is True
    assert d["target_face"] == "back"


def test_directive_anything_else_locks_all_tools():
    d = v2.canvas_directive(S.ASK_ANYTHING_ELSE, {})
    assert d["allowed_tools"] == []


def test_directive_none_for_tail_states():
    assert v2.canvas_directive(S.ASK_QUANTITY, {}) is None


def test_public_data_finalize_triggers_finalize():
    data = v2.v2_public_data(S.FINALIZE_CANVAS, {})
    assert data["trigger_finalize"] is True


def test_reply_uses_intro_text():
    r = v2.v2_reply(S.SHOW_INTRO, {"name": "Sam"}, "Ricardo", "Welcome to MadHats!")
    assert "Welcome to MadHats!" in r
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: FAIL (`AttributeError: canvas_directive`).

- [ ] **Step 3: Add per-tool tip fallbacks to `prompts.py`**

Append to `backend/app/prompts.py`:

```python
# --- v2 step-by-step canvas orchestrator copy ---
V2_TOOL_TIPS = {
    "upload": (
        "Tap the highlighted “Upload image” button to add your logo. "
        "Once it’s on the cap you can drag it to move it, pull a corner to "
        "resize, and use the top handle to rotate."
    ),
    "text": (
        "Tap the highlighted “Add text” button, type your wording, then drag "
        "to position it. You can change the font, size and colour from the "
        "toolbar under the cap."
    ),
    "shape": (
        "Tap the highlighted “Graphics” button to drop in a shape, then drag "
        "to position and resize it. Recolour it from the toolbar under the cap."
    ),
}

V2_DEFAULT_INTRO = (
    "Welcome! I’ll help you put your design straight onto the cap. We’ll add "
    "your logo first, then any text or graphics, and I’ll guide you through "
    "each tool as we go."
)
```

- [ ] **Step 4: Implement `canvas_directive`, `v2_public_data`, `v2_reply` in `state_machine_v2.py`**

Append to `state_machine_v2.py`:

```python
from app import prompts  # noqa: E402  (kept local-style with the other imports at top when moving)

_VALID_FACES = {"front", "back", "left", "right"}


def _logo_face(collected: dict) -> str:
    face = (collected.get("logo_face") or "front")
    return face if face in _VALID_FACES else "front"


def canvas_directive(state: S, collected: dict) -> dict | None:
    """The canvas-control blob for a v2 state, or None when the state drives no
    canvas change (tail/question-only states)."""
    if state is S.ASK_LOGO_PLACEMENT:
        # The customer is about to pick a face + upload; unlock+open upload.
        return {
            "allowed_tools": ["upload"],
            "target_face": _logo_face(collected),
            "auto_open": "upload",
            "instructions": prompts.V2_TOOL_TIPS["upload"],
            "show_done": False,
        }
    if state is S.LOGO_ADJUST:
        return {
            "allowed_tools": ["upload"],
            "target_face": _logo_face(collected),
            "auto_open": None,
            "instructions": prompts.V2_TOOL_TIPS["upload"],
            "show_done": True,
        }
    if state is S.DECOR_ADJUST:
        tool = "text" if collected.get("decor_choice") == "text" else "shape"
        return {
            "allowed_tools": [tool],
            "target_face": _logo_face(collected),
            "auto_open": tool,
            "instructions": prompts.V2_TOOL_TIPS[tool],
            "show_done": True,
        }
    if state in (S.ASK_ANYTHING_ELSE, S.ASK_QUANTITY):
        # Lock every tool once the design phase is over.
        return {"allowed_tools": [], "target_face": None, "auto_open": None,
                "instructions": None, "show_done": False}
    return None


def v2_public_data(state: S, collected: dict) -> dict:
    """Non-PII UI data for a v2 state: chips + directive + trigger flags."""
    from app.services.conversation.state_machine_v2 import progress_v2  # self
    data: dict = {}
    if state is S.SHOW_INTRO:
        data["continuable"] = True
    elif state is S.ASK_LOGO_PLACEMENT:
        data["options"] = ["Front", "Back", "Left", "Right"]
    elif state is S.LOGO_ADJUST:
        data["options"] = ["Done"]
    elif state is S.ASK_ANOTHER_LOGO:
        data["options"] = ["Yes, another logo", "No, that's it"]
    elif state is S.ASK_ADD_DECOR:
        data["options"] = ["Add text", "Add a shape", "No, nothing else"]
    elif state is S.DECOR_ADJUST:
        data["options"] = ["Done"]
    elif state is S.ASK_ANYTHING_ELSE:
        data["options"] = ["Add something else", "No, that's everything"]
    elif state is S.ASK_QUANTITY:
        data["options"] = ["1", "2-11", "12-49", "50-99", "100+", "Not sure"]
    elif state is S.FINALIZE_CANVAS:
        data["trigger_finalize"] = True
    directive = canvas_directive(state, collected)
    if directive is not None:
        data["canvas"] = directive
    data["progress"] = progress_v2(state, collected)
    return data


def v2_reply(state: S, collected: dict, persona: str, intro_text: str) -> str:
    """Deterministic reply copy per v2 state (never LLM-paraphrased, so no
    instruction detail is dropped)."""
    name = collected.get("name") or "there"
    tips = prompts.V2_TOOL_TIPS
    if state is S.SHOW_INTRO:
        return f"{intro_text}\n\nReady? Tap continue when you are."
    if state is S.ASK_LOGO_PLACEMENT:
        return (
            f"Great, {name}! Let’s add your logo. Which part of the cap should it "
            f"go on — front, back, left or right? {tips['upload']}"
        )
    if state is S.LOGO_ADJUST:
        return (
            "Nice — your logo’s on the cap. Do you want the background removed? "
            "You can drag to move it, resize from a corner, or rotate it. "
            "Press Done when the placement looks right."
        )
    if state is S.ASK_ANOTHER_LOGO:
        return "Locked that in. Would you like to add another logo?"
    if state is S.ASK_ADD_DECOR:
        return "Would you like to add any text or a shape to your design?"
    if state is S.DECOR_ADJUST:
        tool = "text" if collected.get("decor_choice") == "text" else "shape"
        return f"{tips[tool]} Press Done when you’re happy with it."
    if state is S.ASK_ANYTHING_ELSE:
        return "Is that everything, or would you like to add anything else?"
    if state is S.ASK_QUANTITY:
        return "How many caps are you after?"
    if state is S.ASK_EMAIL:
        return "What’s the best email to send your design preview to?"
    if state is S.ASK_PURPOSE:
        return "Last thing — if you don’t mind me asking, what’s the hat for?"
    if state is S.FINALIZE_CANVAS:
        return "Perfect — putting your design together now…"
    return "Let’s keep going."
```

> **Note on the `from app import prompts` import:** move it to the top of the
> module with the other imports rather than mid-file; it is shown inline here
> only to keep the diff readable.

- [ ] **Step 5: Run to verify it passes**

Run: `cd backend && pytest tests/test_state_machine_v2.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py backend/app/prompts.py backend/tests/test_state_machine_v2.py
git commit -m "feat(conv): v2 canvas directive builder + reply copy"
```

---

### Task 4: `orchestrator_v2.handle_message`

**Files:**
- Create: `backend/app/services/conversation/orchestrator_v2.py`
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: `state_machine_v2.advance_state_v2/v2_public_data/v2_reply/progress_v2`, `state_machine.ConversationState`, `leads.extract_email/capture_lead_and_verify`, `stores.get_store`, `db.get_supabase`, existing `orchestrator._apply_generation_gate`/`_can_start_design` (reused), `intent_extractor` for quantity/purpose parsing.
- Produces: `async def handle_message(session_id: str, message: str) -> dict` returning `{"reply", "state", "data"}` (same shape as v1). Also re-exports `SessionNotFound` from v1.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_orchestrator_v2.py
import pytest
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


@pytest.mark.asyncio
async def test_kickoff_greets_and_advances_to_ask_name(canvas_session_v2):
    # canvas_session_v2 fixture: a persisted flow_mode="canvas" session at GREETING.
    res = await o2.handle_message(canvas_session_v2, "")
    assert res["state"] == S.ASK_NAME.value


@pytest.mark.asyncio
async def test_name_advances_to_intro_with_admin_text(canvas_session_v2, seed_store_intro):
    await o2.handle_message(canvas_session_v2, "")           # greeting -> ask_name
    res = await o2.handle_message(canvas_session_v2, "Sam")   # name -> show_intro
    assert res["state"] == S.SHOW_INTRO.value
    assert seed_store_intro in res["reply"]
    assert res["data"]["continuable"] is True


@pytest.mark.asyncio
async def test_logo_placement_emits_upload_directive(canvas_session_v2):
    await o2.handle_message(canvas_session_v2, "")
    await o2.handle_message(canvas_session_v2, "Sam")
    res = await o2.handle_message(canvas_session_v2, "continue")  # intro -> placement
    assert res["state"] == S.ASK_LOGO_PLACEMENT.value
    assert res["data"]["canvas"]["allowed_tools"] == ["upload"]


@pytest.mark.asyncio
async def test_done_locks_and_advances_to_another_logo(canvas_session_v2):
    for m in ("", "Sam", "continue", "Front"):
        res = await o2.handle_message(canvas_session_v2, m)
    assert res["state"] == S.LOGO_ADJUST.value
    res = await o2.handle_message(canvas_session_v2, "done")
    assert res["state"] == S.ASK_ANOTHER_LOGO.value
```

> The fixtures `canvas_session_v2`, `seed_store_intro`, `seed_store_intro` follow
> the existing `conftest.py` pattern used by `test_orchestrator*` (a real
> Supabase-backed `design_sessions` row). Reuse the existing session-creation
> helper; see `backend/tests/conftest.py` for the current fixtures and add
> `canvas_session_v2` there (a session with `collected={"flow_mode":"canvas"}`
> and `state="greeting"`).

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_orchestrator_v2.py -q`
Expected: FAIL (`ModuleNotFoundError: orchestrator_v2`).

- [ ] **Step 3: Implement `orchestrator_v2.py`**

```python
# backend/app/services/conversation/orchestrator_v2.py
"""v2 step-by-step canvas orchestrator (parallel to orchestrator.py).

Owns the front half: greeting -> name -> admin intro -> logo loop (<=4) ->
text/shape loop -> quantity -> email -> purpose -> FINALIZE_CANVAS. From
FINALIZE_CANVAS the frontend flattens the canvas and calls /canvas-finalize,
which routes into the SHARED tail (GENERATING -> verify -> deliver -> refine).
Selected only when settings.canvas_orchestrator_v2 and flow_mode == "canvas".
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog

from app.config import settings
from app.db import get_supabase
from app.services import leads as leads_service
from app.services.branding import canvas_intro_text  # Task 7
from app.services.stores import get_store
from app.services.conversation import intent_extractor as ie
from app.services.conversation import state_machine_v2 as v2
from app.services.conversation.orchestrator import (
    SessionNotFound,
    _apply_generation_gate,   # reused (daily-cap honesty gate)
    _can_start_design,        # reused
)
from app.services.conversation.state_machine import (
    ConversationState,
    is_affirmative,
    is_negative,
)

log = structlog.get_logger()
S = ConversationState

_DONE_WORDS = ("done", "looks good", "that's it", "thats it", "finished", "ready", "good")


def _is_done(message: str) -> bool:
    low = (message or "").strip().lower()
    return any(w in low for w in _DONE_WORDS) or is_affirmative(message)


def _face_from(message: str) -> str | None:
    low = (message or "").lower()
    for f in ("front", "back", "left", "right"):
        if f in low:
            return f
    return None


def _apply_v2_fields(state: ConversationState, collected: dict, message: str) -> bool:
    """Capture the field(s) a v2 state expects. Returns email_retry flag."""
    low = (message or "").strip().lower()

    if state is S.ASK_NAME and not collected.get("name"):
        candidate = message.strip().split("\n")[0][:60]
        if candidate and "?" not in candidate and not ie._is_greeting_only(candidate):
            collected["name"] = candidate

    elif state is S.ASK_LOGO_PLACEMENT:
        face = _face_from(message)
        if face:
            collected["logo_face"] = face

    elif state is S.LOGO_ADJUST:
        if _is_done(message):
            collected["logo_done"] = True
            collected["logo_count"] = int(collected.get("logo_count") or 0) + 1

    elif state is S.ASK_ANOTHER_LOGO:
        collected["wants_another_logo"] = is_affirmative(message) and not is_negative(message)
        collected["logo_done"] = False  # reset for the next loop iteration

    elif state is S.ASK_ADD_DECOR:
        if is_negative(message) or "nothing" in low:
            collected["decor_choice"] = None
        elif "text" in low:
            collected["decor_choice"] = "text"
        elif "shape" in low or "graphic" in low:
            collected["decor_choice"] = "shape"
        collected["decor_done"] = False

    elif state is S.DECOR_ADJUST:
        if _is_done(message):
            collected["decor_done"] = True

    elif state is S.ASK_ANYTHING_ELSE:
        collected["wants_more_decor"] = (
            is_affirmative(message) or "add" in low
        ) and not is_negative(message)

    elif state is S.ASK_QUANTITY:
        collected["quantity"] = ie._parse_quantity_heuristic(message)

    elif state is S.ASK_PURPOSE:
        collected["purpose"] = message.strip()

    # Email capture (double opt-in) at ASK_EMAIL.
    email_retry = False
    if state is S.ASK_EMAIL and not collected.get("email_captured"):
        email = leads_service.extract_email(message)
        if email:
            # Need the full session row for capture; caller passes collected only,
            # so this branch is handled in handle_message (has the session).
            collected["_pending_email"] = email
    return email_retry


async def handle_message(session_id: str, message: str) -> dict:
    sb = get_supabase()
    res = sb.table("design_sessions").select("*").eq("id", session_id).limit(1).execute()
    if not res.data:
        raise SessionNotFound(session_id)
    session = res.data[0]

    current = ConversationState(session["state"])
    collected: dict = session.get("collected") or {}
    store = get_store(session.get("store_id")) if session.get("store_id") else None
    persona = (store or {}).get("persona_name") or settings.chatbot_persona_name
    intro_text = canvas_intro_text(store)
    state_before = current.value

    # KICKOFF: greet + advance to ASK_NAME without ingesting the opening turn.
    if current is S.GREETING:
        new_state = S.ASK_NAME
        reply = v2.v2_reply(new_state, collected, persona, intro_text)
    else:
        _apply_v2_fields(current, collected, message)

        # Email capture needs the full session row (leads.capture_lead_and_verify).
        email_retry = False
        if current is S.ASK_EMAIL and collected.pop("_pending_email", None):
            email = leads_service.extract_email(message)
            if email:
                lead_id, ok = leads_service.capture_lead_and_verify(session, collected, email)
                if lead_id:
                    collected["lead_id"] = lead_id
                if ok:
                    collected["email_captured"] = True
                else:
                    email_retry = True

        new_state = v2.advance_state_v2(current, collected)

        # Daily-cap honesty gate on entry to FINALIZE_CANVAS (which leads to
        # generation): reroute to the quote handoff if the customer is capped.
        if new_state is S.FINALIZE_CANVAS and not _can_start_design(session_id):
            collected["generation_blocked"] = "daily_limit"
            new_state = S.QUOTE_REQUESTED

        if email_retry:
            new_state = S.ASK_EMAIL

        # One-shot flag: mark the intro shown.
        if new_state is S.SHOW_INTRO:
            collected["intro_shown"] = True

        reply = v2.v2_reply(new_state, collected, persona, intro_text)

    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()

    sb.table("chat_messages").insert([
        {"session_id": session_id, "role": "user", "content": message,
         "state_before": state_before, "state_after": state_before},
        {"session_id": session_id, "role": "assistant", "content": reply,
         "state_before": state_before, "state_after": new_state.value},
    ]).execute()

    data = v2.v2_public_data(new_state, collected)
    return {"reply": reply, "state": new_state.value, "data": data}
```

> **Downstream tail:** once `finalize_canvas` (Task 6) moves the session to
> `GENERATING`, the frontend's generation poll hits the existing
> `/chat/{id}/generation-advance` and `/verification` routes, which run the
> shared v1 poll functions — v2 does not re-implement them.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_orchestrator_v2.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py backend/tests/test_orchestrator_v2.py backend/tests/conftest.py
git commit -m "feat(conv): v2 orchestrator handle_message (front half + tail handoff)"
```

---

### Task 5: Route dispatch (v1 vs v2)

**Files:**
- Modify: `backend/app/api/routes/chat.py:25-38` (the `chat` handler)
- Test: `backend/tests/test_chat_route_dispatch.py` (create)

**Interfaces:**
- Consumes: `settings.canvas_orchestrator_v2`, both orchestrators' `handle_message`.
- Produces: no new symbols; behaviour = dispatch.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_chat_route_dispatch.py
import pytest
from app.api.routes import chat as chat_route
from app.services.conversation.state_machine import ConversationState as S


@pytest.mark.asyncio
async def test_dispatch_v2_when_flag_on_and_canvas(monkeypatch, canvas_session_v2):
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", True)
    called = {}

    async def fake_v2(sid, msg):
        called["v2"] = True
        return {"reply": "hi", "state": S.ASK_NAME.value, "data": {}}

    monkeypatch.setattr(chat_route, "handle_message_v2", fake_v2)
    await chat_route._dispatch(canvas_session_v2, "")
    assert called.get("v2") is True


@pytest.mark.asyncio
async def test_dispatch_v1_when_flag_off(monkeypatch, canvas_session_v2):
    monkeypatch.setattr(chat_route.settings, "canvas_orchestrator_v2", False)
    called = {}

    async def fake_v1(sid, msg):
        called["v1"] = True
        return {"reply": "hi", "state": S.ASK_NAME.value, "data": {}}

    monkeypatch.setattr(chat_route, "handle_message", fake_v1)
    await chat_route._dispatch(canvas_session_v2, "")
    assert called.get("v1") is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_chat_route_dispatch.py -q`
Expected: FAIL (`AttributeError: _dispatch`).

- [ ] **Step 3: Implement the dispatch**

In `backend/app/api/routes/chat.py`, update the imports and add a `_dispatch` helper:

```python
from app.config import settings
from app.db import get_supabase
from app.services.conversation.orchestrator import (
    SessionNotFound,
    advance_after_generation,
    advance_after_regeneration,
    check_verification,
    handle_message,
)
from app.services.conversation.orchestrator_v2 import handle_message as handle_message_v2


async def _dispatch(session_id: str, message: str) -> dict:
    """Route a chat turn to v2 (canvas sessions, flag on) or v1 (everything else)."""
    if settings.canvas_orchestrator_v2:
        sb = get_supabase()
        res = sb.table("design_sessions").select("collected").eq("id", session_id).limit(1).execute()
        if res.data:
            collected = res.data[0].get("collected") or {}
            if collected.get("flow_mode") == "canvas":
                return await handle_message_v2(session_id, message)
    return await handle_message(session_id, message)
```

Then change the handler body to call `_dispatch`:

```python
    try:
        result = await _dispatch(session_id, body.message)
    except SessionNotFound as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_chat_route_dispatch.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/chat.py backend/tests/test_chat_route_dispatch.py
git commit -m "feat(chat): dispatch canvas sessions to v2 orchestrator behind flag"
```

---

### Task 6: `finalize_canvas` v2 branch (→ GENERATING)

**Files:**
- Modify: `backend/app/api/routes/sessions.py:213-284` (`finalize_canvas`)
- Test: `backend/tests/test_finalize_v2.py` (create)

**Interfaces:**
- Consumes: `settings.canvas_orchestrator_v2`, existing `canvas_describe.canvas_to_elements`, `ConversationState`, `progress` (v1) — but for v2 use `progress_v2`.
- Produces: when v2 active + canvas session, finalize returns `state == "generating"` with `data.trigger_generation is True` and does NOT run the decoration outro.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_finalize_v2.py
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_v2_finalize_goes_straight_to_generating(monkeypatch, app_client, canvas_session_v2, store_headers, minimal_canvas_design):
    from app.api.routes import sessions as sess_route
    monkeypatch.setattr(sess_route.settings, "canvas_orchestrator_v2", True)
    r = await app_client.post(
        f"/sessions/{canvas_session_v2}/canvas-finalize",
        json={"canvas_design": minimal_canvas_design},
        headers=store_headers,
    )
    body = r.json()
    assert body["state"] == "generating"
    assert body["data"]["trigger_generation"] is True
```

> Reuse the existing session/store/client fixtures the other `sessions` route
> tests use (`app_client`, `store_headers`); add `minimal_canvas_design`
> (a `CanvasDesign` dict with one front text element) and `canvas_session_v2`
> to `conftest.py`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_finalize_v2.py -q`
Expected: FAIL (state is `ask_decoration`, not `generating`).

- [ ] **Step 3: Add the v2 branch to `finalize_canvas`**

In `sessions.py`, right after the `reworking` branch returns (after line 263) and **before** the `active = deco_svc.list_types(...)` outro block, insert:

```python
    # v2 step-by-step orchestrator: the design phase already happened in chat,
    # and name/quantity/email/purpose were captured there. Skip the v1
    # decoration/notes outro and go straight to generation.
    if settings.canvas_orchestrator_v2:
        from app.services.conversation.state_machine_v2 import progress_v2
        new_state = S.GENERATING
        reply = "Perfect — generating your design now…"
        sb.table("design_sessions").update(
            {"canvas_design": body.canvas_design, "collected": collected, "state": new_state.value}
        ).eq("id", session_id).execute()
        return {
            "reply": reply,
            "state": new_state.value,
            "data": {"trigger_generation": True, "progress": progress_v2(new_state, collected)},
        }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_finalize_v2.py -q`
Expected: PASS.

- [ ] **Step 5: Run the finalize regression (v1 still hits the outro)**

Run: `cd backend && pytest tests/ -q -k finalize`
Expected: PASS (v1 finalize tests unchanged — the branch is flag-gated).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/sessions.py backend/tests/test_finalize_v2.py backend/tests/conftest.py
git commit -m "feat(sessions): finalize canvas straight to generating under v2 flag"
```

---

### Task 7: Admin-set intro text

**Files:**
- Modify: `backend/app/services/branding.py` (add `canvas_intro_text` + validate the field in `validate_brand`)
- Modify: admin stores PATCH (wherever `validate_brand` merges brand — `backend/app/api/routes/admin_stores.py` or equivalent)
- Test: `backend/tests/test_branding_canvas_intro.py` (create)

**Interfaces:**
- Consumes: `store` dict (may be `None`); `store["brand"]` jsonb.
- Produces:
  - `canvas_intro_text(store: dict | None) -> str` — returns `store.brand.canvas_intro` when a non-empty string, else `prompts.V2_DEFAULT_INTRO`.
  - `validate_brand` accepts an optional `canvas_intro` string (≤600 chars), preserved through PATCH's read-merge.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_branding_canvas_intro.py
from app.services.branding import canvas_intro_text, validate_brand
from app import prompts


def test_default_when_unset():
    assert canvas_intro_text(None) == prompts.V2_DEFAULT_INTRO
    assert canvas_intro_text({"brand": {}}) == prompts.V2_DEFAULT_INTRO


def test_returns_admin_text():
    store = {"brand": {"canvas_intro": "Custom welcome!"}}
    assert canvas_intro_text(store) == "Custom welcome!"


def test_validate_keeps_intro():
    out = validate_brand({"canvas_intro": "Hello team"})
    assert out["canvas_intro"] == "Hello team"


def test_validate_rejects_overlong_intro():
    import pytest
    with pytest.raises(Exception):
        validate_brand({"canvas_intro": "x" * 601})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && pytest tests/test_branding_canvas_intro.py -q`
Expected: FAIL (`ImportError: cannot import name 'canvas_intro_text'`).

- [ ] **Step 3: Implement in `branding.py`**

Add to `backend/app/services/branding.py`:

```python
from app import prompts


def canvas_intro_text(store: dict | None) -> str:
    """The admin-set step-2 intro for the v2 canvas flow, or the MadHats default."""
    brand = (store or {}).get("brand") or {}
    text = brand.get("canvas_intro")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return prompts.V2_DEFAULT_INTRO
```

In `validate_brand`, where other optional string keys are validated, add:

```python
    intro = brand.get("canvas_intro")
    if intro is not None:
        if not isinstance(intro, str) or len(intro) > 600:
            raise ValueError("canvas_intro must be a string of at most 600 characters")
        out["canvas_intro"] = intro
```

> Match the exact `validate_brand` structure already in the file (it builds an
> allow-listed `out` dict). Add `canvas_intro` to that allow-list so the PATCH
> read-merge preserves it. Do **not** add it to `public_brand` unless the
> storefront needs it — v2 reads it server-side via `canvas_intro_text`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd backend && pytest tests/test_branding_canvas_intro.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/branding.py backend/tests/test_branding_canvas_intro.py
git commit -m "feat(branding): admin-set canvas_intro for v2 flow"
```

---

## Frontend

### Task 8: Per-element `locked` in `canvasStore`

**Files:**
- Modify: `frontend/src/store/canvasStore.ts` (`CanvasElement` interface + actions)
- Test: `frontend/src/__tests__/canvasStoreLock.test.ts` (create)

**Interfaces:**
- Consumes: existing store shape.
- Produces:
  - `CanvasElement.locked?: boolean`
  - `lockAll: () => void` — sets `locked: true` on every element on every face.
  - `unlockAll: () => void` — clears `locked` on every element on every face.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/canvasStoreLock.test.ts
import { beforeEach, expect, test } from 'vitest'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => useCanvasStore.getState().reset())

test('lockAll marks every element locked', () => {
  const s = useCanvasStore.getState()
  s.addText('a')
  s.setActiveFace('back'); s.addText('b')
  s.lockAll()
  const { faces } = useCanvasStore.getState()
  expect(faces.front[0].locked).toBe(true)
  expect(faces.back[0].locked).toBe(true)
})

test('unlockAll clears locked', () => {
  const s = useCanvasStore.getState()
  s.addText('a'); s.lockAll(); s.unlockAll()
  expect(useCanvasStore.getState().faces.front[0].locked).toBe(false)
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreLock.test.ts`
Expected: FAIL (`lockAll is not a function`).

- [ ] **Step 3: Implement**

In `canvasStore.ts`, add to `CanvasElement`:

```ts
  /** v2 flow: a locked layer can't be moved/resized/selected. */
  locked?: boolean
```

Add to the `CanvasState` interface:

```ts
  lockAll: () => void
  unlockAll: () => void
```

Add the actions to the store body (near `reset`):

```ts
  lockAll: () => set(s => {
    const faces = { ...s.faces }
    for (const f of FACES) faces[f] = faces[f].map(e => ({ ...e, locked: true }))
    return { faces, selectedId: null }
  }),

  unlockAll: () => set(s => {
    const faces = { ...s.faces }
    for (const f of FACES) faces[f] = faces[f].map(e => ({ ...e, locked: false }))
    return { faces }
  }),
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/canvasStoreLock.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/canvasStore.ts frontend/src/__tests__/canvasStoreLock.test.ts
git commit -m "feat(canvas): per-element locked + lockAll/unlockAll"
```

---

### Task 9: `nodes.tsx` respects `el.locked`

**Files:**
- Modify: `frontend/src/components/DesignStudio/nodes.tsx` (every node's `draggable`, `onClick/onTap`, and the `Transformer` render)
- Test: covered by the surface integration test (Task 13) + a focused node test below.

**Interfaces:**
- Consumes: `CanvasElement.locked`.
- Produces: locked elements are not draggable, not selectable, render no `Transformer`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/lockedNode.test.tsx
import { render } from '@testing-library/react'
import { expect, test, vi } from 'vitest'
import { Stage, Layer } from 'react-konva'
import { TextNode } from '../components/DesignStudio/nodes'
import type { CanvasElement } from '../store/canvasStore'

const base: CanvasElement = {
  id: '1', type: 'text', x: 0.5, y: 0.5, width: 0.3, height: 0.1,
  rotation: 0, zIndex: 0, content: 'hi', locked: true,
}

test('locked text node does not fire onSelect when clicked', () => {
  const onSelect = vi.fn()
  render(
    <Stage width={200} height={200}><Layer>
      <TextNode el={base} stageW={200} stageH={200} isSelected={false} onSelect={onSelect} onChange={() => {}} />
    </Layer></Stage>,
  )
  // A locked node registers no onClick handler, so selection can't fire.
  expect(onSelect).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/lockedNode.test.tsx`
Expected: FAIL (node still draggable / selectable — assertion on handler absence needs the guard).

- [ ] **Step 3: Implement**

For **each** node component in `nodes.tsx` (`TextNode`, `ImageNode`, `ShapeNode`, `DrawingNode`), change the shared `common`/props object so interactivity is gated on `!el.locked`:

```tsx
  const locked = !!el.locked
  const common = {
    ref: shapeRef as never,
    x: el.x * stageW,
    y: el.y * stageH,
    rotation: el.rotation,
    fontSize,
    fontFamily,
    fill,
    draggable: !locked,
    onClick: locked ? undefined : onSelect,
    onTap: locked ? undefined : onSelect,
    onDragEnd: (e: Konva.KonvaEventObject<DragEvent>) =>
      onChange({ x: e.target.x() / stageW, y: e.target.y() / stageH }),
    onTransformEnd: (e: Konva.KonvaEventObject<Event>) => {
      const node = e.target as Konva.Text
      onChange({ rotation: node.rotation(), fontSize: Math.max(8, fontSize * node.scaleX()) })
      node.scaleX(1); node.scaleY(1)
    },
  }
```

And guard the `Transformer` render in each node (it currently renders when `isSelected`):

```tsx
      {isSelected && !locked && (
        <Transformer ref={trRef as never} /* …existing props… */ />
      )}
```

Apply the same `locked`/`draggable: !locked`/`onClick: locked ? undefined : onSelect`/`isSelected && !locked` pattern to `ImageNode`, `ShapeNode`, and `DrawingNode` (each has its own `common` object and Transformer — repeat the guard in all).

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/lockedNode.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DesignStudio/nodes.tsx frontend/src/__tests__/lockedNode.test.tsx
git commit -m "feat(canvas): locked elements are non-interactive"
```

---

### Task 10: `ToolRail` per-tool gating + highlight

**Files:**
- Modify: `frontend/src/components/DesignStudio/ToolRail.tsx`
- Test: `frontend/src/__tests__/ToolRail.test.tsx` (extend)

**Interfaces:**
- Consumes: new props `allowedTools?: Set<'upload'|'text'|'shape'>`, `highlightTool?: 'upload'|'text'|'shape' | null`.
- Produces: when `allowedTools` is provided, only those tool buttons are enabled; the `highlightTool` button gets an accent glow + pulse; others are dimmed. When `allowedTools` is undefined, behaviour is unchanged (legacy `locked` gating).

- [ ] **Step 1: Write the failing test**

```tsx
// add to frontend/src/__tests__/ToolRail.test.tsx
import { render, screen } from '@testing-library/react'
import { ToolRail } from '../components/DesignStudio/ToolRail'

test('only allowed tool is enabled and highlighted', () => {
  render(
    <ToolRail onAddText={() => {}} onUploadClick={() => {}} onGraphicsClick={() => {}}
      colourways={[]} onRender={() => {}} rendering={false} rendered={false}
      allowedTools={new Set(['upload'])} highlightTool="upload" />,
  )
  const upload = screen.getByText('↑ Upload image')
  const text = screen.getByText('+ Add text')
  expect(upload).not.toBeDisabled()
  expect(text).toBeDisabled()
  expect(upload.className).toMatch(/animate-pulse|ring-2/)
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/ToolRail.test.tsx`
Expected: FAIL (prop not supported; text button not disabled).

- [ ] **Step 3: Implement**

Update `ToolRailProps` and the component in `ToolRail.tsx`:

```tsx
type Tool = 'upload' | 'text' | 'shape'

interface ToolRailProps {
  onAddText: () => void
  onUploadClick: () => void
  onGraphicsClick: () => void
  colourways: Colourway[]
  onRender: () => void
  rendering: boolean
  rendered: boolean
  locked?: boolean
  /** v2: when set, ONLY these tool buttons are enabled. */
  allowedTools?: Set<Tool>
  /** v2: the tool to visually highlight (accent glow + pulse). */
  highlightTool?: Tool | null
}

export function ToolRail({
  onAddText, onUploadClick, onGraphicsClick, colourways, onRender,
  rendering, rendered, locked, allowedTools, highlightTool,
}: ToolRailProps) {
  // …existing store hooks unchanged…

  // A tool is disabled if the whole rail is locked, or (v2) it's not in the
  // allowed set. When allowedTools is undefined we fall back to the legacy
  // `locked` behaviour so v1 is unaffected.
  const toolDisabled = (t: Tool) =>
    !!locked || (allowedTools !== undefined && !allowedTools.has(t))
  const hi = (t: Tool) =>
    highlightTool === t ? ' ring-2 ring-accent ring-offset-2 ring-offset-surface animate-pulse' : ''

  return (
    <div className="flex flex-col gap-3 p-4 w-full md:w-64">
      <button onClick={onAddText} disabled={toolDisabled('text')}
        className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('text')}`}>+ Add text</button>
      <button onClick={onUploadClick} disabled={toolDisabled('upload')}
        className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('upload')}`}>↑ Upload image</button>
      <button onClick={onGraphicsClick} disabled={toolDisabled('shape')}
        className={`px-4 py-2 bg-surface border border-border rounded-lg text-sm text-textPrimary hover:border-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-border${hi('shape')}`}>◈ Graphics</button>

      {/* Draw + colourways + render button: gate Draw on `locked` only (v2
          never highlights it); leave the rest unchanged. */}
      {/* …existing draw button, colourway swatches, and render button… */}
    </div>
  )
}
```

> Keep the existing Draw button / colourway / render-button markup exactly as
> it is (use `locked` for their `disabled`). Only the three tool buttons gain
> `toolDisabled`/`hi`.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/ToolRail.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/DesignStudio/ToolRail.tsx frontend/src/__tests__/ToolRail.test.tsx
git commit -m "feat(toolrail): per-tool gating + highlight for v2"
```

---

### Task 11: `chatStore` parses the `canvas` directive + `trigger_finalize`

**Files:**
- Modify: `frontend/src/store/chatStore.ts` (`parseData`, state interface, `reset`)
- Test: `frontend/src/__tests__/chatStoreCanvasDirective.test.ts` (create)

**Interfaces:**
- Consumes: chat `data` blob.
- Produces store fields:
  - `canvasDirective: { allowedTools: string[]; targetFace: string | null; autoOpen: string | null; instructions: string | null; showDone: boolean } | null`
  - `triggerFinalize: boolean`

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/__tests__/chatStoreCanvasDirective.test.ts
import { expect, test, beforeEach } from 'vitest'
import { useChatStore } from '../store/chatStore'

beforeEach(() => useChatStore.getState().reset())

test('parses canvas directive from applyResponse', () => {
  useChatStore.getState().applyResponse('hi', 'ask_logo_placement', {
    canvas: { allowed_tools: ['upload'], target_face: 'front', auto_open: 'upload', instructions: 'tip', show_done: false },
  })
  const d = useChatStore.getState().canvasDirective
  expect(d?.allowedTools).toEqual(['upload'])
  expect(d?.targetFace).toBe('front')
  expect(d?.autoOpen).toBe('upload')
})

test('parses trigger_finalize', () => {
  useChatStore.getState().applyResponse('go', 'finalize_canvas', { trigger_finalize: true })
  expect(useChatStore.getState().triggerFinalize).toBe(true)
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/chatStoreCanvasDirective.test.ts`
Expected: FAIL (`canvasDirective` undefined).

- [ ] **Step 3: Implement**

Add to `ChatStoreState`:

```ts
  /** v2 canvas flow: the current tool-control directive (null = no change). */
  canvasDirective: {
    allowedTools: string[]
    targetFace: string | null
    autoOpen: string | null
    instructions: string | null
    showDone: boolean
  } | null
  /** v2: the frontend should flatten + finalize the canvas now. */
  triggerFinalize: boolean
```

In `parseData`, before the `return`:

```ts
  const rawCanvas = (data.canvas && typeof data.canvas === 'object') ? data.canvas as Record<string, unknown> : null
  const canvasDirective = rawCanvas
    ? {
        allowedTools: Array.isArray(rawCanvas.allowed_tools) ? rawCanvas.allowed_tools as string[] : [],
        targetFace: typeof rawCanvas.target_face === 'string' ? rawCanvas.target_face : null,
        autoOpen: typeof rawCanvas.auto_open === 'string' ? rawCanvas.auto_open : null,
        instructions: typeof rawCanvas.instructions === 'string' ? rawCanvas.instructions : null,
        showDone: rawCanvas.show_done === true,
      }
    : null
  const triggerFinalize = data.trigger_finalize === true
```

Add `canvasDirective, triggerFinalize` to the object `parseData` returns.
Initialise both (`canvasDirective: null`, `triggerFinalize: false`) in the store defaults **and** in `reset()`.

> **Note:** `parseData` spreads its result over the store on every response, so
> `canvasDirective` correctly resets to `null` on any turn whose `data` carries
> no `canvas` key — the directive never "sticks" across steps.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/chatStoreCanvasDirective.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/store/chatStore.ts frontend/src/__tests__/chatStoreCanvasDirective.test.ts
git commit -m "feat(chatstore): parse v2 canvas directive + trigger_finalize"
```

---

### Task 12: Canned per-tool instruction constants (frontend)

**Files:**
- Create: `frontend/src/components/DesignStudio/toolInstructions.ts`
- Test: none (pure constant module; exercised in Task 13).

**Interfaces:**
- Produces: `TOOL_INSTRUCTIONS: Record<'upload'|'text'|'shape', string>` — a frontend mirror of the backend tips, used when the directive carries no `instructions` string (defensive fallback).

- [ ] **Step 1: Create the module**

```ts
// frontend/src/components/DesignStudio/toolInstructions.ts
/** Canned per-tool usage tips (fallback when the chat directive omits copy). */
export const TOOL_INSTRUCTIONS: Record<'upload' | 'text' | 'shape', string> = {
  upload: 'Drag to move it, pull a corner to resize, and use the top handle to rotate.',
  text: 'Type your wording, drag to position, and change font/size/colour in the toolbar under the cap.',
  shape: 'Drag to position and resize; recolour it from the toolbar under the cap.',
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/DesignStudio/toolInstructions.ts
git commit -m "feat(canvas): canned per-tool instruction constants"
```

---

### Task 13: `DesignStudioSurface` reacts to the directive

**Files:**
- Modify: `frontend/src/components/DesignStudio/Surface.tsx`
- Test: `frontend/src/__tests__/surfaceDirective.test.tsx` (create)

**Interfaces:**
- Consumes: `useChatStore().canvasDirective`, `triggerFinalize`, `chatState`; `useCanvasStore().setActiveFace/lockAll`; `useSessionStore().sessionId`.
- Produces: the surface switches face, gates + highlights tools, shows the instruction callout, auto-opens the tool dialog, renders a Done button that posts `"done"`, and runs `doRender()` when `triggerFinalize` flips true.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/surfaceDirective.test.tsx
import { render, screen } from '@testing-library/react'
import { expect, test, beforeEach, vi } from 'vitest'
import { DesignStudioSurface } from '../components/DesignStudio/Surface'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'
import { useCanvasStore } from '../store/canvasStore'

beforeEach(() => {
  useChatStore.getState().reset()
  useCanvasStore.getState().reset()
  useSessionStore.setState({ sessionId: 's1', productRef: null } as never)
})

test('directive shows the instruction callout and Done button', () => {
  useChatStore.setState({
    chatState: 'logo_adjust',
    canvasDirective: { allowedTools: ['upload'], targetFace: 'front', autoOpen: null, instructions: 'Drag to move it', showDone: true },
  } as never)
  render(<DesignStudioSurface />)
  expect(screen.getByText('Drag to move it')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /done/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx`
Expected: FAIL (callout + Done button not rendered).

- [ ] **Step 3: Implement**

In `Surface.tsx`, read the directive and derive tool gating. Replace the `unlocked` derivation + `ToolRail` usage with directive-aware wiring. Key additions:

```tsx
  const canvasDirective = useChatStore(s => s.canvasDirective)
  const triggerFinalize = useChatStore(s => s.triggerFinalize)
  const lockAll = useCanvasStore(s => s.lockAll)

  // v2 = a canvas directive is present. Fall back to the legacy whole-rail
  // gating (chatState === 'canvas_design') when there is no directive (v1).
  const isV2 = canvasDirective !== null
  const allowedTools = isV2 ? new Set(canvasDirective!.allowedTools) : undefined
  const highlightTool = isV2 && canvasDirective!.allowedTools.length === 1
    ? (canvasDirective!.allowedTools[0] as 'upload' | 'text' | 'shape')
    : null

  // Switch to the directive's target face.
  useEffect(() => {
    if (canvasDirective?.targetFace) setActiveFace(canvasDirective.targetFace as Face)
  }, [canvasDirective?.targetFace, setActiveFace])

  // Auto-open the requested tool dialog once per directive.
  useEffect(() => {
    if (canvasDirective?.autoOpen === 'upload') fileRef.current?.click()
    if (canvasDirective?.autoOpen === 'shape') setGraphicsOpen(true)
    if (canvasDirective?.autoOpen === 'text') addText('Your text')
  }, [canvasDirective?.autoOpen, addText])

  // When the chat says finalize, flatten + finalize exactly like the v1 render.
  const finalizeStarted = useRef(false)
  useEffect(() => {
    if (triggerFinalize && !finalizeStarted.current) {
      finalizeStarted.current = true
      void doRender()
    }
  }, [triggerFinalize])

  function postDone() {
    const sid = useSessionStore.getState().sessionId
    if (sid) void useChatStore.getState().sendMessage(sid, 'done')
  }
```

For the legacy path keep `const unlocked = chatState === 'canvas_design'`. Compute the rail-locked flag as: v2 → never whole-locked (per-tool gating owns it); v1 → `!unlocked`.

Add the instruction callout above the canvas and the Done button, and pass the new props to `ToolRail`:

```tsx
      {canvasDirective?.instructions && (
        <div className="mx-4 mt-3 rounded-lg border border-accent/40 bg-accent/5 px-4 py-2 text-sm text-textPrimary">
          {canvasDirective.instructions}
        </div>
      )}
      {/* …existing canvas + SelectedToolbar… */}
      {canvasDirective?.showDone && (
        <button onClick={postDone}
          className="mx-auto mt-2 px-6 py-2 bg-accent hover:bg-accentHover text-white rounded-full text-sm font-semibold">
          Done
        </button>
      )}
```

```tsx
        <ToolRail onAddText={() => addText('Your text')} onUploadClick={() => fileRef.current?.click()}
          onGraphicsClick={() => setGraphicsOpen(true)} colourways={colourways}
          onRender={() => void doRender()} rendering={rendering} rendered={rendered}
          locked={isV2 ? false : !unlocked}
          allowedTools={allowedTools} highlightTool={highlightTool} />
```

Pass `locked={isV2 ? false : !unlocked}` to `CanvasStage` too, so v2's placed
elements stay interactive (the per-element `locked` flag governs individual
locked layers instead).

> **`doRender` reuse:** `doRender()` already flattens every decorated face,
> uploads layouts + previews, calls `finalizeCanvas`, and applies the response.
> Under v2 `finalizeCanvas` returns `state: "generating"` + `trigger_generation`
> (Task 6), so the existing generation trigger in `CustomiseStudio`/chat picks
> up from there. No change to `doRender` itself is required.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/surfaceDirective.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the full frontend suite (guard against regressions)**

Run: `cd frontend && npx vitest run`
Expected: PASS (the 2 known pre-existing `adminQuotes` failures may remain — unrelated).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/Surface.tsx frontend/src/__tests__/surfaceDirective.test.tsx
git commit -m "feat(canvas): surface reacts to v2 directive (tools, highlight, done, finalize)"
```

---

### Task 14: Admin Branding — intro text field

**Files:**
- Modify: `frontend/src/admin/views/BrandingView.tsx`
- Test: extend an existing BrandingView test if present, else `frontend/src/__tests__/brandingCanvasIntro.test.tsx` (create)

**Interfaces:**
- Consumes: existing admin store GET/PATCH (`brand` object).
- Produces: a textarea bound to `brand.canvas_intro`, saved via the existing PATCH (which read-merges brand). Client guard: ≤600 chars.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/__tests__/brandingCanvasIntro.test.tsx
import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import { BrandingView } from '../admin/views/BrandingView'

test('branding view shows a canvas intro field', () => {
  render(<BrandingView />)  // mirror the existing BrandingView test's setup/mocks
  expect(screen.getByLabelText(/canvas intro/i)).toBeInTheDocument()
})
```

> Match however the existing BrandingView tests mount it (store selector,
> mocked API). If BrandingView needs a router/store context in tests, copy that
> harness from the existing branding test file.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/__tests__/brandingCanvasIntro.test.tsx`
Expected: FAIL (no field).

- [ ] **Step 3: Implement**

In `BrandingView.tsx`, alongside the other brand fields, add a controlled textarea bound to the local brand state's `canvas_intro`:

```tsx
        <label className="block">
          <span className="text-sm text-textMuted">Canvas intro (shown after the customer's name)</span>
          <textarea
            aria-label="Canvas intro"
            maxLength={600}
            value={brand.canvas_intro ?? ''}
            onChange={e => setBrand({ ...brand, canvas_intro: e.target.value })}
            className="mt-1 w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm"
            rows={4}
          />
        </label>
```

Ensure the PATCH payload already sends the full `brand` object (it does — the
server read-merges), so `canvas_intro` is persisted without further change.

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npx vitest run src/__tests__/brandingCanvasIntro.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/admin/views/BrandingView.tsx frontend/src/__tests__/brandingCanvasIntro.test.tsx
git commit -m "feat(admin): canvas intro field in Branding view"
```

---

### Task 15: End-to-end verification (flag on) + regression (flag off)

**Files:**
- Test: `backend/tests/test_v2_e2e.py` (create) — full front-half walk.

**Interfaces:**
- Consumes: `orchestrator_v2.handle_message`, a real canvas session.

- [ ] **Step 1: Write the end-to-end test**

```python
# backend/tests/test_v2_e2e.py
import pytest
from app.services.conversation import orchestrator_v2 as o2
from app.services.conversation.state_machine import ConversationState as S


@pytest.mark.asyncio
async def test_full_front_half_walk(canvas_session_v2):
    sid = canvas_session_v2
    turns = [
        ("", S.ASK_NAME),
        ("Sam", S.SHOW_INTRO),
        ("continue", S.ASK_LOGO_PLACEMENT),
        ("Front", S.LOGO_ADJUST),
        ("done", S.ASK_ANOTHER_LOGO),
        ("no", S.ASK_ADD_DECOR),
        ("Add text", S.DECOR_ADJUST),
        ("done", S.ASK_ANYTHING_ELSE),
        ("no", S.ASK_QUANTITY),
        ("50-99", S.ASK_EMAIL),
        ("sam@example.com", S.ASK_PURPOSE),
        ("Staff caps", S.FINALIZE_CANVAS),
    ]
    for msg, expected in turns:
        res = await o2.handle_message(sid, msg)
        assert res["state"] == expected.value, (msg, res["state"])
    # The finalize state tells the frontend to flatten + finalize.
    assert res["data"]["trigger_finalize"] is True
```

> The email turn assumes `capture_lead_and_verify` marks `email_captured` in the
> test environment (existing lead tests rely on the same). If the test harness
> stubs email delivery, follow the same stubbing the existing
> `test_leads*`/`test_orchestrator*` tests use.

- [ ] **Step 2: Run to verify it passes**

Run: `cd backend && pytest tests/test_v2_e2e.py -q`
Expected: PASS.

- [ ] **Step 3: Flag-off regression — v1 canvas unchanged**

Run: `cd backend && pytest tests/ -q`
Expected: PASS (full suite; v1 canvas/orchestrator tests untouched).

- [ ] **Step 4: Full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: PASS (barring the 2 known pre-existing `adminQuotes` failures).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/test_v2_e2e.py
git commit -m "test(v2): end-to-end front-half walk + flag-off regression"
```

---

## Self-Review

**Spec coverage:**
- Env-flag selection, canvas-only scope → Tasks 1, 5. ✅
- New state sequence (name → intro → ≤4 logo loop → text/shape loop → quantity/email/purpose) → Tasks 2, 4, 15. ✅
- Directive-driven canvas control + highlight → Tasks 3, 10, 11, 13. ✅
- Per-element + per-tool locking → Tasks 8, 9, 10, 13. ✅
- Admin-set intro → Task 7 (backend), Task 14 (admin UI). ✅
- Reuse existing tail (generate→verify→deliver→refine) → Tasks 4, 6 (finalize→GENERATING) + existing poll routes (unchanged). ✅
- Integration point: finalize must not double-capture the lead → finalize's v2 branch does no lead capture (email already captured at ASK_EMAIL); noted in Task 6. ✅
- Integration point: directive-absent = v1 behaviour → Task 13 (`isV2` fallback), Task 10 (`allowedTools === undefined` → legacy). ✅
- Testing (backend routing/e2e + flag-off regression; frontend gating/lock/directive) → Tasks 2,4,5,6,15 + 8,9,10,11,13,14. ✅

**Placeholder scan:** No TBD/TODO; each code step shows real code. The two "match the existing fixture/test harness" notes (conftest fixtures, BrandingView mount) point to concrete existing patterns rather than leaving code blank — acceptable because the exact harness lives in files the implementer will open.

**Type consistency:** `canvas_directive` keys (`allowed_tools/target_face/auto_open/instructions/show_done`) match `chatStore.parseData` mapping (`allowedTools/targetFace/autoOpen/instructions/showDone`) and the `ToolRail`/`Surface` props. `advance_state_v2`/`progress_v2`/`v2_public_data`/`v2_reply`/`canvas_directive` names are consistent across Tasks 2–6 and 15. `lockAll`/`unlockAll` consistent (Tasks 8, 13). `handle_message_v2` alias consistent (Task 5). Enum member string values are lowercase-snake and match the frontend state literals used in tests.

**Known follow-ups (out of scope, noted for the team):**
- The v2 `LOGO_ADJUST`/`DECOR_ADJUST` "Done" relies on a `"done"` sentinel message; a stray "done" mid-answer would advance. Acceptable for v1 of this flow (chip-driven).
- `remove_bg` is applied via the existing canvas toggle, not captured in chat — the chat only *asks*; matches the spec's "ask whether the background needs removing".
