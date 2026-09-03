-- Migration 003: seed the default category focus ranking.
--
-- Run after 002_dayline_features.sql has already been committed - Postgres
-- does not allow a new enum value (added via ALTER TYPE ... ADD VALUE in 002)
-- to be used in the same transaction that added it, so this must be a
-- separate SQL Editor run.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

-- Seed the default ranking (highest focus first), matching the user's stated
-- priority order. Safe to re-run - existing rows are left untouched.
insert into category_weights (category, priority) values
  ('AI Coding - React/Python', 'P0'),
  ('AI Coding - DSA', 'P0'),
  ('Behavioral', 'P1'),
  ('System Design', 'P1'),
  ('Leetcode', 'P2')
on conflict (category) do nothing;
