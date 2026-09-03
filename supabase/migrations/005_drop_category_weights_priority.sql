-- Migration 005: drop the now-dead category_weights.priority column.
--
-- 004_category_rank.sql made `rank` the single source of truth for category
-- focus order and left `priority` in place "just in case" - but Postgres
-- validates NOT NULL constraints against the full row on INSERT ... ON
-- CONFLICT DO UPDATE (upsert), even when the conflict branch only updates
-- `rank`. Since nothing reads or writes `priority` anymore (see
-- dayline/adapters/category_weights.py), every re-rank upsert was failing
-- with "null value in column priority violates not-null constraint" - drop
-- the column instead of working around it.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table category_weights drop column priority;
