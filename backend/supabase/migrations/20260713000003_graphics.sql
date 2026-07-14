-- Graphics library: admin-managed clipart + company graphics the customer can
-- drag onto the canvas. Store-scoped (multi-tenant), raster images in the
-- private bucket, served to the browser via the /media proxy.

create table if not exists graphics (
  id           uuid primary key default gen_random_uuid(),
  store_id     uuid references stores(id) on delete cascade,
  category     text not null default 'clipart' check (category in ('clipart', 'company')),
  name         text not null default '',
  storage_path text not null,                       -- private-bucket object path
  sort_order   int  not null default 0,
  active       bool not null default true,
  created_at   timestamptz not null default now()
);
create index if not exists idx_graphics_store on graphics(store_id, category);

-- RLS: service_role full (BYPASSRLS); anon may read only ACTIVE graphics.
alter table graphics enable row level security;
drop policy if exists graphics_read_anon on graphics;
create policy graphics_read_anon on graphics
  for select to anon, authenticated using (active = true);

grant select on graphics to anon, authenticated;
grant all privileges on graphics to service_role;
