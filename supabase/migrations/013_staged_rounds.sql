-- Staged practical rounds: a live session whose interviewer adds production
-- follow-ups to the candidate's own code, stage by stage. Mirrors
-- MockSession.staged_problem_id / MockSession.stages (StageAttempt) and
-- MockRoundType.PRACTICAL_CODING in src/dayline/models.py - keep in sync by
-- hand. Needs 011 and 012.
--
-- * A staged round is an ordinary live session (kind = 'live') plus:
--   - staged_problem_id: a built-in problem id
--     (src/dayline/mock/staged_problems/<id>), not a foreign key.
--   - stages: one object per stage, in order - status, when it started and
--     finished, how many hidden test runs, the first run's outcomes for the
--     stage's own tests, the last run's report, and the candidate's code when
--     the stage finished. Scores are computed from these in code.
-- * Stage transitions, hidden test runs, and the interviewer chat are rows in
--   mock_session_events (its kind column is text, so no change there).
-- * mock_round_type gains 'Practical coding' for the round's rubric.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run. Then run 014 as a SEPARATE run: Postgres refuses to
-- use an enum value in the same transaction that added it.

alter type mock_round_type add value if not exists 'Practical coding';

alter table mock_sessions
  add column staged_problem_id text,
  add column stages jsonb not null default '[]';

create index mock_sessions_staged_problem_id_idx
  on mock_sessions (staged_problem_id)
  where staged_problem_id is not null;
