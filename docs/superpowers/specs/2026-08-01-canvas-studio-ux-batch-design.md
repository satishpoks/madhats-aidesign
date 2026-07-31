# Canvas Studio UX batch — design

Date: 2026-08-01
Status: approved, ready for planning

Six independent UX changes to the v2 canvas studio. They share no state and can
be built in any order; they are one spec because they are one review pass.

1. Focus highlighting — make it obvious whether the next step is on the canvas
   or in the chat.
2. Adjust panel — categorise the element controls, give Move a game-controller
   D-pad, drop the rotate step from 45° to 12.5°.
3. Header — centre the hat name, remove the `› Design` suffix.
4. Chat copy — shorter sentences; split the email-verified turn into two
   messages.
5. Chat message layout — paragraphs, not one run-on blob.
6. Purpose step — accept a refusal, and accept misspelled answers.

---

## 1. Focus highlighting

### Problem

A canvas session alternates between "do something on the canvas" steps and
"answer a question in the chat" steps. Both panels look identical at all times,
so a non-technical customer has no cue where to act. The only existing hints are
the tool-rail highlight (subtle, and deliberately suppressed for the upload
tool) and the instruction callout inside the canvas column.

### Signal — already exists

`data.canvas.allowed_tools` from `state_machine_v2.directive_for`. Every v2-owned
step emits a directive; a tool step lists its one tool, every other step returns
`[]`. So:

- `allowed_tools.length > 0` → the canvas owns this turn.
- `allowed_tools.length === 0` → the chat owns this turn.
- No directive at all (v1 sessions, shared-tail states) → fall back to
  `chatState === 'canvas_design'`, which is v1's existing whole-rail gate.

No backend change is needed for this workstream.

### New: `frontend/src/lib/useActiveSurface.ts`

```ts
export type ActiveSurface = 'canvas' | 'chat'
export function useActiveSurface(): ActiveSurface
```

Reads `chatStore` only. One derivation with two consumers
(`CustomiseStudio/index.tsx` for the panel treatment, and — if useful —
`Surface.tsx`), so the two columns can never disagree about who is active.

### `finalizeFailed` moves into `chatStore`

`Surface.tsx` keeps a local `finalizeFailed` flag: a finalize that 422s (e.g.
the cap-text profanity gate) re-opens the canvas so the customer can act on the
error, even though the directive at `FINALIZE_CANVAS` says `allowed_tools: []`.

A hook reading `chatStore` alone would therefore report `'chat'` while the
canvas is genuinely live — the exact case where a wrong cue is most damaging.
So the flag is lifted to `chatStore.finalizeFailed` (set in `doRender`'s catch,
cleared when a retry starts). `Surface` reads it back for `v2Editing`; the hook
ORs it into the canvas branch. This is the only state move in the workstream.

### Treatment

Applied in `CustomiseStudio/index.tsx` to the two column wrappers.

Active column:
- `ring-2 ring-accent` plus a soft glow:
  `shadow-[0_0_18px_-4px_var(--brand-primary,#FF5C00)]`. Tailwind arbitrary
  values accept a CSS var, so the glow themes per store for free — the same
  mechanism `text-accent`/`bg-accent` already use.
- Full opacity.
- A pill at the top of the column: `▶ Your turn — design here` /
  `▶ Your turn — answer here`. `role="status"` so a screen reader announces the
  handover.

Inactive column:
- `opacity-60` and a `bg-base/40` scrim.
- **Not** `pointer-events-none`. Dimming is a cue, not a lock. The real locking
  already exists and is per-affordance (`stageLocked` on the stage, `ToolRail`'s
  `allowedTools`, `inputLocked` in `ChatColumn`); blocking pointer events here
  would additionally stop the customer scrolling back through the thread or
  re-reading the canvas, which they must always be able to do.

Both transition on `opacity`/`ring` so the handover reads as movement rather
than a flicker.

### Known gap (pre-existing, not fixed here)

Resuming a v2 canvas session mid-design via `?session=<token>` does not
rehydrate the `canvas` directive, so `isV2` is false and the fallback path
applies. The focus cue will read `'chat'` for such a session even mid-design.
This is the same resume gap already recorded in CLAUDE.md; fixing it is a
separate change.

---

## 2. Adjust panel — categories, D-pad, 12.5° rotate

### Problem

`SelectedToolbar` is one wrapping flex row of `Group`s. It was written for the
cramped centre column, where every pixel came off the cap. Since the panel moved
to the tool rail on desktop (`useIsDesktop`) it has room, and the flat row now
reads as an undifferentiated strip of small controls. The four Move arrows sit
in a horizontal line, which does not communicate direction. Rotate steps 45° at
a time, which is too coarse to place a logo.

### Structure — five labelled stacked sections

| Section | Contents |
|---|---|
| **Content** | text content field (text) · Remove-background toggle (image) |
| **Style** | font, colour, size, curve (text) / fill, border colour, border width, filled↔outline (shape) / single colour + width (line shapes) / stroke colour (drawing) |
| **Position** | D-pad · rotate · size |
| **Layer** | ▲ Forward · ▼ Back |
| **Actions** | Duplicate · Delete |

Rules:

- Sections render **only when non-empty**, so an image element shows Content,
  Position, Layer, Actions and no empty Style block.
- Captions are always shown. The existing `compact` mode (captions dropped to
  tooltips below a 640px column) is **removed**: it existed for the cramped
  centre column, and captions are the point of this change.
- Section order is fixed as above (Content first — the customer selected the
  element to change what it says or looks like far more often than to nudge it).

### D-pad

A 3×3 CSS grid:

```
     [ ↑ ]
[ ← ][ ⊕ ][ → ]
     [ ↓ ]
```

- Arrows nudge by the existing `NUDGE = 0.02` in normalised coordinates,
  clamped to `[0,1]` — unchanged behaviour, new layout.
- The centre cell is **Recentre**: `x = 0.5, y = 0.5`. It fills the hole the
  cross leaves and is genuinely useful; leaving it empty would look broken.
- Empty grid corners, so the cross shape is unmistakable.

### Rotate

- `ROTATE_STEP = 12.5` (was 45).
- The degree readout must not round 12.5 to 13. It formats with one decimal and
  strips a trailing `.0`, so the sequence reads `0 · 12.5 · 25 · 37.5 · 50`.
- The typed degree box still accepts any number and still normalises to
  `[0,360)` via the existing `norm360`.
- `aria-label`s and `title`s updated from "45 degrees" to "12.5 degrees".
- Reset (→ 0°) is unchanged.

### Sizing

The measured `maxH` cap stays for the **stacked** (mobile) variant only. That
cap is what stops the sticky panel pushing the cap off the bottom on a phone,
and `CanvasStage` sizes itself from the leftover column height. The **rail**
variant remains uncapped, as today — its column already has `overflow-y-auto`.

Stacking the controls makes the panel taller than the flat row was. On mobile
the cap absorbs this via `maxH` + internal scroll; on desktop the rail column
scrolls. No new measurement logic.

---

## 3. Header

`StoreHeader` becomes three zones:

```
[ logo            ] [ Hat name ] [           menu links ]
  flex-1 basis-0      shrink-0     flex-1 basis-0, justify-end
  min-w-0                          min-w-0
```

Equal `flex-1 basis-0` flanks share the leftover space equally regardless of
their content width, which centres the middle element exactly — no absolute
positioning, so nothing can overlap the logo or the menu on a narrow screen.
The title truncates (`truncate`) rather than pushing the flanks.

`CustomiseStudio` passes `productRef.name` alone. The `› Design` suffix is
removed.

`StoreHeader.test.tsx` gains a case for the three-zone structure. Other callers
of `StoreHeader` that pass no subtitle are unaffected.

---

## 4. Shorter copy, and splitting the email-verified turn

### Copy rewrite

Every v2 customer-facing string is rewritten to one idea per sentence, roughly
12–15 words. Sources: the `ask` / `ask_retry` / `tip` / `instructions` fields in
`canvas_steps.REGISTRY`, and the `V2_*` constants in `prompts.py`.

Constraints that must survive the rewrite:

- **Formal register.** `test_v2_copy_guards._CASUAL` stays as the pin.
- **Chip labels are matched by exact literal** (`state_machine_v2.resolve_chip`).
  Changing a label means changing it in the registry AND in
  `test_v2_e2e.py`'s walk, which types the labels verbatim. Prefer not to change
  chip labels at all in this batch.
- **Background-removal copy must not promise processing or a wait** — ticking is
  instant and the cap on screen does not change. `V2_BG_INSTRUCTIONS` and
  `V2_BG_ALREADY_REMOVED` keep saying *marked*, never *removed*.
- **`REQUEST_QUOTE` still promises the finished design with the quote** — that
  promise is kept by a human, not by code.

### The Adjust panel's position is no longer fixed

Since `useIsDesktop`, the panel is in the tool rail on desktop and above the cap
on mobile. Copy saying "the Adjust panel above the cap" is wrong for desktop —
the majority case. Every such string becomes "**the Adjust panel**", with no
location.

`test_v2_copy_guards.py` changes accordingly:

- `test_the_adjust_panel_is_named_where_the_customer_needs_it` asserts the tips
  name "Adjust panel" (dropping "above the cap").
- `test_no_v2_copy_points_below_the_cap` is generalised: no v2 copy may
  hard-code a position for the panel — none of "above the cap", "below the cap",
  "under the cap". This is a stronger guard than the one it replaces, because
  the position is now responsive and any hard-coded position is wrong somewhere.

### Splitting the email-verified turn

Only this one turn splits (owner decision). Today `check_verification` builds
one string: `V2_EMAIL_VERIFIED_ACK` + the next step's whole copy.

`orchestrator_v2._persist` gains an optional keyword:

```python
async def _persist(..., extra_replies: list[str] | None = None, ...)
```

- It inserts one additional `chat_messages` assistant row per entry, after the
  main reply row, with the same `state_before` / `state_after`.
- It returns them as `data["extra_replies"]`.

`check_verification` then sends `reply = V2_EMAIL_VERIFIED_ACK` and
`extra_replies = [reply_for(next_, ...)]` (no `ack=` argument).

Frontend: `chatStore.parseData` picks up `extra_replies` as `extraReplies:
string[]`; `applyResponse` and `pollVerification` append `res.reply` first, then
one message per entry. Chips and other `data` still describe the LAST message,
which is where the UI renders them anyway (below the whole thread).

`extra_replies` is absent on every other turn, so every existing path is
byte-identical.

---

## 5. Chat message layout

The bubble already has `whitespace-pre-wrap`, so the fix belongs at the source.
Every concatenation that today joins two sentences-worth of copy with a single
space becomes `\n\n`:

- `state_machine_v2.reply_for`: `ack` + body; body + `step.tip`; the
  `DECOR_ADJUST` tip-prepend.
- `orchestrator_v2.handle_message`: the `V2_BG_ALREADY_REMOVED` prepend and the
  `V2_EMAIL_VERIFY_NOTICE` prepend.
- `orchestrator_v2`'s abuse-decline prepend.

Result: an instruction is its own paragraph under the question, instead of
running into it.

---

## 6. Purpose step

### Problem

`ASK_PURPOSE` has `slots=("purpose",)` and
`done_when=lambda c: bool(c.get("purpose"))`. Free text goes to
`intent_extractor.interpret_turn_v2`, which is told to *"fill ONLY what the
customer clearly says — never guess"*. A misspelled answer or a refusal
("rather not say") can come back with no `purpose` field, `done_when` stays
False, and the step re-asks — a loop the customer cannot escape, because
`ASK_PURPOSE` ships no chips.

### Decision

Keep the LLM (so a volunteered "…and make it 100 caps" is still banked). No
chip. Two changes make the step impossible to fail:

**(a) Widen the slot doc.** `_SLOT_DOCS["purpose"]` becomes, in substance:
*"what the caps are for — accept ANY answer, including a refusal ('rather not
say', 'no', 'prefer not to') and including misspellings; record it as written."*

**(b) New `Step.accept_verbatim: bool`.** When the interpreter returns **no**
value for the step's own slot, the raw customer message is banked into that
slot. Set on `ASK_PURPOSE` **only**.

Why a per-step flag and not a global fallback: banking a raw message verbatim is
correct exactly where the answer IS the message. Doing it globally would write
"umm the back one I think" into `logo_face` (an enum) or `quantity` (an int) and
corrupt the design. The flag lives on the registry record for the same reason
`prepare` and `ops` do — the alternative is an `if step.id is ASK_PURPOSE`
branch in the orchestrator, which is the per-state switch the registry exists to
avoid.

Interaction with existing guards, all unchanged:

- The value still passes `ie.validate_fields` (so it stays inside
  `WRITABLE_SLOTS`) and `v2.merge_fields`.
- `LLMUnavailable` already resolves via the step's existing
  `direct_answer=_direct_purpose`; `accept_verbatim` is the *healthy-path*
  equivalent.
- Profanity: `ASK_PURPOSE` is **not** in `_ABUSE_EXEMPT_STEPS`, so a severe
  message is still declined before any of this runs.

---

## Testing

**Backend**
- `accept_verbatim`: interpreter returns `{}` → the raw message lands in
  `purpose` and `done_when` passes; interpreter returns a parsed purpose → that
  wins; the flag is set on no other step.
- `extra_replies`: `check_verification` writes two assistant rows and returns
  both, in order; every other turn returns no `extra_replies` key.
- Copy guards: the position guard and the "names the Adjust panel" guard, in
  their new forms.
- Paragraph joins: `reply_for` puts `\n\n` between question and tip.
- `test_v2_e2e.py`'s walk still passes end to end (it types chip labels
  verbatim, so it is the pin on the copy rewrite not breaking routing).

**Frontend**
- `useActiveSurface`: canvas for a tool step, chat for a no-tool step, canvas
  while `finalizeFailed`, and the v1 fallback on `chatState`.
- `CustomiseStudio`: active column carries the ring, inactive carries the dim,
  pill text matches the surface, and the inactive column is NOT
  `pointer-events-none`.
- `SelectedToolbar`: the five section captions render for a text element; empty
  sections are absent for an image element; the D-pad has five cells with the
  centre recentring; rotate steps 12.5° and the readout shows `12.5`, not `13`.
- `StoreHeader`: three zones, no `› Design`.
- `chatStore`: `applyResponse` and `pollVerification` append the main reply then
  each extra, in order.

Frontend tests run via `docker compose exec -T frontend npx vitest run <path>`
(host-side `npx vitest` is broken on this Windows machine). Backend runs via
`cd backend && CANVAS_ORCHESTRATOR_V2=false ./.venv/Scripts/python.exe -m pytest -q`
for the main suite, and with the flag ON for the five v2-only suites.

## Out of scope

- The v2 mid-design resume gap (no directive rehydrated on `?session=`).
- Per-store configurability of any of the above.
- v1 (non-canvas) conversation copy — untouched; every change here is behind
  `flow_mode == 'canvas'` + the v2 registry, or is v2-only frontend code.
