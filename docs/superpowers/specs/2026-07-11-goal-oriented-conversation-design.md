# Goal-Oriented Conversation Engine — Design

**Date:** 2026-07-11
**Status:** Approved (brainstorm), pending implementation plan
**Supersedes behaviour in:** `2026-07-11-smarter-studio-design.md` (the interpreter-first state machine)

---

## 1. Problem

The current conversation engine advances **one state per turn** and, on any turn the
LLM interpreter classifies as `ask_question` or `chitchat`, it **stays on the current
state and re-asks the same question** (`orchestrator.py:105-110`).

Two consequences:

- **The name is asked twice.** The greeting asks for the name and moves to `ASK_NAME`.
  When the customer replies with a bare word (e.g. "Satish"), the interpreter often
  classifies it as `chitchat`/`ask_question` (it doesn't look like a clear answer), so
  the "stay & re-ask" branch fires and Ricardo asks for the name again.
- **The whole flow feels rigid ("dumb").** The re-ask-on-ambiguity rule triggers at
  every step, and the questionnaire is a long chain of narrow single-field questions
  (placement zone, then placement position, then …), so it reads like a form.

The fix is to move from **strict per-state adherence** to a **goal-oriented model**:
keep a checklist of the fields we need, extract everything the customer volunteers each
turn, and only ever ask for what is genuinely still missing.

## 2. Goals & Non-Goals

**Goals**
- Fill a fixed checklist of design goals ("the 9 steps") naturally, in any order the
  customer offers them.
- Never re-ask a goal that is already satisfied.
- Never loop/re-ask purely because a turn was classified as a question or chit-chat —
  answer inline, keep any data it carried, and proceed to the next unmet goal.
- Make the flow feel conversational: merge placement zone + position, fold the
  decoration recommendation into a single ask, and soft-skip purpose.

**Non-Goals**
- No change to the downstream machinery: generation, email double-opt-in verification,
  show-design, refine/quote/upsell all stay exactly as they are.
- No full LLM planner. The LLM still only interprets/extracts and words replies; the
  engine (code) owns routing. This keeps the hard constraints enforceable and testable.
- No change to the `ConversationState` enum values or the frontend `data` contract
  (`options`/`continuable`/`trigger_*`/`progress`).

## 3. The Goal Checklist

A declarative, ordered list. Each goal has: `key`, `required` (`required` | `soft` |
`optional`), the `ConversationState` used to ask it, and a `satisfied(collected)`
predicate. The questionnaire covers goals 1–8; everything after email is the existing
deterministic post-questionnaire flow.

| # | Goal | Kind | State(s) | Satisfied when |
|---|------|------|----------|----------------|
| 1 | name | required | `ASK_NAME` | `collected.name` non-empty |
| 2 | purpose | soft | `ASK_PURPOSE` | `collected.purpose` non-empty **or** `flags.purpose_asked` |
| 3 | quantity | required | `ASK_QUANTITY` | the `quantity` key is present in `collected` (any int, incl. `0` = "not sure") — presence, not truthiness, so "not sure" counts as answered |
| 4 | decoration_type | required | `RECOMMEND_*` (recommendation folded in) | `collected.decoration_type` set |
| 5 | design source | required | `ASK_HAS_LOGO` | `collected.has_logo` is a bool |
| 5a | uploaded logo | required (logo branch) | `UPLOAD_LOGO` | `collected.uploaded_asset_path` set |
| 5b | remove background | required (logo branch) | `ASK_REMOVE_BG` | `collected.remove_bg` is a bool |
| 5c | design description | required (describe branch) | `DESCRIBE_DESIGN` | `collected.design_description` set |
| 6 | placement | required | `ASK_PLACEMENT_ZONE` (merged) | `collected.placement_zone` set (position defaults to `centre`) |
| 7 | pin annotation | optional | `ASK_PIN_ANNOTATION` | offered once (`flags.pin_offered`); never blocks |
| 8 | email | required | `GENERATING` / `ASK_EMAIL` | `collected.email_captured` true → triggers verification |

**Youth referral** stays a deterministic gate derived from `collected.youth_flag`
(set during purpose extraction); it is shown once, then falls through to quantity.

### `flags`
A small dict persisted alongside `collected` (or namespaced inside it, e.g.
`collected["_flags"]`) recording one-shot events so soft/optional goals are never
nagged: `purpose_asked`, `pin_offered`. Implementation may reuse existing keys where
they already exist.

## 4. Per-Turn Algorithm (orchestrator)

```
handle_message(session, message):
  if state == GREETING:                     # kickoff unchanged
     reply = greeting (asks name once); next = ASK_NAME; return

  interp = interpret_turn(state, message, collected, ...)   # 1 LLM/heuristic call
  apply_all_fields(interp.fields, collected)                # merge EVERYTHING, not just current slot
  derive_branch_booleans(state, message, collected)         # has_logo, wants_pins, etc. (as today)
  handle_inline_email_capture(...)                          # unchanged

  aside = None
  if interp.intent in (ask_question, chitchat):
     aside = interp.question_answer or None                 # answer inline; DO NOT stay/re-ask

  if interp.intent in (revise, backtrack) and target allowed:
     next = target
  else:
     next = next_goal(collected, flags, upsell_count)       # first unmet goal / gate

  mark one-shot flags for the goal we are about to ask (purpose_asked, pin_offered)
  reply = generate_reply(next, collected, persona, aside=aside)
  persist; return reply, next, data(progress)
```

**Deleted:** the `intent in (ask_question, chitchat) → new_state = current` re-ask
branch. A question no longer freezes progress; the data it carried is still captured and
we advance to the next genuinely-unmet goal. The chip-exact-match override that forced
`answer` becomes unnecessary but may be kept as a belt-and-braces no-op.

## 5. `goal_planner.next_goal`

New module `app/services/conversation/goal_planner.py`.

```python
def next_goal(collected: dict, flags: dict, *, upsell_count: int = 0) -> ConversationState:
    """Return the state for the first unmet goal, walking the declarative GOALS
    list and honouring branch selection (has_logo), soft/optional kinds, and the
    downstream gates (email → verify → show → refine → quote → upsell → end)."""
```

Rules:
- Walk goals in order; return the state of the first goal whose `satisfied` predicate
  is false **and** whose kind is `required` (or `soft`/`optional` **and** not yet
  offered).
- Branch on `has_logo` to include 5a/5b or 5c.
- Placement is a single goal: satisfied by `placement_zone`; if the customer gave a zone
  but no position, default `placement_position = "centre"` and treat placement as done.
- Once goals 1–8 are satisfied, hand off to the existing downstream states via the
  current `advance_state` gates (generation/verify/show/refine/upsell). `next_goal`
  returns `GENERATING` when the questionnaire is complete and email not yet captured.

`advance_and_skip` is retired for the questionnaire; `advance_state` is retained for the
post-questionnaire gates it already handles well.

## 6. Reply Wording Changes

- **Auto-recommend decoration:** collapse `DECORATION_ENGINE` (the "working it out…"
  turn) so the recommendation appears directly in the `RECOMMEND_*` message. Remove the
  standalone `decoration_engine` user-facing turn (keep the branch logic that picks
  print vs embroidery vs patch by quantity).
- **Merged placement:** `ASK_PLACEMENT_ZONE` prompt asks where on the cap in one line;
  `ASK_PLACEMENT_POSITION` is no longer a mandatory separate turn (only reached if the
  customer explicitly wants to fine-tune, otherwise defaulted).
- **Soft purpose:** asked once; if unanswered, proceed without re-asking.
- All other STATE_PROMPTS/CANNED_REPLIES unchanged.

## 7. No-LLM-Key Fallback

`interpret_turn` without a key keeps the per-state heuristic extractor (fills the
current slot only). The planner still advances correctly because it asks the next unmet
goal in order — the experience degrades to "one question at a time" but never loops or
re-asks a filled slot. Full multi-field extraction is an LLM-only enhancement. This
preserves the existing "works with no Anthropic key" constraint.

## 8. Progress Indicator

`progress(state, collected)` recomputes "Step X of N" from the goal list: N = count of
`required` goals on the chosen branch; X = index of the current goal. Behaviour matches
today's indicator; only the source of truth moves to the goal list.

## 9. Testing

**`goal_planner` unit tests**
- Empty collected → returns `ASK_NAME`.
- name filled → skips to purpose; name never returned again once set (**name regression**).
- Multiple fields volunteered (name+quantity+purpose) → jumps to decoration.
- Soft purpose: once `purpose_asked`, planner never returns `ASK_PURPOSE` again.
- Decoration recommendation by quantity (1 → warn/print, <12 → print, ≥12 → embroidery).
- has_logo true → upload → remove_bg → placement; has_logo false → describe → placement.
- Merged placement: zone given, no position → placement satisfied, position defaulted.
- Optional pin annotation offered once, never blocks reaching `GENERATING`.
- Email gate: questionnaire complete → `GENERATING`; email captured → hand to verify.

**Orchestrator tests**
- Bare name at `ASK_NAME` fills name and advances to purpose (no second name ask).
- A question mid-flow is answered (aside present) and progress still advances; data in
  the same turn is retained.
- Chit-chat turn does not freeze the flow.
- Existing downstream tests (verification, refine, quote, upsell) remain green.

## 10. Rollout / Risk

- Bounded change: new planner module + orchestrator simplification + minor prompt edits.
  Enum, DB schema, frontend contract, and downstream gates untouched.
- Main risk: a goal predicate that is too strict could still "stick" on a slot. Mitigated
  by unit tests per goal and the soft/optional kinds.
- Reversible: the planner is additive; reverting to `advance_and_skip` restores old
  behaviour if needed.
