-- Record the grid CENTRE on the snapshot. ISSUES I-078.
--
-- WHY NOW, AND WHY THIS IS THE LAST CHEAP MOMENT.
--
-- Storage spec §5 says grid coordinates regenerate from
-- `scan_snapshot.{center, grid_radius_miles, grid_spacing_miles}` plus `point_seq`. The table was
-- built with the two distances and NO centre — so the centre in practice comes from
-- `submarket.center_lat/lng`, which is immutable only by ENFORCEMENT
-- (`seeding.check_geometry_change`) rather than by storage.
--
-- The coverage rollup is unaffected and deliberately stays that way: point distances come from
-- `steps x spacing` and are centre-independent. Phase 3's heatmap is NOT. It needs real lat/lng,
-- so it will read the submarket — and a submarket whose centre is ever corrected would re-render
-- every historical heatmap against coordinates that were never scanned. That is precisely the
-- failure `geometry_version` exists to prevent, arriving through the one door the pin does not
-- cover: the pin fixes the SHAPE of the lattice, not where it was anchored.
--
-- `scan_snapshot` is empty today, so this is an ALTER with nothing to backfill. After the first
-- scan it becomes a backfill that reads today's submarket centre and asserts it was the centre
-- used at scan time — which is exactly the unverifiable claim this column exists to make
-- unnecessary. The window is open only until the first snapshot is written, and what stands
-- between the pipeline and that is a Railway deploy.
--
-- NULLABLE, deliberately. NOT NULL would make a stale writer fail its snapshot insert, and the
-- fail-safe direction on a path that is about to spend money is "the scan proceeds and the gap is
-- visible" rather than "the scan aborts on a bookkeeping column". Tighten to NOT NULL once the
-- first real scan has proven the writer populates it — a one-line migration against a table whose
-- rows will all carry values.

alter table scan_snapshot
  add column if not exists center_lat double precision,
  add column if not exists center_lng double precision;

comment on column scan_snapshot.center_lat is
  'The centre the grid was ACTUALLY generated from, captured at scan time. Storage spec §5 lists '
  'it among the parameters coordinates regenerate from. Null on snapshots written before '
  'migration 20260805140000; readers must fall back to submarket.center_lat and treat the result '
  'as an assumption rather than a record (ISSUES I-078).';

comment on column scan_snapshot.center_lng is
  'See center_lat. Recorded from the same values passed to the geometry generator, in the same '
  'call, so the two cannot diverge.';
