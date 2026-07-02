-- Request-a-Quote flow: an explicit, customer-initiated quote request.
-- Distinct from quote_request_sent (auto-notify at preview delivery). These
-- columns record that the customer opened the emailed quote link, confirmed
-- their design, and asked us to prepare a quote — the "hot lead" signal.
alter table leads add column if not exists notify_by_phone   bool not null default false;
alter table leads add column if not exists quote_note         text;
alter table leads add column if not exists quote_confirmed    bool not null default false;
alter table leads add column if not exists quote_confirmed_at timestamptz;
