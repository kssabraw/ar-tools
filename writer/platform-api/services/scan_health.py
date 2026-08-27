"""Scan-failure streak alerting — a health watch over the suite's scheduled
data collection so a silent upstream outage can't quietly starve the rank /
geogrid drop alerts.

The drop alerts (`rank_drop`, `maps_drop`) can only fire when fresh data exists
to diff. When the upstream data pull keeps failing — a Local Dominator credit
outage, a revoked GSC service-account, a DataForSEO outage — no scan completes,
no comparison runs, and the team hears nothing. That is exactly how five clients
went 23 days with zero geogrid alerts (Local Dominator returning a 500 on every
scheduled scan) before anyone noticed: the *absence* of alerts looked like
"nothing changed."

This closes that gap. The three scheduled data-collection jobs that feed the
drop alerts each record a terminal row in ``async_jobs`` keyed to a client:

  * ``maps_scan``       (entity_id = client_id)          → geo-grid pipeline
  * ``dataforseo_rank`` (entity_id = client_id)          → organic rank pipeline
  * ``gsc_ingest``      (entity_id = gsc_properties.id)   → organic rank pipeline

A daily DB-reads-only sweep computes, per (client, pipeline), the run of
consecutive failures since the last success (a success of *either* organic
source resets the organic streak — the hybrid needs only one working feed). When
that run is both long enough and old enough it emits ONE ``scan_health``
notification through the shared notifications pipe (in-app + Slack), deduped per
streak-episode so an ongoing outage re-nudges at most weekly instead of daily.

Pure helpers (``failure_streak`` / ``should_alert`` / ``episode_key`` /
``build_digest``) are unit-tested; the sweep is best-effort and never raises into
the scheduler.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from config import settings
from db.supabase_client import get_supabase
from services import notifications

logger = logging.getLogger(__name__)

# job_type -> (pipeline_key, human label, deep-link tab). Two job types share the
# "organic" pipeline so a success of either resets the client's organic streak.
_JOB_PIPELINES: dict[str, tuple[str, str, str]] = {
    "maps_scan": ("geogrid", "Maps geo-grid", "maps"),
    "dataforseo_rank": ("organic", "Organic rank", "rankings"),
    "gsc_ingest": ("organic", "Organic rank", "rankings"),
}
_PIPELINE_LABELS = {"geogrid": "Maps geo-grid", "organic": "Organic rank"}
_PIPELINE_TABS = {"geogrid": "maps", "organic": "rankings"}

_TERMINAL = ("complete", "failed")


# ----------------------------------------------------------------------------
# Pure helpers (no I/O) — independently unit-tested.
# ----------------------------------------------------------------------------
@dataclass
class JobRun:
    status: str
    created_at: datetime


@dataclass
class StreakInfo:
    streak: int                              # consecutive failures since last success
    last_success_at: Optional[datetime]      # None if none in the window
    oldest_failure_at: Optional[datetime]    # start of the current failing run


def failure_streak(runs: Sequence[JobRun]) -> StreakInfo:
    """Count consecutive failures back from the most recent terminal run.

    Non-terminal statuses (pending/running) are ignored. Iterating newest-first,
    leading failures accumulate until the first ``complete`` (which anchors the
    streak's start), or the window is exhausted (never succeeded).
    """
    terminal = sorted(
        (r for r in runs if r.status in _TERMINAL),
        key=lambda r: r.created_at,
        reverse=True,
    )
    streak = 0
    oldest_failure: Optional[datetime] = None
    for r in terminal:
        if r.status == "failed":
            streak += 1
            oldest_failure = r.created_at
        else:  # a success — the streak ends here
            return StreakInfo(streak, r.created_at, oldest_failure)
    return StreakInfo(streak, None, oldest_failure)


def should_alert(info: StreakInfo, now: datetime, min_streak: int, min_days: int) -> bool:
    """A streak alerts when it is both long enough (≥ min_streak consecutive
    failures) and old enough (the failing run has spanned ≥ min_days), so a
    couple of same-day retries never fire. Age is measured from the last success
    if there was one, else from the oldest observed failure."""
    if info.streak < min_streak:
        return False
    anchor = info.last_success_at or info.oldest_failure_at
    if anchor is None:
        return False
    return (now - anchor) >= timedelta(days=min_days)


def episode_key(pipeline_key: str, client_id: str, info: StreakInfo, now: datetime) -> str:
    """Dedupe key for one streak episode. The anchor (last-success date, or
    'never') keeps a single ongoing outage on one key so a recovery-then-rebreak
    starts a fresh alert; the ISO-week suffix lets an unresolved outage re-nudge
    at most once a week rather than every daily sweep."""
    anchor = info.last_success_at.date().isoformat() if info.last_success_at else "never"
    year, week, _ = now.isocalendar()
    return f"scan_health:{pipeline_key}:{client_id}:{anchor}:{year}W{week:02d}"


def _days_between(a: Optional[datetime], b: datetime) -> Optional[int]:
    if a is None:
        return None
    return max(0, (b - a).days)


def build_digest(
    client_name: str,
    pipeline_key: str,
    info: StreakInfo,
    sample_error: Optional[str],
    now: datetime,
) -> dict:
    """A {title, summary, severity} digest for one failing (client, pipeline).
    Pure — the notification copy."""
    label = _PIPELINE_LABELS.get(pipeline_key, pipeline_key)
    n = info.streak
    title = f"{label} scans failing for {client_name}"
    days = _days_between(info.last_success_at, now)
    if info.last_success_at is not None and days is not None:
        since = f"; last succeeded {days} day{'s' if days != 1 else ''} ago"
    else:
        stale = _days_between(info.oldest_failure_at, now)
        since = (
            f"; no success in the last {stale} day{'s' if stale != 1 else ''}"
            if stale is not None
            else "; no recent success"
        )
    parts = [
        f"{n} consecutive scheduled {label} run{'s' if n != 1 else ''} have failed{since}. "
        "Drop alerts for this client are blocked until it recovers."
    ]
    if sample_error:
        parts.append(f"Latest error: {sample_error.strip()[:280]}")
    return {"title": title, "summary": " ".join(parts), "severity": "warning"}


# ----------------------------------------------------------------------------
# Sweep (I/O) — best-effort, never raises into the scheduler.
# ----------------------------------------------------------------------------
def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _client_names(supabase, client_ids: Sequence[str]) -> dict[str, str]:
    if not client_ids:
        return {}
    rows = (
        supabase.table("clients").select("id, name").in_("id", list(client_ids)).execute()
    ).data or []
    return {r["id"]: r.get("name") or "Unknown client" for r in rows}


def run_scan_health_sweep() -> dict:
    """Daily: alert on any client whose scheduled data-collection jobs (maps
    geo-grid / organic rank) have been failing in a streak. DB reads only."""
    if not settings.scan_health_enabled:
        return {"skipped": "disabled"}
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    lookback = now - timedelta(days=settings.scan_health_lookback_days)

    try:
        rows = (
            supabase.table("async_jobs")
            .select("job_type, entity_id, status, error, created_at")
            .in_("job_type", list(_JOB_PIPELINES))
            .in_("status", list(_TERMINAL))
            .gte("created_at", lookback.isoformat())
            .order("created_at", desc=True)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("scan_health.read_failed", extra={"error": str(exc)})
        return {"error": str(exc)}

    # Resolve gsc_ingest's property entity → client_id.
    property_ids = sorted(
        {r["entity_id"] for r in rows if r["job_type"] == "gsc_ingest" and r.get("entity_id")}
    )
    prop_to_client: dict[str, str] = {}
    if property_ids:
        try:
            props = (
                supabase.table("gsc_properties")
                .select("id, client_id")
                .in_("id", property_ids)
                .execute()
            ).data or []
            prop_to_client = {p["id"]: p["client_id"] for p in props if p.get("client_id")}
        except Exception as exc:
            logger.warning("scan_health.property_lookup_failed", extra={"error": str(exc)})

    # Group terminal runs by (client_id, pipeline_key); capture the most-recent
    # failure's error per group for the digest (rows are newest-first).
    groups: dict[tuple[str, str], list[JobRun]] = defaultdict(list)
    sample_errors: dict[tuple[str, str], str] = {}
    for r in rows:
        pipeline_key = _JOB_PIPELINES[r["job_type"]][0]
        if r["job_type"] == "gsc_ingest":
            client_id = prop_to_client.get(r.get("entity_id"))
        else:
            client_id = r.get("entity_id")
        if not client_id:
            continue
        ts = _parse_ts(r.get("created_at"))
        if ts is None:
            continue
        key = (client_id, pipeline_key)
        groups[key].append(JobRun(status=r["status"], created_at=ts))
        if r["status"] == "failed" and key not in sample_errors and r.get("error"):
            sample_errors[key] = r["error"]

    # Decide which groups alert, then batch-resolve their client names.
    alerting: list[tuple[tuple[str, str], StreakInfo]] = []
    for key, runs in groups.items():
        info = failure_streak(runs)
        if should_alert(info, now, settings.scan_health_min_streak, settings.scan_health_min_days):
            alerting.append((key, info))

    names = _client_names(supabase, sorted({cid for (cid, _), _ in alerting}))

    emitted = 0
    producer_items: list[dict] = []
    for (client_id, pipeline_key), info in alerting:
        try:
            digest = build_digest(
                names.get(client_id, "Unknown client"),
                pipeline_key,
                info,
                sample_errors.get((client_id, pipeline_key)),
                now,
            )
            nid = notifications.emit(
                client_id=client_id,
                kind="scan_health",
                title=digest["title"],
                summary=digest["summary"],
                severity=digest["severity"],
                payload={
                    "link": f"clients/{client_id}/{_PIPELINE_TABS.get(pipeline_key, 'rankings')}",
                    "pipeline": pipeline_key,
                    "streak": info.streak,
                },
                dedupe_key=episode_key(pipeline_key, client_id, info, now),
            )
            if nid:
                emitted += 1
            producer_items.append(
                {
                    "client_id": client_id,
                    "pipeline_key": pipeline_key,
                    "label": _PIPELINE_LABELS.get(pipeline_key, pipeline_key),
                    "streak": info.streak,
                    "summary": digest["summary"],
                }
            )
        except Exception as exc:  # never break the sweep on one client
            logger.warning(
                "scan_health.emit_failed",
                extra={"client_id": client_id, "pipeline": pipeline_key, "error": str(exc)},
            )

    # Hand the alerting set to the native-task producer so a sustained outage
    # becomes owned board work (PACE picks it up). Called even when nothing is
    # alerting, so a recovered streak closes its task. Best-effort + self-gated.
    try:
        from services import task_producers

        task_producers.on_scan_health(producer_items)
    except Exception as exc:
        logger.warning("scan_health.producer_failed", extra={"error": str(exc)})

    if alerting:
        logger.info(
            "scan_health.sweep_complete",
            extra={"groups": len(groups), "alerting": len(alerting), "emitted": emitted},
        )
    return {"groups": len(groups), "alerting": len(alerting), "emitted": emitted}
