-- Generated full-stack practice projects (the Mock tab's project generator).
-- Mirrors GeneratedProject / GenerationStatus in src/dayline/models.py - keep
-- in sync by hand. Needs 011 (set_updated_at comes from schema.sql) and 013.
--
-- * One row per generation: the candidate's inputs (request), the imported
--   context files (private: only ever sent to the generator model), live
--   progress while it runs, the validated project once ready (artifact:
--   baseline files, the task and change request with their hidden tests and
--   reference solutions, interviewer notes, grader hints), the attempt log
--   kept for debugging, and the tokens it used.
-- * owner is the signed-in email: every read filters on it.
-- * A staged round started from a project stores the project's id in
--   mock_sessions.staged_problem_id (text, as for built-in problems), so no
--   change to mock_sessions.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create table mock_generated_projects (
  id uuid primary key default gen_random_uuid(),
  owner text not null,
  status text not null default 'generating'
    check (status in ('generating', 'ready', 'failed', 'cancelled')),
  -- {prompt, stack, difficulty, durationMin, changeRequestMin, feedback}
  request jsonb not null default '{}',
  -- [{name, content}]
  context_files jsonb not null default '[]',
  title text not null default '',
  -- {phase, attempt, detail} while generating
  progress jsonb not null default '{}',
  artifact jsonb,
  error text not null default '',
  log jsonb not null default '[]',
  -- {inputTokens, outputTokens, cacheReadTokens, cacheWriteTokens, calls}
  usage jsonb not null default '{}',
  -- The project this one regenerates (deleted once this one is ready).
  parent_id uuid references mock_generated_projects(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  finished_at timestamptz
);

create index mock_generated_projects_owner_idx
  on mock_generated_projects (owner, created_at desc);

create trigger mock_generated_projects_set_updated_at
  before update on mock_generated_projects
  for each row execute function set_updated_at();

alter table mock_generated_projects enable row level security;
