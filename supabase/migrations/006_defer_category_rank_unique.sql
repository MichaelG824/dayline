-- Migration 006: make category_weights_rank_unique deferrable.
--
-- A rank swap (e.g. moving category A from rank 1 to 2 and B from 2 to 1)
-- upserts multiple rows in one statement. Postgres checks a plain UNIQUE
-- constraint after each row is written, not after the whole statement/
-- transaction - so setting A's rank to 2 collides with B's still-unchanged
-- rank 2, even though the final result of the swap has no duplicates.
-- Marking the constraint DEFERRABLE INITIALLY DEFERRED postpones the check
-- to transaction commit, after every row in the upsert has its final value.
--
-- Run this once in the Supabase dashboard: SQL Editor -> New query -> paste
-- this whole file -> Run.

alter table category_weights drop constraint category_weights_rank_unique;
alter table category_weights
  add constraint category_weights_rank_unique unique (rank) deferrable initially deferred;
