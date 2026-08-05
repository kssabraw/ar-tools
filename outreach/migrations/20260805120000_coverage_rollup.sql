-- The coverage rollup: `grid_result` -> `prospect_coverage`, one transaction per snapshot.
--
-- Owner: docs/storage-retention-spec.md §4. The PRD carries a copy of `prospect_coverage` as
-- context only (ISSUES R-001 — building `grid_result` from the PRD's copy produced the wrong
-- table once already). `grid_point_status` below is the exception: that one IS PRD-owned
-- (START-HERE §3a) and is reproduced from its DDL verbatim.
--
-- This closes ISSUES I-042 and the last unbuilt half of the retention policy. Until now
-- `drop_cold_partitions` dropped nothing but empty partitions, because it refuses any partition
-- holding a snapshot without a finalized rollup — correct, fail-closed, and not the same as
-- finished.
--
-- ---------------------------------------------------------------------------------------------
-- WHY THIS IS ONE FUNCTION RATHER THAN A SCRIPT
--
-- `rank_vector` must be written in the SAME TRANSACTION as the summary statistics it belongs to.
-- A rollup that produces coverage percentages without vectors must FAIL, not partially succeed:
-- a vector written later, or written in the wrong point_seq order, silently renders every
-- historical heatmap against coordinates that were never used to collect it. The picture still
-- draws and every number still looks plausible, which is what makes it unrecoverable.
--
-- PostgREST gives one transaction per call, so a Python-driven rollup — insert rows, then call
-- the finalizer — physically cannot hold both halves together. Hence one plpgsql function that
-- does the whole snapshot and calls `finalize_snapshot_rollup()` as its last statement. That
-- function re-derives its counts from the data and RAISES on a mismatch, which aborts everything
-- written here. So the two halves of the completion contract line up:
--
--   per ROW      `prospect_coverage.rank_vector` is NOT NULL
--   per SNAPSHOT `snapshot_rollup` cannot exist unless every prospect's row was committed with it
--
-- ---------------------------------------------------------------------------------------------
-- WHY GEOMETRY ARRIVES AS A PARAMETER
--
-- Coordinates are not stored anywhere (storage spec §5). They regenerate from the snapshot's
-- parameters through the PINNED, VERSIONED generator in `api/services/geometry.py`, whose own
-- docstring explains why a second definition of point membership is dangerous: two derivations
-- eventually disagree about a boundary point, and a point flipping in or out RENUMBERS every
-- `point_seq` after it, re-mapping every historical vector.
--
-- Re-implementing the lattice in SQL would create exactly that second definition. So the caller
-- generates the points through the registry — using the SNAPSHOT'S STORED `geometry_version`,
-- never the current default — and passes `[{"seq": n, "dist": miles}, ...]`. This function
-- validates that payload against the snapshot and refuses anything that does not cover
-- `0 .. expected_points-1` exactly.
--
-- Distances are centre-independent (they come from `spacing x steps`), so nothing here depends on
-- `submarket.center_lat/lng`, which is immutable only by convention. See ISSUES I-078.
--
-- ---------------------------------------------------------------------------------------------
-- WHAT THE DENOMINATOR COUNTS
--
-- Points MEASURED, never points where something was FOUND. Twice now that distinction has been
-- got wrong in this system (DECISIONS.md, `actual_points`; ISSUES I-069, the completion marker),
-- so it is stated once more: a grid point that returned an empty pack WAS measured, and "nobody
-- ranks here" is a finding — frequently the strongest one in the grid. A point whose task never
-- collected was NOT measured, and it leaves the denominator entirely rather than counting as an
-- absence nobody observed.
--
-- Hence `live_points` reads `scan_task.status = 'collected'`, which records measurement, and not
-- `grid_result`, which can only record discovery.

-- ---------------------------------------------------------------------------------------------
-- grid_point_status — the land mask (PRD §9a.1, PRD-owned DDL, reproduced verbatim)
--
-- A 5-mile radius at 1-mile spacing assumes a roughly circular land area. In a coastal metro a
-- material share of points fall in water; they return nothing, and coverage for every business in
-- that submarket comes out uniformly depressed — so coastal and inland submarkets score on
-- different scales while looking comparable.
--
-- Self-calibrated from scan data rather than bought as a coastline dataset: N consecutive null
-- scans mask a point, and ANY non-null result reactivates it, because business density changes
-- and coastlines do not. The point stays in the geometry — geometry is immutable — and leaves
-- only the coverage denominator.
-- ---------------------------------------------------------------------------------------------
create table if not exists grid_point_status (
  submarket_id uuid not null references submarket(id) on delete cascade,
  point_seq smallint not null,
  land boolean not null default true,
  consecutive_null_scans smallint not null default 0,
  last_evaluated_at timestamptz,
  primary key (submarket_id, point_seq)
);

comment on table grid_point_status is
  'PRD §9a.1 land mask. One row per grid point per submarket. `land = false` excludes the point '
  'from the coverage DENOMINATOR only — never from the geometry, which is immutable. Updated '
  'inside rollup_snapshot_coverage() so a snapshot''s live_points is contemporaneous with the '
  'claims made from it.';

comment on column grid_point_status.consecutive_null_scans is
  'Consecutive SNAPSHOTS in which this point was measured and returned nothing. Points that were '
  'not measured neither increment nor reset it — an uncollected task is not evidence of an empty '
  'pack. The counter is shared across keywords for a submarket, which is what makes the rule '
  'self-correcting: a point that returns results for ANY keyword resets it (ISSUES I-081).';

alter table grid_point_status enable row level security;

-- ---------------------------------------------------------------------------------------------
-- rollup_snapshot_coverage
-- ---------------------------------------------------------------------------------------------
create or replace function rollup_snapshot_coverage(
  p_snapshot_id uuid,
  p_geometry_version text,
  p_points jsonb,
  p_null_scans_to_mask integer default 3
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $function$
declare
  snap          record;
  n_points      integer;
  bad           bigint;
  rows_written  integer;
  v_live        integer;
  v_dead        integer;
  v_measured    integer;
  v_null_now    integer;
  v_prospects   integer;
begin
  select s.id, s.submarket_id, s.expected_points, s.geometry_version, s.complete
    into snap
    from scan_snapshot s
   where s.id = p_snapshot_id;

  if snap.id is null then
    raise exception 'no such snapshot %', p_snapshot_id;
  end if;

  -- Idempotent by REFUSAL rather than by upsert. A rollup either completed — in which case its
  -- marker exists and there is nothing to redo — or it aborted, in which case the transaction
  -- took every row and every mask increment with it. There is no third state to reconcile, which
  -- is the whole point of doing this in one transaction.
  if exists (select 1 from snapshot_rollup r where r.snapshot_id = p_snapshot_id) then
    return jsonb_build_object(
      'snapshot_id', p_snapshot_id,
      'status', 'already_rolled_up'
    );
  end if;

  -- PRD §9a.3: incomplete snapshots are excluded from scoring, delta computation AND rollup.
  -- Missing points depress coverage, which reads as pain, which promotes prospects for the wrong
  -- reason. Note the consequence, recorded in ISSUES I-075: a snapshot that never reaches the
  -- completeness threshold can never be rolled up, so its partition can never be dropped. That is
  -- fail-closed and costs disk; the alternative costs a false claim.
  if not snap.complete then
    raise exception
      'snapshot % is marked incomplete — PRD §9a.3 excludes incomplete snapshots from rollup',
      p_snapshot_id;
  end if;

  -- The caller must have regenerated geometry through the snapshot's OWN generator. Passing the
  -- version back is what makes that checkable from this side: a caller that used the current
  -- default on a snapshot stamped with an older version is refused rather than trusted.
  if snap.geometry_version is distinct from p_geometry_version then
    raise exception
      'geometry version mismatch for snapshot %: snapshot is %, caller generated points with % '
      '— regenerate with the snapshot''s stored version, never the default',
      p_snapshot_id, snap.geometry_version, p_geometry_version;
  end if;

  select count(*) into n_points from jsonb_array_elements(p_points);
  if n_points <> snap.expected_points then
    raise exception
      'geometry payload has % points, snapshot % expects %',
      n_points, p_snapshot_id, snap.expected_points;
  end if;

  -- Exact coverage of 0..expected-1, both directions. A payload that merely has the right COUNT
  -- could still be missing a point and repeating another, which would place a byte at the wrong
  -- offset in every vector this snapshot writes.
  select count(*) into bad
    from (
      select (e->>'seq')::int as seq from jsonb_array_elements(p_points) e
    ) p
    full join generate_series(0, snap.expected_points - 1) g(seq) on g.seq = p.seq
   where p.seq is null or g.seq is null;
  if bad > 0 then
    raise exception
      'geometry payload does not cover point_seq 0..% exactly (% mismatched)',
      snap.expected_points - 1, bad;
  end if;

  if exists (select 1 from jsonb_array_elements(p_points) e where (e->>'dist') is null) then
    raise exception 'geometry payload has a point with no distance';
  end if;

  -- -------------------------------------------------------------------------------------------
  -- 1. LAND MASK — before the denominator, because live_points must be contemporaneous.
  -- -------------------------------------------------------------------------------------------

  -- Every point in the geometry gets a row. Points are never deleted from here: a masked point
  -- retains its history and can reactivate.
  insert into grid_point_status (submarket_id, point_seq)
  select snap.submarket_id, g.seq::smallint
    from generate_series(0, snap.expected_points - 1) g(seq)
  on conflict (submarket_id, point_seq) do nothing;

  with measured as (
    select t.point_seq,
           exists (
             select 1 from grid_result gr
              where gr.snapshot_id = p_snapshot_id and gr.point_seq = t.point_seq
           ) as found
      from scan_task t
     where t.snapshot_id = p_snapshot_id
       and t.status = 'collected'
  )
  update grid_point_status gps
     set consecutive_null_scans =
           case when m.found then 0
                else least(gps.consecutive_null_scans + 1, 32767)::smallint end,
         land =
           case when m.found then true
                else (gps.consecutive_null_scans + 1) < p_null_scans_to_mask end,
         last_evaluated_at = now()
    from measured m
   where gps.submarket_id = snap.submarket_id
     and gps.point_seq = m.point_seq;

  -- -------------------------------------------------------------------------------------------
  -- 2. THE INVARIANT THAT MUST HOLD BEFORE ANY VECTOR IS PACKED
  --
  -- A prospect can only be found at a point that was measured, and any point that returned
  -- results was just reactivated above — so "present at a point that is not live" should be
  -- impossible. If it ever happens, the byte for that cell would be packed as 255 (dead) and the
  -- rank would vanish silently: coverage understated, heatmap wrong, nothing to notice.
  --
  -- The realistic cause is grid_result rows whose scan_task never reached `collected` — the
  -- collector writes rows first and marks the task second (deliberately: a crash between them
  -- re-collects something free rather than losing something paid), so a crash in that window
  -- leaves exactly this shape. The right response is to re-collect, not to average over it.
  -- -------------------------------------------------------------------------------------------
  select count(*) into bad
    from (
      select distinct gr.point_seq
        from grid_result gr
       where gr.snapshot_id = p_snapshot_id
    ) h
   where not exists (
      select 1
        from scan_task t
        join grid_point_status gps
          on gps.submarket_id = snap.submarket_id and gps.point_seq = t.point_seq
       where t.snapshot_id = p_snapshot_id
         and t.point_seq = h.point_seq
         and t.status = 'collected'
         and gps.land
   );
  if bad > 0 then
    raise exception
      'snapshot % has results at % point(s) that are not live — a point with results cannot be '
      'unmeasured or masked. Re-collect the snapshot rather than rolling it up',
      p_snapshot_id, bad;
  end if;

  -- -------------------------------------------------------------------------------------------
  -- 3. THE ROLLUP ITSELF
  --
  -- One row per PROSPECT present somewhere in this snapshot — exactly the set
  -- finalize_snapshot_rollup() reconciles against (`count(distinct prospect.id)` over
  -- grid_result joined on place_id, compared with `<>`). Writing fewer is the partial rollup
  -- I-069 exists to catch; writing more — pre-seeding every submarket prospect at zero coverage —
  -- would raise just as hard. See ISSUES I-076 for what that means downstream.
  --
  -- `min(rank)` per (prospect, point) rather than a bare join: grid_result has no unique
  -- constraint on (snapshot_id, point_seq, place_id) and the collector's write-then-mark ordering
  -- can legitimately produce duplicates after a crash (ISSUES I-077). Deduping here keeps a
  -- re-collected point from counting twice in points_present.
  -- -------------------------------------------------------------------------------------------
  with geom as (
    select (e->>'seq')::smallint as point_seq,
           (e->>'dist')::numeric as dist_miles
      from jsonb_array_elements(p_points) e
  ),
  live as (
    select g.point_seq, g.dist_miles
      from geom g
      join scan_task t
        on t.snapshot_id = p_snapshot_id
       and t.point_seq = g.point_seq
       and t.status = 'collected'
      join grid_point_status gps
        on gps.submarket_id = snap.submarket_id
       and gps.point_seq = g.point_seq
     where gps.land
  ),
  hits as (
    select pr.id as prospect_id, gr.point_seq, min(gr.rank) as rank
      from grid_result gr
      join prospect pr on pr.place_id = gr.place_id
     where gr.snapshot_id = p_snapshot_id
     group by 1, 2
  ),
  cells as (
    -- Every prospect x every point in the geometry: one cell per byte of the vector, so the
    -- vector's length is the snapshot's expected_points by construction rather than by counting
    -- what happened to be written.
    select p.prospect_id,
           g.point_seq,
           g.dist_miles,
           (l.point_seq is not null) as is_live,
           h.rank
      from (select distinct prospect_id from hits) p
      cross join geom g
      left join live l on l.point_seq = g.point_seq
      left join hits h on h.prospect_id = p.prospect_id and h.point_seq = g.point_seq
  )
  insert into prospect_coverage (
    prospect_id, snapshot_id, coverage_pct, points_present, live_points,
    avg_rank, best_rank, worst_rank, centroid_dist_at_loss, rank_vector
  )
  select
    c.prospect_id,
    p_snapshot_id,
    round(
      100.0 * count(*) filter (where c.is_live and c.rank is not null)
            / nullif(count(*) filter (where c.is_live), 0),
      2
    ),
    (count(*) filter (where c.is_live and c.rank is not null))::smallint,
    (count(*) filter (where c.is_live))::smallint,
    round(avg(c.rank) filter (where c.rank is not null), 2),
    (min(c.rank) filter (where c.rank is not null))::smallint,
    (max(c.rank) filter (where c.rank is not null))::smallint,
    -- centroid_dist_at_loss — "miles from the pin where they drop out" (storage spec §4). No
    -- spec gives a formula, so this is the nearest LIVE point at which the prospect is absent,
    -- and null when they hold every live point. ISSUES I-080 records the alternative reading.
    min(c.dist_miles) filter (where c.is_live and c.rank is null),
    -- The vector. 255 dead-or-unscanned, 0 measured-and-absent, otherwise the rank — storage
    -- spec §4 and reporting spec §4.2. `order by point_seq` inside string_agg is what aligns it
    -- to the pinned geometry; the clamp keeps a rank of 0 (which would read as "absent") and a
    -- rank past a byte (which would read as "dead") out of the two reserved values.
    decode(
      string_agg(
        lpad(
          to_hex(
            case
              when not c.is_live then 255
              when c.rank is null then 0
              else least(greatest(c.rank, 1), 254)
            end
          ), 2, '0'
        ),
        '' order by c.point_seq
      ),
      'hex'
    )
  from cells c
  group by c.prospect_id;

  get diagnostics rows_written = row_count;

  select count(*) filter (where gps.land),
         count(*) filter (where not gps.land)
    into v_live, v_dead
    from grid_point_status gps
   where gps.submarket_id = snap.submarket_id
     and gps.point_seq < snap.expected_points;

  select count(*) into v_measured
    from scan_task t
   where t.snapshot_id = p_snapshot_id and t.status = 'collected';

  select count(*) into v_null_now
    from scan_task t
   where t.snapshot_id = p_snapshot_id
     and t.status = 'collected'
     and not exists (
       select 1 from grid_result gr
        where gr.snapshot_id = p_snapshot_id and gr.point_seq = t.point_seq
     );

  select count(distinct pr.id) into v_prospects
    from grid_result gr
    join prospect pr on pr.place_id = gr.place_id
   where gr.snapshot_id = p_snapshot_id;

  if v_prospects = 0 then
    -- finalize_snapshot_rollup() raises on this too, and its message is the authoritative one.
    -- Saying it here first means the log names the CONDITION rather than leaving the reader to
    -- infer it from a reconciliation failure. Same fail-closed consequence as an incomplete
    -- snapshot: no marker, so the partition is never dropped (ISSUES I-075).
    raise exception
      'snapshot % matched no known prospects — nothing to roll up, and nothing to drop it against',
      p_snapshot_id;
  end if;

  -- LAST STATEMENT, deliberately. It re-derives the prospect count from grid_result and raises
  -- if the rollup covered fewer, which aborts this whole transaction — every coverage row, every
  -- mask increment. A partial rollup therefore cannot exist to be mistaken for a whole one.
  perform finalize_snapshot_rollup(p_snapshot_id);

  return jsonb_build_object(
    'snapshot_id',       p_snapshot_id,
    'status',            'rolled_up',
    'prospects',         rows_written,
    'expected_points',   snap.expected_points,
    'measured_points',   v_measured,
    'live_points',       v_live,
    'dead_points',       v_dead,
    'null_points',       v_null_now
  );
end;
$function$;

comment on function rollup_snapshot_coverage(uuid, text, jsonb, integer) is
  'Storage spec §4. Rolls one snapshot''s grid_result into prospect_coverage — land mask, '
  'summary statistics and rank_vector — in ONE transaction ending in finalize_snapshot_rollup(), '
  'so summaries without vectors cannot survive. Geometry arrives as a parameter from the pinned '
  'generator (api/services/geometry.py); this function never re-derives point membership.';

revoke all on grid_point_status from anon, authenticated;
revoke all on function rollup_snapshot_coverage(uuid, text, jsonb, integer)
  from anon, authenticated, public;

-- Deliberately NOT created here: `v_data_quality` (reporting spec §3.1), which reads
-- `grid_point_status` for its `dead_points` column and is now half-buildable. Its other half
-- counts suppressed `prospect_delta` rows, and that table does not exist yet — so building it now
-- means shipping a spec-owned view with a column missing, which is the same failure class as
-- building `grid_result` from the PRD's copy (ISSUES R-001). The rollup's return payload already
-- reports live/dead/null points per run, which is what a reader needs before the deltas exist.
