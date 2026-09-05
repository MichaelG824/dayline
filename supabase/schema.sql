-- Dayline schema for Supabase (Postgres).
--
-- Mirrors src/dayline/models.py exactly - that file is the source of
-- truth for field names and enum values; keep this in sync with it by hand
-- (see AGENTS.md).
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create extension if not exists pgcrypto;

-- Enums --------------------------------------------------------------------

create type task_category as enum (
  'Behavioral', 'AI Coding', 'Leetcode', 'System Design', 'Errand', 'Other'
);
create type task_priority as enum ('P0', 'P1', 'P2', 'P3');
create type task_status as enum ('Backlog', 'Scheduled', 'Done');
create type task_window as enum ('Morning', 'Afternoon', 'Evening');
create type task_recurrence as enum ('Daily', 'Weekdays', 'Weekly');
create type task_weekday as enum ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun');
create type application_stage as enum (
  'Applied', 'Phone Screen', 'Technical', 'Onsite', 'Offer', 'Rejected'
);

-- Tables ---------------------------------------------------------------------

create table applications (
  id uuid primary key default gen_random_uuid(),
  company text not null,
  role text not null,
  stage application_stage not null default 'Applied',
  applied_at timestamptz,
  next_interview_at timestamptz,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table tasks (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  category task_category not null,
  priority task_priority not null,
  est_duration_min integer not null check (est_duration_min > 0),
  status task_status not null default 'Backlog',
  fixed_time timestamptz,
  preferred_window task_window,
  due_date timestamptz,
  recurs task_recurrence,
  recur_day task_weekday,
  -- The task this preps for, if any. NULL means a plain to-do unrelated to
  -- the job funnel. Deleting an application un-links its tasks rather than
  -- deleting them.
  application_id uuid references applications(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index tasks_application_id_idx on tasks (application_id);
create index tasks_status_idx on tasks (status);
create index applications_next_interview_idx on applications (next_interview_at);

-- Keep updated_at current on every row change ---------------------------------

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger applications_set_updated_at
  before update on applications
  for each row execute function set_updated_at();

create trigger tasks_set_updated_at
  before update on tasks
  for each row execute function set_updated_at();

-- Row Level Security -----------------------------------------------------
-- This app is single-user with no browser-facing Supabase calls: the
-- FastAPI backend is the only client, using the service_role key (never the
-- anon key, never exposed to web/). Enable RLS with no policies, which
-- blocks the anon/public API entirely while the service_role key bypasses
-- RLS by design - the standard "server-only access" posture.
alter table applications enable row level security;
alter table tasks enable row level security;
