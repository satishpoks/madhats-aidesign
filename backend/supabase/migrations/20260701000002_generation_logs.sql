-- Per-call image generation audit log.
--
-- One row per actual provider call (each retry attempt is its own row); cache
-- hits get a single 'cache_hit' row. Inputs (reference image, uploaded logo,
-- full prompt, params) are written before the call; the model response
-- (metadata + full raw response) and output image path after. Images are stored
-- as references — the bytes live in Supabase Storage. No customer PII here.

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
  status              text not null default 'requested',   -- requested | complete | failed | cache_hit
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
