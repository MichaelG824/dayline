-- Mock interviews, phase 2: live sessions in a sandbox. Mirrors MockSession /
-- MockEvent in src/dayline/models.py - keep in sync by hand. Needs 011.
--
-- * mock_sessions gains the live-session record: which practice repo
--   (template) and language pack it ran, when it started and ended, the
--   files at the end, the diff against the starting repo, and the last test
--   run. Pasted-transcript sessions keep kind = 'transcript'.
-- * mock_session_events: what happened during a live session, in order
--   (files saved, tests run). Phase 3's interviewer reads these, and the
--   grader sees them as the work record.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

create type mock_session_kind as enum ('transcript', 'live');
create type mock_session_status as enum ('live', 'ended');

alter table mock_sessions
  add column kind mock_session_kind not null default 'transcript',
  add column status mock_session_status not null default 'ended',
  -- A built-in template id (src/dayline/mock/templates/<id>), not a foreign key.
  add column template_id text,
  add column pack text,
  add column started_at timestamptz,
  add column ended_at timestamptz,
  -- {"path": "contents"} for every text file at the end of the session.
  add column final_files jsonb not null default '{}',
  add column final_diff text not null default '',
  -- The last test run, as the sandbox runner reported it.
  add column test_report jsonb;

create table mock_session_events (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references mock_sessions(id) on delete cascade,
  kind text not null,
  data jsonb not null default '{}',
  at timestamptz not null default now()
);

create index mock_session_events_session_id_idx on mock_session_events (session_id, at);

alter table mock_session_events enable row level security;
