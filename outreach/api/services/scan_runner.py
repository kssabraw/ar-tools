"""Submission and collection for the Maps geogrid. The half that touches the provider and the DB.

Two runs, deliberately on different schedules (PRD §B1, DECISIONS.md):

    submit    per scan cadence (15 days). BILLS. Posts one task per grid point.
    collect   hourly or daily. FREE. Drains `tasks_ready`, stores results, closes snapshots.

**The cadence gap is the load-bearing part.** The ready list holds a task for roughly three days.
A collector running on the scan cadence would let every task age off between runs, silently
converting the normal path into the fallback-by-id path — which still works, which is exactly why
nobody would notice. So collection is frequent, and it is free, so there is no reason for it not
to be.

WHAT MAKES THIS RESTART-SAFE.

Every ordering here is chosen so that an interruption loses at most one point, and always in the
cheap direction. Rows are written `pending` before the provider is paid, so a crash mid-post
leaves work to redo rather than money with no record. Results are written before the task is
marked collected, so a crash mid-collect re-collects (free) rather than losing (paid). Snapshots
are finalized only when every task is terminal, and finalization asserts what it is about to
claim rather than trusting that the writes happened.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import Settings
from . import maps_scan
from .geometry import GEOMETRY_VERSION, generate_points, point_count
from .maps_scan import MapsScanError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.dataforseo.com"


def _auth_header(settings: Settings) -> dict[str, str]:
    creds = f"{settings.dataforseo_login}:{settings.dataforseo_password}"
    encoded = base64.b64encode(creds.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


@dataclass
class SubmitReport:
    snapshot_id: str = ""
    submarket: str = ""
    keyword: str = ""
    expected_points: int = 0
    posted: int = 0
    unposted: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class CollectReport:
    ready_seen: int = 0
    collected: int = 0
    rows_written: int = 0
    still_pending: int = 0
    failed: int = 0
    foreign: int = 0          # ready-list entries this system did not send
    recovered_by_tag: int = 0  # results we could only reattach through the tag
    snapshots_finalized: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def month_of(scanned_at: str | datetime) -> date:
    """The partition key for a snapshot's rows — its OWN month, never the clock's.

    ISSUES I-044. This is a one-line function so that there is exactly one place the derivation
    happens and no call site is tempted to write `date.today()`, which is right until a
    collection lands on the far side of a month boundary from its submission. That gap is hours
    or days wide here, so it is not a theoretical window.
    """
    if isinstance(scanned_at, str):
        scanned_at = datetime.fromisoformat(scanned_at.replace("Z", "+00:00"))
    return scanned_at.date().replace(day=1)


# --- submission -------------------------------------------------------------------------------


async def submit_scan(
    db: Any,
    settings: Settings,
    submarket: dict[str, Any],
    keyword: dict[str, Any],
    *,
    client: httpx.AsyncClient | None = None,
) -> SubmitReport:
    """Open a snapshot for one submarket x keyword and post every point. BILLS.

    The snapshot row is created FIRST and carries `expected_points` from the geometry generator,
    so completeness has a denominator that does not depend on how the scan went. A denominator
    derived after the fact from what came back would make every scan complete by construction.
    """
    report = SubmitReport(
        submarket=str(submarket.get("name") or ""), keyword=str(keyword.get("term") or "")
    )

    radius = float(submarket["grid_radius_miles"])
    spacing = float(submarket["grid_spacing_miles"])
    points = generate_points(
        float(submarket["center_lat"]), float(submarket["center_lng"]), radius, spacing
    )
    expected = point_count(radius, spacing)
    if len(points) != expected:
        # Two paths to the same number disagreeing means one of them is wrong, and a scan built
        # on the wrong one would mis-number every point_seq for the life of the snapshot.
        raise MapsScanError(
            f"geometry disagrees with itself: generated {len(points)}, counted {expected}"
        )
    report.expected_points = expected

    snapshot = (
        db.table("scan_snapshot")
        .insert(
            {
                "submarket_id": submarket["id"],
                "keyword_id": keyword["id"],
                "grid_radius_miles": radius,
                "grid_spacing_miles": spacing,
                "point_count": expected,
                "expected_points": expected,
                "actual_points": 0,
                "complete": False,
                "geometry_version": GEOMETRY_VERSION,
            }
        )
        .execute()
        .data[0]
    )
    snapshot_id = snapshot["id"]
    report.snapshot_id = snapshot_id

    tasks = maps_scan.build_grid_tasks(
        snapshot_id,
        report.keyword,
        points,
        zoom=settings.scan_zoom,
        depth=settings.scan_depth,
        language_code=settings.dataforseo_default_language_code,
        device=settings.scan_device,
    )

    # Rows before money. A `pending` row is a point we might repost; a lost `submitted` row is a
    # paid task nobody can collect.
    db.table("scan_task").insert(
        [{"snapshot_id": snapshot_id, "point_seq": seq, "status": "pending"} for seq, _ in tasks]
    ).execute()

    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    try:
        for batch in maps_scan.chunk(tasks, maps_scan.MAX_TASKS_PER_POST):
            bodies = [body for _, body in batch]
            try:
                response = await client.post(
                    f"{BASE_URL}{maps_scan.TASK_POST_PATH}",
                    headers=_auth_header(settings),
                    json=bodies,
                )
                response.raise_for_status()
                posted = maps_scan.parse_task_post(response.json(), batch)
            except (httpx.HTTPError, MapsScanError) as exc:
                # The batch stays `pending`. Reposting an unposted point costs one point;
                # assuming it posted costs the result. Note the genuinely ambiguous case — a
                # request the provider accepted whose response we never saw — is NOT lost: the
                # tag lets the collector reattach it when it appears on the ready list.
                report.problems.append(f"batch of {len(batch)} failed to post: {exc}")
                report.unposted += len(batch)
                continue

            now = datetime.now(timezone.utc).isoformat()
            for task in posted:
                if task.accepted and task.task_id:
                    db.table("scan_task").update(
                        {
                            "provider_task_id": task.task_id,
                            "status": "submitted",
                            "submitted_at": now,
                        }
                    ).eq("snapshot_id", snapshot_id).eq("point_seq", task.point_seq).execute()
                    report.posted += 1
                else:
                    db.table("scan_task").update(
                        {"last_error": task.error}
                    ).eq("snapshot_id", snapshot_id).eq("point_seq", task.point_seq).execute()
                    report.unposted += 1
                    report.problems.append(f"point {task.point_seq}: {task.error}")
    finally:
        if owns:
            await client.aclose()

    logger.info(
        "geogrid submitted",
        extra={
            "snapshot_id": snapshot_id,
            "posted": report.posted,
            "unposted": report.unposted,
            "expected": expected,
        },
    )
    return report


# --- collection -------------------------------------------------------------------------------


async def collect_ready(
    db: Any,
    settings: Settings,
    *,
    client: httpx.AsyncClient | None = None,
    max_rounds: int = 20,
) -> CollectReport:
    """Drain `tasks_ready`, store every result, finalize whatever that completes. FREE.

    **Loops.** The ready list returns at most 1000 entries and will not reveal the rest until the
    current batch is collected, so a single pass silently under-collects on any cycle bigger than
    that — which is every real cycle, since one market-vertical is ~14 submarkets x 81 points x
    several keywords. `max_rounds` bounds the loop rather than trusting the provider to empty it.
    """
    report = CollectReport()
    owns = client is None
    client = client or httpx.AsyncClient(timeout=settings.dataforseo_request_timeout_seconds)
    touched: set[str] = set()

    try:
        for _ in range(max_rounds):
            response = await client.get(
                f"{BASE_URL}{maps_scan.TASKS_READY_PATH}", headers=_auth_header(settings)
            )
            response.raise_for_status()
            ready = maps_scan.parse_tasks_ready(response.json())
            if not ready:
                break

            mine = [r for r in ready if r.snapshot_id]
            report.ready_seen += len(mine)
            report.foreign += len(ready) - len(mine)
            if not mine:
                # The list is non-empty but none of it is ours. Looping again would return the
                # same entries forever, since only their owner can clear them.
                break

            for entry in mine:
                touched.add(entry.snapshot_id or "")
                await _collect_one(db, settings, client, entry.task_id, entry.snapshot_id,
                                   entry.point_seq, report)

        # The fallback path (PRD §B1.3): anything submitted long enough ago to have aged off the
        # ready list. Results stay retrievable by id for 30 days, so this is a normal recovery
        # and not an emergency — but it is also how a broken collector looks from the outside, so
        # `stale_recovered` is reported rather than absorbed.
        touched |= await _collect_overdue(db, settings, client, report)
    finally:
        if owns:
            await client.aclose()

    for snapshot_id in sorted(s for s in touched if s):
        if finalize_snapshot(db, settings, snapshot_id):
            report.snapshots_finalized.append(snapshot_id)

    return report


async def _collect_one(
    db: Any,
    settings: Settings,
    client: httpx.AsyncClient,
    task_id: str,
    snapshot_id: str | None,
    point_seq: int | None,
    report: CollectReport,
) -> None:
    """Fetch one task and store its rows.

    Order matters: rows first, `collected` last. A crash between them re-collects a task that is
    free to re-collect. The reverse order would mark a point done whose rows never landed, and
    the snapshot would finalize with a hole in it that nothing downstream could detect.
    """
    row = (
        db.table("scan_task")
        .select("id, snapshot_id, point_seq, status")
        .eq("provider_task_id", task_id)
        .limit(1)
        .execute()
        .data
    )
    task_row = row[0] if row else None

    if task_row is None:
        # We never stored this id. Either the post's response was lost, or a previous run of this
        # collector crashed between the POST and the update. The tag is what makes it recoverable.
        if snapshot_id is None or point_seq is None:
            report.problems.append(f"task {task_id} is unknown and carries no usable tag")
            return
        found = (
            db.table("scan_task")
            .select("id, snapshot_id, point_seq, status")
            .eq("snapshot_id", snapshot_id)
            .eq("point_seq", point_seq)
            .limit(1)
            .execute()
            .data
        )
        if not found:
            report.problems.append(
                f"task {task_id} tagged {snapshot_id}:{point_seq}, which is not a known point"
            )
            return
        task_row = found[0]
        db.table("scan_task").update(
            {"provider_task_id": task_id, "status": "submitted"}
        ).eq("id", task_row["id"]).execute()
        report.recovered_by_tag += 1
        logger.warning(
            "geogrid task recovered by tag",
            extra={"task_id": task_id, "snapshot_id": snapshot_id, "point_seq": point_seq},
        )

    if task_row["status"] == "collected":
        return

    seq = int(task_row["point_seq"])
    try:
        response = await client.get(
            f"{BASE_URL}{maps_scan.TASK_GET_PATH}/{task_id}", headers=_auth_header(settings)
        )
        response.raise_for_status()
        state, rows = maps_scan.parse_grid_result(response.json(), seq)
    except (httpx.HTTPError, MapsScanError) as exc:
        # Transient by assumption: the row stays `submitted` and the next tick retries. Collection
        # is free, so retrying costs nothing and giving up costs a paid task.
        report.problems.append(f"task {task_id}: {exc}")
        db.table("scan_task").update({"last_error": str(exc)[:500]}).eq(
            "id", task_row["id"]
        ).execute()
        return

    if state == "pending":
        report.still_pending += 1
        return
    if state == "error":
        report.failed += 1
        db.table("scan_task").update(
            {"status": "failed", "last_error": "provider returned a task-level error"}
        ).eq("id", task_row["id"]).execute()
        return

    snapshot = (
        db.table("scan_snapshot")
        .select("id, scanned_at")
        .eq("id", task_row["snapshot_id"])
        .limit(1)
        .execute()
        .data
    )
    if not snapshot:
        report.problems.append(f"task {task_id} points at a missing snapshot")
        return
    scan_month = month_of(snapshot[0]["scanned_at"])

    if rows:
        db.table("grid_result").insert(
            [
                {
                    "snapshot_id": task_row["snapshot_id"],
                    "scan_month": scan_month.isoformat(),
                    "point_seq": r.point_seq,
                    "place_id": r.place_id,
                    "rank": r.rank,
                }
                for r in rows
            ]
        ).execute()
        report.rows_written += len(rows)

    db.table("scan_task").update(
        {
            "status": "collected",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "result_count": len(rows),
        }
    ).eq("id", task_row["id"]).execute()
    report.collected += 1


async def _collect_overdue(
    db: Any, settings: Settings, client: httpx.AsyncClient, report: CollectReport
) -> set[str]:
    """Collect by id anything that has aged off the ready list, and alert on the truly stuck."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.scan_collect_fallback_days)
    overdue = (
        db.table("scan_task")
        .select("provider_task_id, snapshot_id, point_seq, submitted_at")
        .eq("status", "submitted")
        .lt("submitted_at", cutoff.isoformat())
        .limit(settings.scan_collect_fallback_limit)
        .execute()
        .data
        or []
    )

    alert_cutoff = datetime.now(timezone.utc) - timedelta(days=settings.scan_collect_alert_days)
    touched: set[str] = set()
    for row in overdue:
        task_id = row.get("provider_task_id")
        if not task_id:
            continue
        touched.add(row["snapshot_id"])
        await _collect_one(
            db, settings, client, task_id, row["snapshot_id"], row.get("point_seq"), report
        )
        submitted = row.get("submitted_at")
        if submitted:
            when = datetime.fromisoformat(str(submitted).replace("Z", "+00:00"))
            if when < alert_cutoff:
                # PRD §B1.4. Loud, because a task still uncollected at this age means the
                # collector's schedule is wrong, not that this task is unlucky — and the
                # difference is invisible from any single run.
                logger.error(
                    "geogrid task uncollected past the alert threshold",
                    extra={"task_id": task_id, "submitted_at": submitted},
                )
                report.problems.append(f"task {task_id} uncollected since {submitted}")
    return touched


# --- finalization -----------------------------------------------------------------------------


def finalize_snapshot(db: Any, settings: Settings, snapshot_id: str) -> bool:
    """Close a snapshot once every one of its tasks is terminal. Returns True if it closed.

    `actual_points` counts POINTS COLLECTED, not grid rows. A point that returned no businesses
    was scanned — the answer is "nobody ranks here", which is a finding and often the strongest
    one in the whole grid. Counting rows instead would mark a submarket's genuine dead zones as
    scan failures, and a market with real dead zones would read as permanently incomplete.
    """
    tasks = (
        db.table("scan_task")
        .select("status")
        .eq("snapshot_id", snapshot_id)
        .execute()
        .data
        or []
    )
    if not tasks:
        return False
    if any(t["status"] in ("pending", "submitted") for t in tasks):
        return False

    collected = sum(1 for t in tasks if t["status"] == "collected")
    snapshot = (
        db.table("scan_snapshot")
        .select("expected_points")
        .eq("id", snapshot_id)
        .limit(1)
        .execute()
        .data
    )
    if not snapshot:
        return False
    expected = int(snapshot[0]["expected_points"])
    complete = maps_scan.is_complete(collected, expected, settings.scan_completeness_threshold)

    db.table("scan_snapshot").update(
        {"actual_points": collected, "complete": complete}
    ).eq("id", snapshot_id).execute()

    # Assert rather than assume. This is the guard that catches a writer deriving scan_month from
    # the clock — the mistake that splits one snapshot across two partitions and only surfaces
    # months later, in the retention job, blaming the rollup (ISSUES I-044).
    try:
        db.rpc("assert_snapshot_month", {"p_snapshot_id": snapshot_id}).execute()
    except Exception as exc:  # noqa: BLE001 - the message is the point
        logger.error(
            "snapshot month assertion failed",
            extra={"snapshot_id": snapshot_id, "error": str(exc)},
        )
        raise

    logger.info(
        "geogrid snapshot finalized",
        extra={
            "snapshot_id": snapshot_id,
            "actual_points": collected,
            "expected_points": expected,
            "complete": complete,
        },
    )
    return True
