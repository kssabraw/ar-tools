-- Fanout-sourced silo auto-approval (Platform PRD v1.4.1 §7.7.2 / §8.5).
-- Depends on: silo_candidates table from 20260502130000_silo_candidates.sql.

-- Race amplification fix (PRD v1.4.1 §8.5): prevent two concurrent dedup
-- workers from both creating an exact-text-duplicate row (and thereby both
-- auto-approving it). Embedding-near-duplicates are still handled in the
-- worker via `_find_match`; this index covers only the identical-text race,
-- which is the dominant case (same brief output processed by parallel workers).
-- `rejected` rows are excluded so a fresh proposal can supersede an old reject.
create unique index if not exists uq_silo_client_keyword_active
  on silo_candidates (client_id, suggested_keyword)
  where status <> 'rejected';

-- Auto-approval trigger function. Fires only on INSERT.
-- M2 guard: skip if a row with the same (client_id, suggested_keyword) already
-- exists. Protects against a future caller using INSERT … ON CONFLICT DO UPDATE,
-- where BEFORE INSERT triggers fire even when the conflict resolves to UPDATE;
-- without the guard, the trigger would overwrite status on the path that
-- should preserve it.
create or replace function set_silo_status_for_fanout_sourced()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'proposed'
     and new.source_headings is not null
     and jsonb_typeof(new.source_headings) = 'array'
     and not exists (
       select 1 from silo_candidates
       where client_id = new.client_id
         and suggested_keyword = new.suggested_keyword
         and status <> 'rejected'
     )
     and exists (
       select 1
       from jsonb_array_elements(new.source_headings) as h
       where jsonb_typeof(h) = 'object'
         and h ? 'source'
         and starts_with(h->>'source', 'llm_fanout_')
     )
  then
    new.status := 'approved';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_silo_fanout_auto_approve on silo_candidates;

create trigger trg_silo_fanout_auto_approve
before insert on silo_candidates
for each row
execute function set_silo_status_for_fanout_sourced();

comment on function set_silo_status_for_fanout_sourced() is
  'Auto-approves silo_candidates rows with at least one llm_fanout_* '
  'source_headings entry (PRD v1.4.1 §7.7.2). Insert-only; preserves '
  'explicit non-proposed status; skipped if a same-keyword row already exists.';
