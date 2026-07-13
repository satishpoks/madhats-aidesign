-- Decoration types: admin-managed, per-store list of decoration methods
-- (embroidery, print, patch, …) offered to the customer AFTER they design on
-- the canvas. Store-scoped (multi-tenant). Mirrors the graphics table pattern.

create table if not exists decoration_types (
  id         uuid primary key default gen_random_uuid(),
  store_id   uuid references stores(id) on delete cascade,
  name       text not null,
  sort_order int  not null default 0,
  active     bool not null default true,
  created_at timestamptz not null default now()
);
create unique index if not exists idx_decoration_types_store_name
  on decoration_types(store_id, lower(name));
create index if not exists idx_decoration_types_store on decoration_types(store_id);

-- RLS: service_role full; anon may read only ACTIVE rows (customer chip list).
alter table decoration_types enable row level security;
drop policy if exists decoration_types_read_anon on decoration_types;
create policy decoration_types_read_anon on decoration_types
  for select to anon, authenticated using (active = true);

grant select on decoration_types to anon, authenticated;
grant all privileges on decoration_types to service_role;
