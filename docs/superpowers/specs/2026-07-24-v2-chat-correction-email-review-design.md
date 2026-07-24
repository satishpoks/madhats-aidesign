# v2 Canvas Chat — Correction, Early Email, Pre-Submit Review — Design

**Date:** 2026-07-24
**Status:** Approved (design), pending spec review
**Scope:** v2 canvas conversation only (`CANVAS_ORCHESTRATOR_V2=true` + `flow_mode=="canvas"`). v1 and every non-canvas flow are untouched.

---

## 1. Problem

Three gaps surfaced in the live v2 canvas chat:

1. **No way to correct a mistake mid-chat.** A customer who taps the wrong chip (wrong quantity, wrong face, wrong decoration method) has no way back — the flow only moves forward. They asked for "a back-one-step / resend / correction affordance so mistakes can be fixed immediately."
2. **Email is captured too late and too bluntly.** It sits near the end of the flow (registry index 14, after the decoration method). The intended behaviour — and the PRD's canonical flow (§7.1, FR-04, US-09) — is to grab the email *mid-design, non-intrusively*, "while I'm putting the design together", so it doesn't feel like a data-mine. **Confirmed placement: right after the customer places their first design element**, phrased humbly and smoothly.
3. **No pre-submit review.** The customer submits the quote request straight after `purpose`, with no prompt to check their design across all four views first. They want: *"please recheck all views and confirm your design is as required, or let me know if you want to rework something"* before the quote is sent.

All three are changes to the **backend-orchestrated** registry. The canvas remains the only frontend-owned surface; every new step drives the UI through the existing `canvas` directive.

---

## 2. Architecture context

v2 is registry-driven (`services/conversation/canvas_steps.py`):

- `REGISTRY` is a tuple of `Step` records. Routing is **first-unmet resolution** — `state_machine_v2.next_step` returns the first step whose `done_when(collected)` is False. Pure function of `collected`.
- Chips carry both label and the fields they mean; a chip tap resolves deterministically (0 model calls). Free text goes to the Haiku interpreter, which fills **slots only** and never names a state. `validate_fields` drops anything outside `WRITABLE_SLOTS`.
- `merge_fields` keeps answered steps answered: the one write that can un-answer a settled step (truthy→falsy) is allowed **only** for the step that asked for that slot.
- Loops are slot-clearing (the logo loop is `logos` + `pending_logo`; `_apply_another_logo` re-seeds/clears so first-unmet walks back on its own — no back-edges).
- Every v2-owned step emits a `canvas` directive (`state_machine_v2.canvas_directive`) that the frontend (`DesignStudio/Surface.tsx`) consumes to gate tools, switch faces, and show the Done button.
- Load-bearing invariant: `FINALIZE_CANVAS` is unreachable without `email_captured`, because `ask_email` precedes it and only `_apply_email` sets that flag.

Relevant placement signals (already in `collected`):
- Logo placed: `_pending(c).get("placed")` (set at `LOGO_ADJUST`), later banked into `logos` at `ASK_ANOTHER_LOGO`.
- Text/shape placed: `decor_placed` (set at `DECOR_ADJUST`).

---

## 3. Feature 1 — Email moves to right after the first element

### Behaviour
`ask_email` fires the moment the customer places their **first design element** (logo, text, or shape) and email is not yet captured — and never before any element exists.

### Design
- **Reposition** `ask_email` from index 14 to **immediately after `ASK_LOGO_BG`, before `ASK_ANOTHER_LOGO`**. Combined with the conditional `done_when` below and first-unmet-scans-from-top, this single position is correct on both paths:
  - *Logo path:* first logo placed (`LOGO_ADJUST`) and its background handled (`ASK_LOGO_BG`) → email fires before the "add another logo?" branch.
  - *Text-only path:* the logo steps short-circuit (`logos_done`), so first-unmet reaches the email step with no element yet → it skips → `ASK_ADD_DECOR` → first text/shape placed (`DECOR_ADJUST`) → first-unmet re-scans from the top → email fires.
- **Make it conditional:**
  ```python
  done_when = lambda c: bool(c.get("email_captured")) or not _has_first_element(c)
  ```
  with
  ```python
  def _has_first_element(c: dict) -> bool:
      return (bool(c.get("logos"))
              or bool(_pending(c).get("placed"))
              or bool(c.get("decor_placed")))
  ```
  Same conditional-skip pattern `ask_decoration_mix` already uses. Before any element it is "satisfied" (skipped); once an element exists and email is uncaptured, first-unmet returns it. Because first-unmet always scans from the top, one early registry position covers **both** the logo path and the text-only path.
- **Copy** (humble, in-context, no wait / no data-mine tone):
  > "Love where this is going, {name}. While you keep designing, could I grab your email so I can save your progress and send you the finished design? — [type your email]"
- The double opt-in is unchanged (`_apply_email` → `capture_lead_and_verify`), just earlier; `V2_EMAIL_VERIFY_NOTICE` still explains the verification link as it goes out.

### Preserved invariants
- `email` stays a writable slot of `ask_email`; `email_captured` is set only by `_apply_email` and is not writable, so the interpreter still cannot fake it.
- `ask_email` still precedes `FINALIZE_CANVAS` (early index < finalize), so a design can never be produced for an uncaptured lead.
- A volunteered early email (before any element) is captured by `_apply_email`; the step's `done_when` is then satisfied and skipped — no double-ask.

### Ripple (in-scope decision)
The prior v2 assumption — "email is at the end, so the customer verifies while watching the render" — no longer holds. Resume-email remains **suppressed for v2** in this batch (`_maybe_send_resume_email` early-returns for v2 canvas). Delivery is still gated on verified + design-ready, so nothing regresses. Re-enabling a v2 resume email for early-email abandonment is a **noted follow-up**, out of scope here.

---

## 4. Feature 2 — "↩ Back" to correct the last answer

### Behaviour
A "↩ Back" control lets the customer undo their immediately-previous answer and be re-asked it. One level per press; repeatable. Hidden when there is nothing to go back to.

### Design (stateless — matches "routing is a pure function of collected")
- New pure helper `state_machine_v2.last_answered_step(collected, config=None)`:
  the highest-index step **before** the current first-unmet step whose *writable* slots, when cleared, flip its `done_when` to False. Returns that `Step`, or `None` if there is nothing to undo.
- New handler `orchestrator_v2.handle_back(session_id)`:
  1. Load session/collected.
  2. `target = last_answered_step(collected)`. If `None`, no-op (return the current step unchanged).
  3. Clear `target`'s writable slots from `collected` (the one legitimate slot-clearing gesture — a guarded handler, not the interpreter).
  4. Persist, then return the re-asked step via the normal `reply_for` / `public_data_for` / directive path.
- **Endpoint:** `POST /chat/{session_id}/back` (dedicated; not the message endpoint, so it never reaches the interpreter). Dispatched only for v2 canvas sessions; a non-v2 / non-canvas session returns 400 or a no-op (Back is a v2-canvas affordance).

### Bounds (deliberate)
- Targets the **question** steps (quantity, decoration, `decor_face`, `needed_by`, `purpose`, `another_logo`, …) where a wrong chip is the real pain.
- **Cannot un-capture a verified email:** `email_captured` is not a writable slot, so `ask_email` is never a Back target. This falls out of the existing writable-slot guard — no special-casing.
- **Not shown at the first real step** (`ask_name`) — nothing precedes it.
- **Canvas placements are not deleted by Back.** The canvas is already directly editable; Back re-asks the *question*, it does not remove a placed element. (A Back onto a placement step re-asks "place your…"; the element stays on the canvas for the customer to adjust.)
- **Loops:** Back clears the last loop slot (e.g. `another_logo`) and first-unmet re-asks it, consistent with the existing slot-clearing loop mechanism.

### Frontend
- A small "↩ Back" affordance beside the chip row in the v2 chat, calling `POST /chat/{id}/back` and applying the response like any chat turn.
- Shown only when `data.can_go_back === true` (backend sets it from `last_answered_step(...) is not None`).

---

## 5. Feature 3 — Pre-submit "recheck your views" review step

### Behaviour
Immediately before `REQUEST_QUOTE`, the customer is asked to check their design across all views and either confirm or rework.

### Design
- New `ConversationState.REVIEW_DESIGN` + `Step` record inserted immediately **before** `REQUEST_QUOTE` in `REGISTRY`.
  - Copy: *"Before I send this to our team — take a moment to look over your design across all the views. Happy with it, or would you like to rework anything?"*
  - Chips: `Chip("Looks great, send it", {"design_confirmed": True})`, `Chip("I'd like to rework it", {"design_rework": True})`.
  - `slots = ("design_confirmed", "design_rework")`.
  - `apply = _apply_review` — on `design_rework`, set a rework flag consumed by the canvas directive and clear `design_confirmed`; on confirm, clear `design_rework`.
  - `done_when = lambda c: bool(c.get("design_confirmed"))`.
- **Canvas directive:** `REVIEW_DESIGN` normally emits an all-faces, tools-locked "review" directive (customer can flip through views, not edit). When `design_rework` is set, the directive **unlocks all tools** (`unlockAll()` from workstream A) and shows a Done button.
- **Rework loop (backend-orchestrated, no re-render):** "I'd like to rework it" → directive unlocks the canvas → customer edits → "Done" sends the updated `canvas_design` with the turn (the same way describe-turns already send it), the backend persists it and clears `design_rework`/`design_confirmed`, and re-emits the `REVIEW_DESIGN` directive so the customer lands back on the review. `canvas_design` is not flattened/finalized here — flatten + finalize still happen once, at `FINALIZE_CANVAS`, after the quote is confirmed. No AI render (the photoreal render is admin-triggered post-quote, Workstream C). Every state transition is owned by the backend; the frontend only renders/edits the canvas per directive.
  - *Persistence:* extend the existing `chat.py::_persist_live_canvas_design` (today scoped to `describe_changes`) to also adopt a well-formed `canvas_design` sent on a `REVIEW_DESIGN` rework-Done turn, so an abandon mid-rework keeps the latest edits.

### Progress
`REVIEW_DESIGN` gets a progress position immediately before `REQUEST_QUOTE`; `REQUEST_QUOTE`/`FINALIZE_CANVAS` remain progress-anchored so the counter reads as final.

---

## 6. Final flow

```
name → intro
     → [ has_logo?
         → logo loop (place → bg → another?)      ← EMAIL fires right after the FIRST placement
         → decor loop (add? → place → anything else?) ]
     → quantity → decoration → (decoration_mix?)
     → when-needed → purpose
     → REVIEW_DESIGN  (confirm / rework→canvas→Done→REVIEW_DESIGN)
     → request-quote → finalize
```

`↩ Back` is available on the question steps throughout (not a position in the flow — a cross-cutting affordance).

---

## 7. Testing

- **Backend (pytest, `CANVAS_ORCHESTRATOR_V2=false` baseline stays green):**
  - Email: conditional `done_when` — skipped with no element, asked after first logo placement, asked after first decor placement (text-only path), skipped once captured, volunteered-early email captured-and-skipped. Invariant test: no flow reaches `FINALIZE_CANVAS` without `email_captured` (extend the existing exhaustive permutation guard).
  - Back: `last_answered_step` returns the correct target for representative `collected` states (question step, loop step, first step→None); `handle_back` clears exactly the target's writable slots and re-asks; Back never targets `ask_email`/`email_captured`; Back at `ask_name` is a no-op.
  - Review: `REVIEW_DESIGN` routes after `purpose` and before `request_quote`; confirm advances; rework sets the flag + directive unlocks; registry-order + progress-position coupled tests updated.
  - e2e chip-label walk (`test_v2_e2e`) updated for the new order (email early, review before quote) and driven with the interpreter unavailable, proving chips need no model.
- **Frontend (targeted `vitest run` only — full run stalls on this Windows host):**
  - Back control renders only when `can_go_back`, calls the endpoint, applies the response.
  - `REVIEW_DESIGN` directive: review (locked) vs rework (unlocked) tool gating in `Surface.tsx`.

---

## 8. Out of scope / follow-ups

- Re-enabling a v2 resume email for early-email mid-design abandonment (suppression kept this batch).
- Back deleting canvas elements (canvas edits are handled on the canvas; Back re-asks the question only).
- Multi-level "edit any earlier answer" jump-back UI (Back is one-level, repeatable).
- Voice-input specifics (unchanged).

---

## 9. Coupling & sequencing

All three features touch `canvas_steps.py` and `state_machine_v2.py`, so this is **one spec implemented sequentially** (not parallel worktrees — they would conflict). Suggested order: (1) email reposition, (2) review step, (3) Back — Back's `last_answered_step` should see the final registry order. Coupled declaration sites (registry order, `_PROGRESS_PATH`, `_SLOT_DOCS`, `WRITABLE_SLOTS`, the `satisfy` test helper, e2e walk) are updated in lockstep, as the existing guard tests enforce.
