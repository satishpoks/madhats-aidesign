# Canvas Adjust panel + v2 copy pass — design

**Date:** 2026-07-26
**Status:** approved (design), pending implementation plan
**Scope:** frontend `DesignStudio` layout, backend v2 canvas copy (`prompts.py`,
`canvas_steps.py`, `state_machine_v2.py`)

---

## 1. Problem

Three reported problems, one root cause between the first two.

1. **The element adjustment toolbar is invisible on small screens.**
   `SelectedToolbar` renders *below* `CanvasStage` inside the centre column of
   `Surface.tsx` (`Surface.tsx:299-306`), and that column is a scroll container
   (`overflow-auto`). On a phone the chat already occupies 45vh
   (`CustomiseStudio/index.tsx:27`), so the cap fills what remains and the
   toolbar sits under the fold. A customer who selects an element sees nothing
   happen.

2. **Nothing tells the customer the panel exists.** The v2 tool tips point at
   "the toolbar under the cap" (`prompts.py:1093`, `1097`, `1110`) — which is
   both easy to miss and, after this change, factually wrong.

3. **The v2 chat copy is too casual** for the brand ("Pop your logo on there",
   "Love where this is going!").

Plus one new requirement:

4. **The final stage does not say what the customer receives.**
   `REQUEST_QUOTE` (`canvas_steps.py:733-741`) says the team "will put together
   a quote and get back to you" — it never says the finished design comes with
   it, or that the flagged logo background will be knocked out.

## 2. Non-goals

- No change to `delivery.py`'s quote gate, `maybe_send_quote_confirmation`, or
  the admin render endpoint. The design is still not auto-emailed (see §7).
- No change to the v1 (non-canvas) conversation, its copy, or the shared tail
  states — `flow_mode`-gated and out of scope.
- No new client-side image processing. "Remove background" remains a mark, not
  an edit (the standing constraint in CLAUDE.md).
- No layout change to `CustomiseStudio`'s split (canvas / chat) itself.

---

## 3. Adjust panel — placement

`SelectedToolbar` moves **above** `CanvasStage` in the centre column of
`Surface.tsx`, wrapped in a `sticky top-0 z-20` container. The centre column is
already the scroll container, so `sticky` pins the panel to the top of the
canvas area on every viewport — including the squeezed mobile case that caused
the report.

Same position on desktop and mobile: one code path, one thing for the chat copy
to describe, no responsive divergence to test.

Two accepted consequences, named here so they are not rediscovered as bugs:

- **Layout shift on select.** The panel mounts only when an element is selected
  (`SelectedToolbar` returns `null` otherwise, `SelectedToolbar.tsx:13-14`), so
  the cap shifts down at that moment. This is accepted — the panel appearing at
  the top *is* the signal. No reserved placeholder: it would permanently consume
  the scarce mobile height the change exists to reclaim.
- **Tall panel on narrow widths.** The controls wrap to several rows. The
  controls region therefore gets `max-h-[45vh] overflow-y-auto`: the coloured
  header stays pinned, the controls scroll within themselves, and the cap can
  never be pushed entirely off-screen.

### Selection remains reachable

The gating that decides whether the toolbar mounts at all is unchanged
(`(isV2 ? v2Editing : unlocked) && <SelectedToolbar />`). In particular
`ask_logo_bg` keeps `tool="upload"` so `v2Editing` stays true and the placed
logo stays selectable — the existing load-bearing behaviour documented on that
step (`canvas_steps.py:513-518`). This work must not disturb it.

## 4. Adjust panel — appearance

`SelectedToolbar` becomes a titled panel:

- **Header row:** solid `bg-accent text-white`, reading `Adjust — Text`,
  `Adjust — Image`, `Adjust — Shape` or `Adjust — Drawing`, keyed off
  `el.type`.
- **Body:** existing controls on `bg-surface`, panel outlined `border-accent`.

`bg-accent` resolves to `var(--brand-primary, #FF5C00)` (per-store branding, set
on `:root` by `brandStore`), so the panel themes per store for free.

This is deliberately louder than the existing directive callout
(`Surface.tsx:286-290`, `accent/5` fill + `accent/40` border) so the two read as
distinct elements rather than one block.

**Consequence for copy:** a themed store is not orange, so no copy may name a
colour. Copy refers to "the highlighted **Adjust** panel above the cap".

## 5. Chat points at the panel

Every reference to the toolbar's old position is corrected, and each one now
names the panel and the interaction that opens it (select an element → the
panel opens for that element):

| Constant | Change |
|---|---|
| `V2_TOOL_TIPS["text"]` (`prompts.py:1090`) | "…change the font, size and colour in the **Adjust** panel above the cap." |
| `V2_TOOL_TIPS["shape"]` (`prompts.py:1095`) | "Recolour it in the **Adjust** panel above the cap." |
| `V2_TOOL_TIPS["upload"]` (`prompts.py:1085`) | Adds: select the logo to open the **Adjust** panel above the cap. |
| `V2_BG_INSTRUCTIONS` (`prompts.py:1107`) | "…tick or untick 'Remove background' yourself in the **Adjust** panel above the cap." Still promises no processing and no wait. |
| `LOGO_ADJUST.ask` (`canvas_steps.py:481-484`) | Background-removal toggle located in the **Adjust** panel above the cap. |

Delivery is via the existing mechanism: `reply_for` concatenates the registry
tip verbatim, never through a model (`state_machine_v2.py:316-338`), so the
instruction cannot be paraphrased away.

## 6. Formality pass — full v2 canvas flow

**Register:** warm but businesslike. Second person, no slang, no filler
enthusiasm, exclamation marks only where genuinely earned. Australian English
(`colour`, `organise`) as the codebase already uses.

Representative rewrites (the plan enumerates every string):

| Now | After |
|---|---|
| `V2_ASK_NAME` — "Hi! I'm {persona}… First up, what's your name?" | "Welcome — I'm {persona}, your design assistant. I'll take you through putting your design onto the cap. To begin, may I have your name?" |
| `ASK_HAS_LOGO` — "Great, {name}! Do you have a logo…" | "Thank you, {name}. Do you have a logo or image you'd like on the cap?" |
| `LOGO_ADJUST` — "Pop your logo on there — I've opened the picker for you." | "I've opened the image picker for you." |
| `ASK_EMAIL` — "Love where this is going, {name}! …could I grab your email…" | "You're making good progress, {name}. Could I take your email address so I can save your progress and send your finished design through?" |
| `ASK_ANOTHER_LOGO` — "Locked that in." | "That's saved." |
| `ASK_QUANTITY` — "How many caps are you after?" | "How many caps do you need?" |
| `ASK_PURPOSE` — "Last thing — if you don't mind me asking, what's the hat for?" | "Finally, may I ask what the caps are for?" |
| `FINALIZE_CANVAS` — "Perfect — putting your design together now…" | "Thank you — I'm putting your design together now." |
| `V2_BACK_RESTART_ACK` — "No worries — I've removed that one…" | "Of course — I've removed that one so you can start it again." |
| `V2_COLOUR_DISCLAIMER` — "…pop it below and we'll use it" | "…enter it below and we'll use it" |

`V2_ACK_PROMPT` (`prompts.py:1205`) is in scope: it instructs the model to write
a "friendly, warm" sentence, which is where an otherwise-formal turn regains a
casual tone. It becomes "courteous and professional".

### Chip labels — the constrained part

Chip labels are matched by exact literal (`resolve_chip`,
`state_machine_v2.py:341-355`) and the e2e walk drives the exact strings the UI
ships (`test_v2_e2e.py`). Only clearly casual labels change — e.g.
`"No, that's it"` → `"No, that's all"`, `"No, it's fine as is"` → `"No, it's
fine as it is"` — and `test_v2_e2e.py` is updated in the same commit. This is a
targeted edit, not a rename sweep. `MIX_CHIP_LABEL` is referenced by
`ASK_DECORATION`'s ask copy via f-string and must stay consistent if touched.

## 7. Final-stage delivery promise

`REQUEST_QUOTE.ask` states what the customer receives:

> "Your design is ready, {name}. Select **Request a quote** below and our team
> will review it and email you your finished design{bg_note}, along with your
> quote."

### `{bg_note}` — why it is conditional

If the customer answered "No, it's fine as it is" at `ask_logo_bg`, nothing is
knocked out; a hardcoded "without the background" would be false for *their*
deliverable. So `{bg_note}` is computed:

- any banked logo with `bg == "removed"` → `", with the logo background removed"`
- otherwise → `""`

Source of truth is `collected["logos"]` (each entry carries `bg`, set by
`_apply_logo_bg` and banked by `_apply_another_logo`,
`canvas_steps.py:193-231`), with `collected["pending_logo"]` included
defensively — by `REQUEST_QUOTE` the loop is closed and `pending_logo` is
`None`, but reading both costs nothing and cannot be wrong.

**Mechanism:** a pure helper in `canvas_steps.py` (`bg_note_for(collected)`)
called from `reply_for`, which passes it as a `.format()` kwarg alongside the
existing `colour_note`/`name`/`persona`/`intro`. Unlike `colour_note` it needs
no `store`, so it is computed inside `reply_for` and requires **no**
`orchestrator_v2` signature change. Unused kwargs are ignored by `str.format`,
so no other step's copy is affected.

This mirrors the existing `{colour_note}` precedent on `ASK_FINAL_NOTES`
(`canvas_steps.py:725`) rather than introducing a new mechanism.

### The email must agree

`QUOTE_REFERENCE_EMAIL_BODY` (`prompts.py:808-818`) currently promises only
"a quote for your caps". It gets the matching line so the chat and the inbox do
not contradict each other.

### What is deliberately NOT built

The design is **not** auto-emailed. `delivery.py:96-130` short-circuits preview
delivery for quote-gated sessions and `maybe_send_quote_confirmation` sends the
reference code only; the admin-triggered render
(`POST /admin/quote-requests/{lead_id}/render`) produces the render for sales
and does not forward it to the customer.

So this copy commits the **team** to sending the design with the quote — a human
step, consistent with the human-in-the-loop constraint that the team approves
artwork before a customer sees it. Chosen deliberately over wiring delivery.

**Follow-up ticket (not this work):** an admin "send design + quote to customer"
action, so the promise is backed in software rather than by process.

The chip label stays `"Request a quote"` — accurate, and label changes ripple
into the e2e walk.

## 8. Testing

**Frontend** — new `frontend/src/__tests__/selectedToolbarPlacement.test.tsx`:

- the toolbar precedes the canvas stage in DOM order
- the header shows the element-type label (`Adjust — Text` for a text element)
- the sticky wrapper class is present

Existing `selectedToolbarTransform.test.tsx` and `surfaceDirective.test.tsx`
must stay green — in particular the `ask_logo_bg` selectability behaviour.

**Backend**:

- `reply_for` at `REQUEST_QUOTE` includes the background clause when a logo was
  flagged `removed`, and omits it when none was
- guard: no v2 copy string contains `"under the cap"`
- guard: no v2 copy string contains a banned casual phrase (`"pop your"`,
  `"grab your"`, `"love where"`, `"no worries"`), so tone cannot silently
  regress
- `test_v2_e2e.py` updated for changed chip labels, and still passes with the
  interpreter raising `LLMUnavailable` for the whole walk

Run backend as `CANVAS_ORCHESTRATOR_V2=false pytest -q` (repo default `.env`
flips 3 unrelated tests otherwise); frontend via focused `npx vitest run` on the
affected files, per the Windows tinypool stall noted in CLAUDE.md.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Sticky panel eats mobile height, hiding the cap | `max-h-[45vh]` + internal scroll on the controls region |
| Chip label edits break deterministic chip resolution | Change only the casual few; update `test_v2_e2e.py` in the same commit |
| Copy promises a design email the software never sends | Copy says the **team** sends it; follow-up ticket for an admin send action |
| `bg_note` claims a knockout the customer declined | Conditional on real `logos[].bg == "removed"` state, with a test either way |
| Losing element selection breaks `ask_logo_bg` | `v2Editing` gating untouched; existing tests pin it |
