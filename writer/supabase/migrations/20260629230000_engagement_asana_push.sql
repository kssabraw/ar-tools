-- ============================================================
-- Engagement → Asana push: role routing + the push job type
-- ============================================================
-- Wires the managed-engagement executor to main's real Asana integration
-- (services/asana_service.py). When a strategy plan is approved, each
-- `assigned` action becomes an Asana task in the client's mapped project,
-- routed to the team member whose `role` matches the action's `assignee_role`.
--
-- Two additive pieces:
--   1. asana_team_members.role — the SerMaStr role a member fills, so an
--      `assigned` action (assignee_role ∈ writer/seo_tech/link_builder/va/
--      account_manager) can be routed to a real Asana user. Nullable + no
--      CHECK (kept loose so the role vocabulary can evolve without a migration);
--      an unmatched role just creates an unassigned task a human picks up.
--   2. async_jobs.job_type += 'engagement_asana_push' — the executor enqueues
--      this after approval; the worker creates the Asana tasks off the request
--      path. This restates the FULL deployed union (so it's the last word) plus
--      the new type.
-- ============================================================

alter table asana_team_members add column if not exists role text;

alter table async_jobs drop constraint async_jobs_job_type_check;
alter table async_jobs
  add constraint async_jobs_job_type_check
  check (job_type = any (array[
    'website_scrape', 'page_structure_scrape', 'silo_dedup', 'gsc_ingest',
    'gsc_page_ingest', 'gsc_materialize', 'dataforseo_rank', 'keyword_market',
    'gsc_research', 'rank_report', 'serp_snapshot', 'maps_scan', 'maps_report',
    'local_seo_silo', 'local_seo_generate', 'local_seo_reoptimize_url',
    'local_seo_reoptimize_page', 'service_page_plan', 'rank_location_derive',
    'brand_scan', 'brand_report', 'notification_dispatch', 'reopt_plan',
    'client_report', 'maps_analyze', 'asana_monthly', 'competitor_gbp',
    'review_intel', 'backlink_intel', 'content_intel', 'local_relevance',
    'site_audit', 'backlink_audit', 'citation_audit', 'engagement_asana_push'
  ]));
