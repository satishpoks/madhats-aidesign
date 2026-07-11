-- Tracks whether the "final design" email (sent when the customer settles on a
-- regenerated design) has gone out, so it is sent at most once.
alter table leads add column if not exists final_email_sent boolean not null default false;
alter table leads add column if not exists final_email_sent_at timestamptz;
