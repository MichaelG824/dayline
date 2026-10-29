-- LeetCode problem tracking (the Problems tab), ported from the standalone
-- leetcode-tracker app. Mirrors Problem / Solution / ProblemTag in
-- src/dayline/models.py - keep in sync by hand.
--
-- * problems: the durable thing being practiced (notes, status, confidence).
-- * problem_solutions: many approaches per problem.
-- * problem_tags + problem_tag_links: shared topic tags, many-to-many.
-- * tasks.problem_id: a scheduled practice session links to its problem.
--   Deleting a problem un-links its tasks rather than deleting them.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create type problem_difficulty as enum ('Easy', 'Medium', 'Hard');
create type problem_status as enum ('To do', 'Attempted', 'Solved', 'Review');

create table problems (
  id uuid primary key default gen_random_uuid(),
  number integer,
  slug text,
  title text not null,
  url text,
  difficulty problem_difficulty not null,
  status problem_status not null default 'To do',
  confidence integer check (confidence between 1 and 5),
  notes text not null default '',
  starred boolean not null default false,
  last_attempted_at timestamptz,
  solved_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table problem_solutions (
  id uuid primary key default gen_random_uuid(),
  problem_id uuid not null references problems(id) on delete cascade,
  title text not null,
  language text not null,
  code text not null default '',
  time_complexity text,
  space_complexity text,
  explanation text not null default '',
  is_optimal boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table problem_tags (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  color text
);

create table problem_tag_links (
  problem_id uuid not null references problems(id) on delete cascade,
  tag_id uuid not null references problem_tags(id) on delete cascade,
  primary key (problem_id, tag_id)
);

alter table tasks
  add column if not exists problem_id uuid references problems(id) on delete set null;

create index problems_status_idx on problems (status);
create index problem_solutions_problem_id_idx on problem_solutions (problem_id);
create index problem_tag_links_tag_id_idx on problem_tag_links (tag_id);
create index tasks_problem_id_idx on tasks (problem_id);

create trigger problems_set_updated_at
  before update on problems
  for each row execute function set_updated_at();

create trigger problem_solutions_set_updated_at
  before update on problem_solutions
  for each row execute function set_updated_at();

-- Server-only access, same posture as every other table (see schema.sql).
alter table problems enable row level security;
alter table problem_solutions enable row level security;
alter table problem_tags enable row level security;
alter table problem_tag_links enable row level security;
