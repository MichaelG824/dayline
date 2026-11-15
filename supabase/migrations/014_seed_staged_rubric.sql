-- A starting rubric for staged practical rounds, so they can be graded on
-- day one. Edit it in the Mock tab (Rubrics & standards) rather than here.
--
-- Needs 013, applied in an EARLIER run: this file uses the 'Practical coding'
-- enum value 013 adds, and Postgres refuses a new enum value in the
-- transaction that added it ("unsafe use of new value").
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

insert into mock_rubrics (name, round_type, criteria) values (
  'Staged practical round (default)',
  'Practical coding',
  '[
    {"key": "correctness", "title": "Gets each stage right", "weight": 1.5,
     "description": "Passes each stage''s hidden tests without skipping, and without breaking earlier stages along the way."},
    {"key": "design", "title": "Design that extends", "weight": 1.5,
     "description": "Chooses data structures in stage 1 that later stages extend instead of rewriting; keeps each invariant (map, recency order, size total) in one place."},
    {"key": "edge_cases", "title": "Finds edge cases first", "weight": 1,
     "description": "Handles the tricky cases (expired-but-present keys, oversized items, an update that changes size) before a failing test points them out."},
    {"key": "follow_ups", "title": "Reasons about follow-ups", "weight": 1,
     "description": "Answers production follow-ups (expiry cleanup, size budgets, locking, why a read-write lock does not help when reads mutate) with reasoning grounded in their own code."},
    {"key": "communication", "title": "Communicates while coding", "weight": 1,
     "description": "Explains the plan before coding each stage, thinks out loud, and states the choices a prompt leaves open."},
    {"key": "pace", "title": "Pace", "weight": 0.5,
     "description": "Moves through the stages in roughly the suggested time and uses the test runs deliberately rather than by trial and error."}
  ]'
);
