-- C6.2: per-render operational notes (e.g. "back face not rendered — no back
-- angle photo for this product"). Surfaced to sales in the admin quote-requests
-- view. Design data only, no customer PII.
alter table generations add column if not exists render_notes jsonb;
