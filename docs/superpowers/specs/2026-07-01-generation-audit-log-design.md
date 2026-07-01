# Per-Call Image Generation Audit Log

**Date:** 2026-07-01
**Status:** Approved (brainstorm)
**Owner:** Backend

## Problem

There is no durable record of what is actually sent to and received from the image
generation model. `generations` stores only `prompt_hash` (not the full prompt),
no input-image references, and no provider response. When a preview looks wrong we
cannot see the exact prompt, the reference/logo images used, or what the model
returned. We need a per-call audit trail: log the inputs (reference image, logo,
params, full prompt) **before** every model call and the outputs (model response
metadata, full raw response, output image) **after** every call.

## Decisions

1. **New append-only `generation_logs` table**, one row per actual provider call,
   so all retry attempts are logged separately (the lean `generations` table is
   untouched).
2. **Images are logged as references** (URLs / storage paths); the bytes already
   live in Supabase Storage. No base64 duplication of inputs/outputs in dedicated
   columns.
3. **Full raw response is captured** in addition to a `response_meta` summary. For
   image models the raw response embeds the base64 image, so `raw_response` rows
   are large; this is accepted.

## Constraints

- **Best-effort:** a logging failure must NEVER break generation. All log writes
  are wrapped in try/except and only warn on failure (same pattern as
  `delivery`/`_safe_maybe_send_preview`).
- **No customer PII** (§8.10): only design data (prompt, params, image refs) is
  stored — never customer name/email/phone/notes.

## Design

### 1. Schema — `backend/supabase/migrations/20260701000002_generation_logs.sql`

```sql
create table if not exists generation_logs (
  id                  uuid primary key default gen_random_uuid(),
  generation_id       uuid references generations(id) on delete cascade,
  job_id              uuid,
  session_id          uuid references design_sessions(id) on delete cascade,
  attempt             int not null,
  tier                text,
  reference_image_url text,
  uploaded_asset_url  text,
  full_prompt         text not null,
  params              jsonb,
  request_at          timestamptz not null default now(),
  status              text not null default 'requested',   -- requested|complete|failed|cache_hit
  model               text,
  output_image_url    text,
  response_meta       jsonb,
  raw_response        jsonb,
  error               text,
  latency_ms          int,
  response_at         timestamptz
);
create index if not exists idx_generation_logs_generation on generation_logs(generation_id);
create index if not exists idx_generation_logs_session on generation_logs(session_id);
```

### 2. Service — `backend/app/services/generation_logger.py`

- `log_request(*, generation_id, job_id, session_id, attempt, tier, reference_image_url, uploaded_asset_url, full_prompt, params) -> str | None`
  Inserts the inputs row with `status='requested'`; returns the new log `id`, or
  `None` on any failure (never raises).
- `log_response(log_id, *, status, model=None, output_image_url=None, response_meta=None, raw_response=None, error=None, latency_ms=None) -> None`
  Updates the row identified by `log_id` (no-op when `log_id` is None); sets
  `response_at=now()`; never raises.
- `log_cache_hit(*, generation_id, job_id, session_id, tier, reference_image_url, uploaded_asset_url, full_prompt, params, model, output_image_url) -> None`
  Convenience: writes a single `status='cache_hit'` row (no `raw_response`).

`params` is serialised from `GenerationParams` via `dataclasses.asdict`.

### 3. Provider response capture

`GenerationResult` (in `image_provider.py`) gains two optional fields:

```python
raw_response: dict | None = None
response_meta: dict | None = None
```

`gemini_base._GeminiAdapter.generate` populates both:
- `raw_response` = `_serialise_response(response)` — a JSON-safe dict. Try
  `type(response).to_dict(response)`; on failure fall back to
  `google.protobuf.json_format.MessageToDict(response._result)`; on any further
  failure `{"unserialisable": true, "repr": str(response)[:2000]}`. Bytes fields
  become base64 automatically.
- `response_meta` = `{model, finish_reason, safety_ratings, image_returned,
  candidate_count}` extracted defensively (missing attrs → omitted/None).

The stub adapter sets `response_meta={"stub": True}` and `raw_response=None`.

### 4. Worker wiring — `backend/app/api/routes/generate.py:_run_generation`

- **Cache hit branch:** call `generation_logger.log_cache_hit(...)` with the
  inputs, prompt, and cached output path before returning.
- **Provider branch, inside the retry loop:** for each attempt,
  `log_id = generation_logger.log_request(..., attempt=attempt)` before
  `provider.generate(...)`. On success:
  `log_response(log_id, status='complete', model, output_image_url=result.image_url,
  response_meta=result.response_meta, raw_response=result.raw_response,
  latency_ms=result.latency_ms)`. On exception (each caught attempt):
  `log_response(log_id, status='failed', error=str(exc))`.

  `reference_image_url` and `uploaded_asset_url` are already known in the worker
  (`product_ref["reference_image_url"]`, the signed `uploaded_url`). A job that
  fails twice then succeeds produces three `generation_logs` rows.

All logger calls are best-effort; the worker's existing behaviour (status
updates, delivery trigger, ops alert) is unchanged.

### 5. Testing

- `tests/test_generation_logger.py` (new): `log_request` inserts the expected
  fields and returns the id; `log_response` updates the matching row and sets
  `response_at`; a raised DB error in either is swallowed (returns None / no-op).
- `tests/test_generate.py` (extended): successful run writes a `requested` then
  `complete` update carrying the raw response; a permanently-failing run writes
  `failed` with the error; a transient-then-success run writes one row per
  attempt; cache hit writes a single `cache_hit` row.
- `tests/test_gemini_adapter.py` (new, no network): `_serialise_response` and the
  `response_meta` extraction run against a fake response object and populate
  `GenerationResult`.

## Out of scope

- A read/admin endpoint for the logs (query via Supabase Studio for now).
- Retention/pruning of large `raw_response` rows (revisit if the table grows).
- Any change to delivery, email, caching, or the frontend.

## Acceptance

- Every provider call writes a `generation_logs` row with the reference image,
  logo reference, full prompt, and params before the call, then the model
  response (meta + raw) and output image after.
- Retries produce one row each; cache hits produce a `cache_hit` row.
- A logging failure never fails a generation.
- Full backend `pytest` suite green.
