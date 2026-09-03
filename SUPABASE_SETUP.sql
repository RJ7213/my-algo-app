create table if not exists public.paper_persistence (
  id text primary key,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.paper_persistence enable row level security;

-- The Python server uses SUPABASE_SERVICE_ROLE_KEY, so no public policy is needed.
-- Do NOT put the service-role key in frontend code or expose it publicly.
