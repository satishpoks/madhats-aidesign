-- Per-store branding is stored in the existing stores.brand jsonb (no structural
-- change). This migration only documents the widened shape:
--   brand = {
--     logo_url text (storage path, served via /media proxy),
--     primary_colour text (#hex), header_bg text (#hex), header_text text (#hex),
--     watermark_asset_url text (internal),
--     menu_items jsonb: [{label text, url text}]  -- max 5, http(s) only
--   }
comment on column stores.brand is
  'Per-store branding: logo_url, primary_colour, header_bg, header_text, watermark_asset_url, menu_items[{label,url}]';
