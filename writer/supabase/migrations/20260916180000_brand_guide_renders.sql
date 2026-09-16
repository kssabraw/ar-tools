-- Migration: 20260916180000_brand_guide_renders.sql
-- Purpose: Brand Guide Generator — Phase 3 (PDF render + render profiles).
--   docs/modules/brand-guide-generator-prd-v1_0.md §4.7 (Render) / §6 (data model).
--
--   Phase 3 renders the assembled guide to a portable PDF and stores it in the
--   `reports` bucket + delivers it to the client's Drive folder. Per §4.7 the same
--   stored record renders TWO ways — an `internal` profile (the blunt coherence
--   audit) and a `client` profile (the same findings reframed as forward-looking
--   opportunities + the white-label footer). §6 is explicit that
--   `storage_path`/`pdf_url` are PER PROFILE, but the Phase-1 table carries a single
--   `storage_path`/`pdf_url` pair — those cannot hold two profiles' output.
--
--   So this adds a `renders` jsonb keyed by profile:
--     {"internal": {"storage_path","pdf_url","rendered_at"},
--      "client":   {"storage_path","pdf_url","rendered_at","drive": {...}}}
--   The existing top-level `storage_path`/`pdf_url` are kept as a convenience mirror
--   of the CLIENT profile (the client-facing deliverable) so a simple "latest PDF"
--   read + acceptance criterion #6 still work without unpacking the jsonb.
--
--   No new job type (`brand_guide_render` already lives in the async_jobs CHECK,
--   added in 20260916170000). No status-machine change (the `rendering` state is
--   already in the status CHECK).

alter table brand_guides
  add column if not exists renders jsonb;

comment on column brand_guides.renders is
  'Per-profile PDF render output (PRD §4.7): {"internal": {...}, "client": {...}}, '
  'each carrying storage_path / pdf_url / rendered_at (+ Drive delivery on client). '
  'The top-level storage_path/pdf_url mirror the client profile.';
