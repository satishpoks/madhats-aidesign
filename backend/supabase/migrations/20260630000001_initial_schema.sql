-- MadHats AI Design Studio — initial schema
-- Run via: supabase db push  (or paste into the Supabase SQL editor)

-- =========================================================================
-- stores (tenants)
-- One row per Shopify storefront. Pooled multi-tenancy: every tenant-scoped
-- table carries store_id. public_key is a PUBLISHABLE key embedded in each
-- store's widget snippet and sent as the X-Store-Key header — not a secret.
-- Provider API keys (Gemini/Anthropic/Resend) remain shared, in env vars.
-- =========================================================================
create table if not exists stores (
  id                        uuid primary key default gen_random_uuid(),
  slug                      text unique not null,
  name                      text not null,
  public_key                text unique not null,        -- X-Store-Key (publishable)
  shopify_domain            text,
  allowed_origins           text[] not null default '{}', -- storefront origins for CORS/validation
  persona_name              text not null default 'Ricardo',
  persona_avatar_url        text,
  greeting_template         text,
  brand                     jsonb default '{}'::jsonb,    -- { primary_colour, logo_url, watermark_asset_url }
  sales_notification_email  text,
  status                    text not null default 'active', -- active | inactive
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);
create index if not exists idx_stores_public_key on stores(public_key);

-- =========================================================================
-- design_sessions
-- =========================================================================
create table if not exists design_sessions (
  id            uuid primary key default gen_random_uuid(),
  store_id      uuid references stores(id) on delete cascade,
  share_token   text unique not null,
  state         text not null default 'greeting',
  channel       text not null default 'web',          -- web | mobile
  entry_path    text not null default 'pick_first',   -- pick_first | describe_first
  product_ref   jsonb,
  collected     jsonb default '{}'::jsonb,
  status        text not null default 'draft',
  upsell_count  int not null default 0,               -- max 2
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
create index if not exists idx_design_sessions_store on design_sessions(store_id);

-- =========================================================================
-- chat_messages
-- =========================================================================
create table if not exists chat_messages (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid references design_sessions(id) on delete cascade,
  role          text not null,                        -- user | assistant
  content       text not null,
  state_before  text not null,
  state_after   text not null,
  created_at    timestamptz not null default now()
);
create index if not exists idx_chat_messages_session on chat_messages(session_id, created_at);

-- =========================================================================
-- generations
-- =========================================================================
create table if not exists generations (
  id               uuid primary key default gen_random_uuid(),
  session_id       uuid references design_sessions(id) on delete cascade,
  job_id           uuid unique not null default gen_random_uuid(),
  tier             text not null,                     -- preview | final
  model            text not null,
  status           text not null default 'pending',   -- pending | complete | failed
  image_url        text,
  watermarked_url  text,
  prompt_hash      text,
  cost_usd         numeric(10,6),
  latency_ms       int,
  created_at       timestamptz not null default now()
);
create index if not exists idx_generations_session on generations(session_id);
create index if not exists idx_generations_prompt_hash on generations(prompt_hash);

-- =========================================================================
-- approval_submissions
-- =========================================================================
create table if not exists approval_submissions (
  id                uuid primary key default gen_random_uuid(),
  session_id        uuid references design_sessions(id),
  product_ref       jsonb not null,
  final_image_urls  text[] not null default '{}',
  source_ref        jsonb,
  customer          jsonb,                            -- never written to logs
  review_status     text not null default 'pending',  -- pending | approved | rejected | needs_changes
  reviewer_notes    text,
  decided_at        timestamptz,
  created_at        timestamptz not null default now()
);

-- =========================================================================
-- product_references (stub data for prototype; Shopify sync for MVP)
-- =========================================================================
create table if not exists product_references (
  id                    uuid primary key default gen_random_uuid(),
  store_id              uuid references stores(id) on delete cascade,
  shopify_product_id    text,
  variant_id            text,
  style                 text not null,
  colour                text not null,
  name                  text not null,
  description           text,
  store_url             text,                          -- product page on madhats.com.au
  reference_image_url   text not null,                 -- clean front view used for compositing
  view_images           jsonb default '{}'::jsonb,     -- { front, back, left, right }
  placement_zones       text[] not null default '{}',
  decoration_types      text[] not null default '{}',
  pricing_slabs         jsonb default '[]'::jsonb
);

-- =========================================================================
-- leads
-- =========================================================================
create table if not exists leads (
  id                  uuid primary key default gen_random_uuid(),
  session_id          uuid references design_sessions(id) on delete cascade,
  name                text not null,
  email               text not null,
  phone               text,
  email_verified      bool not null default false,
  verified_at         timestamptz,
  quote_request_sent  bool not null default false,
  quote_sent_at       timestamptz,
  created_at          timestamptz not null default now()
);

-- =========================================================================
-- email_verifications
-- =========================================================================
create table if not exists email_verifications (
  id          uuid primary key default gen_random_uuid(),
  lead_id     uuid references leads(id) on delete cascade,
  token_hash  text not null,
  expires_at  timestamptz not null,
  used_at     timestamptz
);
create index if not exists idx_email_verifications_token on email_verifications(token_hash);

-- =========================================================================
-- chatbot_config
-- =========================================================================
create table if not exists chatbot_config (
  id                  uuid primary key default gen_random_uuid(),
  persona_name        text not null default 'Ricardo',
  persona_avatar_url  text,
  greeting_template   text not null default 'Hi {name}, I''m Ricardo — MadHats'' AI design assistant.',
  upsell_prompts      jsonb default '[]'::jsonb,
  discount_rules      jsonb default '{}'::jsonb,
  updated_at          timestamptz not null default now()
);

-- =========================================================================
-- Row Level Security
-- The backend uses the service_role key (bypasses RLS). RLS is enabled as
-- defence-in-depth; only the public product catalogue is exposed to anon.
-- =========================================================================
alter table stores               enable row level security;
alter table design_sessions      enable row level security;
alter table chat_messages        enable row level security;
alter table generations          enable row level security;
alter table approval_submissions enable row level security;
alter table product_references   enable row level security;
alter table leads                enable row level security;
alter table email_verifications  enable row level security;
alter table chatbot_config       enable row level security;

-- Public read-only access to the product catalogue.
drop policy if exists products_read_anon on product_references;
create policy products_read_anon on product_references
  for select to anon, authenticated using (true);

-- =========================================================================
-- Role grants
-- The backend authenticates as service_role (BYPASSRLS) but still needs
-- table-level privileges. anon needs SELECT on the public product catalogue.
-- =========================================================================
grant usage on schema public to anon, authenticated, service_role;

grant all privileges on all tables in schema public to service_role;
grant all privileges on all sequences in schema public to service_role;

grant select on product_references to anon, authenticated;

-- Ensure future objects created here are reachable too.
alter default privileges in schema public
  grant all on tables to service_role;
alter default privileges in schema public
  grant all on sequences to service_role;
