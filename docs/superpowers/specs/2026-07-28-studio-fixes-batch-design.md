# Studio fixes batch — design

**Date:** 2026-07-28
**Status:** approved, ready for planning

Five independent fixes to the canvas Design Studio and the quote pipeline. They
share no state and can be implemented in any order, but items 1 and 4 touch the
same component (`SelectedToolbar.tsx`) and should land together.

| # | Area | Layer |
|---|---|---|
| 1 | Text-element content field is unfindable | frontend |
| 2 | Obscene/offensive language is unhandled | backend |
| 3 | Quote-confirmation copy claims the email is unconfirmed | backend (one line) |
| 4 | Adjust panel crowds the cap | frontend |
| 5 | Background-removal flag never reaches admin/sales | backend + admin frontend |

---

## 1. Text-element content field

### Problem

`SelectedToolbar.tsx:114-115` renders the text-content input as:

```jsx
<input value={el.content ?? ''} onChange={…}
  className="bg-base border border-border rounded px-1.5 py-0.5 text-xs text-textPrimary w-28"
  aria-label="Text content" />
```

112px wide, `text-xs`, **no visible label** (the `aria-label` is screen-reader
only), and positioned as just another item in a wrapping row alongside the font
dropdown, a colour swatch, and the size and curve sliders.

Meanwhile `Surface.tsx:110` and `Surface.tsx:325` both add the element
pre-filled with the literal `'Your text'`. So the customer adds text, sees
`Your text` sitting on the cap, and must work out that the small unlabelled box
among the sliders is where it gets changed.

### Design

The `text` branch of the panel becomes a vertical stack rather than one flat
wrap row:

```
ADJUST — TEXT
┌────────────────────────────┐
│ YOUR TEXT                  │  ← visible caption
│ ╔════════════════════════╗ │
│ ║ Your text|             ║ │  ← w-full, text-sm, accent border,
│ ╚════════════════════════╝ │    focus ring
│ [Font ▾] [■] A──●─ Curve─●─ │  ← existing controls, unchanged
└────────────────────────────┘
```

- **Row 1** — full-width labelled field. Visible caption, `text-sm`,
  `border-accent`, focus ring. Keeps its `aria-label` for assistive tech.
- **Row 2** — the existing font / colour / size / curve controls, unchanged.

The universal Rotate / Move / Size / Layer order / Actions groups below are
untouched.

### Autofocus is guarded, not unconditional

Focus-and-select fires **only when the content is still the untouched
placeholder**. Consequences:

- A newly added element focuses and selects, so typing replaces `Your text`
  immediately — the actual UX win.
- Re-selecting an element that has already been edited never steals focus, and
  never pops a mobile keyboard over the canvas.

This requires the placeholder to stop being a loose string literal. It is
currently duplicated at `Surface.tsx:110` and `Surface.tsx:325`.

**`TEXT_PLACEHOLDER` moves to `canvasStore.ts`** and all three sites read it.
Without this, the two literals drift and the guard silently stops matching —
failing open to "never autofocus", which is invisible in tests that do not
assert focus.

### Testing

- Field renders with a visible caption and full width.
- Adding a text element focuses and selects the field.
- Selecting an element whose content differs from `TEXT_PLACEHOLDER` does not
  move focus.
- Editing the field still writes `content` through `updateElement`.

---

## 2. Obscene / offensive language — graded handling

### Problem

`backend/app/services/moderation.py` exists and is wired at
`chat.py:83-85` and `generate.py:216-219`, but its Haiku judge
(`_MODERATION_PROMPT`, `moderation.py:15-27`) flags only hate symbols, explicit
sexual content, graphic violence, and clearly illegal content. Profanity passes
straight through — including as **cap text**, which reaches the AI render and
then production artwork.

### Design principle

Chat is lenient; the product is strict. A frustrated customer venting must not
dead-end a sale, but nothing obscene may reach a physical product.

### `backend/app/services/profanity.py` — new, pure

```python
def scan(text: str) -> str:          # "clean" | "mild" | "severe"
def find_terms(text: str) -> list[str]
```

- **No LLM, no I/O.** It therefore cannot stall a turn or fail open, unlike
  `moderation.check_text`. This matches the stall-safety doctrine the rest of
  the conversation engine follows.
- **Word-boundary matching only. Never substrings.**
  `state_machine.is_negative` matching `no` inside `a**no**ther` is an existing
  documented live landmine in this codebase; a substring profanity list is the
  Scunthorpe-problem version of the same bug. Strict `\b` anchors, plus a small
  set of deliberate leet variants (`f*ck`, `sh1t`) as explicit list entries —
  not as a general normalisation pass, which would reintroduce false positives.
- Two severity tiers: `MILD` (common swearing) and `SEVERE` (slurs, hate terms).
- The word lists stay **conservative**. A false positive on the cap path stops a
  customer at the very end of the funnel, which is the worst possible moment.

### Chat path — lenient

Guard in `orchestrator_v2.handle_message`, placed immediately after the
blank-turn no-op (`orchestrator_v2.py:85-98`) and reusing that exact shape:

- `severe` → re-render the current step with a decline prefix, ingesting
  nothing. State unchanged, no slot writes, no advance.
- `mild` → falls through completely untouched. The funnel continues.
- `clean` → unchanged.

It returns a **normal chat reply, not a 422**. A 422 surfaces as an error banner
and reads as a broken app rather than a boundary.

**No strike counter.** A slur declines on first use; mild profanity never
declines. Tracking "sustained" mild abuse is speculative complexity.

**v1 `orchestrator.py` is deliberately not touched.** It is the retained backup
path and the live flow is v2 canvas.

New copy constant in `prompts.py`, subject to the existing
`test_v2_copy_guards.py` register rules.

### Cap path — strict

In `sessions.py::finalize_canvas`, scan every text element's content plus the
notes, **before any DB write and before any lead/sales side-effect**.

- Any hit, `mild` or `severe`, returns 422 naming the offending element so the
  customer knows what to edit.
- `Surface.tsx:271-279`'s existing error banner already surfaces it; no new
  frontend surface is needed.

Ordering matters: finalize triggers reference-code minting and the sales email.
The scan must precede all of it or a rejected design still notifies sales.

### Logging

Log matched terms on a cap-path rejection — the term only, never customer name
or email (security rule 10) — so the word list can be audited against real
false positives.

### Testing

- `scan` returns `clean` for `"Scunthorpe"`, `"assessment"`, `"classic"` — the
  substring traps.
- `scan` tiers mild vs severe correctly.
- A severe chat turn re-renders the same step, writes no slots, and does not
  advance.
- A mild chat turn advances normally.
- Finalize rejects obscene cap text with 422 and names the element.
- Finalize rejection happens before any DB write or sales notification.

---

## 3. Quote-confirmation copy

`sessions.py:280-284` currently reads:

```python
reply = (
    f"All done — your request is in! Your reference is {reference}. "
    "Our team will be in touch with a quote soon. We've also emailed "
    "it to you once you confirm your address."
)
```

The trailing clause is wrong. In v2 the `AWAIT_EMAIL_VERIFY` hard gate means the
address is **already confirmed** by the time `REQUEST_QUOTE` and then
`finalize_canvas` run — the flow cannot reach this line otherwise.

Change to: `"…quote soon. We've also emailed it to you."`

No test asserts the old wording (`test_canvas_routes.py:297-325` asserts only
the reference code, state, and `data.reference_code`). The same string is quoted
in `docs/superpowers/plans/2026-07-24-canvas-quote-flow-C-quote-gated-delivery.md:452`,
which is a historical plan document and is left alone.

---

## 4. Adjust panel placement

### Problem

`SelectedToolbar` renders as the first child of the centre column
(`Surface.tsx:311`), directly above the cap. Because `CanvasStage` sizes itself
from the height left over in that column, every pixel the panel occupies is a
pixel off the design surface — measured live, the panel at ~174px in a 410px
column drove the stage onto its 280px floor.

Meanwhile the ToolRail column has genuine unused space: `ToolRail.tsx:64`'s root
is a plain `flex flex-col` with no `h-full`, so it is content-sized and the
column below the "Design saved" button is empty.

### Design — responsive split

- **Desktop (md+):** the panel mounts inside the rail column, below
  `<ToolRail>` — i.e. below the Done button, in the free space. The cap gets its
  full column height back.
- **Mobile (<md):** unchanged — above the cap.

The mobile position is preserved deliberately. The 2026-07-26 change moved the
panel above the cap precisely because the rail stacks *below* the canvas on a
phone (where the chat already owns 45vh), which put the panel under the fold and
made selecting an element look like it did nothing.

### One instance, not two

Rendering the panel in both columns gated by `md:hidden` / `hidden md:block`
would place two `data-testid="adjust-panel"` nodes in the DOM and break every
`getByTestId` assertion on it.

Instead a **feature-detected `useIsDesktop()`** hook (matchMedia
`(min-width: 768px)`) picks the container. It falls back to `true` when
`matchMedia` is absent — jsdom ships neither it nor `ResizeObserver`, and
constructing one unconditionally throws through every test that mounts
`Surface`, the same trap already documented for the observers in
`SelectedToolbar`'s measuring effect.

### Variant-dependent sizing

`MAX_SHARE = 1/3` (`SelectedToolbar.tsx:8`) exists because the panel steals
height from the cap. In the rail it competes with nothing, so the cap is wrong
there. A `variant: 'rail' | 'stacked'` prop:

| | `stacked` (mobile) | `rail` (desktop) |
|---|---|---|
| Height cap | `MAX_SHARE` of column, floor `MIN_MAX_H` | uses available column height |
| `sticky top-0` | yes | no (the rail column scrolls itself) |

`COMPACT_BELOW = 640` already measures the *column*, not the viewport, so the
rail's 176–256px width correctly collapses captions to tooltips with no change.

### Do not add `h-full` to the ToolRail root

`mt-auto` on the Done button (`ToolRail.tsx:103`) is currently inert, and that
is the desired behaviour. Making the rail fill its column would push Done to the
bottom and force the panel below it off-screen — the exact failure this change
is meant to remove.

### `CanvasStage` needs no change

It already measures its siblings to derive available height, so removing the
panel from the centre column hands the cap that space automatically.

### Testing

- Panel mounts inside the rail column when `matchMedia` reports desktop.
- Panel mounts in the centre column above the cap when it reports mobile.
- Exactly one `adjust-panel` node exists in either case.
- `Surface` mounts without throwing when `matchMedia` is undefined.
- Existing placement assertions updated.

**Known limitation:** CLAUDE.md records that sub-768px has never been
verifiable in-browser in this environment (the extension's `resize_window` is a
no-op and devtools MCP could not attach). The mobile branch therefore rests on
the class-pinning tests and the matchMedia fallback, not on observation.

---

## 5. Background-removal visibility for admin/sales

### Problem

A customer's "Remove background" tick (`SelectedToolbar.tsx:147-148`) survives
only as `collected["elements"][i]["remove_bg"]` in the database and as an
instruction inside the generation prompt (`prompt_builder.py:152`). No
admin-facing surface mentions it:

| Surface | Shows `remove_bg`? |
|---|---|
| `/admin/quote-requests` payload (`admin_leads.py:69-91`) | no — no per-element data at all |
| `QuoteRequestsView.tsx` | no |
| `/admin/quote-requests/{id}/components` | no |
| `SALES_QUOTE_REQUEST_EMAIL_BODY` (`prompts.py:827-844`) | no — no element list at all |
| Sales email attachments (`delivery.py:493-511`) | no |
| `SessionDetailView` "Remove background" row | reads the unrelated **v1** top-level `collected.remove_bg`, so always `—` for canvas sessions |

Sales quotes and produces the job without knowing the background must be knocked
out.

### Governing rule — single source of truth

**Every surface reads `collected["elements"][].remove_bg`** — the same field the
render reads.

Specifically **not** `collected["logos"][].bg`, which records the *chip* answer.
CLAUDE.md already documents that the chip answer and the manual toggle can
diverge, with no way to reconcile them at that point in the flow. Reading the
element field means admin sees exactly what production will actually do.

### 5a. Fix the attachment bug

`components.py:45` reads `el.get("asset_path")`, but `canvas_describe.py:103`
writes `assetPath`. Per-element canvas images are therefore attached to nothing
and appear in no admin component list today — only the single global
`uploaded_asset_path` does.

- Read both keys (`assetPath` then `asset_path`); v1-shaped elements use the
  snake form, so both must work.
- Append `— BACKGROUND TO BE REMOVED` to the component label when the element is
  flagged.
- Improve the label from `Element {i} asset` to name the element and its face.

Without this fix, sales reads "remove background" next to an image they cannot
download.

### 5b. Sales quote-request email

`SALES_QUOTE_REQUEST_EMAIL_BODY` gains a `{design_breakdown}` block — one line
per element, with an explicit marker on flagged ones. Rendered by a pure helper
and filled at `email.py:334-343`.

This is the surface the team actually reads when quoting.

### 5c. `/admin/quote-requests` + view

Rows gain an `elements` summary — kind, text/label, face or zone, `remove_bg`.
**PII-free**: element content only, no customer identity, consistent with the
existing payload boundary. `QuoteRequestsView.tsx` renders a badge on flagged
rows.

### 5d. `SessionDetailView`

Rebind the existing "Remove background" row to derive from
`collected.elements[].remove_bg` (flagged if any element is), retaining the v1
top-level read as a fallback so v1 chat sessions still display correctly.

### Testing

- `enumerate_components` finds per-element assets written as `assetPath`.
- It still finds v1-shaped `asset_path`.
- Flagged elements carry the marker in the label.
- The sales email body contains the breakdown and the marker.
- `/admin/quote-requests` exposes `remove_bg` per element and leaks no PII.
- `SessionDetailView` shows the flag for a canvas session and still works for v1.

---

## Out of scope

- v1 `orchestrator.py` profanity handling (retained backup path).
- A "sustained abuse" strike counter.
- Reconciling `collected["logos"][].bg` with `el.removeBg` — the documented
  divergence is untouched; this spec only ensures every admin surface reads the
  render's source of truth.
- `moderation.check_image`, still a pass-through stub.
- The floating-mobile-bar variant of the Adjust panel.

## Verification

Per CLAUDE.md:

- Backend: `cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
  (baseline **1057** passing), plus a v2-flag-on run for the orchestrator tests.
- Frontend: `cd frontend && npx vitest run src/__tests__` (baseline **249
  passing, 2 failing** — the 2 are pre-existing `adminQuotes` Router-context
  failures) and `npx vitest run src/admin`.
- Re-measure baselines by stashing rather than trusting the recorded numbers.
