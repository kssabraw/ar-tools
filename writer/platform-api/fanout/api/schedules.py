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
from fanout.writer.schedule_planner import ScheduleError, order_clusters, plan_runs

logger = logging.getLogger(__name__)
router = APIRouter()


class ScheduleBody(BaseModel):
    # all_at_once | drip | fixed | weekly | monthly_date | monthly_weekday
    mode: str
    cluster_ids: list[str] | None = None        # None/[] -> the whole session
    # Count per period for the periodic cadences (per day for drip, per week for
    # weekly, per month for the monthly modes).
    per_day: int | None = None
    start_date: date | None = None              # periodic start / fixed target day
    time_of_day: time | None = None
    timezone: str = "UTC"
    # Cadence anchors: weekday (0=Mon .. 6=Sun) for weekly + monthly_weekday;
    # weekdays (a set) for weekly with MULTIPLE days (each is its own slot every
    # week, e.g. [1,3] => one Tue + one Thu weekly); day_of_month (1-31) for
    # monthly_date; week_of_month (1-4, or -1 = last) for monthly_weekday
    # (e.g. weekday=0, week_of_month=1 => first Monday each month).
    weekday: int | None = None
    weekdays: list[int] | None = None
    day_of_month: int | None = None
    week_of_month: int | None = None
    site_base_url: str | None = None            # persisted to the session (links need it)
    # Up to 3 extra URLs (money pages — product/service/landing pages) every generated
    # article should link to, folded into the internal-link injection under the
    # ≤5-outbound cap. Persisted to the session alongside site_base_url. None = leave
    # the session's stored value untouched; [] = clear.
    extra_link_urls: list[str] | None = None
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
    # Opt-in (blog posts only): publish each finished article straight to the
    # linked client's WordPress site, pinning the cluster's slug so the live URL
    # matches the injected internal links. `wp_status` picks 'draft' (a human
    # reviews + publishes in wp-admin) or 'publish' (live immediately).
    wp_publish: bool = False
    wp_status: str = "draft"                    # draft | publish


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


_PERIOD_LABEL = {"drip": "day", "weekly": "week",
                 "monthly_date": "month", "monthly_weekday": "month"}


def _estimate(
    count: int, mode: str, per_day: int | None, start: date | None, *,
    weekday: int | None = None, weekdays: list[int] | None = None,
    day_of_month: int | None = None, week_of_month: int | None = None,
) -> dict:
    s = get_settings()
    cost = round(count * s.writer_article_cost_estimate_usd, 2)
    out = {"count": count, "cost_estimate_usd": cost, "mode": mode}
    if mode == "fixed" and start:
        out["finish_date"] = start.isoformat()
    elif mode in _PERIOD_LABEL and per_day and count:
        import math

        n_periods = math.ceil(count / per_day)
        out["periods"] = n_periods
        out["period_label"] = _PERIOD_LABEL[mode]
        if mode == "drip":
            out["days"] = n_periods                     # back-compat with the old key
        # Best-effort finish date preview (the planner is the source of truth).
        try:
            from fanout.writer.schedule_planner import _period_dates
            dates = _period_dates(
                mode, n_periods, start=start or date.today(), weekday=weekday,
                weekdays=weekdays, day_of_month=day_of_month, week_of_month=week_of_month,
            )
            if dates:
                out["finish_date"] = dates[-1].isoformat()
        except Exception:  # noqa: BLE001 — preview only; create validates for real
            pass
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
    est = _estimate(
        len(targets), body.mode, body.per_day, body.start_date,
        weekday=body.weekday, weekdays=body.weekdays, day_of_month=body.day_of_month,
        week_of_month=body.week_of_month,
    )
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

    # Direct-to-WordPress is offered for every content type (blog posts publish as
    # posts; local SEO / service pages publish as pages, reusing each type's own
    # publish path). It just needs the linked client to have WordPress configured.
    wp_publish = bool(body.wp_publish)
    if wp_publish:
        # Fail fast at schedule time — not silently per-run minutes/days later.
        if body.wp_status not in ("draft", "publish"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="wp_status must be 'draft' or 'publish'.",
            )
        from fanout.api.sessions import _wordpress_publish_available

        if not _wordpress_publish_available(session):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="WordPress publishing needs this session linked to a client with a "
                       "WordPress site URL + application password on its card.",
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

    est = _estimate(
        len(targets), body.mode, body.per_day, body.start_date,
        weekday=body.weekday, weekdays=body.weekdays, day_of_month=body.day_of_month,
        week_of_month=body.week_of_month,
    )
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
            weekday=body.weekday, weekdays=body.weekdays, day_of_month=body.day_of_month,
            week_of_month=body.week_of_month,
        )
    except ScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "min_per_day": exc.min_per_day},
        ) from exc

    # Validated + approved + planned — now it's safe to persist the base URL.
    if body.site_base_url and body.site_base_url.strip() != session.get("site_base_url"):
        store.update_session(session_id, {"site_base_url": body.site_base_url.strip()})
    if body.extra_link_urls is not None:
        extras = [u.strip() for u in body.extra_link_urls if u and u.strip()][:3]
        if extras != (session.get("extra_link_urls") or []):
            store.update_session(session_id, {"extra_link_urls": extras})

    schedule = schedule_store.create_schedule(
        session_id=session_id, user_id=session["user_id"], mode=body.mode, runs=runs,
        per_day=body.per_day, start_date=body.start_date, time_of_day=body.time_of_day,
        tz_name=body.timezone, content_type=body.content_type,
        location=resolved_location, location_code=resolved_location_code,
        # Auto-publish only makes sense when the session is client-linked (the
        # publish target is the client's Drive folder).
        auto_publish=bool(body.auto_publish and session.get("client_id")),
        wp_publish=wp_publish, wp_status=body.wp_status if wp_publish else "draft",
        weekday=body.weekday, weekdays=body.weekdays,
        day_of_month=body.day_of_month, week_of_month=body.week_of_month,
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
    reflowed = 0
    if run.get("content_schedule_id"):
        # Pull the remaining queued articles up into the freed slot (no empty day).
        reflowed = schedule_store.reflow_queued(run["content_schedule_id"])
        schedule_store.complete_if_drained(run["content_schedule_id"])
    return {"status": "cancelled", "run_id": run_id, "reflowed": reflowed}


class BulkCancelBody(BaseModel):
    run_ids: list[str]


@router.post("/sessions/{session_id}/schedule-runs/cancel-bulk")
def cancel_schedule_runs_bulk(
    session_id: str, body: BulkCancelBody, user: AuthedUser = Depends(require_user)
) -> dict:
    """Cancel many still-queued article runs at once, then re-flow each affected
    schedule ONCE (not per run) so the remaining articles compact without an empty
    day. Non-queued / cross-session ids are skipped. Returns how many cancelled."""
    _require_session(user, session_id)
    cancelled = 0
    affected: set[str] = set()
    for run_id in (body.run_ids or [])[:2000]:
        run = schedule_store.get_run(run_id)
        if not run or run["session_id"] != session_id or run["status"] != "queued":
            continue
        if schedule_store.cancel_run(run_id):
            cancelled += 1
            if run.get("content_schedule_id"):
                affected.add(run["content_schedule_id"])
    for sched_id in affected:
        schedule_store.reflow_queued(sched_id)
        schedule_store.complete_if_drained(sched_id)
    return {"status": "cancelled", "cancelled": cancelled}


@router.post("/sessions/{session_id}/schedule-runs/{run_id}/reinstate")
def reinstate_schedule_run(
    session_id: str, run_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Un-cancel a previously cancelled article (changed your mind). Flips it back to
    queued, reactivates the parent schedule if it had drained/cancelled, and re-flows
    the queue so the reinstated article takes a slot (the tail extends by one)."""
    _require_session(user, session_id)
    run = schedule_store.get_run(run_id)
    if not run or run["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run["status"] != "cancelled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This article is {run['status']} — only a cancelled one can be reinstated.",
        )
    if not schedule_store.reinstate_run(run_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Couldn't reinstate this article — its state changed.",
        )
    sched_id = run.get("content_schedule_id")
    if sched_id:
        sched = schedule_store.get_schedule(sched_id)
        # A schedule that had fully drained (or was cancelled) must go active again
        # so the worker will pick the reinstated article up.
        if sched and sched["status"] in ("complete", "cancelled"):
            schedule_store.set_schedule_status(sched_id, "active")
        schedule_store.reflow_queued(sched_id)
    return {"status": "queued", "run_id": run_id}


def _reactivate_if_drained(schedule_id: str | None) -> None:
    """A schedule that had drained to `complete` (its last runs failed) must go
    active again so the worker picks up a retried run. Paused/cancelled/active are
    left as-is (a retry shouldn't silently un-pause or resurrect a cancellation)."""
    if not schedule_id:
        return
    sched = schedule_store.get_schedule(schedule_id)
    if sched and sched["status"] == "complete":
        schedule_store.set_schedule_status(schedule_id, "active")


@router.post("/sessions/{session_id}/schedule-runs/{run_id}/retry")
def retry_schedule_run(
    session_id: str, run_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Manually requeue a single dead-lettered article (failed -> queued, due now,
    attempt budget reset). Only a `failed` run can be retried; the worker picks it
    up on its next tick (the parent schedule is reactivated if it had drained)."""
    _require_session(user, session_id)
    run = schedule_store.get_run(run_id)
    if not run or run["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    if run["status"] != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This article is {run['status']} — only a failed one can be retried.",
        )
    if not schedule_store.retry_failed_run(run_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Couldn't retry this article — its state changed.",
        )
    _reactivate_if_drained(run.get("content_schedule_id"))
    return {"status": "queued", "run_id": run_id}


@router.post("/sessions/{session_id}/schedules/{schedule_id}/retry-failed")
def retry_failed_schedule_runs(
    session_id: str, schedule_id: str, user: AuthedUser = Depends(require_user)
) -> dict:
    """Requeue every dead-lettered article in a schedule at once (failed -> queued,
    due now, attempts reset). Reactivates the schedule if it had drained. Returns
    how many were retried."""
    _require_schedule(user, session_id, schedule_id)
    retried = schedule_store.retry_failed_runs(schedule_id)
    if retried:
        _reactivate_if_drained(schedule_id)
    return {"status": "queued", "retried": retried}


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


class PublishTargetsBody(BaseModel):
    # Any subset; omitted fields are left as-is. wp_status is 'draft' | 'publish'.
    auto_publish: bool | None = None
    wp_publish: bool | None = None
    wp_status: str | None = None


@router.patch("/sessions/{session_id}/schedules/{schedule_id}/publish-targets")
def update_publish_targets(
    session_id: str, schedule_id: str, body: PublishTargetsBody,
    user: AuthedUser = Depends(require_user),
) -> dict:
    """Change where a schedule's remaining articles publish (Google Drive and/or
    WordPress) mid-run. Allowed only while the schedule is **paused** — pause,
    retarget, resume. The worker reads these flags live per article, so the change
    is forward-only: it applies to every run not yet generated, never to already-
    published pieces."""
    session = _require_session(user, session_id)
    sched = schedule_store.get_schedule(schedule_id)
    if not sched or sched["session_id"] != session_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
    if sched["status"] != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pause the schedule before changing where it publishes.",
        )

    updates: dict = {}
    if body.auto_publish is not None:
        # Drive publishing targets the client's folder — only meaningful when linked.
        updates["auto_publish"] = bool(body.auto_publish and session.get("client_id"))
    if body.wp_publish is not None:
        wp = bool(body.wp_publish)
        if wp:
            from fanout.api.sessions import _wordpress_publish_available

            if not _wordpress_publish_available(session):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="WordPress publishing needs this session linked to a client with a "
                           "WordPress site URL + application password on its card.",
                )
        updates["wp_publish"] = wp
    if body.wp_status is not None:
        if body.wp_status not in ("draft", "publish"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="wp_status must be 'draft' or 'publish'.",
            )
        updates["wp_status"] = body.wp_status

    row = schedule_store.update_schedule_fields(schedule_id, updates) or sched
    return {"status": "updated", "schedule": row}


class CadenceBody(BaseModel):
    # all_at_once | drip | fixed | weekly | monthly_date | monthly_weekday
    mode: str
    per_day: int | None = None
    start_date: date | None = None
    time_of_day: time | None = None
    timezone: str = "UTC"
    weekday: int | None = None
    weekdays: list[int] | None = None           # weekly: multiple days, each a slot/week
    day_of_month: int | None = None
    week_of_month: int | None = None


@router.patch("/sessions/{session_id}/schedules/{schedule_id}/cadence")
def update_cadence(
    session_id: str, schedule_id: str, body: CadenceBody,
    user: AuthedUser = Depends(require_user),
) -> dict:
    """Re-time a schedule's remaining (still-queued) articles to a new cadence — e.g.
    1/week -> 1/day. Allowed only while **paused** (pause, re-time, resume). Forward-
    only: completed/running articles keep their timestamps; the count and cost are
    unchanged (same articles, new spacing). Re-plans the queued runs pillars-first (their
    existing order) under the new cadence and updates the parent schedule's cadence
    columns."""
    sched = _require_schedule(user, session_id, schedule_id)
    if sched["status"] != "paused":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Pause the schedule before changing its cadence.",
        )
    queued = schedule_store.queued_runs_ordered(schedule_id)
    if not queued:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No queued articles left to reschedule.",
        )
    try:
        planned = plan_runs(
            [r["cluster_id"] for r in queued], mode=body.mode, per_day=body.per_day,
            start_date=body.start_date, time_of_day=body.time_of_day, tz_name=body.timezone,
            weekday=body.weekday, weekdays=body.weekdays, day_of_month=body.day_of_month,
            week_of_month=body.week_of_month,
        )
    except ScheduleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": str(exc), "min_per_day": exc.min_per_day},
        ) from exc

    rescheduled = schedule_store.apply_reschedule(queued, planned)
    row = schedule_store.update_schedule_fields(schedule_id, {
        "mode": body.mode,
        "per_day": body.per_day,
        "start_date": body.start_date.isoformat() if body.start_date else None,
        "time_of_day": (body.time_of_day or time(9, 0)).isoformat(),
        "timezone": body.timezone,
        # Persist the anchors so a later cancel/reinstate re-flow uses this cadence.
        "weekday": body.weekday, "weekdays": body.weekdays,
        "day_of_month": body.day_of_month, "week_of_month": body.week_of_month,
    }) or sched
    logger.info("schedule_cadence_changed",
                extra={"event": "schedule_cadence_changed", "schedule_id": schedule_id,
                       "mode": body.mode, "rescheduled": rescheduled})
    return {"status": "updated", "rescheduled": rescheduled, "schedule": row}
