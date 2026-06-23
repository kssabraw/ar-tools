-- Maps Local Rank Analysis report (Module #5).
-- Each per-keyword scan result gets an auto-generated, client-facing report:
-- deterministic geo-grid rollups (ring/sector analytics) + an LLM narrative
-- (Claude Sonnet) + the octant-based hyper-local pin suggestions, optionally
-- published to the client's Drive folder as a Google Doc.

alter table public.maps_scan_results
  -- 'pending' (queued/in-flight) | 'complete' | 'failed'; null = never generated.
  add column if not exists report_status text,
  add column if not exists report_error text,
  -- The full report Markdown (client-facing) the narrative + tables.
  add column if not exists report_md text,
  -- Structured side-outputs from the same generation pass.
  add column if not exists report_weak_directions text,
  add column if not exists report_top_competitors jsonb,
  -- Octant pin generator output ({ok, points:[{lat,lng,octant,...}], debug}).
  add column if not exists report_octant_pins jsonb,
  -- Deterministic rollups (ring_summaries / sectors_overall / overall / horizon)
  -- cached so the printable report renders without recomputing from rank_grid.
  add column if not exists report_analytics jsonb,
  add column if not exists report_doc_url text,
  add column if not exists report_generated_at timestamptz;
