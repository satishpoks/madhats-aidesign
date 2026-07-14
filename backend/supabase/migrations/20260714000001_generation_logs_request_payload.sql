-- Replace generation_logs.params with the real image-model send payload.
--
-- `params` held GenerationParams (placement/decoration/remove_bg), which is NOT
-- what actually shapes the model call — the image model receives `contents`
-- (labelled reference/logo/layout-guide images + the final prompt). We now log
-- that exact final payload instead: `request_payload` = { model, contents:[...] }
-- with text parts verbatim and image parts as role/mime/source_url/byte-size
-- (the bytes themselves live in Storage, referenced by source_url).
alter table generation_logs add column if not exists request_payload jsonb;
alter table generation_logs drop column if exists params;
