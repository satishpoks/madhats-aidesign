-- Decoupled async generation + gated preview delivery.
-- Adds the idempotency flag on leads and error/attempts tracking on
-- generations, so the delivery primitive (app/services/delivery.py) can
-- gate sending on "verified AND has a complete image AND not already sent".
alter table leads       add column if not exists preview_email_sent bool not null default false;
alter table leads       add column if not exists preview_sent_at    timestamptz;
alter table generations add column if not exists error              text;
alter table generations add column if not exists attempts           int  not null default 0;
