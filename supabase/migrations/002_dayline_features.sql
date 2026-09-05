-- Migration 002: Dayline feature set - category restructure, planned_date,
-- interviews, and category focus weighting.
--
-- Run after 001 (schema.sql) has already been applied. Written as a separate
-- migration rather than editing schema.sql in place, since schema.sql is
-- treated as already-deployed history.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

-- 1. Category enum: split the old single 'AI Coding' bucket into the two
--    ranked variants the user actually distinguishes (AI-assisted React/Python
--    practice vs. AI-assisted DSA practice). Postgres can add enum values
--    cheaply but can't drop them in the same transaction-safe way, so the old
--    'AI Coding' value is left in place, unused, rather than removed. If real
--    rows already use 'AI Coding', reassign them by hand to one of the two new
--    values before relying on the new categories for those tasks - there is no
--    reliable automatic mapping.
alter type task_category add value if not exists 'AI Coding - React/Python';
alter type task_category add value if not exists 'AI Coding - DSA';

-- 2. planned_date on tasks: the specific calendar day a one-shot task should
--    be worked, distinct from due_date (a deadline) and fixed_time (a
--    time-of-day anchor). NULL preserves the original "eligible every day
--    until done" backlog behavior.
alter table tasks add column if not exists planned_date date;
create index if not exists tasks_planned_date_idx on tasks (planned_date);

-- scheduled_time: the outcome of the last planning run (when the scheduler
-- actually placed this task), distinct from fixed_time (an immutable anchor
-- the planner re-reads every run). Not a Task dataclass field - mirrors how
-- InMemoryTaskSource tracks it on the side too.
alter table tasks add column if not exists scheduled_time timestamptz;

-- 3. Interviews: a separate entity from applications.next_interview_at, since
--    one company can have multiple rounds of different types at different
--    times (e.g. a Behavioral round Tuesday and a System Design round
--    Thursday for the same company).
create type interview_category as enum (
  'AI Coding - React/Python', 'AI Coding - DSA', 'Behavioral', 'System Design', 'Leetcode'
);

create table interviews (
  id uuid primary key default gen_random_uuid(),
  -- Deleting the application deletes its interviews too (unlike
  -- tasks.application_id's on delete set null): an interview round without
  -- its application is meaningless, whereas a task can stand alone.
  application_id uuid not null references applications(id) on delete cascade,
  category interview_category not null,
  scheduled_at timestamptz not null,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index interviews_application_id_idx on interviews (application_id);
create index interviews_scheduled_at_idx on interviews (scheduled_at);

create trigger interviews_set_updated_at
  before update on interviews
  for each row execute function set_updated_at();

alter table interviews enable row level security;

-- Optional link from a task to the specific interview it preps for, so the
-- scheduler can bump that task's effective priority as the interview
-- approaches (see dayline/scheduler/run.py's interview-proximity bump).
alter table tasks add column if not exists interview_id uuid references interviews(id) on delete set null;
create index if not exists tasks_interview_id_idx on tasks (interview_id);

-- 4. Category focus weighting: lets the user re-rank the 5 prep categories'
--    default priority without hand-editing every existing task. See
--    dayline/adapters/category_weights.py for how this is read/written.
create table category_weights (
  category task_category primary key,
  priority task_priority not null,
  updated_at timestamptz not null default now()
);

create trigger category_weights_set_updated_at
  before update on category_weights
  for each row execute function set_updated_at();

alter table category_weights enable row level security;

-- Seeding the default ranking is in 003_seed_category_weights.sql, run
-- separately: Postgres won't let a new enum value (added above via ALTER
-- TYPE ... ADD VALUE) be used in the same transaction that added it.
