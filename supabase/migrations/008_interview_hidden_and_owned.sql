-- Supports auto-discovering interviews from the real Google Calendar instead
-- of requiring a manual "Import" click per event (see
-- adapters/interview_calendar_sync.py, api/main.py's list_interviews):
--
-- * google_event_owned distinguishes an interview whose calendar event
--   Dayline itself created (safe to delete on cancel) from one that was
--   auto-discovered from an existing event (never safe to delete).
-- * hidden lets a false positive (a personal call, a duplicate entry) be
--   dismissed from the tracked list without ever touching the real
--   calendar event, and without it reappearing on the next discovery pass.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table interviews add column if not exists google_event_owned boolean not null default false;
alter table interviews add column if not exists hidden boolean not null default false;
