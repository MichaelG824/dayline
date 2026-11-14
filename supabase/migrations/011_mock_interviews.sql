-- Mock interviews, phase 1 (the Mock tab): a private question bank, rubrics,
-- interviewer/grading guidelines, and graded sessions. Mirrors MockQuestion /
-- MockRubric / MockGuideline / MockSession / Scorecard in
-- src/dayline/models.py - keep in sync by hand.
--
-- * mock_questions: reported or remembered interview questions. A question
--   reported more than once points at its first copy via canonical_id, so
--   "seen N times" is a count, not a duplicate list.
-- * mock_rubrics: what a round is graded on (criteria + weights, jsonb).
-- * mock_guidelines: free-text standards (how strict, what "good" means).
-- * mock_sessions: one practice attempt. Phase 1 sessions are pasted
--   transcripts; later phases record live sessions into the same table.
-- * mock_scorecards: the grader's output for a session (one per grading run).
-- * tasks.mock_session_id: prep tasks created from a scorecard's weak areas.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create type mock_question_source as enum ('own', '1point3acres', 'other');
create type mock_round_type as enum (
  'AI-assisted project',
  'Algorithm',
  'System design',
  'Debugging',
  'Behavioral'
);

create table mock_questions (
  id uuid primary key default gen_random_uuid(),
  source mock_question_source not null default 'own',
  source_url text,
  company text,
  role text,
  round_type mock_round_type not null,
  title text not null,
  prompt_md text not null default '',
  constraints text[] not null default '{}',
  follow_ups text[] not null default '{}',
  language_hint text,
  original_text text not null default '',
  original_language text,
  reported_on date,
  canonical_id uuid references mock_questions(id) on delete set null,
  notes text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table mock_rubrics (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  round_type mock_round_type,
  -- [{"key": "...", "title": "...", "description": "...", "weight": 1}]
  criteria jsonb not null default '[]',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table mock_guidelines (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  body_md text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table mock_sessions (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  question_id uuid references mock_questions(id) on delete set null,
  rubric_id uuid references mock_rubrics(id) on delete set null,
  guideline_id uuid references mock_guidelines(id) on delete set null,
  transcript text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table mock_scorecards (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references mock_sessions(id) on delete cascade,
  overall_score numeric(4, 2) not null,
  summary text not null default '',
  -- [{"key", "title", "score", "evidence": [{"quote", "verified"}], "improvement"}]
  criteria jsonb not null default '[]',
  strengths text[] not null default '{}',
  -- [{"title", "why", "taskName", "category", "estDurationMin"}]
  weak_areas jsonb not null default '[]',
  grader_model text not null,
  created_at timestamptz not null default now()
);

alter table tasks
  add column if not exists mock_session_id uuid references mock_sessions(id) on delete set null;

create index mock_questions_canonical_id_idx on mock_questions (canonical_id);
create index mock_sessions_created_at_idx on mock_sessions (created_at desc);
create index mock_scorecards_session_id_idx on mock_scorecards (session_id, created_at desc);
create index tasks_mock_session_id_idx on tasks (mock_session_id);

create trigger mock_questions_set_updated_at
  before update on mock_questions
  for each row execute function set_updated_at();

create trigger mock_rubrics_set_updated_at
  before update on mock_rubrics
  for each row execute function set_updated_at();

create trigger mock_guidelines_set_updated_at
  before update on mock_guidelines
  for each row execute function set_updated_at();

create trigger mock_sessions_set_updated_at
  before update on mock_sessions
  for each row execute function set_updated_at();

-- Server-only access, same posture as every other table (see schema.sql).
alter table mock_questions enable row level security;
alter table mock_rubrics enable row level security;
alter table mock_guidelines enable row level security;
alter table mock_sessions enable row level security;
alter table mock_scorecards enable row level security;

-- A starting rubric and guideline so grading works on day one. Edit them in
-- the Mock tab rather than here.
insert into mock_rubrics (name, round_type, criteria) values (
  'AI-assisted coding (default)',
  'AI-assisted project',
  '[
    {"key": "understanding", "title": "Understands the problem", "weight": 1,
     "description": "Restates the task, reads the existing code and tests before changing anything, asks clarifying questions."},
    {"key": "reproduce", "title": "Reproduces before fixing", "weight": 1,
     "description": "Runs the tests or the app to see the failure first, and confirms the fix with the same check."},
    {"key": "ai_use", "title": "Uses the AI critically", "weight": 1.5,
     "description": "Gives the AI focused prompts, reads and verifies what it produces, rejects or corrects wrong suggestions instead of pasting blindly."},
    {"key": "code_quality", "title": "Code quality", "weight": 1,
     "description": "Small, readable changes that match the surrounding code; handles edge cases; no leftover debug code."},
    {"key": "communication", "title": "Communicates while working", "weight": 1,
     "description": "Thinks out loud, explains tradeoffs and decisions, keeps the interviewer informed of progress and blockers."},
    {"key": "follow_ups", "title": "Handles follow-ups", "weight": 1,
     "description": "Answers extension and scaling questions with concrete, reasoned designs rather than buzzwords."}
  ]'
);

insert into mock_guidelines (name, body_md) values (
  'Default standards',
  'Grade like a senior engineer on a real hiring loop.

- A score of 3 means "hire-level for a mid/senior engineer"; reserve 4 for clearly strong evidence.
- Missing evidence is not evidence: if the transcript never shows a behaviour, score it low and say what was missing.
- Prefer one specific, actionable improvement per criterion over general advice.'
);
