# Canvas Studio UX Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Six UX fixes to the v2 canvas studio — show which panel the customer should work in, categorise the element Adjust panel with a D-pad and a finer rotate step, centre the hat name in the header, shorten the chat copy and split the email-verified turn in two, render chat replies as paragraphs, and make the purpose step impossible to fail.

**Architecture:** Backend changes are all inside the v2 canvas registry/orchestrator (`app/services/conversation/`) and `app/prompts.py` — every one is gated behind `flow_mode == "canvas"` + `CANVAS_ORCHESTRATOR_V2`, so v1 is untouched. Frontend changes are additive: one new hook (`useActiveSurface`), one new store flag (`chatStore.finalizeFailed`), one new response field (`data.extra_replies`), plus a restructure of `SelectedToolbar` and `StoreHeader`.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React 18 / TypeScript / Zustand / Tailwind / Vitest + Testing Library (frontend).

## Global Constraints

- **Chip labels are matched by exact literal** (`state_machine_v2.resolve_chip`). Do NOT change any chip label in this batch — `test_v2_e2e.py` types them verbatim.
- **Formal register.** No casual phrasing. `test_v2_copy_guards._CASUAL` pins: `"pop your"`, `"pop it"`, `"grab your"`, `"love where"`, `"no worries"`, `"are you after"`, `"tap"` (word-boundary-anchored on the left, so `"tapping"` also fails).
- **Background-removal copy must never promise processing or a wait.** Ticking sets a flag; nothing is matted client-side and the cap on screen does not change. Say **marked**, never **removed**.
- **No PII in logs.** The customer's email/name must never reach a log line or an exception string.
- **Backend tests:** `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q` for the main suite. The five v2-only suites (`test_orchestrator_v2`, `test_v2_e2e`, `test_v2_copy_guards`, `test_state_machine_v2`, `test_canvas_steps`) run with `CANVAS_ORCHESTRATOR_V2=true`.
- **Frontend tests:** `docker compose exec -T frontend npx vitest run <path>`. Host-side `npx vitest` is broken on this Windows machine (missing `@vitest/utils`). If Docker is down, `cd frontend && npx vitest run <path>` may work for some files — if it fails with a missing-module error, that is the known gotcha, not your change.
- **Baseline before this branch:** backend 1196 passing; `frontend/src/__tests__` 273 passing / 2 failing (the 2 are pre-existing `adminQuotes` Router-context failures). Do not "fix" those two.

## File Structure

**Backend**
- `app/services/conversation/canvas_steps.py` — add `Step.accept_verbatim`; set it on `ASK_PURPOSE`; rewrite registry `ask` copy. (Tasks 1, 4)
- `app/services/conversation/intent_extractor.py` — widen `_SLOT_DOCS["purpose"]`. (Task 1)
- `app/services/conversation/orchestrator_v2.py` — verbatim fallback; paragraph joins; `extra_replies`. (Tasks 1, 2, 3)
- `app/services/conversation/state_machine_v2.py` — paragraph joins in `reply_for`. (Task 2)
- `app/prompts.py` — rewrite the `V2_*` copy constants. (Task 4)
- `tests/test_orchestrator_v2.py`, `tests/test_canvas_steps.py`, `tests/test_v2_copy_guards.py` — new/updated tests.

**Frontend**
- `src/store/chatStore.ts` — `extraReplies` parsing + append; `finalizeFailed` flag. (Task 5)
- `src/lib/useActiveSurface.ts` — **new**. Which panel owns the current turn. (Task 6)
- `src/components/CustomiseStudio/index.tsx` — focus ring / dim / pill. (Task 7)
- `src/components/DesignStudio/Surface.tsx` — read `finalizeFailed` from the store instead of local state. (Tasks 5, 7)
- `src/components/StoreHeader.tsx` — three-zone header. (Task 8)
- `src/components/DesignStudio/SelectedToolbar.tsx` — five sections, D-pad, 12.5°. (Task 9)
- `src/__tests__/` — `chatStoreExtraReplies.test.ts`, `useActiveSurface.test.tsx`, `customiseStudioFocus.test.tsx` (new); `CustomiseStudio.test.tsx`, `StoreHeader.test.tsx`, `selectedToolbarTransform.test.tsx`, `selectedToolbarPlacement.test.tsx` (updated).

---

## Task 1: Purpose step accepts anything

**Files:**
- Modify: `backend/app/services/conversation/canvas_steps.py` (the `Step` dataclass, ~line 91; the `ASK_PURPOSE` record, ~line 771)
- Modify: `backend/app/services/conversation/intent_extractor.py:642`
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (~line 170, after the field-resolution branches)
- Test: `backend/tests/test_orchestrator_v2.py`, `backend/tests/test_canvas_steps.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `canvas_steps.Step.accept_verbatim: bool` (default `False`). No other task reads it.

**Background.** `ASK_PURPOSE` has `slots=("purpose",)` and `done_when=lambda c: bool(c.get("purpose"))`, and it ships **no chips**. Free text goes to `intent_extractor.interpret_turn_v2`, whose prompt says *"fill ONLY what the customer clearly says — never guess"*. A misspelled answer or a refusal ("rather not say") comes back with no `purpose` field, `done_when` stays False, and the step re-asks forever with no button to escape via.

- [ ] **Step 1: Write the failing tests**

Add to the end of `backend/tests/test_orchestrator_v2.py`:

```python
# --- ASK_PURPOSE accepts anything (2026-08-01) --------------------------------

def _at_purpose_store():
    """A session parked at ASK_PURPOSE, built by walking the registry."""
    from tests.canvas_step_helpers import seed_for
    collected = seed_for(cs.by_id(S.ASK_PURPOSE))
    collected["flow_mode"] = "canvas"
    return {"session": {"id": "s1", "state": S.ASK_PURPOSE.value,
                        "collected": collected, "upsell_count": 0}}


@pytest.mark.asyncio
async def test_purpose_banks_a_refusal_verbatim_when_the_interpreter_reads_nothing(monkeypatch):
    """A refusal is a valid answer. The interpreter declines to fill `purpose`
    for "rather not say", which left done_when unmet and re-asked forever — and
    ASK_PURPOSE ships no chips, so there was no way out."""
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {})            # interpreter reads nothing
    res = await o2.handle_message("s1", "rather not say")
    assert store["session"]["collected"]["purpose"] == "rather not say"
    assert res["state"] != S.ASK_PURPOSE.value


@pytest.mark.asyncio
async def test_purpose_banks_a_misspelled_answer_verbatim(monkeypatch):
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {})
    await o2.handle_message("s1", "stff uniforsm for the shp")
    assert store["session"]["collected"]["purpose"] == "stff uniforsm for the shp"


@pytest.mark.asyncio
async def test_a_parsed_purpose_still_wins_over_the_verbatim_fallback(monkeypatch):
    """The fallback fires ONLY when the interpreter read nothing into the slot."""
    store = _at_purpose_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _llm_returns(monkeypatch, {"purpose": "staff uniforms"})
    await o2.handle_message("s1", "umm stff uniforsm i guess")
    assert store["session"]["collected"]["purpose"] == "staff uniforms"
```

Add to the end of `backend/tests/test_canvas_steps.py`:

```python
def test_accept_verbatim_is_set_on_ask_purpose_only():
    """Banking a raw message verbatim is correct exactly where the answer IS
    the message. Globally it would write "umm the back one I think" into
    logo_face (an enum) or quantity (an int) and corrupt the design."""
    verbatim = {s.id for s in cs.REGISTRY if s.accept_verbatim}
    assert verbatim == {S.ASK_PURPOSE}
```

- [ ] **Step 2: Run them to verify they fail**

Run:
```
cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_orchestrator_v2.py -k purpose tests/test_canvas_steps.py -k accept_verbatim
```
Expected: FAIL — `AttributeError: 'Step' object has no attribute 'accept_verbatim'` for the registry test, and the orchestrator tests fail with `purpose` absent / state unchanged.

- [ ] **Step 3: Add the `accept_verbatim` field**

In `canvas_steps.py`, in the `Step` dataclass immediately after the `back_clears` field:

```python
    # When the interpreter returns NO value for this step's own slot, bank the
    # raw customer message into it. Set on ASK_PURPOSE only.
    #
    # Per-step, not global, and deliberately so: banking a raw message verbatim
    # is correct exactly where the answer IS the message. Applied globally it
    # would write "umm the back one I think" into logo_face (an enum) or
    # quantity (an int) and corrupt the design. Distinct from `direct_answer`,
    # which fires only during an LLM OUTAGE — this is the healthy-path
    # equivalent, for a step where a re-ask is worse than an imperfect answer.
    accept_verbatim: bool = False
```

- [ ] **Step 4: Set it on `ASK_PURPOSE`**

Replace the `ASK_PURPOSE` record:

```python
    Step(
        id=S.ASK_PURPOSE,
        ask="Finally, what are the caps for?",
        slots=("purpose",),
        direct_answer=_direct_purpose,
        # This step ships NO chips, so an unanswerable turn has no escape hatch:
        # a refusal ("rather not say") or a misspelling the interpreter declines
        # to read leaves done_when unmet and re-asks forever. accept_verbatim
        # makes that impossible — whatever they typed becomes the answer.
        accept_verbatim=True,
        done_when=lambda c: bool(c.get("purpose")),
    ),
```

- [ ] **Step 5: Widen the slot doc**

In `intent_extractor.py`, replace the `"purpose"` entry of `_SLOT_DOCS`:

```python
    "purpose": (
        "purpose (string) — what the caps are for. Accept ANY answer, including "
        "a refusal ('rather not say', 'no', 'prefer not to'), and accept "
        "misspellings; record what they said, as they wrote it"
    ),
```

- [ ] **Step 6: Wire the fallback into the orchestrator**

In `orchestrator_v2.handle_message`, insert immediately after the
`elif fields is None: fields = {}` line and **before** `collected.pop("_fail_count", None)`:

```python
    if step.accept_verbatim and not any(fields.get(s) for s in step.slots):
        # The interpreter read nothing into this step's own slot — a misspelled
        # answer, or a refusal it declined to treat as an answer. For this step
        # the message IS the answer, so bank it rather than re-ask a question
        # the customer just answered. Still validated (so it can only land in a
        # declared slot) and still guarded by the step's own apply.
        fields = {**fields,
                  **ie.validate_fields({step.slots[0]: message.strip()})}
```

- [ ] **Step 7: Run the tests to verify they pass**

Run:
```
cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_canvas_steps.py tests/test_state_machine_v2.py \
  tests/test_v2_e2e.py tests/test_v2_copy_guards.py
```
Expected: PASS, no regressions.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/conversation/canvas_steps.py \
        backend/app/services/conversation/intent_extractor.py \
        backend/app/services/conversation/orchestrator_v2.py \
        backend/tests/test_orchestrator_v2.py backend/tests/test_canvas_steps.py
git commit -m "fix(v2): the purpose step accepts a refusal or a misspelled answer"
```

---

## Task 2: Chat replies render as paragraphs

**Files:**
- Modify: `backend/app/services/conversation/state_machine_v2.py:320-342` (`reply_for`)
- Modify: `backend/app/services/conversation/orchestrator_v2.py:131`, `:220-230`
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: nothing.
- Produces: every v2 reply joins its parts with `"\n\n"` instead of `" "`. Task 4's copy rewrite assumes this.

**Background.** The chat bubble already has `whitespace-pre-wrap` (`ChatColumn.tsx:459`), so the fix belongs at the source. Today `reply_for` joins the LLM ack, the question and the tool tip with single spaces, producing one run-on paragraph that is hard to read on a phone.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_orchestrator_v2.py`:

```python
# --- paragraph layout (2026-08-01) -------------------------------------------

def test_reply_for_separates_the_question_from_its_tool_tip_with_a_blank_line():
    """One run-on paragraph is what made these replies hard to read. The bubble
    is whitespace-pre-wrap, so the separation has to come from the copy."""
    from app.services.conversation import state_machine_v2 as v2
    step = cs.by_id(S.ASK_LOGO_PLACEMENT)          # has a tip
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i")
    assert step.tip in body
    assert "\n\n" + step.tip in body


def test_reply_for_separates_the_ack_from_the_question_with_a_blank_line():
    from app.services.conversation import state_machine_v2 as v2
    step = cs.by_id(S.ASK_QUANTITY)
    body = v2.reply_for(step, {}, persona="Ricardo", intro="i", ack="Understood.")
    assert body.startswith("Understood.\n\n")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q tests/test_orchestrator_v2.py -k "blank_line"`
Expected: FAIL — the parts are joined with a single space.

- [ ] **Step 3: Change the joins in `reply_for`**

In `state_machine_v2.py`, replace the body of `reply_for` (keeping the docstring, extended):

```python
def reply_for(step: Step, collected: dict, *, persona: str, intro: str,
              ack: str = "", colour_note: str = "") -> str:
    """ack (LLM, best-effort) + the step's copy + its tool tip (verbatim).

    The tip is concatenated from the registry and never passes through a model,
    so a warm paraphrase cannot drop "select the highlighted button" and leave
    the customer stuck. Without an ack the reply is simply the scripted copy.

    Parts are joined with a BLANK LINE, not a space. The chat bubble is
    `whitespace-pre-wrap`, so this is what makes an instruction render as its
    own paragraph under the question instead of running into it.
    """
    if step.id is S.DECOR_ADJUST:
        # The tip is resolved at runtime (text vs shape), so it is PREPENDED to
        # this step's copy rather than appended like every other step. `step.ask`
        # is used rather than a re-typed literal so the two cannot drift.
        body = f"{prompts.V2_TOOL_TIPS[_decor_tool(collected)]}\n\n{step.ask}"
    else:
        asked = step.ask_retry and step.id.value in (collected.get("_asked") or [])
        body = (step.ask_retry if asked else step.ask).format(
            name=collected.get("name") or "there",
            persona=persona,
            intro=intro,
            colour_note=colour_note,
        )
        if step.tip and step.id is not S.LOGO_ADJUST:
            body = f"{body}\n\n{step.tip}"
    return f"{ack}\n\n{body}".strip() if ack else body
```

- [ ] **Step 4: Change the three prepends in `orchestrator_v2`**

In `handle_message`, the abuse decline (~line 131):

```python
        reply = f"{prompts.V2_ABUSE_DECLINE}\n\n" + v2.reply_for(
            step, collected, persona=persona, intro=intro, colour_note=colour_note)
```

The background-already-marked prepend (~line 223):

```python
        reply = f"{prompts.V2_BG_ALREADY_REMOVED}\n\n{reply}".strip()
```

The verification notice (~line 230):

```python
        reply = f"{prompts.V2_EMAIL_VERIFY_NOTICE.format(email=addr)}\n\n{reply}".strip()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```
cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_state_machine_v2.py
```
Expected: PASS. If a pre-existing test asserted an exact single-space-joined string, update that assertion to the blank-line form — the copy is unchanged, only the separator.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/conversation/state_machine_v2.py \
        backend/app/services/conversation/orchestrator_v2.py \
        backend/tests/test_orchestrator_v2.py
git commit -m "fix(v2): join reply parts with a blank line so instructions read as paragraphs"
```

---

## Task 3: Split the email-verified turn into two messages

**Files:**
- Modify: `backend/app/services/conversation/orchestrator_v2.py` (`_persist`, `check_verification`)
- Test: `backend/tests/test_orchestrator_v2.py`

**Interfaces:**
- Consumes: Task 2's blank-line joins (so the second bubble is already well laid out).
- Produces: the chat response may carry `data["extra_replies"]: list[str]` — additional assistant messages to append **after** `reply`, in order. Task 5 consumes this.

**Background.** `check_verification` currently builds one string: `V2_EMAIL_VERIFIED_ACK` + the whole next-step copy. Two unrelated things (a confirmation and a new question) arrive as one bubble.

- [ ] **Step 1: Make the fake table record inserted rows**

`_FakeTable.insert` in `backend/tests/test_orchestrator_v2.py` currently discards its rows. Replace it:

```python
    def insert(self, rows):
        self.store.setdefault("rows", []).extend(rows)
        return self
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_orchestrator_v2.py`:

```python
# --- the verified turn is two messages (2026-08-01) ---------------------------

@pytest.mark.asyncio
async def test_verification_ack_and_the_next_question_are_two_separate_messages(monkeypatch):
    """A confirmation and a new question are two unrelated things. Merged into
    one bubble the customer reads past the confirmation into the question."""
    store = _at_email_store()
    store["session"]["state"] = S.AWAIT_EMAIL_VERIFY.value
    store["session"]["collected"]["email_captured"] = True
    store["session"]["collected"]["email_verified"] = True
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))

    res = await o2.check_verification("s1")

    assert res["reply"] == prompts.V2_EMAIL_VERIFIED_ACK
    extras = res["data"]["extra_replies"]
    assert len(extras) == 1
    assert prompts.V2_EMAIL_VERIFIED_ACK not in extras[0]     # not duplicated

    # Both are persisted, in order, as assistant rows — and no phantom user row.
    assistant = [r for r in store["rows"] if r["role"] == "assistant"]
    assert [r["content"] for r in assistant] == [res["reply"], extras[0]]
    assert not [r for r in store["rows"] if r["role"] == "user"]


@pytest.mark.asyncio
async def test_an_ordinary_turn_carries_no_extra_replies(monkeypatch):
    """`extra_replies` is absent on every other path, so nothing else changes."""
    store = _new_store()
    monkeypatch.setattr(o2, "get_supabase", lambda: _FakeSB(store))
    _no_llm(monkeypatch)
    res = await o2.handle_message("s1", "")
    assert "extra_replies" not in res["data"]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q tests/test_orchestrator_v2.py -k "extra_replies or two_separate_messages"`
Expected: FAIL — `KeyError: 'extra_replies'`.

- [ ] **Step 4: Add `extra_replies` to `_persist`**

Replace `_persist`'s signature and body in `orchestrator_v2.py`:

```python
async def _persist(sb, session_id, collected, step, reply, state_before, new_state,
                   *, user_message: str | None = "", data: dict | None = None,
                   config: dict | None = None,
                   extra_replies: list[str] | None = None) -> dict:
    """Write the state + the chat rows, and shape the response.

    `step` is the step the session now RESTS on (None only for the capped
    QUOTE_REQUESTED handoff, which supplies its own `data`). `config` is the
    store's canvas_flow — only consulted for the `_public` fallback below (an
    explicit `data=` always wins), so `can_go_back` in that fallback is scoped
    to the same config-composed registry as the turn that produced it.

    `user_message=None` writes the assistant row ONLY, for a turn the customer
    didn't take (check_verification, which advances off an out-of-band email
    click). `""` is different and still writes an empty user row — that's the
    GREETING kickoff's existing shape.

    `extra_replies` are FURTHER assistant messages, shown after `reply`. Each
    becomes its own persisted row and its own chat bubble, so two unrelated
    things (a confirmation and the next question) don't arrive merged. They are
    surfaced on `data`, not as a new top-level response key, so the response
    shape stays `{reply, state, data}` for every existing caller.
    """
    sb.table("design_sessions").update(
        {"state": new_state.value, "collected": collected,
         "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", session_id).execute()
    rows = [] if user_message is None else [
        {"session_id": session_id, "role": "user", "content": user_message,
         "state_before": state_before, "state_after": state_before},
    ]
    for content in [reply, *(extra_replies or [])]:
        rows.append(
            {"session_id": session_id, "role": "assistant", "content": content,
             "state_before": state_before, "state_after": new_state.value})
    sb.table("chat_messages").insert(rows).execute()
    if data is None:
        data = _public(step, collected, config) if step else {}
    if extra_replies:
        data["extra_replies"] = list(extra_replies)
    return {"reply": reply, "state": new_state.value, "data": data}
```

- [ ] **Step 5: Split the reply in `check_verification`**

In `check_verification`, replace the `reply = v2.reply_for(...)` call and the
`return await _persist(...)` that follows it:

```python
    # Two messages, not one: the confirmation is its own bubble so it can't be
    # read past on the way to the question. `ack=` is deliberately NOT passed —
    # that is what would merge them back together.
    next_question = v2.reply_for(next_, collected, persona=persona,
                                 intro=canvas_intro_text(store),
                                 colour_note=colour_disclaimer_text(
                                     store, collected.get("name") or "there"))
    return await _persist(sb, session_id, collected, next_,
                          prompts.V2_EMAIL_VERIFIED_ACK, current.value,
                          next_.id, user_message=None, config=flow_config,
                          extra_replies=[next_question])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q tests/test_orchestrator_v2.py`
Expected: PASS. The pre-existing
`test_verification_poll_advances_the_flow_once_the_link_is_opened` asserts
`prompts.V2_EMAIL_VERIFIED_ACK in res["reply"]`, which still holds (`reply` is
now exactly that string).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/conversation/orchestrator_v2.py \
        backend/tests/test_orchestrator_v2.py
git commit -m "feat(v2): send the email-verified ack as its own message"
```

---

## Task 4: Shorter copy, and no hard-coded Adjust-panel position

**Files:**
- Modify: `backend/app/prompts.py:1102-1245` (the `V2_*` block)
- Modify: `backend/app/services/conversation/canvas_steps.py` (registry `ask` strings)
- Modify: `backend/tests/test_v2_copy_guards.py`

**Interfaces:**
- Consumes: Task 2's blank-line joins.
- Produces: no code interface. Chip labels are unchanged.

**Background.** Long sentences are hard to read in a narrow chat column. Separately, the Adjust panel moved into the tool rail on desktop (`useIsDesktop`), so copy saying "the Adjust panel **above the cap**" is wrong for the majority case — but "below the cap" would be wrong on mobile. The position is responsive; the copy must stop naming one.

- [ ] **Step 1: Rewrite the copy-guard tests first**

Replace the two position tests in `backend/tests/test_v2_copy_guards.py`:

```python
def test_no_v2_copy_hard_codes_the_adjust_panels_position():
    """The panel's position is RESPONSIVE — the tool rail on desktop, above the
    cap on mobile (see frontend useIsDesktop). Any hard-coded position is wrong
    in one of the two layouts, so the copy must name the panel and stop there.
    Supersedes the old "under the cap" check, which only caught one of three."""
    for s in _v2_copy_strings():
        low = s.lower()
        for stale in ("above the cap", "below the cap", "under the cap"):
            assert stale not in low, f"hard-coded panel position {stale!r} in: {s!r}"


def test_the_adjust_panel_is_named_where_the_customer_needs_it():
    """The tool tips are the only place a customer is told how to restyle what
    they placed, and they are concatenated verbatim (never through a model), so
    naming the panel there is what makes it discoverable."""
    for key in ("text", "shape"):
        assert "Adjust panel" in prompts.V2_TOOL_TIPS[key]
    assert "Adjust panel" in prompts.V2_BG_INSTRUCTIONS
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q tests/test_v2_copy_guards.py`
Expected: FAIL — `hard-coded panel position 'above the cap'` in several strings.

- [ ] **Step 3: Rewrite the `prompts.py` constants**

Replace each of these in `backend/app/prompts.py` (leave every surrounding
comment block in place — they document constraints, not copy):

```python
V2_TOOL_TIPS = {
    "upload": (
        'Select the highlighted "Upload image" button to add your logo.\n\n'
        "Drag to move it. Pull a corner to resize. Use the top handle to "
        "rotate.\n\n"
        "Select the logo to open the Adjust panel."
    ),
    "text": (
        'Select the highlighted "Add text" button, then type your wording.\n\n'
        "Drag to position it. Select it to open the Adjust panel, where you "
        "can change the font, size and colour."
    ),
    "shape": (
        'Select the highlighted "Graphics" button to add a shape.\n\n'
        "Drag to position and resize it. Select it to open the Adjust panel "
        "to recolour it."
    ),
}

V2_BG_INSTRUCTIONS = (
    "If it does, I'll mark it now. We'll knock the background out when we "
    "render your design, so the cap on screen won't change.\n\n"
    'You can also tick or untick "Remove background" yourself in the Adjust '
    "panel."
)

V2_BG_ALREADY_REMOVED = (
    "I can see you've already marked that logo's background for removal. "
    "I'll skip that question."
)

V2_REWORK_INSTRUCTIONS = (
    "Every tool is open again. Move, resize, add or remove anything you "
    "need.\n\nSelect Done when you're happy with it."
)

V2_ASK_NAME = (
    "Welcome. I'm {persona}, your design assistant.\n\nMay I have your name?"
)

V2_ASK_NAME_RETRY = (
    "Apologies, I didn't catch that. What name should I put on the brief?"
)

V2_ASK_EMAIL_RETRY = (
    "That email address doesn't look quite right. Please check it and enter "
    "it again."
)

V2_DEFAULT_INTRO = (
    "Let's begin. We'll start with your logo, then add any text or graphics. "
    "I'll guide you through each tool."
)

V2_EMAIL_VERIFY_NOTICE = (
    "Thank you. I've sent a verification link to {email}.\n\n"
    "Please open it to confirm your address."
)

V2_AWAIT_VERIFY = (
    "I'll wait here until that's confirmed. The moment you open the link, "
    "we'll carry on."
)

V2_AWAIT_VERIFY_RETRY = (
    "I do need your address confirmed before we continue.\n\n"
    "Please open the verification link I've sent you. If it hasn't arrived, "
    "please check your spam folder."
)

V2_COLOUR_DISCLAIMER = (
    "One note before we send this over, {name}. Screen colours aren't always "
    "exact.\n\n"
    "What you see is a guide. Our team matches your design to the closest "
    "embroidery and print colours.\n\n"
    "Reference charts — embroidery: {embroidery_url} · print: {print_url}\n\n"
    "Have a specific print colour (CMYK or Pantone) or an embroidery thread "
    "number? Enter it below and we'll use it.\n\n"
    "Any final notes for the team? Type them here, or select "
    '"Nothing to add".'
)
```

Also tighten the ack instruction so the LLM half stays short. In
`V2_ACK_PROMPT`, replace the second line:

```
Write ONE short, courteous sentence of at most 12 words acknowledging what the customer just told you. Then stop.
```

- [ ] **Step 4: Rewrite the registry `ask` strings**

In `canvas_steps.py`, replace only the `ask` / `ask_retry` values below. **Do
not touch any `Chip(...)` label, any `done_when`, or any other field.**

```python
# ASK_HAS_LOGO
        ask="Thank you, {name}. Do you have a logo or image for the cap?",

# ASK_LOGO_PLACEMENT
        ask="Which part of the cap should it go on?",
        ask_retry="Where should this one go?",

# LOGO_ADJUST
        ask=("I've opened the image picker for you.\n\n"
             "Drag your logo to move it, pull a corner to resize, or rotate "
             "it.\n\n"
             "Select it to open the Adjust panel — the background-removal "
             "toggle is there too.\n\n"
             "Select Done when the placement looks right."),

# ASK_EMAIL
        ask=("Thank you, {name}. Please enter your email address.\n\n"
             "I'll save your design, send you a reference code, and email "
             "your artwork and quote."),

# ASK_ADD_DECOR
        ask="Would you like to add text or a shape?",

# ASK_DECOR_PLACEMENT
        ask="Which part of the cap should it go on?",

# ASK_ANYTHING_ELSE
        ask="Is that everything?",

# ASK_DECORATION
        ask=("How would you like this decorated?\n\n"
             "Choose the method that suits — our team will confirm what works "
             "best for your artwork.\n\n"
             f"Select '{MIX_CHIP_LABEL}' if you need more than one method. "
             "Mixing costs more per hat."),

# ASK_DECORATION_MIX
        ask=("Certainly. Please tell me which methods you'd like and where "
             "each one goes.\n\n"
             "I'll pass that straight to the team. Mixing does add to the "
             "cost per hat."),

# REVIEW_DESIGN
        ask=("Before I send this to our team, {name}, please review your "
             "design across all the views.\n\n"
             "Are you happy with it, or would you like to rework anything?"),

# REWORK_CANVAS
        ask=("Please adjust anything you'd like on the canvas.\n\n"
             "Select Done and I'll bring you back to the review."),

# REQUEST_QUOTE
        ask=("Your design is ready, {name}.\n\n"
             "Select \"Request a quote\" below. Our team will review it and "
             "email you your finished design with your quote."),
```

`ASK_PURPOSE`'s `ask` was already shortened in Task 1. `SHOW_INTRO`,
`ASK_LOGO_BG`, `ASK_ANOTHER_LOGO`, `ASK_QUANTITY`, `DECOR_ADJUST`, `NEEDED_BY`,
`ASK_FINAL_NOTES` and `FINALIZE_CANVAS` are already one short sentence — leave
them.

- [ ] **Step 5: Run the guards and the whole v2 suite**

Run:
```
cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_v2_copy_guards.py tests/test_v2_e2e.py tests/test_orchestrator_v2.py \
  tests/test_canvas_steps.py tests/test_state_machine_v2.py
```
Expected: PASS. `test_v2_e2e.py` types chip labels verbatim, so a green walk is
the proof the rewrite did not break routing.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (baseline 1196 + the tests added in Tasks 1–3).

- [ ] **Step 7: Commit**

```bash
git add backend/app/prompts.py backend/app/services/conversation/canvas_steps.py \
        backend/tests/test_v2_copy_guards.py
git commit -m "copy(v2): shorter chat sentences; stop hard-coding the Adjust panel's position"
```

---

## Task 5: `chatStore` — extra replies and a shared `finalizeFailed`

**Files:**
- Modify: `frontend/src/store/chatStore.ts`
- Modify: `frontend/src/components/DesignStudio/Surface.tsx:48`, `:221`, `:284`
- Test: `frontend/src/__tests__/chatStoreExtraReplies.test.ts` (create)

**Interfaces:**
- Consumes: `data.extra_replies: string[]` from Task 3.
- Produces:
  - `useChatStore.getState().finalizeFailed: boolean` — true while a rejected canvas finalize has re-opened the canvas.
  - `useChatStore.setState({ finalizeFailed })` is how `Surface` sets it.
  - `applyResponse` / `pollVerification` append `reply` then each `extra_replies` entry, in order.

**Background.** `Surface.tsx` keeps `finalizeFailed` in local `useState`. A finalize that 422s (e.g. the cap-text profanity gate) re-opens the canvas so the customer can act on the error, even though `FINALIZE_CANVAS`'s directive says `allowed_tools: []`. Task 6's hook reads `chatStore`, so it would report "chat" while the canvas is genuinely live — the one moment a wrong cue does real damage. Lifting the flag is what keeps the two honest.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/chatStoreExtraReplies.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({
  sendChat: vi.fn(),
  sendBack: vi.fn(),
  pollVerification: vi.fn(),
  pollRegeneration: vi.fn(),
  pollGenerationAdvance: vi.fn(),
}))

import { pollVerification as pollVerificationApi } from '../lib/api'
import { useChatStore } from '../store/chatStore'

beforeEach(() => {
  useChatStore.getState().reset()
  vi.clearAllMocks()
})

describe('extra_replies', () => {
  it('applyResponse appends the main reply then each extra, in order', () => {
    useChatStore.getState().applyResponse('Your email is confirmed.', 'ask_another_logo', {
      extra_replies: ['Would you like to add another logo?'],
    })
    expect(useChatStore.getState().messages.map(m => m.text)).toEqual([
      'Your email is confirmed.',
      'Would you like to add another logo?',
    ])
  })

  it('applyResponse appends only the reply when there are no extras', () => {
    useChatStore.getState().applyResponse('Just the one.', 'ask_quantity', {})
    expect(useChatStore.getState().messages).toHaveLength(1)
  })

  it('pollVerification appends the ack and the next question as two messages', async () => {
    vi.mocked(pollVerificationApi).mockResolvedValue({
      reply: 'Thank you — your email address is confirmed.',
      state: 'ask_another_logo',
      data: { extra_replies: ['Would you like to add another logo?'] },
    } as never)
    await useChatStore.getState().pollVerification('s1')
    expect(useChatStore.getState().messages.map(m => m.text)).toEqual([
      'Thank you — your email address is confirmed.',
      'Would you like to add another logo?',
    ])
  })
})

describe('finalizeFailed', () => {
  it('defaults to false and is cleared by reset()', () => {
    expect(useChatStore.getState().finalizeFailed).toBe(false)
    useChatStore.setState({ finalizeFailed: true })
    useChatStore.getState().reset()
    expect(useChatStore.getState().finalizeFailed).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/chatStoreExtraReplies.test.ts`
Expected: FAIL — only one message appended; `finalizeFailed` is `undefined`.

- [ ] **Step 3: Add `extraReplies` parsing and the `finalizeFailed` flag**

In `frontend/src/store/chatStore.ts`:

Add to the `ChatStoreState` interface, after `backRemovesElement`:

```ts
  /** v2 canvas: a finalize was REJECTED (e.g. the cap-text profanity gate), so
   *  the canvas is re-opened for the customer to act on the error even though
   *  FINALIZE_CANVAS's directive hands over no tool. Lives here rather than in
   *  Surface's local state because useActiveSurface must see it — otherwise the
   *  focus cue says "chat" while the canvas is genuinely live. */
  finalizeFailed: boolean
```

Inside `parseData`, before the `return`:

```ts
  // Further assistant messages to append AFTER `reply`, each as its own bubble
  // (backend orchestrator_v2._persist). Absent on every ordinary turn.
  const extraReplies = Array.isArray(data.extra_replies)
    ? (data.extra_replies as string[]).filter(t => typeof t === 'string')
    : []
```

Add `extraReplies` to `parseData`'s returned object. Then add a helper just
below `uid()`:

```ts
/** The assistant bubbles one response produces: the main reply, then each
 *  extra, in order. Shared by every response handler so a split turn can never
 *  render in one place and not another. */
function assistantMessages(reply: string, extraReplies: string[]): ChatMessage[] {
  return [reply, ...extraReplies].map(text => ({ id: uid(), role: 'assistant' as const, text }))
}
```

`extraReplies` must NOT be persisted as store state — it is per-response. So in
every `set({...parsed})` call, strip it. The simplest safe edit: destructure it
out at each use site. In `applyResponse`:

```ts
  applyResponse: (reply, state, data) => {
    const { extraReplies, ...parsed } = parseData(data)
    set(s => ({
      messages: [...s.messages, ...assistantMessages(reply, extraReplies)],
      chatState: state,
      ...parsed,
      sending: false,
      chatError: null,
    }))
  },
```

In `pollVerification`:

```ts
      const { extraReplies, ...parsed } = parseData(res.data)
      set(state => ({
        messages: [
          ...state.messages,
          ...assistantMessages(res.reply as string, extraReplies),
        ],
        chatState: res.state,
        ...parsed,
      }))
```

`parseData` has exactly seven call sites (`chatStore.ts` lines 154, 209, 247,
264, 280, 298, 317). Every one of them must destructure `extraReplies` out, or
it lands in the store as an undeclared key:

| Line | Function | Treatment |
|---|---|---|
| 154 | `kickoff` | destructure + `assistantMessages(res.reply, extraReplies)` |
| 209 | `sendMessage` | destructure + `assistantMessages(res.reply, extraReplies)` |
| 247 | `hydrate` | destructure and **DISCARD** — see below |
| 264 | `applyResponse` | destructure + `assistantMessages` (shown above) |
| 280 | `pollVerification` | destructure + `assistantMessages` (shown above) |
| 298 | `advanceRegeneration` | destructure + `assistantMessages(res.reply, extraReplies)` |
| 317 | `advanceGeneration` | destructure + `assistantMessages(res.reply, extraReplies)` |

`hydrate` is the one exception and it matters: it rebuilds the whole thread from
persisted `chat_messages` history, and `_persist` already wrote each extra as
its own row. Appending them again there would duplicate every split message on
every resume. So:

```ts
    // Discarded, not appended: `messages` already contains the extra rows —
    // _persist persisted each one — so re-appending would duplicate them.
    const { extraReplies: _ignored, ...parsed } = parseData(data)
```

Finally add `finalizeFailed: false` to the initial state object AND to the
object `reset()` sets.

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/chatStoreExtraReplies.test.ts`
Expected: PASS.

- [ ] **Step 5: Move `finalizeFailed` out of `Surface`'s local state**

In `frontend/src/components/DesignStudio/Surface.tsx`:

Delete the local declaration on line 48
(`const [finalizeFailed, setFinalizeFailed] = useState(false)`) and read it
from the store instead, next to the other chat selectors near line 28:

```tsx
  // Lifted out of local state so useActiveSurface can see it: a rejected
  // finalize re-opens the canvas, and the focus cue must follow.
  const finalizeFailed = useChatStore(s => s.finalizeFailed)
```

In `doRender`, replace `setFinalizeFailed(false)` (line ~221) with:

```tsx
    useChatStore.setState({ finalizeFailed: false })
```

and `setFinalizeFailed(true)` in the catch (line ~284) with:

```tsx
      useChatStore.setState({ finalizeFailed: true })
```

- [ ] **Step 6: Run the Surface tests**

Run:
```
docker compose exec -T frontend npx vitest run \
  src/__tests__/surfaceDirective.test.tsx src/__tests__/surfaceRework.test.tsx \
  src/__tests__/chatStore.test.ts src/__tests__/chatStoreBack.test.ts \
  src/__tests__/chatStoreCanvasDirective.test.ts
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/store/chatStore.ts \
        frontend/src/components/DesignStudio/Surface.tsx \
        frontend/src/__tests__/chatStoreExtraReplies.test.ts
git commit -m "feat(chat): render extra_replies as separate bubbles; share finalizeFailed"
```

---

## Task 6: `useActiveSurface` hook

**Files:**
- Create: `frontend/src/lib/useActiveSurface.ts`
- Test: `frontend/src/__tests__/useActiveSurface.test.tsx` (create)

**Interfaces:**
- Consumes: `chatStore.canvasDirective`, `chatStore.chatState`, `chatStore.finalizeFailed` (Task 5).
- Produces:
  ```ts
  export type ActiveSurface = 'canvas' | 'chat'
  export function useActiveSurface(): ActiveSurface
  ```
  Task 7 consumes it.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/useActiveSurface.test.tsx`:

```tsx
import { beforeEach, describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useActiveSurface } from '../lib/useActiveSurface'
import { useChatStore } from '../store/chatStore'

const directive = (allowedTools: string[]) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone: false, unlockAll: false,
})

beforeEach(() => useChatStore.getState().reset())

describe('useActiveSurface', () => {
  it('is the canvas when the v2 directive hands over a tool', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
  })

  it('is the chat when the v2 directive hands over no tool', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('chat')
  })

  it('is the canvas while a rejected finalize has re-opened it', () => {
    // FINALIZE_CANVAS's directive is `allowed_tools: []`, but the canvas IS
    // live — the customer has to edit the text the gate rejected.
    useChatStore.setState({
      canvasDirective: directive([]), finalizeFailed: true,
    } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
  })

  it('falls back to the v1 whole-rail gate when there is no directive', () => {
    useChatStore.setState({ canvasDirective: null, chatState: 'canvas_design' } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('canvas')
    useChatStore.setState({ canvasDirective: null, chatState: 'ask_quantity' } as never)
    expect(renderHook(() => useActiveSurface()).result.current).toBe('chat')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/useActiveSurface.test.tsx`
Expected: FAIL — `Cannot find module '../lib/useActiveSurface'`.

- [ ] **Step 3: Write the hook**

Create `frontend/src/lib/useActiveSurface.ts`:

```ts
import { useChatStore } from '../store/chatStore'

export type ActiveSurface = 'canvas' | 'chat'

/**
 * Which panel the customer should act in on THIS turn.
 *
 * The backend already answers this: every v2-owned step emits a canvas
 * directive, and a step that hands over a tool is a canvas step while every
 * other step returns `allowed_tools: []`. Deriving it once here (rather than
 * in each panel) is what stops the two columns disagreeing about who is active
 * — a contradiction is worse than no cue at all.
 *
 * `finalizeFailed` is an explicit exception: FINALIZE_CANVAS hands over no
 * tool, but a REJECTED finalize re-opens the canvas so the customer can fix
 * what the gate refused (see Surface.doRender's catch). Reading the directive
 * alone would point them at the chat while the thing they must edit is on the
 * canvas.
 *
 * No directive at all means this is not a v2 turn — a v1 session, or a shared
 * tail state — so fall back to v1's existing whole-rail gate.
 */
export function useActiveSurface(): ActiveSurface {
  const canvasDirective = useChatStore(s => s.canvasDirective)
  const chatState = useChatStore(s => s.chatState)
  const finalizeFailed = useChatStore(s => s.finalizeFailed)

  if (canvasDirective === null) {
    return chatState === 'canvas_design' ? 'canvas' : 'chat'
  }
  return canvasDirective.allowedTools.length > 0 || finalizeFailed ? 'canvas' : 'chat'
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/useActiveSurface.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useActiveSurface.ts frontend/src/__tests__/useActiveSurface.test.tsx
git commit -m "feat(studio): derive which panel owns the current turn"
```

---

## Task 7: Focus highlighting in `CustomiseStudio`

**Files:**
- Modify: `frontend/src/components/CustomiseStudio/index.tsx`
- Test: `frontend/src/__tests__/customiseStudioFocus.test.tsx` (create)

**Interfaces:**
- Consumes: `useActiveSurface()` (Task 6).
- Produces: `data-testid="canvas-column"` and `data-testid="chat-column-wrap"` on the two column wrappers, each carrying `data-active="true" | "false"`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/__tests__/customiseStudioFocus.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../components/DesignStudio/Surface', () => ({
  DesignStudioSurface: () => <div data-testid="surface" />,
}))
vi.mock('../components/CustomiseStudio/ChatColumn', () => ({
  ChatColumn: () => <div data-testid="chat-column" />,
}))

import { useSessionStore } from '../store/sessionStore'
import { useChatStore } from '../store/chatStore'
import { CustomiseStudio } from '../components/CustomiseStudio'

const directive = (allowedTools: string[]) => ({
  allowedTools, targetFace: null, autoOpen: null,
  instructions: null, showDone: false, unlockAll: false,
})

beforeEach(() => {
  useChatStore.getState().reset()
  useSessionStore.setState({
    sessionId: 'sess-1', shareToken: 't', state: 'greeting',
    productRef: {
      id: 'p1', name: 'Classic Snapback', colour: 'Black', style: 'snapback',
      reference_image_url: 'https://example.com/cap.jpg', view_images: {},
    },
    entryContext: null, view: 'canvas',
  } as never)
})

describe('CustomiseStudio focus cue', () => {
  it('marks the canvas active and the chat inactive on a canvas step', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('true')
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('false')
  })

  it('marks the chat active and the canvas inactive on a chat step', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').dataset.active).toBe('true')
    expect(screen.getByTestId('canvas-column').dataset.active).toBe('false')
  })

  it('rings the active column and dims the inactive one', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('canvas-column').className).toContain('ring-2')
    expect(screen.getByTestId('chat-column-wrap').className).toContain('opacity-60')
  })

  it('never blocks pointer events on the inactive column', () => {
    // Dimming is a CUE, not a lock. The real locking is per-affordance
    // (stageLocked, ToolRail allowedTools, ChatColumn inputLocked). Blocking
    // pointer events here would also stop the customer scrolling back through
    // the thread or re-reading the cap, which they must always be able to do.
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByTestId('chat-column-wrap').className)
      .not.toContain('pointer-events-none')
  })

  it('names the surface in the pill so the cue is not colour-only', () => {
    useChatStore.setState({ canvasDirective: directive(['upload']) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/design here/i)
  })

  it('moves the pill to the chat on a chat step', () => {
    useChatStore.setState({ canvasDirective: directive([]) } as never)
    render(<CustomiseStudio />)
    expect(screen.getByRole('status').textContent).toMatch(/answer here/i)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/customiseStudioFocus.test.tsx`
Expected: FAIL — `Unable to find an element by: [data-testid="canvas-column"]`.

- [ ] **Step 3: Implement the focus treatment**

Replace `frontend/src/components/CustomiseStudio/index.tsx` entirely:

```tsx
import { useSessionStore } from '../../store/sessionStore'
import { DesignStudioSurface } from '../DesignStudio/Surface'
import { StoreHeader } from '../StoreHeader'
import { ChatColumn } from './ChatColumn'
import { MilestoneBar } from './MilestoneBar'
import { useActiveSurface, type ActiveSurface } from '../../lib/useActiveSurface'

/** Ring + glow on the panel the customer should act in; a scrim on the other.
 *  The glow reads `--brand-primary` so it themes per store, the same way
 *  `text-accent` / `bg-accent` already do. */
const ACTIVE_CLASSES =
  'ring-2 ring-accent shadow-[0_0_18px_-4px_var(--brand-primary,#FF5C00)] ' +
  'transition-[opacity,box-shadow] duration-300'
/** Deliberately NOT `pointer-events-none`: dimming is a cue, not a lock. The
 *  real locking is per-affordance (CanvasStage `locked`, ToolRail
 *  `allowedTools`, ChatColumn `inputLocked`). Blocking pointer events here
 *  would also stop the customer scrolling back through the thread or
 *  re-reading the cap, which they must always be able to do. */
const INACTIVE_CLASSES = 'opacity-60 transition-[opacity,box-shadow] duration-300'

function FocusPill({ surface }: { surface: ActiveSurface }) {
  return (
    <div
      role="status"
      className="mx-4 mt-3 self-start inline-flex items-center gap-1.5 rounded-full bg-accent/10 border border-accent px-3 py-1 text-xs font-semibold text-accent"
    >
      <span aria-hidden="true">▶</span>
      {surface === 'canvas' ? 'Your turn — design here' : 'Your turn — answer here'}
    </div>
  )
}

/**
 * CustomiseStudio — the split-screen canvas experience.
 * LEFT: the full interactive canvas studio (DesignStudioSurface).
 * RIGHT: a live chat column (ChatColumn), dormant until "See it rendered"
 *        hydrates the chat store, then driving verify → deliver → refine
 *        in place (no full-screen ChatPanel handoff).
 *
 * The two columns look identical at all times, so a non-technical customer had
 * no cue where to act on a given step. `useActiveSurface` answers that from the
 * backend directive; here it drives a ring + glow on one column and a scrim on
 * the other, plus a named pill (so the cue is never colour-only).
 */
export function CustomiseStudio() {
  const productRef = useSessionStore(s => s.productRef)
  const active = useActiveSurface()
  const canvasActive = active === 'canvas'

  return (
    <div className="h-screen bg-base flex flex-col">
      <StoreHeader title={productRef?.name} />
      <MilestoneBar />

      {/* Desktop: canvas (flex-1) left, chat (fixed) right. Mobile: stacked. */}
      <div className="flex-1 flex flex-col md:flex-row min-h-0">
        <div
          data-testid="canvas-column"
          data-active={String(canvasActive)}
          className={`flex-1 flex flex-col min-h-0 min-w-0 ${canvasActive ? ACTIVE_CLASSES : INACTIVE_CLASSES}`}
        >
          {canvasActive && <FocusPill surface="canvas" />}
          <div className="flex-1 flex min-h-0 min-w-0">
            <DesignStudioSurface />
          </div>
        </div>
        {/* Chat width scales with the screen: a laptop/iPad keeps roughly the old
            width (the canvas is tight there), a desktop gives the conversation a
            noticeably bigger share. Mobile (`w-full` + the 45vh split) unchanged. */}
        <div
          data-testid="chat-column-wrap"
          data-active={String(!canvasActive)}
          className={`border-t md:border-t-0 md:border-l border-border flex-shrink-0 w-full md:w-[360px] lg:w-[420px] xl:w-[480px] 2xl:w-[560px] h-[45vh] md:h-auto flex flex-col min-h-0 ${!canvasActive ? ACTIVE_CLASSES : INACTIVE_CLASSES}`}
        >
          {!canvasActive && <FocusPill surface="chat" />}
          <ChatColumn />
        </div>
      </div>
    </div>
  )
}
```

Note this passes `title={productRef?.name}` to `StoreHeader` — Task 8 renames
the prop from `subtitle` and drops the `› Design` suffix. If you are executing
Task 7 before Task 8, keep `subtitle={productRef ? productRef.name : undefined}`
and switch it in Task 8.

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/customiseStudioFocus.test.tsx src/__tests__/CustomiseStudio.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CustomiseStudio/index.tsx \
        frontend/src/__tests__/customiseStudioFocus.test.tsx
git commit -m "feat(studio): highlight the panel the customer should work in"
```

---

## Task 8: Centred hat name in the header

**Files:**
- Modify: `frontend/src/components/StoreHeader.tsx`
- Modify: `frontend/src/components/CustomiseStudio/index.tsx` (the `StoreHeader` prop)
- Test: `frontend/src/__tests__/../components/StoreHeader.test.tsx`, `frontend/src/__tests__/CustomiseStudio.test.tsx`

**Interfaces:**
- Consumes: nothing.
- Produces: `StoreHeader` takes `title?: string` (was `subtitle?: string`). Task 7's snippet already passes `title`.

**Background.** The hat name currently renders inline right after the logo as
`"${productRef.name} › Design"`. Two changes: drop the `› Design` suffix, and
centre the name in the header.

Centring uses **equal `flex-1 basis-0` flanks**, not absolute positioning:
`flex-1 basis-0` makes the two outer zones share the leftover space equally
regardless of their content widths, which centres the middle element exactly —
and unlike an absolutely-positioned title it can never overlap the logo or the
menu on a narrow screen.

- [ ] **Step 1: Write the failing tests**

Read the existing `frontend/src/components/StoreHeader.test.tsx` first and keep
its cases. Append:

```tsx
describe('centred title', () => {
  it('renders the title with no breadcrumb suffix', () => {
    render(<StoreHeader title="Classic Snapback" />)
    expect(screen.getByTestId('header-title').textContent).toBe('Classic Snapback')
  })

  it('centres it with equal-basis flanks, not absolute positioning', () => {
    // `flex-1 basis-0` on BOTH flanks makes them share the leftover space
    // equally whatever their content, which centres the middle exactly. An
    // absolutely-positioned title would overlap the logo or the menu on a
    // narrow screen instead.
    render(<StoreHeader title="Classic Snapback" />)
    const title = screen.getByTestId('header-title')
    const header = title.closest('header')!
    const flanks = header.querySelectorAll('[data-header-flank]')
    expect(flanks).toHaveLength(2)
    flanks.forEach(f => {
      expect(f.className).toContain('flex-1')
      expect(f.className).toContain('basis-0')
    })
    expect(title.className).not.toContain('absolute')
  })

  it('renders no title node when none is given', () => {
    render(<StoreHeader />)
    expect(screen.queryByTestId('header-title')).toBeNull()
  })
})
```

And update the breadcrumb case in `frontend/src/__tests__/CustomiseStudio.test.tsx`:

```tsx
  it('shows the shared header with the hat name and no breadcrumb suffix', () => {
    render(<CustomiseStudio />)
    expect(screen.getByText('MAD HATS')).toBeInTheDocument()
    expect(screen.getByTestId('header-title').textContent).toBe('Classic Snapback')
  })
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose exec -T frontend npx vitest run src/components/StoreHeader.test.tsx src/__tests__/CustomiseStudio.test.tsx`
Expected: FAIL — no `header-title` testid.

- [ ] **Step 3: Rewrite `StoreHeader`**

Replace `frontend/src/components/StoreHeader.tsx`:

```tsx
import { useBrandStore } from '../store/brandStore'

/**
 * Branded studio header: store logo (or name) on the left, an optional centred
 * title, and up to 5 external main-menu links on the right. Colours come from
 * CSS vars (with MadHats fallbacks) set by brandStore.applyBrandVars.
 *
 * The title is centred by giving BOTH flanks `flex-1 basis-0`: they then share
 * the leftover space equally whatever their content width, so the middle
 * element lands dead centre. An absolutely-positioned title would centre too,
 * but would overlap the logo or the menu on a narrow screen.
 */
export function StoreHeader({ title }: { title?: string }) {
  const { brand, storeName } = useBrandStore()
  const menu = (brand.menu_items ?? []).slice(0, 5)
  const headerStyle = {
    background: 'var(--brand-header-bg, #ffffff)',
    color: 'var(--brand-header-text, #1A1D29)',
  }

  return (
    <header
      className="border-b border-border px-6 py-2 flex items-center gap-3 flex-shrink-0"
      style={headerStyle}
    >
      <div data-header-flank className="flex-1 basis-0 min-w-0 flex items-center">
        {brand.logo_url ? (
          <img src={brand.logo_url} alt={storeName || 'MAD HATS'} className="h-8 w-auto object-contain" />
        ) : (
          <span className="font-extrabold text-lg tracking-wide">
            {storeName || 'MAD HATS'}
          </span>
        )}
      </div>

      {title && (
        <span
          data-testid="header-title"
          className="flex-shrink-0 max-w-[40%] truncate text-sm font-semibold"
        >
          {title}
        </span>
      )}

      <div data-header-flank className="flex-1 basis-0 min-w-0 flex items-center justify-end">
        {menu.length > 0 && (
          <nav className="flex items-center gap-4 overflow-x-auto">
            {menu.map((m, i) => (
              <a
                key={i}
                href={m.url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium hover:opacity-70 whitespace-nowrap"
              >
                {m.label}
              </a>
            ))}
          </nav>
        )}
      </div>
    </header>
  )
}
```

- [ ] **Step 4: Update the one `StoreHeader` caller**

`src/components/CustomiseStudio/index.tsx:19` is the only production call site
(verified with `grep -rn "StoreHeader" src --include=*.tsx`; the only others are
in `StoreHeader.test.tsx`, which passes no props). Replace it with:

```tsx
      <StoreHeader title={productRef?.name} />
```

Re-run that grep after the edit to confirm no `subtitle=` remains.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose exec -T frontend npx vitest run src/components/StoreHeader.test.tsx src/__tests__/CustomiseStudio.test.tsx src/__tests__/customiseStudioFocus.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/StoreHeader.tsx \
        frontend/src/components/StoreHeader.test.tsx \
        frontend/src/components/CustomiseStudio/index.tsx \
        frontend/src/__tests__/CustomiseStudio.test.tsx
git commit -m "fix(header): centre the hat name and drop the breadcrumb suffix"
```

---

## Task 9: Adjust panel — five sections, D-pad, 12.5° rotate

**Files:**
- Modify: `frontend/src/components/DesignStudio/SelectedToolbar.tsx` (full rewrite)
- Test: `frontend/src/__tests__/selectedToolbarTransform.test.tsx` (update), `frontend/src/__tests__/selectedToolbarPlacement.test.tsx` (update one case)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: no code interface. Preserves `data-testid="adjust-panel"`,
  `data-testid="adjust-controls"`, the `variant` prop, the `overflow-y-auto`
  class on the controls region and its measured `maxHeight`, and the accessible
  names `Nudge left/right/up/down`, `Reset rotation`, `Rotation degrees`,
  `Increase size`, `Decrease size`, `Bring forward`, `Send back`, `Duplicate`,
  `Delete`, and the groups `Layer order` and `Actions`.

**Background.** The panel is one wrapping flex row written for the cramped
centre column. Since it moved to the tool rail on desktop it has room, and the
flat row reads as an undifferentiated strip. The four Move arrows sit in a
horizontal line, which communicates nothing about direction. Rotate steps 45°,
which is far too coarse to place a logo.

- [ ] **Step 1: Update the rotate assertions in the transform test**

In `frontend/src/__tests__/selectedToolbarTransform.test.tsx`, replace the
first test and the two other places that name 45 degrees:

```tsx
  test('+12.5° / −12.5° rotate and normalise into [0,360)', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Rotate right 12.5 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(12.5)
    // 12.5 - 12.5 - 12.5 wraps: 12.5 → 0 → 347.5
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 12.5 degrees' }))
    fireEvent.click(screen.getByRole('button', { name: 'Rotate left 12.5 degrees' }))
    expect(useCanvasStore.getState().faces.front.find(e => e.id === id)?.rotation).toBe(347.5)
  })

  test('the degree readout shows 12.5, never a rounded 13', () => {
    selectedText()
    render(<SelectedToolbar />)
    fireEvent.click(screen.getByRole('button', { name: 'Rotate right 12.5 degrees' }))
    expect((screen.getByLabelText('Rotation degrees') as HTMLInputElement).value).toBe('12.5')
  })
```

In the `'drawings offer rotate + move but NO size buttons'` test and the
`'every transform control has a hover tooltip'` list, replace
`'Rotate right 45 degrees'` / `'Rotate left 45 degrees'` with the 12.5 forms.

Then append the new-structure tests:

```tsx
describe('SelectedToolbar sections', () => {
  test('groups the controls into labelled sections', () => {
    selectedText()
    render(<SelectedToolbar />)
    for (const name of ['Content', 'Style', 'Position', 'Layer order', 'Actions']) {
      expect(screen.getByRole('group', { name })).toBeInTheDocument()
    }
  })

  test('omits a section that has nothing in it for this element type', () => {
    // An image has no Style controls — an empty captioned block would read as
    // a broken panel.
    const s = useCanvasStore.getState()
    s.addImage('http://x/a.png', 1)
    s.select(useCanvasStore.getState().faces.front[0].id)
    render(<SelectedToolbar />)
    expect(screen.queryByRole('group', { name: 'Style' })).toBeNull()
    expect(screen.getByRole('group', { name: 'Position' })).toBeInTheDocument()
  })

  test('Move is a D-pad cross with a recentre in the middle', () => {
    const id = selectedText()
    render(<SelectedToolbar />)
    const pad = screen.getByRole('group', { name: 'Move' })
    expect(pad.className).toContain('grid-cols-3')
    fireEvent.click(screen.getByRole('button', { name: 'Centre on the cap' }))
    const el = useCanvasStore.getState().faces.front.find(e => e.id === id)!
    expect(el.x).toBe(0.5)
    expect(el.y).toBe(0.5)
  })

  test('captions are always shown — no tooltip-only compact mode', () => {
    // The old panel hid its captions below a measured column width. That mode
    // existed for the cramped centre column; captions are the point now.
    selectedText()
    render(<SelectedToolbar />)
    const rotate = screen.getByRole('group', { name: 'Position' })
    const caption = Array.from(rotate.querySelectorAll('span'))
      .find(s => s.textContent === 'Position')
    expect(caption?.className).not.toContain('hidden')
  })
})
```

- [ ] **Step 2: Replace the obsolete caption test in the placement test**

In `frontend/src/__tests__/selectedToolbarPlacement.test.tsx`, DELETE the test
named `'drops the group captions to tooltips on a narrow column, keeping them
for screen readers'` — the compact mode it pins is being removed. Replace it
with:

```tsx
  test('keeps its group captions at every column width (the compact mode is gone)', () => {
    // The captions used to be hidden below a measured column width, to save
    // ~24px per group in the cramped centre column. The panel now lives in the
    // tool rail on desktop and the captions are the point of the restructure,
    // so they are unconditional.
    selectText()
    render(<SelectedToolbar />)
    const position = screen.getByRole('group', { name: 'Position' })
    const caption = Array.from(position.querySelectorAll('span'))
      .find(s => s.textContent === 'Position')
    expect(caption).toBeTruthy()
    expect(caption?.className).not.toContain('hidden')
  })
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec -T frontend npx vitest run src/__tests__/selectedToolbarTransform.test.tsx src/__tests__/selectedToolbarPlacement.test.tsx`
Expected: FAIL — no `Rotate right 12.5 degrees` button, no `Content`/`Style`/`Position` groups.

- [ ] **Step 4: Rewrite `SelectedToolbar.tsx`**

Replace the file entirely:

```tsx
import { useEffect, useRef, useState } from 'react'
import { useCanvasStore, LINE_SHAPES, TEXT_PLACEHOLDER } from '../../store/canvasStore'
import { WEB_SAFE_FONTS, GOOGLE_FONTS } from '../../lib/fonts'

/** The panel may never eat more than this share of the column it shares with
 *  the cap. A share, not a fixed height, because the column's height is
 *  viewport-derived. */
const MAX_SHARE = 1 / 3
/** Floor, so the cap is never so tight the panel is unusable — below this it
 *  scrolls internally instead of shrinking further. */
const MIN_MAX_H = 72

/** Header label per element type — the panel names what it is adjusting, so a
 *  customer who selects something knows the panel that just appeared is for it. */
const ADJUST_LABELS: Record<string, string> = {
  text: 'Text', image: 'Image', shape: 'Shape', drawing: 'Drawing',
}

/** One click of ⟲ / ⟳. Was 45°, which is far too coarse to place a logo —
 *  eight positions on the whole circle. 12.5° gives fine control while still
 *  being one tap, and the readout formats to one decimal so the sequence reads
 *  0 · 12.5 · 25 · 37.5 rather than a lying rounded 13. */
const ROTATE_STEP = 12.5
const NUDGE = 0.02
const SIZE_FACTOR = 1.1

/** One decimal, but only when there is one — "45", not "45.0". */
function fmtDeg(v: number): string {
  const r = Math.round(v * 10) / 10
  return Number.isInteger(r) ? String(r) : r.toFixed(1)
}

/** `stacked` shares the centre column with the cap (mobile) — capped and
 *  sticky. `rail` sits in the tool rail below the Done button (desktop), where
 *  it competes with nothing, so it takes no height cap and needs no sticky. */
export function SelectedToolbar({ variant = 'stacked' }: { variant?: 'rail' | 'stacked' } = {}) {
  const activeFace = useCanvasStore(s => s.activeFace)
  const faces = useCanvasStore(s => s.faces)
  const selectedId = useCanvasStore(s => s.selectedId)
  const update = useCanvasStore(s => s.updateElement)
  const remove = useCanvasStore(s => s.removeElement)
  const duplicate = useCanvasStore(s => s.duplicate)
  const reorder = useCanvasStore(s => s.reorder)

  const el = faces[activeFace].find(e => e.id === selectedId)

  // Cap the controls region at a share of the column, MEASURED. `vh` cannot be
  // right here: it is a fraction of the VIEWPORT, but this panel lives in a
  // column shorter than the viewport by the chat and two header bars — and
  // because the root is `sticky top-0`, an over-cap panel stays pinned for the
  // whole scroll range and the cap never comes back.
  //
  // No feedback loop: the column's height comes from the flex row above it
  // (viewport-derived, content-independent), so the panel resizing can never
  // change the number it just read — the same property CanvasStage relies on.
  // The observer is feature-detected: jsdom ships none, and constructing one
  // unconditionally throws through every test that mounts Surface.
  const rootRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLInputElement>(null)
  const [maxH, setMaxH] = useState<number | null>(null)
  useEffect(() => {
    const col = rootRef.current?.parentElement
    if (!col) return
    const measure = () => {
      // Only the stacked variant caps its height: there it steals pixels from
      // the cap, which CanvasStage sizes from the leftover column height. In the
      // rail there is no cap beside it — the column's own overflow-y-auto
      // handles a long panel.
      setMaxH(variant === 'rail'
        ? null
        : Math.max(MIN_MAX_H, Math.round(col.clientHeight * MAX_SHARE)))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(col)
    window.addEventListener('resize', measure)
    return () => { ro?.disconnect(); window.removeEventListener('resize', measure) }
    // Keyed on the selected element: with nothing selected this component
    // renders null, so there is no DOM and no parent to measure. Re-running as
    // the panel mounts is what gets the first measurement at all.
  }, [el?.id, variant])

  // Rail variant only: the panel mounts BELOW <ToolRail> inside an
  // overflow-y-auto column and deliberately takes no height cap, so on a short
  // column a newly-shown panel can land at or past the fold with no scroll cue
  // — verbatim the "selecting an element looks like it did nothing" bug this
  // panel's placement work exists to fix. `block: 'nearest'` so an
  // already-visible panel doesn't jump.
  //
  // Feature-detected like the observer above: jsdom leaves scrollIntoView
  // undefined on some element types, and calling it unconditionally throws
  // through every test that mounts this panel. The stacked variant is sticky at
  // the top of its own column and must not scroll.
  useEffect(() => {
    if (variant !== 'rail') return
    const node = rootRef.current
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' })
    }
  }, [el?.id, variant])

  // Focus+select ONLY while the content is still the untouched placeholder, so
  // a freshly added element can be typed straight over. Re-selecting an element
  // the customer already edited must not steal focus — on a phone that pops the
  // keyboard over the canvas. Keyed on the id alone: the guard goes false on the
  // first keystroke, so re-running per character would be pointless churn.
  useEffect(() => {
    if (el?.type !== 'text' || el.content !== TEXT_PLACEHOLDER) return
    contentRef.current?.focus()
    contentRef.current?.select()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [el?.id])

  if (!el) return null

  // --- Universal transform helpers (rotate / move / size) ---
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v))
  const norm360 = (deg: number) => ((deg % 360) + 360) % 360
  const rotateBy = (delta: number) => update(el.id, { rotation: norm360((el.rotation ?? 0) + delta) })
  const nudge = (dx: number, dy: number) =>
    update(el.id, { x: clamp01((el.x ?? 0) + dx), y: clamp01((el.y ?? 0) + dy) })
  const recentre = () => update(el.id, { x: 0.5, y: 0.5 })
  const resize = (factor: number) => {
    if (el.type === 'text') {
      update(el.id, { fontSize: Math.max(8, Math.round((el.fontSize ?? 36) * factor)) })
    } else {
      update(el.id, {
        width: clamp01((el.width ?? 0.2) * factor),
        height: clamp01((el.height ?? 0.2) * factor),
      })
    }
  }
  // Drawings have no width/height (geometry lives in `points`), matching their
  // rotate-only on-canvas Transformer — so size is not offered for them.
  const canResize = el.type !== 'drawing'
  const isLineShape = el.type === 'shape' && LINE_SHAPES.includes(el.shapeKind ?? 'rect')
  // An image's only control is the background flag, which is Content, not Style
  // — so an image has no Style section at all. An empty captioned block reads
  // as a broken panel, which is why every section is conditional.
  const hasContent = el.type === 'text' || el.type === 'image'
  const hasStyle = el.type === 'text' || el.type === 'shape' || el.type === 'drawing'

  return (
    <div ref={rootRef} data-testid="adjust-panel"
      className={`${variant === 'stacked' ? 'sticky top-0 z-20 ' : ''}w-full shrink-0 bg-surface border border-accent rounded-xl overflow-hidden shadow-sm`}>
      <div className="bg-accent text-white px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide">
        Adjust — {ADJUST_LABELS[el.type] ?? 'Element'}
      </div>
      <div data-testid="adjust-controls"
        className="flex flex-col px-2 overflow-y-auto"
        style={maxH ? { maxHeight: maxH } : undefined}>

        {hasContent && (
          <Section label="Content">
            {el.type === 'text' && (
              <label className="basis-full flex flex-col gap-0.5">
                <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">Your text</span>
                <input ref={contentRef} value={el.content ?? ''}
                  onChange={e => update(el.id, { content: e.target.value })}
                  className="w-full bg-base border border-accent rounded px-2 py-1 text-sm text-textPrimary focus:outline-none focus:ring-2 focus:ring-accent/40"
                  aria-label="Text content" />
              </label>
            )}
            {el.type === 'image' && (
              <label className="flex items-center gap-1.5 text-xs text-textPrimary"
                title="Flag this image so the design team knocks out its background when producing the artwork">
                <input type="checkbox" checked={!!el.removeBg}
                  onChange={e => update(el.id, { removeBg: e.target.checked })} />
                Remove background
              </label>
            )}
          </Section>
        )}

        {hasStyle && (
          <Section label="Style">
            {el.type === 'text' && (
              <>
                <select value={el.font ?? 'Arial'} onChange={e => update(el.id, { font: e.target.value })}
                  className="bg-base border border-border rounded px-1.5 py-0.5 text-xs max-w-[7rem]" aria-label="Font"
                  style={{ fontFamily: el.font ?? 'Arial' }}>
                  <optgroup label="Standard">
                    {WEB_SAFE_FONTS.map(f => (
                      <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
                    ))}
                  </optgroup>
                  <optgroup label="Google Fonts">
                    {GOOGLE_FONTS.map(f => (
                      <option key={f.family} value={f.family} style={{ fontFamily: f.family }}>{f.label}</option>
                    ))}
                  </optgroup>
                </select>
                <input type="color" value={el.colour ?? '#ffffff'} onChange={e => update(el.id, { colour: e.target.value })}
                  className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Text colour" />
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Font size">
                  <span aria-hidden="true">A</span>
                  <input type="range" className="w-20" min={12} max={96} value={el.fontSize ?? 36}
                    onChange={e => update(el.id, { fontSize: Number(e.target.value) })} aria-label="Font size" />
                </label>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Curve the text">
                  <span aria-hidden="true">Curve</span>
                  <input type="range" className="w-20" min={-100} max={100} step={5} value={el.curve ?? 0}
                    onChange={e => update(el.id, { curve: Number(e.target.value) })} aria-label="Curve text" />
                </label>
              </>
            )}
            {el.type === 'drawing' && (
              <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Stroke colour">
                <span>Colour</span>
                <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
                  className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Stroke colour" />
              </label>
            )}
            {isLineShape && (
              <>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Colour">
                  <span>Colour</span>
                  <input type="color" value={el.fill ?? '#111827'} onChange={e => update(el.id, { fill: e.target.value })}
                    className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Shape colour" />
                </label>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Thickness">
                  <span>Width</span>
                  <input type="range" className="w-20" min={2} max={30} value={el.strokeWidth ?? 6}
                    onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Line thickness" />
                </label>
              </>
            )}
            {el.type === 'shape' && !isLineShape && (
              <>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Fill colour">
                  <span>Fill</span>
                  <input type="color" value={el.fill ?? '#2563eb'} onChange={e => update(el.id, { fill: e.target.value, filled: true })}
                    className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Fill colour" />
                </label>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Border colour">
                  <span>Border</span>
                  <input type="color" value={el.stroke ?? '#111827'} onChange={e => update(el.id, { stroke: e.target.value })}
                    className="w-6 h-6 p-0 border-0 bg-transparent" aria-label="Border colour" />
                </label>
                <label className="flex items-center gap-1 text-[11px] text-textMuted" title="Border width">
                  <span>W</span>
                  <input type="range" className="w-20" min={0} max={24} value={el.strokeWidth ?? 0}
                    onChange={e => update(el.id, { strokeWidth: Number(e.target.value) })} aria-label="Border width" />
                </label>
                <button
                  onClick={() => update(el.id, el.filled === false
                    ? { filled: true }
                    : { filled: false, strokeWidth: Math.max(el.strokeWidth ?? 0, 4) })}
                  className={btn}
                  title="Toggle filled / outline"
                >
                  {el.filled === false ? 'Outline' : 'Filled'}
                </button>
              </>
            )}
          </Section>
        )}

        <Section label="Position">
          {/* A game-controller cross, not a row of four arrows: the layout IS
              the label. The centre cell recentres — it fills the hole the cross
              leaves (an empty middle reads as a missing button) and is
              genuinely the fastest way to recover a dragged-off element. */}
          <div className="grid grid-cols-3 gap-1 w-max" role="group" aria-label="Move">
            <span />
            <button onClick={() => nudge(0, -NUDGE)} className={btn} title="Move up" aria-label="Nudge up">↑</button>
            <span />
            <button onClick={() => nudge(-NUDGE, 0)} className={btn} title="Move left" aria-label="Nudge left">←</button>
            <button onClick={recentre} className={btn} title="Centre on the cap" aria-label="Centre on the cap">⊕</button>
            <button onClick={() => nudge(NUDGE, 0)} className={btn} title="Move right" aria-label="Nudge right">→</button>
            <span />
            <button onClick={() => nudge(0, NUDGE)} className={btn} title="Move down" aria-label="Nudge down">↓</button>
            <span />
          </div>

          <div className="flex flex-col gap-1.5">
            {/* Curved arrows (⟲/⟳), never confusable with Move's straight
                directional arrows or Layer order's Fwd/Back glyphs below. */}
            <div className="flex items-center gap-1" role="group" aria-label="Rotate">
              <button onClick={() => rotateBy(-ROTATE_STEP)} className={btn}
                title="Rotate 12.5° left" aria-label="Rotate left 12.5 degrees">⟲</button>
              <input type="number" step={ROTATE_STEP} value={fmtDeg(el.rotation ?? 0)}
                onChange={e => update(el.id, { rotation: norm360(Number(e.target.value) || 0) })}
                className="w-14 bg-base border border-border rounded px-1 py-0.5 text-xs text-textPrimary"
                aria-label="Rotation degrees" title="Set an exact rotation in degrees" />
              <button onClick={() => rotateBy(ROTATE_STEP)} className={btn}
                title="Rotate 12.5° right" aria-label="Rotate right 12.5 degrees">⟳</button>
              <button onClick={() => update(el.id, { rotation: 0 })} className={btn}
                title="Reset rotation to 0°" aria-label="Reset rotation">Reset</button>
            </div>
            {canResize && (
              <div className="flex items-center gap-1" role="group" aria-label="Size">
                <span className="text-[11px] text-textMuted">Size</span>
                <button onClick={() => resize(1 / SIZE_FACTOR)} className={btn} title="Make smaller" aria-label="Decrease size">−</button>
                <button onClick={() => resize(SIZE_FACTOR)} className={btn} title="Make larger" aria-label="Increase size">+</button>
              </div>
            )}
          </div>
        </Section>

        {/* Deliberately TEXT + stacked-square glyphs, never the bare ↑/↓ the
            D-pad above owns. "Forward" = toward the top of the stack; "Back" =
            toward the bottom — unrelated to on-screen position, which is what
            Move controls. */}
        <Section label="Layer order">
          <button onClick={() => reorder(el.id, 'up')} className={btn}
            title="Bring this element forward, in front of whatever is on top of it" aria-label="Bring forward">▲Fwd</button>
          <button onClick={() => reorder(el.id, 'down')} className={btn}
            title="Send this element back, behind whatever is under it" aria-label="Send back">▼Back</button>
        </Section>

        <Section label="Actions">
          <button onClick={() => duplicate(el.id)} className={btn} title="Duplicate this element" aria-label="Duplicate">Duplicate</button>
          <button onClick={() => remove(el.id)} className="px-1.5 py-0.5 text-xs text-red-600 border border-red-200 rounded hover:bg-red-50 transition-colors"
            title="Delete this element" aria-label="Delete">Delete</button>
        </Section>
      </div>
    </div>
  )
}

/** One captioned block of the panel. The caption is unconditional — the old
 *  panel hid it below a measured column width to save ~24px per group in the
 *  cramped centre column, but the panel now lives in the tool rail on desktop
 *  and the captions are the whole point of the restructure. `role="group"` +
 *  `aria-label` keep it machine-readable as well as sighted-labelled. */
function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section role="group" aria-label={label}
      className="flex flex-col gap-1 py-2 border-t border-border first:border-t-0">
      <span className="text-[10px] uppercase tracking-wide text-textMuted leading-none">{label}</span>
      <div className="flex flex-wrap items-start gap-2">{children}</div>
    </section>
  )
}

const btn = 'px-1.5 py-0.5 text-xs border border-border rounded hover:border-accent transition-colors'
```

- [ ] **Step 5: Run the tests to verify they pass**

Run:
```
docker compose exec -T frontend npx vitest run \
  src/__tests__/selectedToolbarTransform.test.tsx \
  src/__tests__/selectedToolbarPlacement.test.tsx \
  src/__tests__/selectedToolbarText.test.tsx \
  src/__tests__/adjustPanelPlacement.test.tsx
```
Expected: PASS. If `adjustPanelPlacement.test.tsx`'s
`'applies no height cap in the rail variant'` fails, check that
`data-testid="adjust-controls"` still carries `overflow-y-auto` and no inline
`maxHeight` for `variant="rail"`.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DesignStudio/SelectedToolbar.tsx \
        frontend/src/__tests__/selectedToolbarTransform.test.tsx \
        frontend/src/__tests__/selectedToolbarPlacement.test.tsx
git commit -m "feat(adjust): labelled sections, a D-pad for Move, and a 12.5 degree rotate step"
```

---

## Task 10: Full-suite verification and in-browser check

**Files:** none modified — this task is verification only.

**Interfaces:**
- Consumes: every prior task.
- Produces: a green baseline and an in-browser confirmation.

- [ ] **Step 1: Run the whole backend suite**

Run: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
Expected: PASS. Baseline was 1196; this branch adds ~8.

- [ ] **Step 2: Run the v2-only suites with the flag on**

Run:
```
cd backend && CANVAS_ORCHESTRATOR_V2=true ./.venv/Scripts/python.exe -m pytest -q \
  tests/test_orchestrator_v2.py tests/test_v2_e2e.py tests/test_v2_copy_guards.py \
  tests/test_state_machine_v2.py tests/test_canvas_steps.py
```
Expected: PASS.

- [ ] **Step 3: Run the frontend suite**

Run: `docker compose exec -T frontend npx vitest run src/__tests__`
Expected: PASS except the two pre-existing `adminQuotes` failures (missing
Router context). Confirm the count went UP from 273 and that the failures are
still exactly those two — if a third appears, it is yours.

- [ ] **Step 4: Type-check and build the frontend**

Run: `docker compose exec -T frontend npx tsc --noEmit`
Expected: no errors. In particular, every `StoreHeader` call site must have
moved from `subtitle` to `title`.

- [ ] **Step 5: Check it in the browser**

Bring the stack up (`docker compose up -d`), open the studio with
`CANVAS_ORCHESTRATOR_V2=true` in the root `.env` (recreate the backend after
changing it: `docker compose up -d --force-recreate backend`), and walk a
canvas session far enough to confirm:

1. The name question dims the canvas and rings the chat, with the
   "Your turn — answer here" pill on the chat column.
2. Answering through to the logo placement step flips the ring and the pill to
   the canvas.
3. Selecting a placed element opens the Adjust panel with five captioned
   sections; the D-pad reads as a cross; ⟳ steps the readout to `12.5`, not `13`;
   ⊕ recentres.
4. The header shows the hat name centred, with no `› Design`.
5. Chat replies show the instruction as its own paragraph under the question.

- [ ] **Step 6: Record the outcome in CLAUDE.md**

Add a bullet to the "Current implementation state" list in `CLAUDE.md`
summarising: the focus cue and its `useActiveSurface` derivation (including why
`finalizeFailed` had to move into `chatStore`); the Adjust panel's five sections
/ D-pad / 12.5° step and the removal of the compact caption mode; the centred
header; `data.extra_replies` and the split verified turn; the blank-line
paragraph joins; and `Step.accept_verbatim` on `ASK_PURPOSE` with the reason it
is per-step rather than global. Update the test counts.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: record the canvas studio UX batch in project memory"
```
