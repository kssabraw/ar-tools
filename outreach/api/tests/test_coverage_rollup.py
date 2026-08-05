"""The coverage rollup's Python half, and a drift guard on the SQL half.

What is testable here and what is not, deliberately:

The AGGREGATION is SQL — one plpgsql function, because `rank_vector` has to be written in the same
transaction as the summary statistics and PostgREST gives one transaction per call. Mocking
Postgres to assert that a function behaves as written proves nothing, so the aggregation is
verified live by `tests/coverage_rollup.sql` (the same posture as `tests/storage_partitioning.sql`
and for the same reason).

What IS pure, and worth testing here:

  * the geometry payload — ordering, coverage of 0..n-1, centre-independence, and the refusal to
    default a version;
  * the verification path, which recomputes coverage from a stored vector and reconciles it
    against the stored columns — an acceptance criterion in storage spec §12, and the thing that
    would catch a vector packed against the wrong geometry;
  * `rollup` being free, which a future refactor could quietly break.

Plus a drift guard on the SQL's two reserved byte values, since the encoding is stated in two
places and a disagreement between them is silent: the numbers stay plausible and the heatmap
still draws.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from api.scripts.run_market import PAID_COMMANDS
from api.services import coverage_rollup as cr
from api.services.geometry import GEOMETRY_VERSION, UnknownGeometryVersion, point_count

MIGRATION = (
    Path(__file__).resolve().parents[2] / "migrations" / "20260805120000_coverage_rollup.sql"
)


# --- geometry payload -------------------------------------------------------------------------


def test_payload_covers_every_point_seq_exactly_once():
    payload = cr.distance_payload(5.0, 1.0, GEOMETRY_VERSION)
    seqs = [p["seq"] for p in payload]
    assert seqs == list(range(point_count(5.0, 1.0)))
    assert len(payload) == 81


def test_payload_is_in_point_seq_order():
    """Order is the whole contract. The SQL aligns bytes with `order by point_seq`, but the
    payload is also validated against `generate_series`, so an out-of-order payload would pass the
    membership check and place distances against the wrong points."""
    payload = cr.distance_payload(5.0, 1.0, GEOMETRY_VERSION)
    assert payload == sorted(payload, key=lambda p: p["seq"])


def test_distances_never_exceed_the_radius():
    """The clip is `distance <= radius`, so a distance past it means the payload was built from a
    different lattice than the one that was scanned."""
    payload = cr.distance_payload(5.0, 1.0, GEOMETRY_VERSION)
    assert max(p["dist"] for p in payload) <= 5.0
    assert min(p["dist"] for p in payload) == 0.0  # the centre point exists


def test_payload_is_centre_independent():
    """Why the rollup never reads `submarket.center_lat/lng`.

    Distances come from `steps x spacing`; latitude stretches only the longitude STEP. If this
    ever stopped holding, the rollup would depend on a column that is immutable by enforcement
    rather than by storage, and a corrected centre would silently rewrite `centroid_dist_at_loss`
    for every historical snapshot. See ISSUES I-078.
    """
    from api.services.geometry import generate_points

    equator = [round(p.distance_miles, 4) for p in generate_points(0.0, 0.0, 5.0, 1.0)]
    los_angeles = [round(p.distance_miles, 4) for p in generate_points(34.05, -118.24, 5.0, 1.0)]
    assert equator == los_angeles


def test_payload_requires_a_version_and_refuses_an_unknown_one():
    """`generate_points` defaults its version; this deliberately does not.

    Regenerating a historical snapshot with the current generator is named in CLAUDE.md as a
    mistake, and a default parameter is how it would get made — silently, since the wrong
    coordinates still render.
    """
    with pytest.raises(TypeError):
        cr.distance_payload(5.0, 1.0)  # type: ignore[call-arg]
    with pytest.raises(UnknownGeometryVersion):
        cr.distance_payload(5.0, 1.0, "v99")


# --- pending selection ------------------------------------------------------------------------


def _snap(sid, *, complete=True, scanned_at="2026-08-01T00:00:00Z"):
    return {"id": sid, "complete": complete, "scanned_at": scanned_at}


def test_pending_skips_incomplete_and_already_rolled_up():
    snapshots = [
        _snap("a"),
        _snap("b", complete=False),
        _snap("c"),
    ]
    assert cr.pending_snapshot_ids(snapshots, {"c"}) == ["a"]


def test_pending_is_oldest_first():
    """A partition drops from the oldest end, so the snapshot nearest to blocking retention is the
    one an interrupted run should have got to first."""
    snapshots = [
        _snap("new", scanned_at="2026-08-04T00:00:00Z"),
        _snap("old", scanned_at="2026-06-01T00:00:00Z"),
        _snap("mid", scanned_at="2026-07-01T00:00:00Z"),
    ]
    assert cr.pending_snapshot_ids(snapshots, set()) == ["old", "mid", "new"]


# --- vector decoding --------------------------------------------------------------------------


def test_decode_accepts_every_shape_the_driver_returns():
    """PostgREST hands bytea back as a `\\x`-prefixed hex STRING. Treating that as bytes gives a
    grid of 2n+2 points with every value wrong — and it would still render."""
    raw = bytes([1, 0, 255])
    assert cr.decode_rank_vector(raw) == [1, 0, 255]
    assert cr.decode_rank_vector(bytearray(raw)) == [1, 0, 255]
    assert cr.decode_rank_vector(memoryview(raw)) == [1, 0, 255]
    assert cr.decode_rank_vector("\\x0100ff") == [1, 0, 255]
    assert cr.decode_rank_vector("0100ff") == [1, 0, 255]


def test_decode_refuses_a_type_it_cannot_read():
    with pytest.raises(TypeError):
        cr.decode_rank_vector(12345)


# --- recomputation ----------------------------------------------------------------------------


def test_recompute_excludes_dead_points_from_the_denominator():
    """The property the whole rollup exists to preserve: the denominator counts LIVE points, and
    a dead point is neither present nor absent — it was never measured there."""
    vector = [1, 2, 0, 255, 255]
    assert cr.recompute_coverage(vector) == {
        "points_present": 2,
        "live_points": 3,
        "dead_points": 2,
        "coverage_pct": 66.67,
        "avg_rank": 1.5,
        "best_rank": 1,
        "worst_rank": 2,
    }


def test_recompute_handles_a_prospect_absent_everywhere_live():
    vector = [0, 0, 255]
    stats = cr.recompute_coverage(vector)
    assert stats["coverage_pct"] == 0.0
    assert stats["avg_rank"] is None and stats["best_rank"] is None


def test_recompute_handles_an_all_dead_grid():
    """Should be unreachable — a prospect only gets a row by appearing somewhere, and a point with
    results is live. `coverage_pct` is NOT NULL in the schema, so if this ever happened the insert
    would fail loudly rather than store a zero nobody could interpret."""
    assert cr.recompute_coverage([255, 255])["coverage_pct"] is None


# --- reconciliation ---------------------------------------------------------------------------


def _row(vector, **overrides):
    stats = cr.recompute_coverage(vector)
    row = {
        "rank_vector": bytes(vector),
        "coverage_pct": stats["coverage_pct"],
        "points_present": stats["points_present"],
        "live_points": stats["live_points"],
        "avg_rank": stats["avg_rank"],
        "best_rank": stats["best_rank"],
        "worst_rank": stats["worst_rank"],
        "centroid_dist_at_loss": 2.0 if stats["points_present"] < stats["live_points"] else None,
    }
    row.update(overrides)
    return row


def test_a_consistent_row_reconciles_clean():
    assert cr.reconcile(_row([1, 3, 0, 255]), expected_points=4) == []


def test_reconcile_catches_a_summary_that_disagrees_with_its_own_vector():
    problems = cr.reconcile(_row([1, 3, 0, 255], points_present=5))
    assert len(problems) == 1
    assert "points_present" in problems[0] and "5" in problems[0]


def test_reconcile_catches_a_vector_of_the_wrong_length():
    """The failure mode this exists for: a vector packed against a different geometry than the
    snapshot's. Every statistic can still agree with the vector and every one of them be about the
    wrong grid."""
    problems = cr.reconcile(_row([1, 0, 255]), expected_points=81)
    assert any("81" in p and "3 bytes" in p for p in problems)


def test_reconcile_checks_centroid_dist_presence_not_value():
    """It cannot be recomputed from the vector — distances are geometry, not measurement — so only
    its presence is checked. Inventing a second derivation here would be the same
    second-definition trap the geometry version registry exists to close."""
    absent_somewhere = _row([1, 0, 255], centroid_dist_at_loss=None)
    assert any("centroid_dist_at_loss" in p for p in cr.reconcile(absent_somewhere))

    holds_everything = _row([1, 2, 255], centroid_dist_at_loss=1.0)
    assert any("holds every live point" in p for p in cr.reconcile(holds_everything))


def test_reconcile_tolerates_rounding_but_not_a_real_difference():
    row = _row([1, 2, 0])
    row["coverage_pct"] = 66.66  # stored rounding vs 66.67
    assert cr.reconcile(row) == []
    row["coverage_pct"] = 66.0
    assert cr.reconcile(row) != []


# --- the SQL, guarded against drift -----------------------------------------------------------


def test_migration_exists():
    assert MIGRATION.exists()


def test_sql_and_python_agree_on_the_reserved_bytes():
    """The encoding is stated in storage spec §4, in the SQL that writes it, and in this module
    that reads it back. A disagreement is silent: 255 read as a rank would put a dead point at the
    bottom of the pack, and 0 read as dead would shrink the denominator."""
    sql = MIGRATION.read_text()
    assert f"then {cr.BYTE_DEAD}" in sql
    assert f"then {cr.BYTE_ABSENT}" in sql
    assert f"least(greatest(c.rank, 1), {cr.BYTE_DEAD - 1})" in sql


def test_finalize_is_the_last_statement_of_the_rollup():
    """The completion contract's whole load-bearing property (ISSUES I-069). If the finalizer ever
    stops being last, a statement after it could write rows the marker has already vouched for."""
    sql = MIGRATION.read_text()
    body = sql[sql.index("$function$"):]
    after = body[body.index("perform finalize_snapshot_rollup"):]
    # Only the return, the end of the function, and comments may follow it.
    statements = [
        line.strip()
        for line in after.splitlines()[1:]
        if line.strip() and not line.strip().startswith("--")
    ]
    assert statements[0].startswith("return jsonb_build_object"), statements[:3]


def test_the_vector_is_packed_in_point_seq_order():
    """`string_agg` without an ORDER BY has no defined order at all, and the resulting vector would
    be plausible, stable-looking, and aligned to nothing."""
    sql = MIGRATION.read_text()
    assert re.search(r"string_agg\(.*?order by c\.point_seq", sql, re.S)


def test_the_denominator_reads_scan_task_not_grid_result():
    """Count what was MEASURED, never what was FOUND — the correction this system has now needed
    three times (DECISIONS.md `actual_points`, ISSUES I-069, and here). `scan_task.status =
    'collected'` records measurement; grid_result can only record discovery."""
    sql = MIGRATION.read_text()
    live_cte = sql[sql.index("live as ("):sql.index("hits as (")]
    assert "scan_task" in live_cte and "status = 'collected'" in live_cte
    assert "gps.land" in live_cte


def test_rollup_is_free_and_must_stay_free():
    """`rollup` contacts no provider. Spend-gating it would make the collector's tick refuse on
    every deploy that has no confirmation token — which is every routine deploy — and the backlog
    would silently stop draining. Same reasoning as `collect` (HANDOFF §8a)."""
    assert "rollup" not in PAID_COMMANDS
    assert "collect" not in PAID_COMMANDS
