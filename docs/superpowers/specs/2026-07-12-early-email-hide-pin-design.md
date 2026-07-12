# Early email capture + hide pin placement — design

> Date: 2026-07-12
> Scope: conversation flow (backend state machine + orchestrator + prompts,
> frontend chat store + panel). No changes to generation, delivery gating, or
> the email/verification mechanism itself.

## 1. Goal

Two changes to the Ricardo conversation flow:

1. **Hide the pin-point placement step** (the "drop a pin on the cap" flow) —
   remove it from the flow *for now*, without deleting the code, so it can be
   switched back on later.
2. **Ask for the email earlier** — right after the customer provides their
   design source (logo upload or design description), framed as *"this saves
   your progress"* — instead of only at the very end during generation. The ask
   is **non-blocking**: verification is sent as it is today, the conversation
   keeps going into the per-element deep-dive, and delivery still happens in the
   background once the email is verified AND generation is complete.

## 2. Current flow (relevant slice)

```
… ASK_HAS_LOGO
     ├─ UPLOAD_LOGO ─(→ ASK_REMOVE_BG)─┐
     └─ DESCRIBE_DESIGN ───────────────┤ seeds pending_element
                                        ▼
                                 ELEMENT_DEEPDIVE (loop)
                                        ▼
                                 ASK_MORE_ELEMENTS
                                        ▼
                                 ASK_PIN_ANNOTATION → PIN_ANNOTATE_MODE   ← hide
                                        ▼
                                 GENERATING  (asks email + triggers generation)
                                        ▼
                                 VERIFY_EMAIL (rests; frontend polls)
                                        ▼
                    EMAIL_VERIFIED → SEND_PREVIEW_EMAIL → SHOW_DESIGN → OFFER_REFINE
```

`GENERATING` today does two jobs: it asks for the email *and* triggers async
generation, and it advances to `VERIFY_EMAIL` only when the customer types their
email on that turn.

## 3. Target flow

```
… ASK_HAS_LOGO
     ├─ UPLOAD_LOGO ─(→ ASK_REMOVE_BG)─┐
     └─ DESCRIBE_DESIGN ───────────────┤ seeds pending_element
                                        ▼
                          SAVE_PROGRESS_EMAIL   ← NEW, once, non-blocking
                          (capture email + send verification, then continue)
                                        ▼
                                 ELEMENT_DEEPDIVE (loop)
                                        ▼
                                 ASK_MORE_ELEMENTS
                                        ▼
                                 GENERATING  (triggers generation only)
                                        ▼   (advance_after_generation, after gen settles)
                                 VERIFY_EMAIL ──(already verified?)──► collapse to OFFER_REFINE
                                        ▼ (not yet)
                    EMAIL_VERIFIED → SEND_PREVIEW_EMAIL → SHOW_DESIGN → OFFER_REFINE
```

Pin states (`ASK_PIN_ANNOTATION`, `PIN_ANNOTATE_MODE`) become unreachable but
remain in the codebase.

## 4. Design decisions

### 4.1 Hide pin (reversible)

- `goal_planner.next_goal`: delete the step-6 block that returns
  `ASK_PIN_ANNOTATION` when `pin_offered` is unset. Once elements are offered,
  fall straight through to `GENERATING`.
- `state_machine.advance_state`, `ASK_MORE_ELEMENTS` branch: drop the
  `pin_offered` check — when there is no pending element, go to `GENERATING`.
- Keep the enum members, `TRANSITIONS`/`ALLOWED_BACKTRACKS` entries, the
  `PinAnnotator` component, the `pin_annotate_mode` UI branch, and the `/pins`
  route untouched. Reversal = re-add the two routing lines.

### 4.2 Early email = new dedicated state `SAVE_PROGRESS_EMAIL`

A **separate** state (not a reuse of `ASK_EMAIL`) so the early "return to the
questionnaire" routing and the terminal "go to verify" routing never collide
inside `advance_state`.

- New enum value `SAVE_PROGRESS_EMAIL = "save_progress_email"`.
- **Goal-planner-routed** (NOT in `GATE_STATES`). Inserted in
  `goal_planner.next_goal` *before* the `pending_element` deep-dive check:

  ```python
  # Early email checkpoint — once a design source exists, capture the email
  # (saves progress) exactly once, then fall through to the deep-dive.
  if (collected.get("pending_element") or collected.get("elements")) \
          and not collected.get("email_prompt_shown"):
      return S.SAVE_PROGRESS_EMAIL
  ```

- One-shot: the orchestrator sets `collected["email_prompt_shown"] = True` when
  it lands on `SAVE_PROGRESS_EMAIL` (mirrors the existing `elements_offered` /
  `pin_offered` one-shot flags).
- **Capture:** extend the orchestrator's inline email-capture condition from
  `current in (GENERATING, ASK_EMAIL)` to also include `SAVE_PROGRESS_EMAIL`.
  A usable email → `capture_lead_and_verify` (sends the verification link,
  unchanged) → `email_captured = True`.
- **Routing after it:** `SAVE_PROGRESS_EMAIL` is goal-routed, so on the next
  turn `_route` calls `goal_planner.next_goal`, which now skips
  `SAVE_PROGRESS_EMAIL` (`email_prompt_shown` set) and returns the deep-dive.
  Whether or not a usable email was given, we proceed — **non-blocking, no
  dead-end.** If no email was captured, the terminal fallback (§4.3) covers it.
- **Message** (`prompts.py`, both `STATE_PROMPTS` and `CANNED_REPLIES`):
  *"What's the best email for you? I'll save your progress so you can pick this
  design back up anytime — and send the finished design across when it's ready."*
- **`_public_data`:** free-text state (email typed in), so return `{}` (no
  chips, no `continuable`) — same treatment as `ASK_EMAIL`.

### 4.3 `GENERATING` advances itself: `advance_after_generation`

`GENERATING` no longer asks for the email in the common case, so it needs a
nudge to move on once generation settles. Mirror the existing regeneration
pattern.

- **Backend** `orchestrator.advance_after_generation(session_id)`:
  - No-op (`reply=None`) unless the session is at `GENERATING`.
  - `new_state = advance_state(GENERATING, collected)`:
    - `email_captured` True → `VERIFY_EMAIL`.
    - `email_captured` False → `ASK_EMAIL` (terminal fallback ask — today's
      behaviour, advanced by the customer's email turn).
  - If `new_state is VERIFY_EMAIL` **and** `collected["email_verified"]` (they
    clicked the link during the deep-dive): collapse through
    `EMAIL_VERIFIED → … → OFFER_REFINE` and use the existing collapsed ack
    (*"Your email's verified — your design's in your inbox and on-screen
    now."*), reusing the same logic as `check_verification`.
  - Otherwise word the reply for `new_state` normally (verify reminder, or the
    fallback email ask) and persist. Append only Ricardo's line (no phantom
    user turn), same as `check_verification` / `advance_after_regeneration`.
- **Route:** add `POST /chat/{session_id}/advance-generation` (alongside the
  existing verify/regeneration poll routes).
- **Frontend:**
  - `chatStore.advanceGeneration(sessionId)` — mirrors `advanceRegeneration`
    (calls the new endpoint, appends the reply if non-null).
  - In `ChatPanel`, chain it after generation settles:
    `startGeneration(sessionId).then(() => advanceGeneration(sessionId),
    () => advanceGeneration(sessionId))` — success or failure, so the customer
    is never stranded at `generating` (same guarantee as regeneration).
  - `startGeneration` stays once-guarded per session.

### 4.4 `GENERATING` message

`GENERATING`'s copy no longer asks for the email (it's captured earlier).
Reword `STATE_PROMPTS["generating"]` / `CANNED_REPLIES["generating"]` to just:
*"Putting your design together now — I'll pop it in your inbox and on-screen the
moment it's ready."* The rare no-email-captured path still gets a proper ask via
the `ASK_EMAIL` fallback that `advance_after_generation` routes to.

## 5. Edge cases

- **Customer clicks verify link during the deep-dive** → `email_verified` flips
  in the DB (leads route, unchanged). We don't act on it mid-gather. At the end,
  `advance_after_generation` sees it and collapses straight to `OFFER_REFINE`.
- **Customer never gives an email early** → `email_prompt_shown` set, flow
  proceeds; `advance_after_generation` routes `GENERATING → ASK_EMAIL`; the
  existing terminal capture + `VERIFY_EMAIL` path takes over. No delivery
  without an email — customer's choice.
- **Customer types a design detail at `SAVE_PROGRESS_EMAIL`** instead of an
  email → the per-turn interpreter still extracts volunteered fields, so nothing
  is lost; no email captured, flow proceeds.
- **Resume/hydrate** → `email_prompt_shown` persisted in `collected`, so the
  early ask never repeats on reload.
- **Progress counter** → `_progress_path` currently ends at `ASK_EMAIL`. Add
  `SAVE_PROGRESS_EMAIL` to the path (replacing the terminal `ASK_EMAIL` slot as
  the email step) so "Step X of N" stays accurate; `ASK_EMAIL` remains a
  post-question fallback.

## 6. Out of scope / unchanged

- Generation timing (still at the end, full design first), delivery gating,
  verification token mechanism, email templates, the pin backend route and
  component (dormant, not deleted).

## 7. Test impact

- Backend: state-machine routing tests (pin no longer reached; new early-email
  transition), goal-planner tests, orchestrator tests for `SAVE_PROGRESS_EMAIL`
  capture + non-blocking continue, new `advance_after_generation` tests
  (verified / not-verified / no-email branches), progress-counter test.
- Frontend: chat store `advanceGeneration`, `ChatPanel` generation-settle chain.
- Update any test asserting the old pin step or the old `GENERATING`
  email-ask copy.
