-- Migration: fanout-sourced silo auto-approval
-- Date: 2026-05-07
-- PRD: content-platform-prd-v1_4.md v1.4.1 (§7.7.2 "Fanout-sourced auto-approval", §8.5, §14.1)
--
-- Policy: when a new silo_candidates row is inserted whose source_headings JSONB
-- array contains at least one heading with source matching llm_fanout_*
-- (llm_fanout_chatgpt | llm_fanout_claude | llm_fanout_gemini | llm_fanout_perplexity
-- per Brief Generator PRD v2.0 §6), set status='approved' instead of the column
-- default 'proposed'. The trigger only overrides when the inbound status is
-- 'proposed' so explicit writes (e.g., backfills) are respected. Auto-approval
-- does NOT auto-dispatch a run; the user still clicks "Approve and Generate Run"
-- on the silo dashboard. Dedup-hit UPDATEs are unaffected (BEFORE INSERT only).
--
-- Depends on: silo_candidates table (created in the v1.4 migration).
-- Idempotent: uses CREATE OR REPLACE FUNCTION + DROP TRIGGER IF EXISTS.

create or replace function set_silo_status_for_fanout_sourced()
returns trigger
language plpgsql
as $$
begin
  if new.status = 'proposed'
     and new.source_headings is not null
     and jsonb_typeof(new.source_headings) = 'array'
     and exists (
       select 1
       from jsonb_array_elements(new.source_headings) as h
       where h ? 'source'
         and (h->>'source') like 'llm_fanout_%'
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
  'Auto-approves silo_candidates rows whose source_headings include any heading '
  'with source matching llm_fanout_* (per platform PRD v1.4.1 §7.7.2). '
  'Only fires on INSERT and only when inbound status = proposed.';
