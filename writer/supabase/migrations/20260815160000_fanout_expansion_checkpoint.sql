-- Resumable Fanout expansion (issue #686 Phase 2).
--
-- A per-session checkpoint of the expensive expansion work (each silo's raw
-- candidate pool + the shared seed-level pool + done flags), so a requeued
-- durable expand run rehydrates the silos that already finished and only re-pays
-- the unfinished ones. Null except while a resumable run is mid-flight; cleared
-- on success or a terminal error/cancel. Only used when
-- fanout_resumable_expand_enabled is on — additive and inert otherwise.
alter table fanout.sessions
  add column if not exists expansion_checkpoint jsonb;
