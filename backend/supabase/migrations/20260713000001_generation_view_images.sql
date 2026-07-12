-- Multi-view generation: a design may AI-render several angles (front hero +
-- any decorated back/side view). The primary hero stays in image_url /
-- watermarked_url (backward-compatible: polling, cache, delivery gate); the full
-- per-view set is stored here as { view: { image_url, watermarked_url } }.
alter table generations
  add column if not exists view_images jsonb not null default '{}'::jsonb;
