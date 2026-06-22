-- Migration: 20260622190000_keywords_client_anchor.sql
-- Purpose: Organic Rank Tracker (Module #4) — DataForSEO fallback.
--          Re-anchor tracked keywords to the CLIENT (not a GSC property) so the
--          tracker works without GSC: when GSC can't be accessed for the site,
--          or the site doesn't rank for a keyword (so GSC has nothing), the
--          keyword automatically falls back to a weekly DataForSEO live rank.
-- See: docs/modules/organic-rank-tracker-prd-v1_0.md §2 (hybrid thesis).

-- Keywords now belong to the client; the GSC property is optional enrichment.
alter table tracked_keywords
  add column if not exists client_id uuid references clients(id) on delete cascade;

-- Backfill from each keyword's property (property_id was previously required).
update tracked_keywords tk
   set client_id = gp.client_id
  from gsc_properties gp
 where tk.property_id = gp.id
   and tk.client_id is null;

alter table tracked_keywords alter column client_id set not null;

-- The GSC property is now optional (a DataForSEO-only client has none).
alter table tracked_keywords alter column property_id drop not null;

-- Uniqueness is per client+keyword (a property can't be the anchor anymore).
alter table tracked_keywords
  drop constraint if exists tracked_keywords_property_keyword_unique;
alter table tracked_keywords
  add constraint tracked_keywords_client_keyword_unique unique (client_id, keyword);

create index if not exists idx_tracked_keywords_client on tracked_keywords (client_id);

-- Widen async_jobs.job_type for the weekly DataForSEO rank job.
alter table async_jobs
  drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type in ('website_scrape', 'silo_dedup', 'gsc_ingest',
                      'gsc_materialize', 'dataforseo_rank'));
