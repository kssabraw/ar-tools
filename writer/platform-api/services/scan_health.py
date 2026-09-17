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
from datetime import date, datetime, timedelta, timezone
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


# ----------------------------------------------------------------------------
# Rank-data FRESHNESS watch — the dead-man's switch.
#
# scan_health above catches jobs that FAIL. This catches the failure both prior
# silent freezes shared: jobs SUCCEED but the data stops advancing. It reads the
# actual data recency (rank_keyword_metrics) rather than job outcomes, so it fires
# whatever the cause — a too-narrow ingest window, a materialize bug, a scheduler
# outage, or the next unknown one. Edge-triggered via rank_freshness_status:
# ok→stale opens an alert, stale→ok posts a recovery.
# ----------------------------------------------------------------------------
def freshness_threshold(has_gsc_property: bool, gsc_days: int, df_days: int) -> int:
    """Max days a client's rank data may go without advancing before it's stale.

    A GSC-connected client should get near-daily data (threshold just above GSC's
    ~2-3 day finalization lag); a DataForSEO-only client refreshes weekly, so it
    gets a longer leash. Pure."""
    return gsc_days if has_gsc_property else df_days


def evaluate_freshness(
    last_data_at: Optional[date], has_gsc_property: bool, today: date,
    gsc_days: int, df_days: int,
) -> dict:
    """Classify one client's rank-data recency. Pure.

    `last_data_at` is the ALL-TIME freshest date the tracker has any rank data
    (GSC position or DataForSEO rank) for the client. None means it has never had
    any data — a setup/first-pull matter, not a regression — so it is never
    flagged stale here (scan_health / the empty-state UI cover that). An
    established client whose freshest data is older than its threshold IS stale.
    Returns {stale, days_stale, threshold, no_data_ever}."""
    threshold = freshness_threshold(has_gsc_property, gsc_days, df_days)
    if last_data_at is None:
        return {"stale": False, "days_stale": None, "threshold": threshold, "no_data_ever": True}
    days = (today - last_data_at).days
    return {"stale": days > threshold, "days_stale": days, "threshold": threshold, "no_data_ever": False}


def freshness_episode_key(client_id: str, last_data_at: Optional[date], now: datetime) -> str:
    """Dedupe key for a staleness episode. Anchored on the stuck date so data
    resuming (then re-stalling) starts a fresh alert; the ISO-week suffix lets an
    unresolved stall re-nudge at most weekly rather than every daily sweep. Pure."""
    anchor = last_data_at.isoformat() if last_data_at else "none"
    year, week, _ = now.isocalendar()
    return f"rank_freshness:{client_id}:{anchor}:{year}W{week:02d}"


def build_freshness_digest(
    client_name: str, days_stale: Optional[int], threshold: int,
    last_data_at: Optional[date], has_gsc_property: bool,
) -> dict:
    """{title, summary, severity} for one client whose rank data has stalled.
    Critical once the stall is ≥ 2× the expected cadence. Pure — the alert copy."""
    src = "GSC + DataForSEO" if has_gsc_property else "DataForSEO"
    severity = "critical" if (days_stale is not None and days_stale >= 2 * threshold) else "warning"
    last = last_data_at.isoformat() if last_data_at else "unknown"
    span = f"{days_stale} days" if days_stale is not None else "an extended period"
    title = f"Rank data has stopped updating for {client_name}"
    summary = (
        f"No new rank data in {span} (last update {last}; expected new data at least every "
        f"{threshold} days from {src}). The rank tracker has silently stalled for this client — "
        f"the collection jobs may be succeeding while returning nothing. Check the GSC/DataForSEO "
        f"pipeline before the numbers reach a report."
    )
    return {"title": title, "summary": summary, "severity": severity}


def build_freshness_portfolio_digest(stale: list[dict], now: datetime) -> dict:
    """One loud portfolio alert when several clients are stale at once — the shape
    of a systemic outage, which should scream on day one, not client-by-client.
    `stale` is [{client_name, days_stale}, …]. Pure."""
    n = len(stale)
    names = ", ".join(s["client_name"] for s in stale[:8])
    if n > 8:
        names += f", +{n - 8} more"
    title = f"Rank data has stalled for {n} clients"
    summary = (
        f"{n} clients' rank trackers have stopped receiving new data: {names}. "
        f"This many at once points at a systemic pipeline outage (GSC ingest window / "
        f"service account / DataForSEO), not a per-client issue — investigate now."
    )
    return {"title": title, "summary": summary, "severity": "critical"}


def _max_date_where_not_null(supabase, keyword_ids: Sequence[str], field: str) -> Optional[date]:
    """Freshest date across a client's keywords with a non-null `field`, or None.
    One top-1 read using the codebase's standard not-null filter form."""
    try:
        rows = (
            supabase.table("rank_keyword_metrics")
            .select("date")
            .in_("keyword_id", list(keyword_ids))
            .not_.is_(field, "null")
            .order("date", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("rank_freshness.latest_data_read_failed",
                       extra={"field": field, "error": str(exc)})
        return None
    if not rows:
        return None
    raw = rows[0].get("date")
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


def _latest_data_date(supabase, keyword_ids: Sequence[str]) -> Optional[date]:
    """Freshest date the tracker has ANY rank data (GSC position or DataForSEO
    rank) across a client's keywords, all-time — the max of the two sources."""
    if not keyword_ids:
        return None
    dates = [
        d for d in (
            _max_date_where_not_null(supabase, keyword_ids, "gsc_position"),
            _max_date_where_not_null(supabase, keyword_ids, "tracked_rank"),
        )
        if d is not None
    ]
    return max(dates) if dates else None


def run_rank_freshness_sweep() -> dict:
    """Daily: alert when a client's rank tracker stops receiving new data even
    though its collection jobs report success — the dead-man's switch. DB reads
    only (plus the rank_freshness_status upsert). Best-effort; never raises."""
    if not settings.rank_freshness_enabled:
        return {"skipped": "disabled"}
    supabase = get_supabase()
    now = datetime.now(timezone.utc)
    today = now.date()

    try:
        kw_rows = (
            supabase.table("tracked_keywords")
            .select("id, client_id")
            .eq("active", True)
            .execute()
        ).data or []
    except Exception as exc:
        logger.error("rank_freshness.keyword_read_failed", extra={"error": str(exc)})
        return {"error": str(exc)}
    by_client: dict[str, list[str]] = defaultdict(list)
    for r in kw_rows:
        if r.get("client_id"):
            by_client[r["client_id"]].append(r["id"])
    if not by_client:
        return {"clients": 0}

    # Which clients have a verified GSC property (→ expect near-daily data)?
    try:
        props = (
            supabase.table("gsc_properties")
            .select("client_id")
            .eq("access_status", "ok")
            .in_("client_id", list(by_client))
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("rank_freshness.property_read_failed", extra={"error": str(exc)})
        props = []
    gsc_clients = {p["client_id"] for p in props if p.get("client_id")}

    try:
        prior_rows = (
            supabase.table("rank_freshness_status")
            .select("client_id, status")
            .in_("client_id", list(by_client))
            .execute()
        ).data or []
    except Exception as exc:
        logger.warning("rank_freshness.status_read_failed", extra={"error": str(exc)})
        prior_rows = []
    prior_status = {r["client_id"]: r.get("status") for r in prior_rows}

    gsc_days = settings.rank_freshness_gsc_stale_days
    df_days = settings.rank_freshness_df_stale_days
    names = _client_names(supabase, list(by_client))

    stale_now: list[dict] = []
    opened = recovered = 0
    for client_id, keyword_ids in by_client.items():
        has_gsc = client_id in gsc_clients
        last_data_at = _latest_data_date(supabase, keyword_ids)
        verdict = evaluate_freshness(last_data_at, has_gsc, today, gsc_days, df_days)
        was_stale = prior_status.get(client_id) == "stale"

        # Persist current state (powers the portfolio read + UI freshness).
        try:
            supabase.table("rank_freshness_status").upsert(
                {
                    "client_id": client_id,
                    "status": "stale" if verdict["stale"] else "ok",
                    "last_data_at": last_data_at.isoformat() if last_data_at else None,
                    "days_stale": verdict["days_stale"],
                    "threshold_days": verdict["threshold"],
                    "stale_since": now.isoformat() if (verdict["stale"] and not was_stale) else None,
                    "updated_at": now.isoformat(),
                },
                on_conflict="client_id",
            ).execute()
        except Exception as exc:
            logger.warning("rank_freshness.status_upsert_failed",
                           extra={"client_id": client_id, "error": str(exc)})

        client_name = names.get(client_id, "Unknown client")
        if verdict["stale"]:
            stale_now.append({"client_id": client_id, "client_name": client_name,
                              "days_stale": verdict["days_stale"]})
            # Alert on the ok→stale transition, and re-nudge weekly while unresolved
            # (the episode key carries the ISO week). emit() dedupes atomically.
            try:
                digest = build_freshness_digest(
                    client_name, verdict["days_stale"], verdict["threshold"],
                    last_data_at, has_gsc,
                )
                nid = notifications.emit(
                    client_id=client_id,
                    kind="rank_data_stale",
                    title=digest["title"],
                    summary=digest["summary"],
                    severity=digest["severity"],
                    payload={"link": f"clients/{client_id}/rankings",
                             "days_stale": verdict["days_stale"],
                             "last_data_at": last_data_at.isoformat() if last_data_at else None},
                    dedupe_key=freshness_episode_key(client_id, last_data_at, now),
                )
                if nid and not was_stale:
                    opened += 1
            except Exception as exc:
                logger.warning("rank_freshness.emit_failed",
                               extra={"client_id": client_id, "error": str(exc)})
        elif was_stale and not verdict["no_data_ever"]:
            # stale→ok: post a recovery once (deduped on the recovery date).
            try:
                notifications.emit(
                    client_id=client_id,
                    kind="rank_data_recovered",
                    title=f"Rank data is flowing again for {client_name}",
                    summary=(f"New rank data has resumed (last update "
                             f"{last_data_at.isoformat() if last_data_at else 'recent'}). "
                             f"The earlier stall has cleared."),
                    severity="info",
                    payload={"link": f"clients/{client_id}/rankings"},
                    dedupe_key=f"rank_freshness_recovered:{client_id}:{today.isoformat()}",
                )
                recovered += 1
            except Exception as exc:
                logger.warning("rank_freshness.recovery_emit_failed",
                               extra={"client_id": client_id, "error": str(exc)})

    # Systemic outage → one loud portfolio alert (deduped per day).
    if len(stale_now) >= settings.rank_freshness_portfolio_min:
        try:
            digest = build_freshness_portfolio_digest(stale_now, now)
            notifications.emit(
                client_id=None,
                kind="rank_data_stale",
                title=digest["title"],
                summary=digest["summary"],
                severity=digest["severity"],
                payload={"link": "rankings", "stale_clients": len(stale_now)},
                dedupe_key=f"rank_freshness_portfolio:{today.isoformat()}",
            )
        except Exception as exc:
            logger.warning("rank_freshness.portfolio_emit_failed", extra={"error": str(exc)})

    if stale_now:
        logger.info("rank_freshness.sweep_complete",
                    extra={"clients": len(by_client), "stale": len(stale_now),
                           "opened": opened, "recovered": recovered})
    return {"clients": len(by_client), "stale": len(stale_now),
            "opened": opened, "recovered": recovered}


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
