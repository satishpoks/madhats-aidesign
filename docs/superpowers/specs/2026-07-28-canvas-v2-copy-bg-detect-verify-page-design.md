# Canvas v2 — greeting/email copy, background-tick detection, branded verify page

**Date:** 2026-07-28
**Status:** Design, approved for planning

Four independent changes to the v2 canvas flow. Two are copy edits to single
constants. One closes a real gap where the backend cannot see a canvas fact the
customer has already expressed. One brings the last unbranded customer-facing
surface into line with the per-store branding work.

They share no state and can be implemented and tested independently.

---

## 1. Greeting copy

**File:** `backend/app/prompts.py` — `V2_ASK_NAME` (~line 1130)

Replace with:

```
Welcome! I'm {persona}, your design assistant. I'll help bring your cap design
to life. May I please know your name?
```

`{persona}` is already the sole format key on this constant; nothing else
changes. `V2_ASK_NAME_RETRY` is untouched.

**Register note (accepted, not a blocker).** The rest of the v2 copy avoids
exclamation marks — `V2_ACK_PROMPT` explicitly instructs the model "no
exclamation marks" — and this line reintroduces one. This is the owner's
wording and ships as written. It is recorded here so a later reader does not
"fix" it back.

`test_v2_copy_guards.py` covers `V2_ASK_NAME`; the new text trips neither the
`_CASUAL` list nor the "under the cap" pin.

---

## 2. Email-step copy

**File:** `backend/app/services/conversation/canvas_steps.py` — `ASK_EMAIL.ask`
(~line 528)

Replace with:

```
Great job, {name}. Please enter your email address so I can save your design,
provide you a reference code and send you your artwork and quotation.
```

`{name}` is already available to every registry `ask` string. The draft's
"Great Job Ric" was resolved with the owner as the **customer's** name, not the
persona's — Ricardo is the bot, and a bot praising itself reads wrong.

**Forward-promise note.** This step now promises a reference code, but
`leads.reference_code` is minted later, at `REQUEST_QUOTE`. The promise is
accurate about the outcome and only inaccurate about the timing, which the
customer cannot observe. No code change follows from it. Do not "fix" this by
minting the code early — the code is the quote-request tracking reference and
minting it before the design is finalised would create references for abandoned
sessions.

No other field on the step changes: `slots`, `apply=_apply_email`,
`direct_answer=_direct_email` and the `done_when` all stay exactly as they are.
In particular the `done_when` early-skip logic is load-bearing and untouched.

---

## 3. Auto-detect a manually-ticked "Remove background"

### The problem

`removeBg` is a field on a canvas element in the frontend `canvasStore`. The
canvas blob is not persisted until finalize, so during the design phase the
backend has **no way to observe it**. A customer who ticks the toggle in the
Adjust panel themselves is then asked `ASK_LOGO_BG` — "Does your logo have a
background that needs removing?" — as though they had not. That is the reported
bug: "it didn't recognise that I ticked remove background".

Note this is the mirror image of the existing `_ops_logo_bg` path, which
already solves the *other* direction (chip tap → backend tells the frontend to
tick). What is missing is the read.

### Mechanism — a one-way read on the Done turn

Chosen over a live "fire on tick" call. The tick is only actionable at one
moment (when `ASK_LOGO_BG` would be asked), a turn already exists at exactly
that moment, and a silent mid-step call would introduce a race with whatever
turn is in flight. Rejected: "both", as pure redundancy.

**Frontend** — `frontend/src/store/chatStore.ts`, `sendMessage`.

`sendChat(sessionId, message, canvasDesign?)` (`lib/api.ts:78`) already accepts
a canvas blob; `sendMessage` currently passes one only at `describe_changes`
(`chatStore.ts:197-200`). Widen that condition to also include `logo_adjust` —
the state the customer is in when they press **Done** to close logo placement.

No other state sends a canvas. Keep this narrow: it mirrors the deliberate hard
scoping on `_persist_live_canvas_design` (`chat.py:31-53`), which exists so a
stray or hostile design blob on an unrelated turn cannot overwrite work.

**Transport** — `backend/app/api/routes/chat.py`.

`_dispatch(session_id, message)` does not currently carry `body.canvas_design`;
only `_persist_live_canvas_design` sees it, and that writes to the DB solely at
`describe_changes` / `rework_canvas`. Thread the blob through:

- `_dispatch(session_id, message, canvas_design=None)`
- → `handle_message_v2(session_id, message, canvas_design=None)`

**v1 `handle_message` is not passed the blob and its signature does not
change.** v1 is the retained backup path and stays byte-identical.

**Backend logic** — `backend/app/services/conversation/canvas_steps.py`.

A new pure function, declared next to the logo steps it serves:

```python
def observe_canvas(collected: dict, canvas_design: dict | None) -> bool:
    """Read a manually-ticked background removal off the live canvas.

    Returns True if it wrote pending_logo["bg"] = "removed" on this call.
    """
```

Behaviour:

1. Return `False` unless there is a pending logo with a `face` and no `bg` yet.
   (Already answered means already routed — never overwrite.)
2. Find the **last unlocked element of type `image`** on that face. This is the
   identical anchor `canvasStore.lockPlaced` and `patchPendingLogo`
   (`canvasStore.ts:188-192`) use, and for the identical reason: the backend has
   no element id, because `canvas_design` is only written at finalize.
   `toCanvasDesign()` returns `{ colourway, faces }` with `locked` and
   `removeBg` intact on each element, so the rule is directly applicable.
3. If that element has truthy `removeBg`, set `pending_logo["bg"] = "removed"`
   and return `True`. Otherwise return `False`.

Pure over plain dicts — no DB, no I/O, no model call — so it is testable in
isolation, consistent with the rest of the registry.

**Wiring** — `backend/app/services/conversation/orchestrator_v2.py`.

Call `observe_canvas` once per turn, **after** the current step's `apply` has
run and **before** `next_step` is resolved. After-`apply` matters: on the Done
turn `_apply_logo_placed` is what marks the logo placed, and running the
observation first would be reading against a half-applied state.

The write satisfies `ASK_LOGO_BG.done_when` (`"bg" in _pending(c)`), so
**first-unmet routing skips the step by itself**. No new branch, no back-edge,
no special case in the router. The registry stays a pure function of
`collected`.

### Acknowledgement

New constant in `prompts.py`:

```python
V2_BG_ALREADY_REMOVED = (
    "I can see you've already removed the background on that logo, so I'll "
    "skip that question."
)
```

When `observe_canvas` returns `True`, prepend it to the reply for that turn —
in front of the next step's copy, in the same concatenate-verbatim style the
tool tips use. It never passes through a model.

It must be added to `_v2_copy_strings()` in `test_v2_copy_guards.py` so it is
held to the same register and toolbar-position rules as every other v2 string.

### Scope boundaries

These are deliberate limits, not omissions:

- **Not ticked at Done → ask the question, exactly as today.** Absence of a tick
  is silence, not a "no".
- **Never unticks.** `observe_canvas` only ever writes `"removed"`. It cannot
  write `"none"`, and it cannot overwrite an existing `bg` value.
- **Per logo.** `_apply_another_logo` re-seeds `pending_logo`, so each pass of
  the logo loop is judged on its own canvas state.
- **`tool="upload"` on `ASK_LOGO_BG` is unaffected.** When the step *is* asked
  it still hands over the upload tool, which is what keeps the placed logo
  unlocked and selectable so the toggle is reachable at all
  (`Surface.tsx:111-113`, `canvasStore.ts:36`). That constraint is unchanged;
  this change only affects whether the step is reached.

### Tests

- `observe_canvas` unit tests over plain dicts: ticked → writes + returns True;
  unticked → no write; `bg` already set → no overwrite; no pending logo → False;
  malformed/missing blob → False, no raise; a *locked* ticked image is ignored
  (it belongs to a previous logo).
- Orchestrator test: a Done turn carrying a ticked canvas lands on the step
  *after* `ASK_LOGO_BG`, and the reply contains `V2_BG_ALREADY_REMOVED`.
- Orchestrator test: a Done turn with no tick still lands on `ASK_LOGO_BG`.
- Frontend `chatStore` test: the canvas blob is sent at `logo_adjust` and is
  *not* sent at an unrelated state.

---

## 4. Branded verification pages

### The problem

`VERIFICATION_SUCCESS_HTML` and `VERIFICATION_ERROR_HTML` (`prompts.py:871`,
`:901`) hardcode `#ff5c00` and a "MAD HATS / AI Design Studio" header. Every
other customer-facing surface — the studio, the preview email, the verification
email, the resume email — themes per store off `stores.brand`. These two pages
were missed by that work, so a branded store's customer clicks a themed email
and lands on a MadHats-orange page.

### Changes

**`backend/app/prompts.py`** — convert both constants to `string.Template`
shells taking `$store_name`, `$primary_colour` and `$logo_html`, structurally
matching `BRANDED_EMAIL_HTML` (`prompts.py:615`).

`Template` (not `.format()`) for the same reason `BRANDED_EMAIL_HTML` uses it:
these are HTML/CSS blobs and `.format()` would choke on literal braces.

`VERIFICATION_ERROR_HTML` keeps its existing `{message}` slot — it becomes
`$message` under `Template`, and `_error_page`'s call site updates with it.

**`backend/app/api/routes/leads.py`** — `confirm_verification` resolves the
session's store and renders the **success** page through it. (`_error_page` is
unchanged apart from the `Template` call-site update — see the error-page note
below.)

The route already has everything it needs: it fetches `lead` at line 117 and
`session_id` at 118. Store resolution follows the existing pattern verbatim
(`leads.py:206-216`):

```python
store = None
if store_id:
    from app.services.stores import get_store
    store = get_store(store_id)
store_name = (store or {}).get("name") or "MadHats"
primary_colour = ((store or {}).get("brand") or {}).get("primary_colour") or "#ff5c00"
```

**Crash-safety is mandatory here.** Branding must never turn a successful
verification into an error page — the verification itself has already been
committed to the database by the time the page renders. Wrap the resolution so
any failure falls back to MadHats defaults, matching how
`_maybe_send_resume_email` already treats store resolution as best-effort.

**Logo.** Emails inline the logo as a CID attachment; a web page cannot. Use
the `/media` proxy URL from `branding.public_brand`, which is the allow-listed
customer-safe subset and never exposes `watermark_asset_url`. If there is no
logo, `$logo_html` falls back to the store name as text — the same fallback
`StoreHeader.tsx` uses.

**Error page — always renders on the MadHats defaults.** Its shell becomes a
`Template` for consistency with the success page, but no branch feeds it a
store.

Two of the three error branches *cannot* resolve one: an expired or malformed
token is rejected before any lead is loaded (`leads.py:90-95`). The third —
already-used (`leads.py:108-111`) — is after the token decode, so it could look
up the lead and theme itself, but that is a DB round-trip added solely for
branding on a dead-end page. Not worth it.

The consequence, stated plainly so nobody is surprised later: a branded store's
customer clicking an expired link still sees MadHats orange. Accepted.

### The close message

**No Close button** — owner decision, taken after this was raised: browsers
block `window.close()` on a tab the user opened themselves, which is exactly
what clicking an email link does, so the button would silently do nothing on
most desktop browsers.

Instead the existing line (`prompts.py:891`) is promoted from trailing body
text to a **highlighted callout**: a tinted panel with a left border in
`$primary_colour`, placed above the body copy.

```
You can close this page now and head back to the chat.
```

Inline styles only, consistent with the rest of these documents.

### Tests

- Success page renders a configured store's name and primary colour, and does
  not contain `#ff5c00` or "MAD HATS".
- An unconfigured store (or no store) renders the MadHats lockup and
  `#ff5c00` — i.e. **branding is a no-op** for a store that has configured
  none.

  Note this is deliberately *weaker* than the "byte-identical to before" bar
  the per-store branding work held itself to, and it has to be: the highlighted
  callout is new copy for **every** customer, branded or not. Byte-identical to
  today's page is not achievable and not wanted. The default header block must
  still be a **literal** ("MAD HATS" / "AI Design Studio"), never derived from
  `store_name` — `"MadHats".upper()` is `"MADHATS"`, with no space, which is
  the exact trap `email.py:205` already documents.
- A store lookup that raises still returns HTTP 200 with the default-themed
  success page, and the verification is still committed.
- The close message is present on the success page.
- Error page renders with its message on the defaults.

---

## Out of scope

Named so a reader does not expect them:

- **The v2 resume gap.** Reloading a v2 canvas session mid-design does not
  rehydrate the `canvas` directive, so the customer gets v1's whole-rail lock.
  Pre-existing, untouched here.
- **No in-chat "resend the link"** affordance at the verification gate.
  Pre-existing, untouched here.
- **`VERIFICATION_EMAIL_BODY` / `RESUME_EMAIL_BODY` body text** still says
  "MadHats" while their shell is themed. Known deferred ticket; this change
  covers the landing pages only.
- **v1 (`orchestrator.py`) is not modified by any of the four changes.**
