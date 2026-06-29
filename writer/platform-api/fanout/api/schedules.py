"""M15 slice 5 — content scheduling API (handoff.md §9.4 / §9.9).

`Schedule all` (or a chosen subset) materializes a `content_schedules` parent + one
`scheduled_article_runs` per cluster; the slice-4 worker drains them at their `scheduled_at`.
Three modes: all-at-once, drip N/day, or a specific date (deliver-by). Both roles act on
sessions they can see (RLS via `_require_session`); a VA whose batch estimate exceeds
`writer_schedule_approval_threshold_usd` ($90) is blocked pending owner approval (the owner
is never gated). Pause = toggle the parent (the worker's claim only takes `active` schedules).
"""

from __future__ import annotations

import logging
from datetime import date, time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from fanout.api.sessions import _require_session
from fanout.auth import AuthedUser, require_user
from fanout.auth.dependencies import get_role
from fanout.config import get_settings
from fanout.storage import silo as store
from fanout.writer import schedule_store
from fanout.writer.schedule_planner import ScheduleError, finish_date, order_clusters, plan_runs

logger = logging.getLogger(__name__)
router = APIRouter()


class ScheduleBody(BaseModel):
    mode: str                                   # all_at_once | drip | fixed
    cluster_ids: list[str] | None = None        # None/[] -> the whole session
    per_day: int | None = None                  # drip
    start_date: date | None = None              # drip start / fixed target day
    time_of_day: time | None = None
    timezone: str = "UTC"
    site_base_url: str | None = None            # persisted to the session (links need it)
    # Which generator each run uses. 'local_seo_page' needs a client-linked
    # session + a target `location`. 'service_page' needs a client-linked
    # session (keyword-only, no location/base URL); it creates a suite
    # service_page run (service_brief -> service_writer). Both produce
    # first-class suite artifacts instead of the Fanout blog writer's output.
    content_type: str = "blog_post"             # blog_post | local_seo_page | service_page
    location: str | None = None                 # local_seo_page: target area
    location_code: int | None = None            # local_seo_page: optional DataForSEO city code
    # Opt-in: publish each finished piece to the linked client's Google Drive
    # folder as a Google Doc, right after it generates. Best-effort + requires a
    # client-linked session (no-ops otherwise).
    auto_publish: bool = False


# ----- helpers --------------------------------------------------------------


def _session_cluster_ids(session_id: str, cluster_ids: list[str] | None) -> list[str]:
    """The session's cluster ids (deduped), filtered to the requested subset. Unordered —
    enough for the estimate's count (ordering doesn't change the set)."""
    ids = list(dict.fromkeys(c["id"] for c in store.list_clusters(session_id) if c.get("id")))
    if cluster_ids:
        chosen = set(cluster_ids)
        ids = [i for i in ids if i in chosen]
    return ids


def _ordered_targets(session_id: str, cluster_ids: list[str] | None) -> list[str]:
    """Pillars-first ordered target cluster ids (reads the architecture). Used by create,
    where write order matters; the estimate skips this and just counts the set."""
    ids = _session_cluster_ids(session_id, cluster_ids)
    architecture = (store.get_architecture(session_id) or {}).get("architecture_json")
    return order_clusters(architecture, ids)


def _estimate(count: int, mode: str, per_day: int | None, start: date | None) -> dict:
    s = get_settings()
    cost = round(count * s.writer_article_cost_estimate_usd, 2)
    out = {"count": count, "cost_estimate_usd": cost, "mode": mode}
    if mode == "drip" and per_day and count:
        from fanout.writer.schedule_planner import schedule_days
        days = schedule_days(count, per_day)
        out["days"] = days
        if start:
            out["finish_date"] = finish_date(start, count, per_day).isoformat()
    elif mode == "fixed" and start:
        out["finish_date"] = start.isoformat()
    return out


# ----- endpoints ------------------------------------------------------------


@router.post("/sessions/{session_id}/schedule-estimate")
def schedule_estimate(
    session_id: str, body: ScheduleBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Preview a schedule without creating it: count (after the double-book filter), cost,
    drip finish date, and whether a VA would need owner approval."""
    _require_session(user, session_id)
    candidates = _session_cluster_ids(session_id, body.cluster_ids)
    pending = schedule_store.pending_cluster_ids(session_id)
    targets = [c for c in candidates if c not in pending]
    est = _estimate(len(targets), body.mode, body.per_day, body.start_date)
    est["already_scheduled"] = len(candidates) - len(targets)
    s = get_settings()
    est["requires_approval"] = (
        get_role(user) != "owner" and est["cost_estimate_usd"] > s.writer_schedule_approval_threshold_usd
    )
    est["approval_threshold_usd"] = s.writer_schedule_approval_threshold_usd
    return est


@router.post("/sessions/{session_id}/schedule")
def create_schedule(
    session_id: str, body: ScheduleBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Validate + plan + materialize a schedule. Persists `site_base_url` to the session if
    supplied. Skips clusters already queued in another active schedule (double-book guard).
    A VA over the $90 batch threshold is refused with `requires_approval` (owner not gated)."""
    session = _require_session(user, session_id)
    is_local_seo = body.content_type == "local_seo_page"
    is_service_page = body.content_type == "service_page"
    resolved_location: str | None = None
    resolved_location_code: int | None = None

    if is_service_page:
        # Service pages are generated against a client (brand voice / ICP) for a
        # head commercial query — keyword-only, so no target area and no internal-
        # link base URL. They create a suite service_page run.
        if not session.get("client_id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Service pages need a client. Link this session to a client to "
                       "schedule them.",
            )
        base_url = None
    elif is_local_seo:
        # Local SEO pages are generated against a client's GBP for a target area —
        # both are required, and there's no internal-link injection so no base URL.
        if not session.get("client_id"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Local SEO pages need a client. Link this session to a client (with a "
                       "Google Business Profile) to schedule them.",
            )
        if not (body.location or "").strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A target area / location is required for Local SEO pages.",
            )
        # Validate + canonicalize the area now (not per-run), so a typo / unrecognized
        # city fails fast here — with suggestions — instead of silently failing each
        # scheduled run minutes later. Reuses the suite's resolver (the same one the
        # single-page Local SEO form uses), keyed to the client's country.
        import asyncio

        from services import locations_service
        from services.local_seo_service import _get_client

        client = _get_client(session["client_id"])
        resolved_location, resolved_location_code = asyncio.run(
            locations_service.resolve_location(client, body.location.strip(), body.location_code)
        )
        base_url = None
    else:
        # Base URL must be available (links are absolute), but don't persist it until the whole
        # request is validated/approved/planned — so a request that 400s leaves no side effect.
        base_url = (body.site_base_url or "").strip() or session.get("site_base_url")
        if not base_url:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A site base URL is required so internal links are absolute. Set it in the modal.",
            )

    ordered = _ordered_targets(session_id, body.cluster_ids)
    pending = schedule_store.pending_cluster_ids(session_id)
    targets = [c for c in ordered if c not in pending]
    skipped = len(ordered) - len(targets)
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nothing to schedule (no clusters, or all are already scheduled).",
        )

    est = _estimate(len(targets), body.mode, body.per_day, body.start_date)
    s = get_settings()
    if get_role(user) != "owner" and est["cost_estimate_usd"] > s.writer_schedule_approval_threshold_usd:
        return {
            "status": "requires_approval", "created": False,
            "estimate": est, "skipped": skipped,
            "approval_threshold_usd": s.writer_schedule_approval_threshold_usd,
        }

    try:
        runs = plan_runs(
            targets, mode=body.mode, per_day=body.per_day, start_date=body.start_date,
            time_of_day=body.time_of_day, tz_name=body.timezone,
        )
    except ScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "min_per_day": exc.min_per_day},
        ) from exc

    # Validated + approved + planned — now it's safe to persist the base URL.
    if body.site_base_url and body.site_base_url.strip() != session.get("site_base_url"):
        store.update_session(session_id, {"site_base_url": body.site_base_url.strip()})

    schedule = schedule_store.create_schedule(
        session_id=session_id, user_id=session["user_id"], mode=body.mode, runs=runs,
        per_day=body.per_day, start_date=body.start_date, time_of_day=body.time_of_day,
        tz_name=body.timezone, content_type=body.content_type,
        location=resolved_location, location_code=resolved_location_code,
        # Auto-publish only makes sense when the session is client-linked (the
        # publish target is the client's Drive folder).
        auto_publish=bool(body.auto_publish and session.get("client_id")),
    )
    logger.info("schedule_created", extra={"event": "schedule_created", "session_id": session_id,
                                           "mode": body.mode, "runs": len(runs), "skipped": skipped})
    return {"status": "scheduled", "created": True, "schedule": schedule,
            "scheduled": len(runs), "skipped": skipped, "estimate": est}


@router.get("/sessions/{session_id}/schedules")
def list_schedules(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """The session's schedule batches with live progress counts (for the overview UI)."""
    _require_session(user, session_id)
    schedules = schedule_store.list_schedules(session_id)
    progress = schedule_store.progress_by_schedule(session_id)        # one paged scan, no N+1
    empty = {s: 0 for s in ("queued", "running", "complete", "failed", "cancelled")} | {"total": 0}
    for sch in schedules:
        sch["progress"] = progress.get(sch["id"], dict(empty))
    return {"schedules": schedules}


@router.get("/sessions/{session_id}/schedule-runs")
def list_schedule_runs(session_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    """All scheduled runs for a session (cluster, scheduled_at, status, error)."""
    _require_session(user, session_id)
    return {"runs": schedule_store.list_runs(session_id)}


@router.post("/sessions/{session_id}/schedule-runs/{run_id}/cancel")
def cancel_schedule_run(
    session_id: str, run_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Cancel a single still-queued article run, leaving the rest of its schedule running. A run
    that's already writing (running) or finished (complete/failed/cancelled) can't be stopped."""
    _require_session(user, session_id)
    run = schedule_store.get_run(run_id)
    if not run or run["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run["status"] != "queued":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This article is already {run['status']} — too late to cancel.",
        )
    if not schedule_store.cancel_run(run_id):
        # Lost the race with the worker between the read and the conditional update.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This article just started writing — too late to cancel.",
        )
    if run.get("content_schedule_id"):
        schedule_store.complete_if_drained(run["content_schedule_id"])
    return {"status": "cancelled", "run_id": run_id}


def _require_schedule(user: AuthedUser, session_id: str, schedule_id: str) -> dict:
    _require_session(user, session_id)
    sched = schedule_store.get_schedule(schedule_id)
    if not sched or sched["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    return sched


@router.post("/sessions/{session_id}/schedules/{schedule_id}/pause")
def pause_schedule(session_id: str, schedule_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    _require_schedule(user, session_id, schedule_id)
    schedule_store.set_schedule_status(schedule_id, "paused")
    return {"status": "paused"}


@router.post("/sessions/{session_id}/schedules/{schedule_id}/resume")
def resume_schedule(session_id: str, schedule_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    _require_schedule(user, session_id, schedule_id)
    schedule_store.set_schedule_status(schedule_id, "active")
    return {"status": "active"}


@router.post("/sessions/{session_id}/schedules/{schedule_id}/cancel")
def cancel_schedule(session_id: str, schedule_id: str, user: AuthedUser = Depends(require_user)) -> dict:
    _require_schedule(user, session_id, schedule_id)
    cancelled = schedule_store.cancel_schedule(schedule_id)
    return {"status": "cancelled", "cancelled_runs": cancelled}
