"""The coverage rollup's caller, and the path that verifies it afterwards.

The rollup ITSELF is `rollup_snapshot_coverage()` in migration `20260805120000`, and it is one
plpgsql function on purpose: `rank_vector` must be written in the same transaction as the summary
statistics, and PostgREST gives one transaction per call. A Python loop that inserted rows and
then called the finalizer could not hold both halves together — and a rollup that produces
coverage percentages without vectors must FAIL rather than partially succeed, because a vector
written later (or in the wrong point_seq order) renders every historical heatmap against
coordinates that were never used to collect it, with the picture still drawing.

So this module does three things and deliberately not a fourth:

    1. Regenerates each snapshot's geometry through the PINNED generator, using the snapshot's
       STORED `geometry_version` — never the current default.
    2. Calls the function, one snapshot per transaction.
    3. Recomputes coverage FROM the stored `rank_vector` and reconciles it against the stored
       summary columns (storage spec §12: "Coverage statistics recomputable from rank_vector and
       reconcile with stored values").

It does not aggregate. Storage spec §9 requires coverage computation to run in Postgres — pulling
~1,600 grid rows per snapshot into Python to compute percentages is both slow and billed as
egress — and re-deriving point membership here would create a second definition of the geometry,
which is the failure `geometry.py`'s version registry exists to prevent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .geometry import generate_points
from .paging import fetch_all

logger = logging.getLogger(__name__)

# The two reserved bytes, from storage spec §4 and reporting spec §4.2. `255` covers BOTH
# land-masked and never-scanned, which is why it cannot also be a rank: the renderer has to be
# able to draw a dead point differently from "not found", and conflating them overstates pain in
# the direction a prospect can catch.
BYTE_ABSENT = 0
BYTE_DEAD = 255

# Distances ride the wire as decimals. Four places is ~0.16 metres at these magnitudes — far
# finer than the flat 69-miles-per-degree approximation the lattice is built on — and it keeps the
# payload comparable run to run, which matters because `centroid_dist_at_loss` is stored from it.
_DISTANCE_PLACES = 4


@dataclass
class RollupReport:
    considered: int = 0
    rolled_up: int = 0
    already_done: int = 0
    prospect_rows: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


# --- geometry ---------------------------------------------------------------------------------


def distance_payload(
    radius_miles: float, spacing_miles: float, version: str
) -> list[dict[str, Any]]:
    """`[{"seq": n, "dist": miles}, ...]` for one snapshot's grid, in point_seq order.

    **Centre-independent, and that is load-bearing rather than a convenience.** A point's distance
    from the pin comes from `steps x spacing`; latitude only stretches the longitude STEP, never
    the membership or the offsets. So the rollup needs `grid_radius_miles` and
    `grid_spacing_miles` — both stored on the immutable snapshot — and never reads
    `submarket.center_lat/lng`, which is immutable only by convention and enforcement
    (`seeding.check_geometry_change`). See ISSUES I-078.

    `version` is REQUIRED and has no default, unlike `generate_points`. A default here would be
    the exact mistake CLAUDE.md names: regenerating a historical snapshot with the current
    generator. An unknown version raises out of the registry rather than falling back.
    """
    points = generate_points(0.0, 0.0, radius_miles, spacing_miles, version=version)
    return [
        {"seq": point.point_seq, "dist": round(point.distance_miles, _DISTANCE_PLACES)}
        for point in points
    ]


# --- what needs rolling up --------------------------------------------------------------------


def pending_snapshot_ids(
    snapshots: list[dict[str, Any]], rolled_up_ids: "set[str]"
) -> list[str]:
    """Complete snapshots with no rollup marker, oldest first. Pure.

    Ordered oldest-first because a partition drops from the oldest end, so the snapshot closest to
    blocking the retention job is the one worth rolling up first if a run is interrupted.
    """
    return [
        s["id"]
        for s in sorted(snapshots, key=lambda s: str(s.get("scanned_at") or ""))
        if s.get("complete") and s["id"] not in rolled_up_ids
    ]


def find_pending(db: Any) -> list[dict[str, Any]]:
    """The snapshot rows still needing a rollup.

    Both reads go through `fetch_all`: PostgREST caps an unbounded select at 1000 rows silently
    (HANDOFF §6.5), and both of these grow with every cycle of every market — `scan_snapshot` at
    ~30 rows per market-vertical per cycle, `snapshot_rollup` at exactly the same rate. A
    truncated marker list would look like a backlog of unrolled snapshots and re-roll nothing,
    since each one is refused by its own marker; a truncated snapshot list would silently skip
    the newest work.
    """
    snapshots = fetch_all(
        lambda: db.table("scan_snapshot")
        .select("id, submarket_id, grid_radius_miles, grid_spacing_miles, "
                "geometry_version, expected_points, complete, scanned_at")
        .eq("complete", True)
    )
    rolled = fetch_all(lambda: db.table("snapshot_rollup").select("snapshot_id"))
    done = {r["snapshot_id"] for r in rolled}
    wanted = set(pending_snapshot_ids(snapshots, done))
    return [
        s
        for s in sorted(snapshots, key=lambda s: str(s.get("scanned_at") or ""))
        if s["id"] in wanted
    ]


# --- the call ---------------------------------------------------------------------------------


def rollup_snapshot(db: Any, settings: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Roll one snapshot up. One RPC, therefore one transaction, therefore all-or-nothing."""
    payload = distance_payload(
        float(snapshot["grid_radius_miles"]),
        float(snapshot["grid_spacing_miles"]),
        snapshot["geometry_version"],
    )
    response = db.rpc(
        "rollup_snapshot_coverage",
        {
            "p_snapshot_id": snapshot["id"],
            "p_geometry_version": snapshot["geometry_version"],
            "p_points": payload,
            "p_null_scans_to_mask": settings.land_mask_null_scans,
        },
    ).execute()
    return response.data or {}


def run_rollup(
    db: Any, settings: Any, *, snapshot_ids: "list[str] | None" = None, limit: int | None = None
) -> RollupReport:
    """Roll up every complete snapshot that has no marker yet.

    Per-snapshot failures are collected rather than raised. One snapshot that cannot be rolled up
    — incomplete, matched no prospects, or holding results at a point whose task never collected —
    must not stop the others: its partition stays put (fail-closed, ISSUES I-075) and the rest of
    the backlog still clears.
    """
    report = RollupReport()

    pending = find_pending(db)
    if snapshot_ids is not None:
        wanted = set(snapshot_ids)
        pending = [s for s in pending if s["id"] in wanted]
        # Named snapshots that are NOT pending are worth a word rather than a silent omission:
        # "I asked for this one and nothing happened" is the report a caller needs.
        for missing in sorted(wanted - {s["id"] for s in pending}):
            report.problems.append(
                f"snapshot {missing} is not awaiting rollup — it is either incomplete, "
                f"already rolled up, or not a snapshot"
            )
    if limit is not None:
        pending = pending[:limit]

    report.considered = len(pending)

    for snapshot in pending:
        try:
            result = rollup_snapshot(db, settings, snapshot)
        except Exception as exc:  # noqa: BLE001 — one bad snapshot must not stop the backlog
            report.problems.append(f"snapshot {snapshot['id']}: {exc}")
            logger.error(
                "coverage rollup failed",
                extra={"snapshot_id": snapshot["id"], "error": str(exc)[:500]},
            )
            continue

        report.results.append(result)
        if result.get("status") == "already_rolled_up":
            report.already_done += 1
            continue
        report.rolled_up += 1
        report.prospect_rows += int(result.get("prospects") or 0)
        logger.info("coverage rollup complete", extra=dict(result))

    return report


# --- verification -----------------------------------------------------------------------------
#
# Storage spec §4: "The vector is sufficient for heatmap rendering and for recomputing every
# coverage statistic, so it also serves as a verification path if a rollup is ever suspected of
# being wrong." §12 makes that an acceptance criterion. These are the functions that make it one.


def decode_rank_vector(raw: Any) -> list[int]:
    """A stored `rank_vector` as a list of byte values, one per grid point in point_seq order.

    Accepts what the driver actually hands back, which is not always `bytes`: PostgREST returns
    bytea as a hex string prefixed `\\x`, and memoryview shows up depending on the path. Getting
    this wrong is silent — a hex STRING has a length of 2n+2 and would report a grid twice its
    real size with every byte wrong.
    """
    if isinstance(raw, str):
        text = raw[2:] if raw.startswith("\\x") else raw
        return list(bytes.fromhex(text))
    if isinstance(raw, memoryview):
        return list(raw.tobytes())
    if isinstance(raw, (bytes, bytearray)):
        return list(bytes(raw))
    raise TypeError(f"cannot decode a rank_vector of type {type(raw).__name__}")


def recompute_coverage(vector: list[int]) -> dict[str, Any]:
    """Every stored summary column, re-derived from the vector alone.

    Note what the vector cannot carry back: `centroid_dist_at_loss` needs distances, which are
    geometry rather than measurement, so it is verified separately (see `reconcile`). Everything
    else is recoverable, which is the property that lets a dropped partition keep its picture.
    """
    live = [b for b in vector if b != BYTE_DEAD]
    ranks = [b for b in live if b != BYTE_ABSENT]
    return {
        "points_present": len(ranks),
        "live_points": len(live),
        "dead_points": len(vector) - len(live),
        "coverage_pct": round(100.0 * len(ranks) / len(live), 2) if live else None,
        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "best_rank": min(ranks) if ranks else None,
        "worst_rank": max(ranks) if ranks else None,
    }


def reconcile(row: dict[str, Any], expected_points: int | None = None) -> list[str]:
    """Disagreements between one stored `prospect_coverage` row and its own vector.

    Returns an empty list when the row is self-consistent. Each disagreement names both numbers,
    because "coverage mismatch" without them sends the reader to re-derive what the check already
    knows.

    `centroid_dist_at_loss` is checked only for PRESENCE-consistency — it must exist when at least
    one live point is absent, and must not when the prospect holds every live point. Its VALUE
    depends on distances the vector does not carry, and inventing a second way to derive it here
    would be the same second-definition trap the geometry registry exists to close.
    """
    problems: list[str] = []
    vector = decode_rank_vector(row["rank_vector"])

    if expected_points is not None and len(vector) != expected_points:
        problems.append(
            f"rank_vector is {len(vector)} bytes, snapshot expects {expected_points} points"
        )

    computed = recompute_coverage(vector)
    for column in ("points_present", "live_points", "coverage_pct", "avg_rank",
                   "best_rank", "worst_rank"):
        stored = row.get(column)
        derived = computed[column]
        if stored is None and derived is None:
            continue
        if stored is None or derived is None:
            problems.append(f"{column}: stored {stored!r}, vector implies {derived!r}")
            continue
        if abs(float(stored) - float(derived)) > 0.011:
            problems.append(f"{column}: stored {stored}, vector implies {derived}")

    absent_live = computed["live_points"] - computed["points_present"]
    loss = row.get("centroid_dist_at_loss")
    if absent_live > 0 and loss is None:
        problems.append(
            f"centroid_dist_at_loss is null but the prospect is absent at {absent_live} live "
            f"point(s)"
        )
    if absent_live == 0 and loss is not None:
        problems.append(
            f"centroid_dist_at_loss is {loss} but the prospect holds every live point"
        )

    return problems


def verify_rollup(db: Any, snapshot_id: str) -> dict[str, Any]:
    """Re-derive every coverage statistic for one snapshot from its stored vectors."""
    snapshot = (
        db.table("scan_snapshot")
        .select("id, expected_points")
        .eq("id", snapshot_id)
        .limit(1)
        .execute()
        .data
    )
    expected = int(snapshot[0]["expected_points"]) if snapshot else None

    rows = fetch_all(
        lambda: db.table("prospect_coverage")
        .select("prospect_id, coverage_pct, points_present, live_points, avg_rank, "
                "best_rank, worst_rank, centroid_dist_at_loss, rank_vector")
        .eq("snapshot_id", snapshot_id)
    )

    problems: list[str] = []
    for row in rows:
        for problem in reconcile(row, expected):
            problems.append(f"prospect {row['prospect_id']}: {problem}")

    return {
        "snapshot_id": snapshot_id,
        "rows": len(rows),
        "expected_points": expected,
        "problems": problems,
    }
