-- Adds the linked Google Calendar event id to interviews, so a synced
-- interview can be re-synced (delete old event, create new) or have its
-- calendar event removed when the interview itself is deleted. See
-- dayline/adapters/interview_calendar_sync.py.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table interviews add column if not exists google_event_id text;
