# Structured Back — checkpoint restore for the v2 canvas flow

**Date:** 2026-08-01
**Status:** Approved (design)
**Scope:** The `↩ Back` affordance in the v2 canvas conversation (`CANVAS_ORCHESTRATOR_V2` on, `flow_mode == "canvas"`). No change to v1 or to any non-canvas flow — they never emit `can_go_back`.
**Supersedes:** `2026-07-25-v2-canvas-back-element-restart-design.md` (its element-restart branch and single-step lock are removed by this work).

---

## 1. Problem

Back is derived, not recorded. `orchestrator_v2.handle_back` walks the registry
backwards via `state_machine_v2.last_answered_step`, picks the highest-index
answered step, clears that step's writable slots (plus its `back_clears`), and
lets first-unmet routing re-ask it.

Three consequences, all visible to the customer:

1. **Chat and canvas desync.** The rewind only ever touches `collected`. The
   canvas is never rewound, because the backend has no record of what it looked
   like earlier — `canvas_design` is written only at finalize, and the live blob
   reaches the backend on just two turn kinds (`describe_changes`,
   `rework_canvas`). So the bot re-asks about a logo that is still sitting on
   the cap looking finished.
2. **One slot per press.** A customer who wants to change something four
   questions back cannot get there: `_back_used` disables Back until the next
   forward answer, so each press costs a full round trip and a re-answer.
3. **The mid-element special case is a patch over the same hole.** Because
   per-slot rewind walks *into* an element's attribute sequence, the previous
   design added `_ELEMENT_ADJUST_STEPS` + a "Remove this element and start it
   over?" confirm dialog to stop it. That is the right behaviour arrived at by
   the wrong route: the element, not the slot, is the natural unit.

## 2. Goals

- Back opens a **menu of named destinations**, not a blind single-step rewind.
- Picking one restores the session **to exactly how it was** at that moment —
  `collected`, conversation state, the canvas, and the visible chat thread.
- Everything after the chosen point is **discarded from the live session but
  retained on the server** for audit.
- Destinations that would unpick something already agreed are **not offered**.

## 3. Non-goals

- No change to v1 (`orchestrator.py`) or to the shared tail states.
- No admin UI for the retained audit branches. The data lands; surfacing it is
  separate work.
- No backfill for sessions already in flight when this ships (see §8).
- No change to `chat.py::_persist_live_canvas_design`'s scoping. This work reads
  the live canvas on more turns but still never widens what may **write**
  `design_sessions.canvas_design`.

## 4. Approach

**Chosen: snapshot and restore.** Capture `(collected, canvas_design, chat
watermark)` on entry to each checkpoint; going back writes the snapshot back.

**Rejected: keep deriving, but derive better** — extend the current
slot-clearing to also emit canvas ops that undo each element. This is what the
superseded design started down. It requires the backend to model, per step, what
the customer did on the canvas, which it cannot see; every new tool or element
type would need a matching undo rule. Snapshots make the question not arise:
what was true is stored, not inferred.

**Rejected: full event-sourced undo** (record every turn, replay to any point).
More general, and the generality is unused — the customer thinks in "the logo",
not "the twelfth turn". It would also make the offerable-list logic depend on
replay rather than a pure predicate, which is a large step away from how the
rest of v2 is built.

## 5. The checkpoint model

### 5.1 What a checkpoint is

A checkpoint is a **customer-meaningful moment**, declared in the
`canvas_steps.REGISTRY` alongside the step that opens it. An element loop pass
is exactly one checkpoint — the face question, the placement, and the
background question are *inside* it, not beside it. That is what keeps the menu
readable and keeps the maintenance burden at "one record per checkpoint".

| Checkpoint kind | Opens at | Label example | `frozen_when` |
|---|---|---|---|
| `name` | `ASK_NAME` | `Your name — Satish` | `email_verified` |
| `has_logo` | `ASK_HAS_LOGO` | `Logo or image — yes` | `decor_done` |
| `logo` (loop) | `ASK_LOGO_PLACEMENT` | `Logo 2 — back, background removed` | `decor_done` |
| `decor` (loop) | `ASK_ADD_DECOR` | `Text "MADHATS" — left side` | `decor_done` |
| `quantity` | `ASK_QUANTITY` | `Quantity — 50` | `design_confirmed` |
| `decoration` | `ASK_DECORATION` | `Decoration — Embroidery` | `design_confirmed` |
| `needed_by` | `NEEDED_BY` | `Needed by — 3 weeks` | `design_confirmed` |
| `purpose` | `ASK_PURPOSE` | `What it's for — team caps` | `design_confirmed` |

Every other registry step is **never a destination**: `SHOW_INTRO` (an ack, not
an answer), `LOGO_ADJUST` / `ASK_LOGO_BG` / `ASK_ANOTHER_LOGO` /
`ASK_DECOR_PLACEMENT` / `DECOR_ADJUST` / `ASK_ANYTHING_ELSE` (inside a
checkpoint), `ASK_DECORATION_MIX` (a follow-up to `ASK_DECORATION`), `ASK_EMAIL`
/ `AWAIT_EMAIL_VERIFY` (§5.3), and `REVIEW_DESIGN` / `REWORK_CANVAS` /
`ASK_FINAL_NOTES` / `REQUEST_QUOTE` / `FINALIZE_CANVAS` (past the last floor).

### 5.2 Freezing

`frozen_when` is a **pure predicate over `collected`**, so the entire
offerable-list computation is testable with plain dicts, no database and no LLM
— matching how the rest of v2 routing is built.

The two flags it reads already exist and are already set by chips the customer
taps:

- **`decor_done`** — set by **"No, that's everything"** at `ASK_ANYTHING_ELSE`.
  The design is agreed; every design checkpoint (name aside) stops being
  offerable. The customer can still change the design through `REVIEW_DESIGN`'s
  **"I'd like to rework it"** chip, which is untouched by this work.
- **`design_confirmed`** — set by **"Looks great, send it"** at `REVIEW_DESIGN`.
  The brief answers freeze too, so the offerable list becomes empty and Back
  disappears entirely for the rest of the session.

An empty list is how "no going back" expresses itself — there is no separate
disable flag to keep in sync.

Note that freezing is **per-checkpoint, not a positional floor.** `name` freezes
on `email_verified`, which happens mid-design; the logo placed just before the
email step stays rewindable. A floor model cannot express that.

### 5.3 Email and the name banner

The email address is never a destination. Once verified it must not change
(the double opt-in already fired and the lead row is written); and before
verification there is no window in which it could be edited, because
`AWAIT_EMAIL_VERIFY` freezes the whole chat — input, mic, chips and Back — until
the link is clicked. So it is simply absent from the registry's checkpoint
declarations, with no special case anywhere.

Restoring to a checkpoint *earlier* than the email step (e.g. Logo 1) must leave
`email_captured` / `email_verified` intact. This is **not** automatic: a
snapshot taken before the email step records a `collected` that predates
verification, so a naive replacement would un-verify a verified customer and
re-ask for their address. §6.3's carry-forward rule is what prevents it, and it
is the single most important correctness detail in this design.

**New UI:** the captured name renders in the canvas column above the tool rail
as `Design for <Name>`, from the moment the name is captured. It becomes
permanent at email verification, which is the same moment the `name` checkpoint
leaves the menu — the displayed identity and the lead record stop being editable
together rather than drifting apart.

## 6. Capture and restore

### 6.1 Storage

One new table. Migration `20260801000001_session_checkpoints.sql`.

```sql
create table if not exists session_checkpoints (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references design_sessions(id) on delete cascade,
  seq            int  not null,          -- monotonic per session, 1-based
  kind           text not null,          -- 'name' | 'logo' | 'decor' | ...
  label          text not null,          -- rendered at capture, from `collected`
  step_id        text not null,          -- the opener step to re-ask
  collected      jsonb not null,         -- session `collected` on entry
  canvas_design  jsonb,                  -- live canvas on entry; null before any exists
  chat_watermark uuid,                   -- last chat_messages.id on entry; null if none
  created_at     timestamptz not null default now(),
  superseded_at  timestamptz             -- set when a restore branches past it
);
create unique index if not exists idx_session_checkpoints_seq
  on session_checkpoints(session_id, seq);
create index if not exists idx_session_checkpoints_live
  on session_checkpoints(session_id, seq) where superseded_at is null;
```

And one column on the existing table, same migration:

```sql
alter table chat_messages add column if not exists superseded_at timestamptz;
```

`chat_messages` rows are **never deleted**. Both readers
(`sessions.py:388`, `admin_diagnostics.py:189`) gain a filter; the customer-facing
one filters superseded rows out, the admin one deliberately does not.

A separate table rather than a jsonb array on `design_sessions` because the rows
are append-only, are queried by `seq`, carry two independent lifecycle
timestamps, and would otherwise mean rewriting a growing blob on every turn.

### 6.2 Capture

In `orchestrator_v2`, when a turn resolves to a step that **opens** a checkpoint
and no live checkpoint for that opener-instance exists yet, write one row before
the step's question is persisted.

The snapshot is correct by construction: the turn that carries the session *into*
Logo 2 carries `collected` and the canvas as they stood at the **end** of Logo 1.
Nothing is derived.

This requires one frontend change: `chatStore.sendMessage` currently attaches
`toCanvasDesign()` only on `describe_changes` and `logo_adjust` turns. It must
attach it on **every** v2 canvas turn. `chat.py::_persist_live_canvas_design`
keeps its existing hard scoping — the blob feeds the checkpoint row, and the
rule about which turns may overwrite `design_sessions.canvas_design` is
unchanged.

Loop checkpoints are keyed by opener step **plus loop index** (`len(logos)`,
`len(decor)` at entry), so a second pass through `ASK_LOGO_PLACEMENT` captures a
second row rather than colliding with the first.

### 6.3 Restore

`POST /chat/{session_id}/back` takes `{"seq": <int>}`. Given a live checkpoint
row *K*:

1. **`design_sessions.collected` ← the snapshot, then carry forward the
   protected keys.** Verified against the code, the set is
   `{email_captured, email_verified, lead_id, quote_requested, reference_code}`:
   `_apply_email` writes the first three, `leads._mark_session_verified` writes
   `email_verified` **out of band** (an emailed link click, which can land at any
   point after the snapshot was taken), and `_apply_request_quote` writes the
   last two. Each is copied from the *current* `collected` onto the restored one.
   This is the same protection `state_machine_v2._TERMINAL_FLAGS` provides today,
   applied at the restore boundary instead of the clear boundary — and it must be
   a single named constant, since a key added to that set later and missed here
   is a silent data-loss bug. `quote_requested` / `reference_code` are carried for
   safety rather than necessity: once set, the offerable list is empty and no
   restore can run.
2. **`design_sessions.state` ← `step_id`.** The router needs no special casing:
   `collected` genuinely is what it was, so first-unmet lands on that step by
   itself. Setting `state` explicitly keeps the persisted state consistent for a
   mid-restore reload.
3. **Supersede.** `session_checkpoints` rows with `seq > K` and `chat_messages`
   rows created after `chat_watermark` get `superseded_at = now()`. Nothing is
   deleted; the discarded branch stays fully reconstructable.
4. **Respond** with the re-asked opener step plus `data.canvas_restore =
   <the snapshot's canvas_design>`.

The frontend applies `canvas_restore` via `canvasStore.fromCanvasDesign` **in
the response handler in `chatStore`**, next to where `canvas_ops` is applied
today — deliberately **not** in a React effect, for the reason already recorded
in the codebase: an effect fires on change and would re-apply on resume.

A snapshot whose `canvas_design` is null (the `name` checkpoint, captured before
any canvas exists) omits `canvas_restore` and leaves the canvas alone.

### 6.4 Concurrency and staleness

Restoring a `seq` that is already superseded, unknown, or belongs to a frozen
checkpoint returns **409**. The frontend re-renders the current step from the
response rather than retrying. This covers the double-tap and the stale second
tab; a lost race resolves to "you are where you are", never to a double restore.

## 7. Frontend

**`chatStore`**

- `parseData` reads `data.back_targets` → `backTargets: {seq, label, kind}[]`
  (newest first, already filtered server-side) and `data.canvas_restore`.
- `goBackTo(sessionId, seq)` replaces `goBack(sessionId)`.
- The response handler applies `canvas_restore` through `fromCanvasDesign`.
- `hydrate` needs no change: superseded rows are filtered by the API, so a
  resumed session naturally shows the branched thread.
- `backRemovesElement` and its parse are removed.

**`ChatColumn`**

- Back is rendered only when `backTargets.length > 0`.
- Tapping it renders the destination list inline in the existing chip styling,
  plus **Cancel — stay here**. No round trip: the list ships on every turn.
- The `confirmingBack` / "Remove this element and start it over?" confirm is
  removed.

**`Surface`**

- `Design for <Name>` above `ToolRail`, from `collected.name` as surfaced on
  chat `data`.

**`lib/api.ts`** — `sendBack(sessionId)` gains the `seq` argument.

## 8. What is removed

The current back machinery is replaced wholesale, not extended:

- `orchestrator_v2`: the `_ELEMENT_ADJUST_STEPS` branch of `handle_back`,
  `_restart_element`, the `_back_used` set/pop, and `back_removes_element` in
  `_public`.
- `state_machine_v2`: `last_answered_step`, `_ELEMENT_ADJUST_STEPS`, and the
  `can_go_back` computation (replaced by "is `back_targets` non-empty").
- `canvas_steps`: the `Step.back_clears` field and its one user
  (`ASK_DECORATION`). It exists solely to make derived-flag steps detectable by
  `last_answered_step`; snapshots make it moot.
- `prompts.V2_BACK_RESTART_ACK`.
- `_TERMINAL_FLAGS` survives but moves role: it becomes the carry-forward set at
  the restore boundary (§6.3) rather than a subtraction at the clear boundary.

## 9. Migration and rollout

Sessions already in flight when this ships have **no checkpoint rows**, so their
offerable list is empty and Back is simply absent. They complete normally. No
backfill and no half-restored state — the failure mode of a partial backfill
(restoring to a snapshot that was reconstructed rather than recorded) is exactly
the class of bug this design exists to remove.

## 10. Edge cases

- **Restore to `name`.** The canvas snapshot is null, so the canvas is left
  alone; `Design for <Name>` re-renders when the new name is captured. Only
  reachable before email verification, by §5.2.
- **Restore to Logo 1 with a verified email.** The design rewinds to empty while
  the email stays verified — correct, and mildly odd-looking. Accepted
  deliberately: the alternative (freezing everything below the email step) would
  make the feature nearly unusable, since verification normally happens while
  the customer is still designing.
- **Restore during `AWAIT_EMAIL_VERIFY`.** Unreachable — the gate disables Back
  along with every other input.
- **A checkpoint opener that is never reached** (e.g. `ASK_LOGO_PLACEMENT` for a
  text-only customer) captures no row and is never offered.
- **`ASK_DECORATION_MIX`.** Not a checkpoint; restoring to `decoration` re-asks
  the method and the mix follow-up naturally re-derives from the answer.
- **Two browser tabs.** The 409 path (§6.4) is the whole answer; no locking.

## 11. Testing

**Backend — pure, plain dicts, no DB (`test_canvas_steps` / `test_state_machine_v2`):**
- Every registry step either declares a checkpoint or is explicitly excluded;
  the declared set matches §5.1 exactly (a guard test, so adding a step forces a
  decision).
- `frozen_when` per checkpoint: `name` freezes on `email_verified` and not
  before; design checkpoints freeze on `decor_done`; brief checkpoints freeze on
  `design_confirmed`; the offerable list is empty once `design_confirmed`.
- Label rendering for each kind, including a loop index and a missing/partial
  value.

**Backend — orchestrator (`test_orchestrator_v2` / `test_v2_e2e`):**
- Entering a checkpoint opener writes exactly one row; a second loop pass writes
  a second row with the next `seq`.
- Restore replaces `collected` rather than merging, and carries forward
  `email_captured` / `email_verified`.
- Restore supersedes later checkpoints and later chat rows, and **deletes
  nothing** (row counts unchanged).
- Restore returns `data.canvas_restore` when the snapshot has one and omits it
  when null.
- A superseded / unknown / frozen `seq` returns 409 and leaves the session
  untouched.
- A session with no checkpoint rows offers no targets (the in-flight case).
- The e2e walk gains a back-and-continue leg, driving the exact chip labels the
  UI ships.

**Frontend:**
- `chatStore`: `backTargets` reflects `data.back_targets`; `goBackTo` posts the
  seq; `canvas_restore` is applied in the response handler and **not** in an
  effect (a resume must not re-apply it).
- `ChatColumn`: the menu renders from `backTargets`, hides when empty, Cancel
  makes no request, and the removed confirm dialog is gone.
- `canvasStore`: `fromCanvasDesign` restores a snapshot including lock state.
- `Surface`: the name banner renders on capture and is absent before it.

**Existing tests to update:** `chatStoreBack.test.ts` and the back-related cases
in `test_orchestrator_v2` / `test_state_machine_v2` are rewritten rather than
extended — they assert the derivation this design removes.

## 12. Files touched

**Backend**
- `supabase/migrations/20260801000001_session_checkpoints.sql` — new table + `chat_messages.superseded_at`.
- `services/conversation/canvas_steps.py` — `Checkpoint` dataclass, `Step.checkpoint`, declarations; remove `back_clears`.
- `services/conversation/state_machine_v2.py` — `back_targets(collected, config)`; remove `last_answered_step` / `_ELEMENT_ADJUST_STEPS`.
- `services/conversation/checkpoints.py` *(new)* — capture, restore, supersede. Kept out of `orchestrator_v2` so the DB work has one home and the orchestrator stays a router.
- `services/conversation/orchestrator_v2.py` — capture hook, `handle_back(seq)`, `_public` emits `back_targets`; remove `_restart_element` / `_back_used` / `back_removes_element`.
- `api/routes/chat.py` — `/back` takes a body; thread the live canvas on every v2 turn.
- `api/routes/sessions.py` — filter superseded chat rows.
- `prompts.py` — back-menu copy; remove `V2_BACK_RESTART_ACK`.

**Frontend**
- `store/chatStore.ts` — `backTargets`, `goBackTo`, `canvas_restore`; send the canvas every v2 turn; remove `backRemovesElement`.
- `components/CustomiseStudio/ChatColumn.tsx` — destination menu; remove the confirm.
- `components/DesignStudio/Surface.tsx` — `Design for <Name>`.
- `lib/api.ts` — `sendBack(sessionId, seq)`.
