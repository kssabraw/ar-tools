-- Keyword Research: persist a per-run filter-transparency blob.
--
-- Fixes the "low quality / hard to use" complaint: previously the run-time filter
-- warnings ("filtered 183 keywords…") and the list of dropped keywords existed only
-- in the async job result — shown once, then lost on navigation. Re-opening a thin
-- run showed a handful of rows with no explanation of what was cut or why.
--
-- `filter_summary` stores, per run:
--   * raw_pool     — unique keyword candidates the paid sources returned before any
--                    gate (a small pool = seeds too narrow, not over-filtering)
--   * kept         — surviving keyword count
--   * dropped_total / by_reason — per-reason tallies for the "what we filtered" panel
--   * dropped      — a capped sample of {keyword, reason} so a VA can SEE what was cut
--   * warnings     — the filter/drift/thin-pool advisories (re-shown on read; not
--                    derivable from the surviving keyword rows)
-- Backfill-free: pre-migration runs read as NULL and simply show no panel.

alter table public.keyword_research_runs
  add column if not exists filter_summary jsonb;
