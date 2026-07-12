-- Blank-hat design flow: admin-managed blank hat catalogue + session flow_mode.

create table if not exists hat_types (
  id                uuid primary key default gen_random_uuid(),
  store_id          uuid references stores(id) on delete cascade,
  slug              text not null,
  name              text not null,
  style             text not null default '',
  description       text,
  blank_view_images jsonb not null default '{}'::jsonb,   -- {front,back,left,right} storage paths
  colours           jsonb not null default '[]'::jsonb,   -- [{name, hex}]
  placement_zones   text[] not null default '{}',
  decoration_types  text[] not null default '{}',
  pricing_slabs     jsonb not null default '[]'::jsonb,
  active            bool not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (store_id, slug)
);
create index if not exists idx_hat_types_store on hat_types(store_id);

alter table design_sessions
  add column if not exists flow_mode text not null default 'customise';

-- RLS: service_role full (BYPASSRLS); anon may read only ACTIVE hat types.
alter table hat_types enable row level security;
drop policy if exists hat_types_read_anon on hat_types;
create policy hat_types_read_anon on hat_types
  for select to anon, authenticated using (active = true);

grant select on hat_types to anon, authenticated;
grant all privileges on hat_types to service_role;
