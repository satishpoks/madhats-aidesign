# Admin Generation-Jobs Panel — Design

**Date:** 2026-07-14
**Status:** Approved

## Problem

When an image-generation job stalls (a hung/deadline-bound provider call), the
only way to see it or unstick it today is via raw SQL / curl against the DB and
the admin endpoints. That requires a developer. Ops needs a self-serve way to
**see generation jobs and their status** and **trigger a fix** for stuck ones,
directly in the admin panel.

Context: an automatic watchdog (`/admin/generations/reap-stuck`, driven by a
compose sidecar every 180s) plus a new per-call provider timeout already
self-heal most stalls. This feature is about **visibility** and a **manual
override**, not replacing the automatic path.

## Scope

In:
- A read-only endpoint to list recent generation jobs with status.
- An OpsView section: summary tiles, a live table, auto-refresh, and a
  "Reap stuck now" button (reuses the existing bulk `reap-stuck`).

Out (YAGNI): per-job retry, per-store filtering, pagination beyond a `limit`.

## Backend

### `GET /admin/generations` (new, in `admin_generations.py`)

Gated by `X-Admin-Secret` (like the rest of `/admin/*`).

Query params:
- `status` — optional filter: `pending | failed | complete`. Omitted = recent
  across all statuses.
- `limit` — default 50, 1..200.
- `stuck_minutes` — default `generate.STUCK_MINUTES_DEFAULT`; used only to
  compute the `stalled` flag.

Response (plain dict, matching the diagnostics routes):
```json
{
  "summary": { "pending": 0, "stalled": 0, "failed": 0, "complete": 0 },
  "stuck_minutes": 8,
  "items": [
    {
      "job_id": "…", "session_id": "…", "store_id": "…",
      "tier": "preview", "status": "pending", "model": "pending",
      "error": null, "attempts": 0,
      "created_at": "…", "age_seconds": 123, "stalled": false
    }
  ]
}
```

Rules:
- **No customer PII** — no prompt, no `collected`, no lead details. Only the
  operational job fields above.
- `stalled` = `status == "pending"` AND `age_seconds >= stuck_minutes*60`.
- `summary` counts are computed over the returned window (recent `limit` rows,
  or the filtered set), so the tiles reflect what the table shows. `stalled` is
  a subset of `pending`.
- Ordered newest-first by `created_at`.

`reap-stuck` is unchanged.

## Frontend

### `adminApi.ts`
- `listGenerations(status?, limit?, stuckMinutes?): Promise<GenerationJobs>`
- `reapStuck(stuckMinutes?): Promise<ReapResult>` → `POST /admin/generations/reap-stuck`
- Types: `GenerationJob`, `GenerationJobs` (`{summary, stuck_minutes, items}`),
  `ReapResult` (`{reaped, retried, gave_up}`).

### `OpsView.tsx` — new "Generation jobs" section (above or below existing ones)
- **Summary tiles:** Pending · Stalled · Failed · Complete (Stalled tile
  emphasised when > 0).
- **Controls:** a status filter (All/Pending/Failed/Complete), a Refresh
  button, an Auto-refresh toggle (poll ~10s), and a "Reap stuck now" button.
- **Table:** status badge, age (humanised), tier, model, session id
  (truncated), error snippet. **Stalled rows highlighted amber.**
- **Reap flow:** "Reap stuck now" asks for confirmation (it re-enqueues real
  renders), calls `reapStuck`, shows the `{reaped, retried, gave_up}` tally,
  then re-fetches the list.
- Empty state when no jobs; `ErrorBanner` on fetch/reap failure.

## Data flow

Mount → `listGenerations(filter)` → render tiles + table. Auto-refresh interval
re-fetches with the current filter. "Reap stuck now" → `reapStuck()` → tally →
immediate re-fetch. The status filter re-fetches on change.

## Testing

Backend (`tests/test_admin_generations.py`):
- Lists rows newest-first; `status` filter narrows results.
- `stalled` flag true for an old pending row, false for a recent one and for
  non-pending rows.
- `summary` counts match; response carries no prompt/collected/lead fields.
- Auth gate: missing/wrong `X-Admin-Secret` → 401.

Frontend (`OpsView.test.tsx`):
- Renders summary tiles + table rows from a mocked `listGenerations`.
- "Reap stuck now" (confirmed) calls `reapStuck` and triggers a re-fetch.

## Non-goals / trade-offs

- The `summary` reflects the fetched window, not a global DB aggregate — keeps
  the query single-round-trip and matches the table. Good enough for triage.
- No websocket/live push; a 10s poll is sufficient for an ops screen.
