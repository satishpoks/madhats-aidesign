-- Admin authentication + per-store authorization.
-- Named admin users log in with email + password; each is assigned 1+ stores.
-- The env ADMIN_SECRET remains the un-deletable bootstrap super admin (no row).

create table if not exists admin_users (
  id            uuid primary key default gen_random_uuid(),
  email         text not null,
  password_hash text not null,          -- pbkdf2_sha256$iterations$salt_b64$hash_b64
  is_super      boolean not null default false,
  status        text not null default 'active',   -- active | disabled
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create unique index if not exists idx_admin_users_email on admin_users (lower(email));

create table if not exists admin_user_stores (
  admin_user_id uuid not null references admin_users(id) on delete cascade,
  store_id      uuid not null references stores(id) on delete cascade,
  primary key (admin_user_id, store_id)
);
create index if not exists idx_admin_user_stores_store on admin_user_stores (store_id);
