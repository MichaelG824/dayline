-- Migration 004: give category_weights a true total order.
--
-- Priority (P0-P3) has only 4 distinct values for 5 prep categories, so any
-- UI that lets the user freely reorder all 5 (drag/up-down-arrow style) is
-- lossy: two categories tied at the same Priority have no way to record
-- which one the user actually ranked higher, and any tie-break collapses
-- back to a fixed order - silently undoing the user's reorder. `rank` is an
-- explicit, unique 1-5 integer with no ties; Priority is now *derived* from
-- rank (via a fixed bucket, see dayline/adapters/category_weights.py) only
-- when resolving a new task's default priority or bulk-reprioritizing the
-- backlog - it is no longer the stored ranking itself.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table category_weights add column if not exists rank integer;

update category_weights set rank = case category
  when 'AI Coding - React/Python' then 1
  when 'AI Coding - DSA' then 2
  when 'Behavioral' then 3
  when 'System Design' then 4
  when 'Leetcode' then 5
end
where rank is null;

alter table category_weights alter column rank set not null;
alter table category_weights add constraint category_weights_rank_unique unique (rank);

-- The old `priority` column is left in place (still NOT NULL from its
-- original creation) but is no longer read or written by the application -
-- `rank` is now the single source of truth for category focus order.
