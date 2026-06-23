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
    # Which generator each run uses. 'local_seo_page' requires the session to be
    # linked to a client (GBP) and a target `location`; it produces suite Local
    # SEO pages via the nlp-api generator instead of the Fanout blog writer.
    content_type: str = "blog_post"             # blog_post | local_seo_page
    location: str | None = None                 # local_seo_page: target area
    location_code: int | None = None            # local_seo_page: optional DataForSEO city code


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

    if is_local_seo:
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
        location=(body.location or "").strip() or None, location_code=body.location_code,
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
