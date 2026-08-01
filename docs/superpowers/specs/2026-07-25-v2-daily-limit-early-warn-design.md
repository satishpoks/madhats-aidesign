# v2 canvas — daily-limit early warn + admin over-limit flag

**Date:** 2026-07-25
**Scope:** backend only (v2 canvas orchestrator). No frontend badge (deferred).
**Flag:** applies only when `CANVAS_ORCHESTRATOR_V2` and `flow_mode == "canvas"`.

## Problem

The v2 canvas flow is **quote-gated**: the customer never triggers an AI render —
they build the canvas, request a quote, and the render is produced **admin-side
later** (`sessions.py` canvas-finalize v2 branch). But `orchestrator_v2` still ran
a leftover **honesty gate** at `FINALIZE_CANVAS`:

```python
if next_.id is S.FINALIZE_CANVAS and not _can_start_design(session_id):
    reply = GENERATION_BLOCKED_ASIDE + CANVAS_QUOTE_ASK
    return _persist(..., S.QUOTE_REQUESTED, ...)   # v1-owned tail
```

`_can_start_design` counts **AI renders per email in 24h** (cap
`designs_per_customer_per_day`, default 2). Since a v2 customer never renders, that
counter only trips from unrelated/legacy renders on the same email. When it did
(live session `1a1b0ef2`), the customer — who had just tapped "Request a quote" —
saw "You've reached today's design limit, so I can't spin up a fresh render right
now", then the NEXT turn was handled by **v1** (`QUOTE_REQUESTED` is a v1-owned
shared tail state), landing on v1's "I've opened your quote form below" →
`session_end`. Three flaws: (1) a render-limit message in a flow that never
renders, (2) sprung at the very end after the whole design, (3) a v1 detour that
breaks the strictly-v2 experience.

## Decisions (product)

- **Warn early, still allow.** Keep the existing render counter. Check it once, at
  email capture. If over, show a gentle heads-up and **continue** the v2 flow to
  `REQUEST_QUOTE → FINALIZE_CANVAS` (nothing blocked, no v1 detour).
- **Persist an over-limit flag on the lead** so the admin can know which email
  exceeded the limit. (Frontend badge NOT built — the flag is surfaced in the
  `/admin/quote-requests` API response; a view badge can be added later.)

## Changes

1. **`orchestrator_v2.handle_message`**
   - Delete the `FINALIZE_CANVAS` honesty gate block.
   - In the existing `ASK_EMAIL` post-capture block (where `email_captured` is
     freshly set and the verify-notice is prepended): if
     `not _can_start_design(session_id)`, prepend `prompts.V2_DAILY_LIMIT_NOTICE`
     and call `leads_service.flag_over_daily_limit(collected["lead_id"])`.

2. **`prompts.py`** — add `V2_DAILY_LIMIT_NOTICE` (honest copy for a no-render
   flow; `{name}` placeholder). Leave `GENERATION_BLOCKED_ASIDE` / `CANVAS_QUOTE_ASK`
   (v1 still uses them).

3. **`services/leads.py`** — add `flag_over_daily_limit(lead_id)` → best-effort
   update `over_daily_limit=true, over_daily_limit_at=now()`. No-op on missing id.
   PII-safe (lead id only in logs).

4. **`api/routes/admin_leads.py::list_quote_requests`** — include
   `over_daily_limit` + `over_daily_limit_at` in the response dict.

5. **Migration** `supabase/migrations/20260725000001_leads_over_daily_limit.sql` —
   `over_daily_limit boolean not null default false`, `over_daily_limit_at timestamptz`.
   Must be applied to the hosted Supabase.

## Non-goals / notes

- The notice is informational only — every v2 design goes to the team regardless
  of the cap, so this signals "you've been busy today", it does not change routing.
- Check happens **once**, at email capture; the flag records "was over at email
  time" (matches the rolling-window caveat — accepted).
- v1 orchestrator, `limits.py`, and the shared tail are untouched.

## Tests (TDD)

- Capped at `ASK_EMAIL` → reply contains the notice, state advances to the next
  design step (not `QUOTE_REQUESTED`), and the lead is flagged.
- Not capped at `ASK_EMAIL` → no notice, no flag.
- Reaching `FINALIZE_CANVAS` while capped → returns `FINALIZE_CANVAS` +
  `trigger_finalize`, never `QUOTE_REQUESTED`.
- `leads.flag_over_daily_limit` sets both columns; no-ops on `None`.
- `list_quote_requests` returns the flag.
- Rewrite `test_daily_cap_reroutes_to_the_quote_ask` to the early-warn behavior.

---

**Port note (2026-08-01):** this spec was written against a branch 131 commits
behind current `master` and does not describe the exact registry state at port
time — most notably, `AWAIT_EMAIL_VERIFY` (a hard email-verification gate) was
added directly after `ASK_EMAIL` on 2026-07-26, after this spec was written, so
"the next design step" the email-capture turn now advances to is
`AWAIT_EMAIL_VERIFY`, not a design step. The decisions and mechanism above
(check once at email capture, warn-and-continue, delete the `FINALIZE_CANVAS`
honesty gate, persist `leads.over_daily_limit`) were ported unchanged; the
migration was re-dated `20260801000002` to sort after everything already applied
on this branch. See `orchestrator_v2.py` and `test_orchestrator_v2.py` for the
adapted implementation and tests.
