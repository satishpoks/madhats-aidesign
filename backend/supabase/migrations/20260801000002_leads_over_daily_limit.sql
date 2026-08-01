-- v2 daily-limit early-warn (ported from 19bae6e, 2026-07-25 design). When a
-- customer's email is already over the daily design cap at email capture, the
-- v2 canvas flow warns (it never blocks — the flow is quote-gated) and persists
-- this flag so the admin can see which emails exceeded the limit, even after
-- the rolling 24h window later drops the count below the cap. Set once, at
-- email capture, by leads.flag_over_daily_limit.
alter table leads add column if not exists over_daily_limit    bool not null default false;
alter table leads add column if not exists over_daily_limit_at timestamptz;
