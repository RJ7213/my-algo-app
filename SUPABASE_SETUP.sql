create table if not exists public.paper_persistence (
  id text primary key,
  payload jsonb not null,
  updated_at timestamptz not null default now()
);

alter table public.paper_persistence enable row level security;

grant all on table public.paper_persistence to service_role;

-- The Python server uses SUPABASE_SERVICE_ROLE_KEY.
-- Never place the service-role key in Streamlit/browser code.
