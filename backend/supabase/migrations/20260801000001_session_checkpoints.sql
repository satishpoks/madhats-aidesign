-- =========================================================================
-- session_checkpoints — snapshot-and-restore for the v2 canvas Back menu.
-- Rows are append-only: a restore marks later rows superseded_at, never
-- deletes them, so a discarded branch stays reconstructable for audit.
-- =========================================================================
create table if not exists session_checkpoints (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references design_sessions(id) on delete cascade,
  seq            int  not null,
  kind           text not null,
  label          text not null,
  step_id        text not null,
  collected      jsonb not null,
  canvas_design  jsonb,
  chat_watermark uuid,
  created_at     timestamptz not null default now(),
  superseded_at  timestamptz
);
create unique index if not exists idx_session_checkpoints_seq
  on session_checkpoints(session_id, seq);
create index if not exists idx_session_checkpoints_live
  on session_checkpoints(session_id, seq) where superseded_at is null;

alter table session_checkpoints enable row level security;

-- Chat rows are hidden from the customer after a restore branches past them,
-- but retained for the admin/audit reader.
alter table chat_messages add column if not exists superseded_at timestamptz;
