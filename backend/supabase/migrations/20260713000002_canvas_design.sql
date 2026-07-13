-- Canvas Design Studio: persist the customer's interactive canvas state.
-- Additive + nullable; customise/blank chat sessions leave it NULL.
alter table public.design_sessions
  add column if not exists canvas_design jsonb;

comment on column public.design_sessions.canvas_design is
  'Interactive canvas state (faces -> elements, colourway) for flow_mode=canvas sessions.';
