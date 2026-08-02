# Canvas Studio flow polish — design

Date: 2026-08-02
Branch: `feat/canvas-studio-flow-polish`

Five independent changes to the v2 canvas Design Studio. Four are frontend-only;
one (the watermark) is a backend correctness fix with a documented root cause;
one (the redirect) adds two per-store brand fields end to end.

---

## Scope

| # | Change | Layer |
|---|---|---|
| 1 | Hide the tool rail's controls whenever the canvas is not editable | frontend |
| 2 | Watermark persists from the review to the very end (and on resume) | backend + docs |
| 3 | End-of-session countdown dialog → redirect to the store's Shopify URL | backend + admin + frontend |
| 4 | Column header + chat lane colours: Ricardo = Primary, customer = Chat bubble | frontend |
| 5 | Mobile (<768px): one panel at a time, auto-switching, with manual tabs | frontend |

Out of scope, deliberately: per-store CORS, the v2 resume directive gap, the
white-on-accent contrast ticket, and any change to the v1 (non-canvas)
conversation.

---

## 1. Tool rail hidden until the canvas is editable

### Problem

`ToolRail` always renders its six controls (Add text, Upload image, Graphics,
Draw, cap-colour swatches, "Done designing"). During the intro Q&A — and at
every other chat-only step — they are rendered `disabled` at 50% opacity. A
non-technical customer reads a column of greyed-out buttons as a broken app,
not as "not yet".

### Design

`Surface.tsx` already computes exactly the right predicate for "the canvas is
editable on this turn":

```ts
const v2Editing = isV2 && (canvasDirective!.allowedTools.length > 0 || finalizeFailed)
```

Add a single derived flag and pass it to `ToolRail`:

```ts
const toolsVisible = isV2 ? v2Editing : unlocked
```

`ToolRail` gains an optional `toolsVisible?: boolean` prop (defaulting to
`true`, so no existing call site or test changes meaning). When it is `false`
the component renders **only its sizing wrapper** — no buttons, no swatches, no
render button.

**Decision (confirmed with the owner):** gate on "editable this turn", not
"past the intro". The tools are therefore also hidden at `ask_quantity`,
`ask_decoration`, `needed_by`, `ask_purpose`, `review_design`,
`ask_final_notes`, `request_quote` and `finalize_canvas`. That is the faithful
reading of "hide them because they aren't usable", and it reinforces the
existing whose-turn focus cue rather than fighting it.

### The width must stay reserved

The empty rail keeps `w-full md:w-44 lg:w-52 xl:w-64` and its padding.
`CanvasStage` sizes itself from a live measurement of the centre column
(`ResizeObserver` + `MutationObserver`, see the 2026-07-26 responsive-stage
work). Collapsing the rail to zero width would therefore resize the cap on
every turn transition, which is worse than the problem being fixed.

`SelectedToolbar` (the desktop Adjust panel) is a sibling of `ToolRail` inside
the right rail and is already gated on `showAdjust`, which resolves to the same
`v2Editing`. It is untouched.

### Verification

- `ToolRail` unit test: with `toolsVisible={false}` none of the six controls are
  in the DOM; the root still carries the width classes.
- With `toolsVisible` absent (v1 call shape) every control renders — the
  default must be permissive.
- Surface-level test: at a directive with `allowed_tools: []` the rail is
  empty; at `allowed_tools: ["upload"]` it is populated.

---

## 2. Watermark persists to the end

### Root cause (already ticketed in CLAUDE.md)

Only `state_machine_v2.public_data_for` emits the `watermark` key. Every other
payload producer is `orchestrator._public_data` — which serves both v1-delegated
turns (`generating`, `verify_email`, `offer_refine`, `quote_requested`) **and**
every resume, because `sessions.get_session` imports and calls the same
function. With the key absent, `chatStore.parseData` falls back to
`rawCanvas !== null`, and a v1-delegated turn carries no canvas directive — so
the watermark switches off the moment the flow leaves `finalize_canvas`, and on
any reload.

### Design

One pure predicate, in `state_machine_v2`, is the single source of truth:

```python
def watermark_for_state(state: str, collected: dict) -> bool:
    """True when the on-screen canvas must carry its watermark overlay.

    Pure: a function of the persisted state string plus `collected`, so it
    answers identically for a live turn, a v1-delegated tail turn and a resume.
    """
    if collected.get("flow_mode") != "canvas":
        return False                       # v1 session/blank flows: unchanged
    if collected.get("design_rework"):
        return False                       # reworking IS editing
    if collected.get("design_confirmed"):
        return True                        # the whole tail, and any resume
    step = cs.by_id_value(state)
    return bool(step and step.id in _WATERMARKED_STEPS)
```

Ordering matters and is load-bearing:

- `design_rework` is checked **before** `design_confirmed` because
  `_apply_review` pops the other flag on each tap, but a rework pass that
  re-reaches `review_design` must not re-watermark a canvas the customer is
  about to edit again.
- The `_WATERMARKED_STEPS` fallback is what covers `review_design` itself,
  where neither flag is set yet — including a **resume** landing there.
- The `flow_mode` guard keeps every non-canvas flow byte-identical.

### Call sites

Both producers call it, so they cannot drift:

1. `state_machine_v2.public_data_for` — replaces `watermark_for(step)`.
   Behaviourally identical on every v2-owned step (verified case by case:
   `review_design` → step fallback True; `rework_canvas` → `design_rework`
   truthy → False; `ask_final_notes`/`request_quote`/`finalize_canvas` →
   `design_confirmed` truthy → True; every earlier step → False).
2. `orchestrator._public_data` — new `data["watermark"] = ...`. Reached by v1
   turns and by `sessions.get_session`, which is the resume path.

`watermark_for(step)` is retained (it is the declarative statement of which
steps watermark) but becomes an internal helper of the new function.

The frontend needs no change: `parseData` already prefers an explicit flag. Its
`rawCanvas !== null` default stays as a safety net for a frontend deployed ahead
of the backend.

### Documentation debt paid at the same time

- The comment at `state_machine_v2.py:349-352` claims the frontend "falls back
  to its own default — which is `true`". It is `false`. Corrected.
- The CLAUDE.md open ticket ("every chat payload with NO `canvas` directive now
  renders the canvas UNwatermarked") is resolved and removed.

### Verification

Table-driven pytest over `watermark_for_state`, covering: each v2-owned step;
`rework_canvas`; the tail states (`generating`, `verify_email`,
`quote_requested`, `offer_refine`) with `design_confirmed` set; a resume at
`review_design` with neither flag; a rework in progress; and a non-canvas
(`flow_mode="session"`) session at every one of those states (all False).
Plus one test that `orchestrator._public_data` actually emits the key.

---

## 3. End-of-session countdown → Shopify redirect

### Trigger

`chatState === 'quote_requested'`. That is the terminal state for a v2 canvas
session: `sessions.finalize_canvas` returns it with the `MH-XXXXXX` reference in
the reply and `data.reference_code`.

If the store has configured no redirect URL, **nothing happens at all** — no
dialog, no lock. Unconfigured stores behave exactly as today.

### Backend — two new brand fields

`stores.brand` is jsonb, so there is no migration.

`services/branding.py`:

- `validate_brand` accepts `redirect_url` (must be an `http(s)` URL with a
  netloc — the same rule `_validate_menu_items` applies; empty string clears it)
  and `redirect_seconds` (int, `5 <= n <= 300`; anything else raises
  `ValueError`; absent means "use the default").
- Both are added to `_PUBLIC_KEYS` so `public_brand` serves them to the customer
  widget. `redirect_url` is not a media path, so it is passed through
  unmodified — only `logo_url` goes through `media_url`.

The existing `if not val: continue` loop in `public_brand` naturally drops an
unset URL and a `0`/absent seconds value, which is the wanted behaviour.

`DEFAULT_REDIRECT_SECONDS = 30` lives in `branding.py` as a named constant and
is the value the admin form pre-fills.

### Admin

`admin/views/BrandingView.tsx` gains a "Return to shop" block: a text input for
the URL and a number input for the seconds, next to the colour pickers. The
client-side `validate()` mirrors the server rules (this file already does that
for menu items, and `test_configurable_step_ids_are_exactly_the_safe_subset`
sets the precedent that the mirroring is deliberate).

### Frontend — `RedirectCountdown.tsx`

New component in `components/CustomiseStudio/`, modelled on `ReviewDialog`:
portal, backdrop click guarded against bubbling from inside the panel, Escape
handling, focus trap, and deliberate initial focus on the low-cost control
("Stay here") rather than the destructive one.

Behaviour:

- Opens when `chatState === 'quote_requested'` **and** `brand.redirect_url` is
  set.
- Counts down once per second from `brand.redirect_seconds ?? 30`.
- At zero, `window.location.assign(redirect_url)`.
- **Go to the shop now** → redirect immediately.
- **Stay here** → clears the interval and closes the dialog. Per the owner's
  ruling the session stays read-only so the design remains on screen; only the
  redirect is cancelled.
- The interval is cleared on unmount and whenever the dialog closes, so a
  cancelled countdown can never fire later.

### Locking

`ChatColumn` gains:

```ts
const sessionEnded = chatState === 'quote_requested'
const inputLocked = sending || awaitingEmailVerify || sessionEnded
```

`sessionEnded` additionally suppresses the chip rows, `options2`, the Continue
affordance, the Back menu and the voice block — the same set
`awaitingEmailVerify` already suppresses, for the same reason: an affordance
that cannot move the conversation reads as a broken bot.

The canvas needs no separate lock. At `quote_requested` there is no directive,
so `isV2` is false and `locked = !unlocked` is already true; change 1 then hides
the controls outright.

`sessionEnded` is deliberately keyed on the chat state alone, **not** on whether
a redirect URL is configured — the session really has ended either way, and a
store without a redirect URL should still not be invited to keep typing.

### Verification

Backend: `validate_brand` accept/reject cases for both fields (valid https URL,
`ftp://`, no netloc, empty string clears, seconds 4/5/300/301, non-int);
`public_brand` exposes both; a `/storefront` test asserting the round trip.

Frontend, with fake timers: the dialog opens at `quote_requested` with a URL and
does not without one; the counter decrements; reaching zero calls
`location.assign`; "Go to the shop now" calls it immediately; "Stay here" closes
and no `assign` happens after further ticks. Plus a `ChatColumn` test that the
input, Send, chips and Back are all gone at `quote_requested`.

---

## 4. Column header and chat lane colours

### Problem

`ColumnHeader` hardcodes `bg-canvasAccent` for both halves, so the two columns
are indistinguishable by colour and neither reflects the store's Primary colour.
`ChatColumn`'s assistant lane also uses `border-canvasAccent`.

### Design

| Surface | Before | After | CSS var |
|---|---|---|---|
| Chat column header (Ricardo) | `bg-canvasAccent` | `bg-accent` | `--brand-primary` |
| Canvas column header (customer) | `bg-canvasAccent` | `bg-chatUserBubble` | `--chat-user-bubble` |
| Assistant message lane | `border-canvasAccent` | `border-accent` | `--brand-primary` |
| Customer message lane | `border-chatUserBubble` | unchanged | `--chat-user-bubble` |
| Tool rail / Done / instruction callout | `canvasAccent` | unchanged | `--canvas-accent` |

`ColumnHeader` takes a `tone: 'primary' | 'customer'` prop rather than a raw
class string, so the two allowed values are enumerable and testable and a caller
cannot invent a third.

### Backward compatibility

`applyBrandVars` already derives `--chat-user-bubble` from
`brand.chat_user_bubble || brand.primary_colour`, and the Tailwind fallback is
`#FF5C00`. An unconfigured store therefore renders both bars in exactly the
orange they are today.

### Known limitation (recorded, not fixed)

White header text on a store-chosen `chat_user_bubble` can fall below 4.5:1.
This is the same unbounded contrast issue already ticketed for the accent
header and the Done button; fixing it properly means deriving the header text
colour with `brandStore.readableOn`, which is a separate change across every
accent surface.

### Verification

`ColumnHeader` renders `bg-accent` for `tone="primary"` and `bg-chatUserBubble`
for `tone="customer"` when active, and neither when resting; `CustomiseStudio`
passes the right tone to each column; `ChatColumn`'s assistant lane carries
`border-accent` and the customer lane `border-chatUserBubble`.

---

## 5. Mobile — one panel at a time

### Design

`CustomiseStudio/index.tsx` calls the existing `useIsDesktop()` (Tailwind `md`,
feature-detected, falls back to `true` under jsdom).

Below `md`:

- A two-tab bar renders under `MilestoneBar`: **Chat** | **Design**.
- Only the selected panel is visible.
- `const [tab, setTab] = useState<ActiveSurface>('chat')` plus
  `useEffect(() => setTab(active), [active])`, where `active` is
  `useActiveSurface()`. Because the effect fires only when `active` *changes*, a
  manual peek sticks until the flow moves — then the auto-switch takes over
  again. This is the whole mechanism; there is no second source of truth.
- The session opens on **chat**: at mount there is no directive and `chatState`
  is `''`, so `useActiveSurface()` answers `'chat'`.
- The tab that is not selected shows a small dot when it *is* the active
  surface — i.e. "the flow wants you over here".

At `md` and above the current side-by-side layout, both `ColumnHeader`s and the
active/resting card treatment are completely unchanged.

### The hidden panel is hidden, never unmounted

This is the correctness constraint of the whole change. `Surface.doRender()`
flattens through `stageRef` in a loop over the decorated faces; unmounting the
Konva stage would null the ref and break finalize outright, and remounting it
would lose the in-progress design.

So the non-selected column is hidden with `display:none` (Tailwind `hidden`)
while staying mounted. Two consequences were checked:

- Export size is safe. `canvasFlatten` derives `pixelRatio` from
  `stage.width()`, so every export is `EXPORT_EDGE_PX` (960) regardless of the
  displayed size — the invariant `canvasFlattenExportSize.test.ts` already pins.
- Element geometry is safe. All coordinates are normalised against the logical
  `STAGE_W`/`STAGE_H` (480), which does not move with the displayed size.

### Belt and braces: force the canvas visible for the flatten

At `finalize_canvas` the directive hands over no tool, so `useActiveSurface()`
answers `'chat'` and the canvas would be `display:none` during the multi-face
flatten loop. Konva should still paint and `toDataURL` should still work — but
that relies on browser behaviour we have not measured, and a silent blank export
would be catastrophic and hard to attribute.

So: when `triggerFinalize` is true, the mobile tab is forced to `'canvas'`.
This removes the dependency entirely, and it also shows the customer their
design while it is being captured. Implemented as an additional effect, not by
complicating `useActiveSurface` — that hook answers "where should the customer
act", which is a different question from "what must be painted".

### Verification

Component tests with a mocked `matchMedia` (jsdom ships none): below `md` only
one panel is in the layout and both are still mounted; tapping a tab switches;
a directive change re-syncs the tab; `triggerFinalize` forces `'canvas'`; at
`md` and above no tab bar renders and both panels show.

**Honest limitation.** A sub-768px viewport has not been drivable in this
environment in any previous batch (the Chrome extension's `resize_window` is a
no-op here and the devtools MCP could not attach). The mobile layout is
therefore pinned by jsdom class-string and mount-presence tests, which perform
no real layout. The final report will say so explicitly rather than claiming a
browser-verified mobile walk.

---

## Files touched

**Backend**
- `app/services/conversation/state_machine_v2.py` — `watermark_for_state`, comment fix
- `app/services/conversation/orchestrator.py` — emit `watermark` in `_public_data`
- `app/services/branding.py` — `redirect_url`, `redirect_seconds`, `DEFAULT_REDIRECT_SECONDS`
- `tests/` — new cases in the watermark, branding and storefront suites

**Frontend**
- `components/DesignStudio/ToolRail.tsx` — `toolsVisible`
- `components/DesignStudio/Surface.tsx` — compute and pass `toolsVisible`
- `components/CustomiseStudio/ColumnHeader.tsx` — `tone`
- `components/CustomiseStudio/ChatColumn.tsx` — assistant lane colour, `sessionEnded`
- `components/CustomiseStudio/RedirectCountdown.tsx` — **new**
- `components/CustomiseStudio/index.tsx` — tones, mobile tabs, mount the countdown
- `lib/types.ts` — `Brand.redirect_url`, `Brand.redirect_seconds`
- `admin/views/BrandingView.tsx` — the two new fields
- `src/__tests__/` — new suites per the verification sections above

**Docs**
- `CLAUDE.md` — resolve the watermark ticket, record the new brand fields and
  the mobile-verification limitation

---

## Risks

| Risk | Mitigation |
|---|---|
| Hiding the rail changes the measured column width and resizes the cap each turn | The empty rail keeps its width classes; asserted by a test |
| `watermark_for_state` regresses a v1 or blank flow | `flow_mode != "canvas"` short-circuit, plus explicit non-canvas test cases |
| A hidden Konva stage exports blank on mobile | The panel is never unmounted, and `triggerFinalize` forces the canvas visible |
| The redirect fires on a store that never configured one | No URL ⇒ the dialog never mounts and no timer starts |
| A cancelled countdown fires later | The interval is cleared on cancel and on unmount; covered by a fake-timer test |
