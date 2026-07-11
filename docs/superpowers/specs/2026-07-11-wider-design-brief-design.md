# Wider Design Brief + Goal-Leading Conversation — Design Spec

Date: 2026-07-11
Branch: feat/smarter-studio
Status: Approved (brainstorm) — ready for implementation plan

## 1. Problem

Two limits in the current conversation engine:

1. **The design brief is too narrow.** Design intake is a hard either/or
   (`ASK_HAS_LOGO`): the customer *either* uploads a logo *or* describes a
   design. The logo path (`UPLOAD_LOGO → ASK_REMOVE_BG → placement`) never asks
   about text, extra graphics, colours, or style, so a customer **cannot** say
   "here's our logo, *and also* put the team name under it in gold with a small
   star." The uploaded logo becomes the only decoration element. The
   prompt builder's uploaded-asset branch only appends extra context if
   `design_description.summary` happens to be set — and nothing in the logo path
   sets it.

2. **The post-verification flow repeats itself.** After the customer verifies
   their email, the chat walks through three consecutive statement-only states —
   `EMAIL_VERIFIED`, `SEND_PREVIEW_EMAIL`, `SHOW_DESIGN` — each with near-identical
   "your design is on its way to your inbox" copy, each requiring a **Continue**
   tap. It reads as the same message repeating, and the actual "want to tweak
   anything?" offer (`OFFER_REFINE`) is buried behind those taps.

## 2. Goal & Principle

Gather the customer's **full requirement** conversationally before generating,
and make the AI **goal-leading, not just goal-understanding**: every reply
acknowledges the specific thing the customer just said *and* steers toward the
goal (a complete brief → a design they love), answering side-questions inline
without losing the thread.

Scope decisions (confirmed with the user):

- Intake: **keep** logo-vs-describe as the starting point, then add an
  "anything else?" gather loop that both paths funnel into. (Not a full
  open-brief rewrite.)
- Refinement: customers can **add and modify** any element after generation
  (e.g. "now add our team name in gold"), reusing the same brief interpreter.
- Post-verification: collapse the three redundant statements into **one**
  message that lands straight on the tweak offer.

## 3. Design

### 3.1 One canonical structured brief (merge-not-overwrite)

`collected["design_description"]` becomes the single accumulating brief for both
paths:

```
{ summary: str, text_elements: [str], colours: [str], imagery: [str], style: str }
```

New helper `merge_brief(existing, incoming) -> dict`:

- List fields (`text_elements`, `colours`, `imagery`): append, de-duplicated,
  order-preserving.
- Scalar fields (`summary`, `style`): fill if empty; a non-empty incoming value
  replaces only when the customer is explicitly revising that field.

Every place that produces design elements (the describe turn, the gather loop,
and refinement change requests) routes through `merge_brief` so nothing is lost.

### 3.2 New gather-loop states (mirrors the pin-annotation pattern)

Two new `ConversationState` members, modelled on the existing, tested
`ASK_PIN_ANNOTATION` / `PIN_ANNOTATE_MODE` pair:

- `ASK_MORE_ELEMENTS` — offered exactly once (one-shot flag `elements_offered`).
  Copy: *"Anything else you'd like on the cap — text, a slogan, extra graphics,
  particular colours? Or say 'that's everything' and I'll get generating."*
  `_public_data` options: `["Add text", "Add a graphic", "That's everything"]`.
- `ADD_ELEMENTS_MODE` — loop. Extracts the stated element into the brief via
  `merge_brief`, then re-offers: *"Added '<x>'. Anything else, or ready to place
  it?"* Loops while the customer keeps adding; exits when they decline.

Transitions:

```
UPLOAD_LOGO   → ASK_REMOVE_BG → ASK_MORE_ELEMENTS
DESCRIBE_DESIGN               → ASK_MORE_ELEMENTS
ASK_MORE_ELEMENTS  → ADD_ELEMENTS_MODE (customer adds) | ASK_PLACEMENT_ZONE (declines)
ADD_ELEMENTS_MODE  → ADD_ELEMENTS_MODE (add_another_element) | ASK_PLACEMENT_ZONE
```

Branch booleans derived in `_apply_fields` from the raw message (works with and
without an LLM key), same style as `wants_pins` / `add_another_pin`:

- At `ASK_MORE_ELEMENTS`: `wants_more_elements` = customer supplied an element or
  affirmed, and did not decline.
- At `ADD_ELEMENTS_MODE`: `add_another_element` = "another"/affirmative and not a
  decline signal ("that's it", "that's everything", "generate", "done", "no").

Element extraction reuses `DESIGN_EXTRACTION_PROMPT` (LLM) / the no-key
heuristic, then `merge_brief` into `design_description`.

### 3.3 Goal planner

Add the optional gather goal between design-source and placement, guarded by the
one-shot flag exactly like pins:

```
... design source satisfied ...
if not collected.get("elements_offered"): return S.ASK_MORE_ELEMENTS
if not collected.get("placement_zone"): return S.ASK_PLACEMENT_ZONE
if not collected.get("pin_offered"): return S.ASK_PIN_ANNOTATION
return S.GENERATING
```

`ADD_ELEMENTS_MODE` is a gate/loop state routed by `advance_state`, so it joins
`GATE_STATES`. Set `collected["elements_offered"] = True` when
`ASK_MORE_ELEMENTS` is first reached (one-shot, mirrors `pin_offered`).

### 3.4 Prompt builder — enumerate elements on the uploaded-asset path

`_design_block` currently, for uploaded assets, appends only
`design_description.summary`. Extend the uploaded-asset branch to enumerate the
same fields the described-design branch already does — `text_elements`
(render exactly as written), `colours`, `imagery`, `style` — so a logo **plus**
gathered text/graphics all reach the model. Skip empty fields (no dangling
labels). The described-design branch is unchanged.

### 3.5 Post-verification collapse (kill the repeat)

`check_verification` (the poll that advances the chat once the emailed link is
clicked) auto-advances through `SEND_PREVIEW_EMAIL` and `SHOW_DESIGN` and lands
directly on `OFFER_REFINE`, emitting **one** combined line:

> "Your email's verified — your design's in your inbox and on-screen now. Want
> to tweak anything, or are you happy with it?"

Implementation: add `SEND_PREVIEW_EMAIL` and `SHOW_DESIGN` to
`AUTO_ADVANCE_STATES` so the existing `while new_state in AUTO_ADVANCE_STATES`
walk collapses them. `EMAIL_VERIFIED` remains the single confirmation state that
`check_verification` words.

**Safety check (verify in plan):** email delivery is decoupled/async in
`services/delivery.py`, gated on verification + a complete real generation, and
is **not** triggered by the `SEND_PREVIEW_EMAIL` conversation state. Auto-
advancing past that state therefore has no delivery side effect. The on-screen
design reveal is gated by `RELEASED_STATES`, which includes `OFFER_REFINE`, so
landing there still reveals the design. Both to be confirmed before coding.

### 3.6 Refinement can add elements

`DESCRIBE_CHANGES` routes the change message through the same element
extraction + `merge_brief` (so "add our team name in gold" updates
`text_elements` before regenerating), while still setting `last_change` /
`change_request` for the raw injection the prompt builder already does. The
`REGENERATING → OFFER_REFINE` loop and the `limits.can_edit()` per-session cap
are unchanged.

### 3.7 Goal-leading replies

The new states' `STATE_PROMPTS` instruct the LLM to (a) acknowledge the specific
element just captured, and (b) steer toward the goal (finish the brief → place →
generate). The existing inline `aside` mechanism (answer a side-question first,
then re-ask the state's question) is reused — no new machinery. Without an LLM
key, `CANNED_REPLIES` gains entries for the two new states.

## 4. Out of Scope / YAGNI

- No full open-brief rewrite of the questionnaire (rejected in favour of the
  gather loop).
- No new frontend components — the new states emit standard `options` chips that
  `ChatPanel` already renders; the design viewer / progress indicator are
  unchanged.
- The gather loop is **not** counted in the "Step X of N" progress path (it is
  optional, exactly like pin annotation).
- No change to email delivery, quote flow, upsell, or the daily design cap.

## 5. Testing

- State machine: new states + transitions; `ADD_ELEMENTS_MODE` self-loop;
  `ASK_MORE_ELEMENTS` decline → placement; `SEND_PREVIEW_EMAIL` / `SHOW_DESIGN`
  auto-advance so verification lands on `OFFER_REFINE`.
- Goal planner: gather goal ordering; `elements_offered` one-shot; already-filled
  slots skipped.
- `merge_brief`: append/de-dupe lists, fill/replace scalars.
- Prompt builder: uploaded-asset path enumerates text/imagery/colours/style;
  empties skipped; described-design path unchanged.
- Orchestrator: `_apply_fields` derives `wants_more_elements` /
  `add_another_element` with and without an LLM key; `DESCRIBE_CHANGES` merges an
  "add" request into the brief.
- Progress: totals unchanged by the optional gather loop.

## 6. Files touched (anticipated)

- `backend/app/services/conversation/state_machine.py` — new states,
  transitions, `AUTO_ADVANCE_STATES`, backtracks.
- `backend/app/services/conversation/goal_planner.py` — gather goal + `GATE_STATES`.
- `backend/app/services/conversation/orchestrator.py` — `_apply_fields` branch
  booleans, one-shot flag, `_public_data`, `DESCRIBE_CHANGES` merge,
  `check_verification` (already collapses via `AUTO_ADVANCE_STATES`).
- `backend/app/services/prompt_builder.py` — `merge_brief` helper (or a small
  `brief.py`), uploaded-asset enumeration.
- `backend/app/prompts.py` — `STATE_PROMPTS` + `CANNED_REPLIES` for the two new
  states; goal-leading wording.
- `backend/tests/` — new/updated tests per §5.
- Frontend: none expected (verify `ChatPanel` renders the new option chips).
