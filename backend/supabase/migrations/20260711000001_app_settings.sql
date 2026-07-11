-- Global (single-row) studio settings, editable from the admin panel with no
-- developer involvement. id is pinned to 1 so there is always exactly one row.
create table if not exists app_settings (
  id                            int primary key default 1,
  regen_edits_per_session       int  not null default 3,
  designs_per_customer_per_day  int  not null default 2,
  faq_knowledge                 text not null default '',
  updated_at                    timestamptz not null default now(),
  constraint app_settings_singleton check (id = 1)
);

insert into app_settings (id) values (1) on conflict (id) do nothing;
