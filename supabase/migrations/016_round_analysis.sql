-- Timed change requests, interviewer styles, and the AI-assisted round
-- analysis. Mirrors MockSession.interviewer_style / InterviewerStyle in
-- src/dayline/models.py - keep in sync by hand. Needs 011 and 013.
--
-- * mock_sessions.interviewer_style: how a staged round's interviewer talks
--   ('realistic' or 'coach'). Null means coach (every round from before this
--   migration). Only realistic rounds write it, and generated rounds are
--   realistic by default, so starting one needs this migration.
-- * The change request's arrival is a 'stage_unlocked' row in
--   mock_session_events (its kind column is text, so no change there), and
--   each 'file_saved' row now also carries the save's diff in its data.
-- * A seeded rubric for analysing generated AI-assisted full-stack rounds.
--   It uses the existing 'AI-assisted project' round type (011), so no enum
--   value is added and this file runs in one go.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table mock_sessions
  add column interviewer_style text
    check (interviewer_style in ('realistic', 'coach'));

insert into mock_rubrics (name, round_type, criteria) values (
  'AI-assisted full-stack round',
  'AI-assisted project',
  '[
    {"key": "understanding", "title": "Understands the codebase first", "weight": 1,
     "description": "Reads the relevant code, runs the app or the tests, or asks the assistant about the codebase before changing it, instead of editing blind."},
    {"key": "prompting", "title": "Prompt quality and scoping", "weight": 1,
     "description": "Prompts are specific and scoped: they name files, functions, constraints, and the expected behaviour, and ask for one well-defined change at a time."},
    {"key": "plan_first", "title": "Plans before editing", "weight": 0.75,
     "description": "Uses plan mode (or states a plan) before asking for edits, especially for multi-file changes and after the change request."},
    {"key": "diff_review", "title": "Reviews AI diffs", "weight": 1.5,
     "description": "Reads each proposed diff before deciding: rejects or corrects wrong edits, takes time proportional to the change, and never accepts large edits in seconds."},
    {"key": "verification", "title": "Verifies with tests and the app", "weight": 1.25,
     "description": "Runs the tests and checks the running app after accepting changes, and before calling a stage done."},
    {"key": "change_request", "title": "Handles the change request", "weight": 1.25,
     "description": "Reacts quickly and deliberately when the change request arrives: clarifies the requirement, finds where it lands in the code, and plans before editing."},
    {"key": "time_management", "title": "Time management", "weight": 0.75,
     "description": "Spends time in proportion to each stage, avoids long unproductive stretches, and leaves time to verify before the end."},
    {"key": "correctness", "title": "Final correctness (both stages)", "weight": 1.5,
     "description": "Both the task and the change request work at the end: their hidden tests pass and stage 1 still passes after stage 2."}
  ]'
);
