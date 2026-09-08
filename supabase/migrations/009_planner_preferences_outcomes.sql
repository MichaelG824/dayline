-- Planner preference memory + lightweight outcome log for analysis-first chat.
--
-- preferences: single-row JSON prefs (peak hours, category caps, standing rules)
--   injected into the chat system prompt / get_preferences tool every turn.
-- outcomes: append-only events (proposal accept/reject, completions, duration
--   overrides) read via get_recent_outcomes for retros. Never auto-mutates ranks.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create table if not exists planner_preferences (
  id text primary key default 'default',
  preferences jsonb not null default '{}'::jsonb,
  free_text text,
  updated_at timestamptz not null default now()
);

insert into planner_preferences (id, preferences)
values ('default', '{}'::jsonb)
on conflict (id) do nothing;

create table if not exists planner_outcomes (
  id uuid primary key default gen_random_uuid(),
  kind text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists planner_outcomes_created_at_idx
  on planner_outcomes (created_at desc);

create trigger planner_preferences_set_updated_at
  before update on planner_preferences
  for each row execute function set_updated_at();

alter table planner_preferences enable row level security;
alter table planner_outcomes enable row level security;
