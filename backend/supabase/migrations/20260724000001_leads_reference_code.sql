-- Quote-gated delivery (Workstream C). The customer explicitly requests a quote;
-- we mint a customer-facing tracking reference (MH-XXXXXX), stop emailing the
-- design, and email only the reference after verification. reference_code is the
-- request identity (unique). quote_requested marks the explicit submit gesture;
-- quote_confirmation_sent dedups the one-time customer-reference + sales emails.
alter table leads add column if not exists reference_code          text;
alter table leads add column if not exists quote_requested         bool not null default false;
alter table leads add column if not exists quote_requested_at      timestamptz;
alter table leads add column if not exists quote_confirmation_sent bool not null default false;

create unique index if not exists idx_leads_reference_code
  on leads(reference_code) where reference_code is not null;
