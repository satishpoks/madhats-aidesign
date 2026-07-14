-- Configurable watermark text (single diagonal line stamped on preview images),
-- editable from the admin Settings panel.
alter table app_settings
  add column if not exists watermark_text text not null default 'MADHATS PREVIEW';
