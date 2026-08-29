-- Everhour time-tracking integration — Phase 3 (time pull + rollups).
--
-- The read side: a daily whole-team pull of Everhour time records into a new
-- `time_entries` ledger, rolled up into `tasks.actual_hours`. Per the plan doc
-- (docs/modules/everhour-time-tracking-integration-plan-v1_0.md §4, §6). Purely
-- additive; the whole integration stays gated on `everhour_enabled` (default
-- False), so this is a behavioral no-op until a real Everhour account is
-- provisioned and the flag is flipped.
--
--   * tasks.actual_hours — a DERIVED, recomputed column (sum of that task's
--     time_entries.seconds / 3600). Never hand-edited; the sync job always
--     recomputes it from time_entries, so a partial/failed sync can't leave it
--     half-updated in a way that compounds. Null → no logged time yet.
--
--   * time_entries — one row per Everhour time record, keyed by the Everhour
--     record id (the idempotency key). Upsert-by-record-id: an edited entry's
--     `seconds` changes in place; a deleted entry (Everhour models a delete as
--     `time: 0` on the same id, §11.9) re-reads within the rolling window and
--     zeroes its contribution to every rollup — no separate reconciliation pass.
--
--     client_id is NULLABLE (owner ruling 2026-08-29 + plan §10): ad-hoc /
--     internal time whose Everhour project maps to no suite client still gets a
--     row (for per-member utilization), it just carries no client_id and is
--     excluded from client/margin rollups. task_id is nullable for the same
--     reason — ad-hoc time with no native-task match. everhour_task_id is kept
--     even when task_id is null so a later mirror/backfill can re-join it.
--
--     billable is captured from day one (free on the same API response) but
--     nothing consumes it in v1 — the consuming logic (billable/non-billable
--     margin) is deferred to Phase 4.
--
-- Indexes back the three rollup shapes (§4 step 5): by task_id (actual_hours
-- recompute), by (client_id, entry_date) (client Time card), by
-- (member_id, entry_date) (PACE utilization).
--
-- The async_jobs job_type CHECK is widened to accept `everhour_sync`. Rebuilt
-- from the LIVE constraint (verified 2026-08-29 — the live set matches the
-- 20260829130000 list, ending `score_external`,`everhour_mirror`), preserving
-- every existing type + appending the new value.
--
-- RLS on, service-role only (suite convention) — this is an internal
-- capacity/margin signal, never exposed to a client login. Idempotent
-- throughout (add-if-not-exists / create-if-not-exists / drop-then-add CHECK).

-- ---------------------------------------------------------------------------
-- tasks.actual_hours (materialized rollup)
-- ---------------------------------------------------------------------------
alter table public.tasks
  add column if not exists actual_hours numeric;

comment on column public.tasks.actual_hours is
  'Logged hours for this task, rolled up from time_entries by the everhour_sync job (sum(seconds)/3600). Derived + recomputed, never hand-edited. Null → no logged time yet.';

-- ---------------------------------------------------------------------------
-- time_entries ledger
-- ---------------------------------------------------------------------------
create table if not exists public.time_entries (
  id                  uuid primary key default gen_random_uuid(),
  everhour_record_id  text not null unique,
  client_id           uuid references public.clients(id) on delete cascade,
  member_id           uuid references public.asana_team_members(id) on delete set null,
  task_id             uuid references public.tasks(id) on delete set null,
  everhour_task_id    text,
  entry_date          date not null,
  seconds             integer not null,
  billable            boolean,
  comment             text,
  synced_at           timestamptz not null default now(),
  created_at          timestamptz not null default now()
);

comment on table public.time_entries is
  'Everhour time records pulled one-way into the suite (Phase 3). One row per Everhour time record, keyed by everhour_record_id (idempotency key). Upsert-by-id: edits change seconds in place, a delete re-reads as time:0. Rolled up into tasks.actual_hours + read-time per-client/per-member totals.';

create index if not exists idx_time_entries_task
  on public.time_entries (task_id);
create index if not exists idx_time_entries_client_date
  on public.time_entries (client_id, entry_date);
create index if not exists idx_time_entries_member_date
  on public.time_entries (member_id, entry_date);

alter table public.time_entries enable row level security;
-- No policies → service-role only (the suite convention for internal tables;
-- the platform-api uses the service-role key, which bypasses RLS).

-- ---------------------------------------------------------------------------
-- async_jobs job_type CHECK — append everhour_sync
-- ---------------------------------------------------------------------------
alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs add constraint async_jobs_job_type_check check (
  job_type = any (array[
    'website_scrape','page_structure_scrape','page_structure_parse','silo_dedup','gsc_ingest',
    'gsc_page_ingest','gsc_materialize','dataforseo_rank','keyword_market','gsc_research','rank_report',
    'serp_snapshot','maps_scan','maps_report','local_seo_silo','local_seo_generate','local_seo_reoptimize_url',
    'local_seo_reoptimize_page','service_page_plan','rank_location_derive','brand_scan','brand_report',
    'notification_dispatch','reopt_plan','client_report','maps_analyze','asana_monthly','competitor_gbp',
    'review_intel','backlink_intel','content_intel','local_relevance','syndication_scan','syndication_item',
    'freeze_check','citation_check','page_backlink_intel','strategy_review','maps_image_backfill',
    'brand_voice_scan','icp_scan','asana_push','competitor_intel','gbp_metrics_ingest','internal_link_analyze',
    'internal_link_apply','rank_keyword_report','local_seo_action','backlink_snapshot','content_batch_item',
    'task_month_generate','task_due_sweep','task_import_asana','leadoff_tryout','leadoff_scout','leadoff_ai_probe',
    'domain_overview','keyword_gap','link_gap','leadoff_permits','leadoff_geocode','qa_review',
    'leadoff_signal_refresh','leadoff_city_finder','leadoff_income_backfill','leadoff_county_backfill',
    'keyword_research','ecommerce_generate','ecommerce_reoptimize_url','ecommerce_action','github_infer_patterns',
    'illustrate_run','blog_github_publish','gbp_post_publish','gbp_post_generate','gbp_posts_sync','site_inventory',
    'website_provision','website_theme_compile','website_core_pages','website_page_publish','website_deploy_poll',
    'website_page_generate','deliverables_sheet_provision','deliverables_log','deliverable_notes_scan',
    'service_page_score','service_page_reoptimize','keyword_topic_research','keyword_research_report',
    'backlink_lookup','fanout_report','blog_score','blog_reoptimize','fanout_expand','gbp_onboard',
    'gbp_search_keywords','fanout_plan','fanout_regate','fanout_fanout','fanout_architecture','ga4_ingest',
    'gbp_reviews','leadoff_map_refresh','leadoff_placement','leadoff_zip_demand','voice_revalidate',
    'autonomy_run','score_external','everhour_mirror','everhour_sync'
  ])
);
