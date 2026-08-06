"""Platform API — main FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from routers.activity import router as activity_router
from routers.asana import router as asana_router
from routers.assistant import router as assistant_router
from routers.backlinks import router as backlinks_router
from routers.brand import router as brand_router
from routers.brand_voice import router as brand_voice_router
from routers.briefs import router as briefs_router
from routers.citations import router as citations_router
from routers.clients import router as clients_router
from routers.competitors import router as competitors_router
from routers.domain_intel import router as domain_intel_router
from routers.keyword_research import router as keyword_research_router
from routers.content_schedule import router as content_schedule_router
from routers.dashboard import router as dashboard_router
from routers.deliverables import router as deliverables_router
from routers.files import router as files_router
from routers.forecast import router as forecast_router
from routers.freeze import router as freeze_router
from routers.goals import router as goals_router
from routers.gbp_metrics import router as gbp_metrics_router
from routers.gbp_posts import router as gbp_posts_router
from routers.gbp_oauth import router as gbp_oauth_router
from routers.gsc import router as gsc_router
from routers.gsc_research import router as gsc_research_router
from routers.guides import router as guides_router
from routers.icp import router as icp_router
from routers.internal_linking import router as internal_linking_router
from routers.leadoff import router as leadoff_router
from routers.ecommerce import router as ecommerce_router
from routers.local_seo import router as local_seo_router
from routers.maps import router as maps_router
from routers.notifications import router as notifications_router
from routers.outreach import router as outreach_router
from routers.pace import router as pace_router
from routers.publish import router as publish_router
from routers.pulse import router as pulse_router
from routers.qa import router as qa_router
from routers.rank import router as rank_router
from routers.recipe import router as recipe_router
from routers.reopt import router as reopt_router
from routers.reports import router as reports_router
from routers.slack_events import router as slack_events_router
from routers.strategist import router as strategist_router
from routers.runs import router as runs_router
from routers.silos import router as silos_router
from routers.sops import router as sops_router
from routers.syndication import router as syndication_router
from routers.tasks import router as tasks_router
from routers.users import router as users_router
from routers.websites import router as websites_router
from services.gsc_scheduler import gsc_scheduler
from services.job_worker import drain_inflight_jobs, job_worker
from services.orchestrator import recover_stuck_runs

# Topic Fanout Tool — vendored sub-package (writer/platform-api/fanout/).
# Self-contained: its own config, fanout-schema-scoped Supabase client, and
# Supabase-JWT auth deps. Mounted here under a /fanout prefix so the suite
# runs one backend / one login. See fanout/ for the original (kssabraw/
# info-site-kw-research-cluster).
from fanout.api import exports as fanout_exports
from fanout.api import health as fanout_health
from fanout.api import projects as fanout_projects
from fanout.api import reports as fanout_reports
from fanout.api import schedules as fanout_schedules
from fanout.api import sessions as fanout_sessions
from fanout.writer import scheduler as fanout_scheduler
from fanout import run_recovery as fanout_run_recovery

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_REQUEST_ID_CHARS = string.ascii_uppercase + string.digits


def _new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_REQUEST_ID_CHARS) for _ in range(12))


async def _fanout_orphan_sweep_later() -> None:
    """Run the fanout fallback sweep once, after the deploy handover window has
    closed. Cancelled at shutdown, so a short-lived container simply never sweeps
    — the shutdown hook covers it instead."""
    from fanout.config import get_settings as _fanout_settings

    try:
        await asyncio.sleep(_fanout_settings().orphan_sweep_delay_s)
        await asyncio.get_running_loop().run_in_executor(
            None, fanout_run_recovery.recover_orphaned_runs
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # pragma: no cover - best-effort
        logger.warning("fanout_orphan_sweep_failed", extra={"error": str(exc)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("platform-api starting up")
    await recover_stuck_runs()
    # Seed the in-app Guides portal with default content (idempotent on slug;
    # never overwrites edits). Best-effort — must not block startup.
    try:
        from services import guide_store

        guide_store.seed_defaults()
    except Exception as exc:  # pragma: no cover - startup best-effort
        logger.warning("guides_seed_startup_failed", extra={"error": str(exc)})
    # Start background job workers + GSC ingest scheduler. Two worker lanes:
    # main claims everything; the interactive lane only claims short,
    # user-awaited job types so they don't queue behind long background work.
    # Verify the SSH publish transport if one is configured. Best-effort and
    # non-blocking in effect (a few seconds at most): the point is that a bad
    # key or wrong path is loud on deploy rather than discovered when a
    # scheduled article fails to publish hours later.
    try:
        from services import wordpress_publish as _wp

        _ssh_check = await _wp.ssh_selftest()
        if _ssh_check is None:
            pass
        elif _ssh_check["ok"]:
            # Inline, not extra=: basicConfig above formats only %(message)s, so
            # anything passed via extra never reaches the logs.
            logger.info("wordpress_ssh_selftest_ok detail=%s", _ssh_check["detail"])
        else:
            logger.error("wordpress_ssh_selftest_failed detail=%s", _ssh_check["detail"])
    except Exception as exc:  # pragma: no cover - startup best-effort
        logger.warning("wordpress_ssh_selftest_error error=%s", str(exc))
    worker_task = asyncio.create_task(job_worker())
    interactive_worker_task = (
        asyncio.create_task(
            job_worker(job_types=list(settings.interactive_job_types), lane="interactive")
        )
        if settings.interactive_job_types
        else None
    )
    scheduler_task = asyncio.create_task(gsc_scheduler())
    # Start the Topic Fanout in-process content scheduler (its own asyncio loop;
    # claims due scheduled article runs). Driven explicitly here rather than via
    # the vendored sub-app's lifespan, which is not invoked when its routers are
    # mounted into this app.
    await fanout_scheduler.start()
    # Fallback recovery for Topic Fanout pipeline runs whose process died too hard
    # to run its shutdown hook (OOM / SIGKILL). Deliberately DELAYED, not run at
    # startup: a deploy leaves the outgoing container working for ~15s after this
    # one boots, and a sweep that early would reap its still-live run. The normal
    # case is handled from the dying side below. See fanout/run_recovery.py.
    fanout_orphan_task = asyncio.create_task(_fanout_orphan_sweep_later())
    yield
    fanout_orphan_task.cancel()
    try:
        await fanout_scheduler.stop()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        logger.warning("fanout_scheduler_stop_failed", extra={"error": str(exc)})
    # Stop ALL lanes before draining: cancel first (so no lane can claim a fresh
    # job mid-shutdown and orphan it), await them (a cancelled mid-run job keeps
    # its id registered — see the worker loop), THEN requeue what was in flight
    # so the next container claims it immediately instead of waiting out the
    # stale-job reaper. Best-effort — a hard SIGKILL that skips this whole path
    # still self-heals via the reaper.
    tasks = [t for t in (worker_task, interactive_worker_task, scheduler_task) if t]
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass
    try:
        await drain_inflight_jobs()
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        logger.warning("job_worker_drain_failed", extra={"error": str(exc)})
    # Last, so anything that could still finish has: mark the Topic Fanout
    # pipeline runs THIS process owns as interrupted. Those jobs run in a
    # per-process executor with the session status as their claim, so without
    # this they strand at `running` with no worker and no way to restart. Only
    # this process's own runs are touched, and only if still live — so a deploy's
    # incoming container can't disturb them, and a job that finished in the grace
    # window keeps its own terminal status.
    try:
        await asyncio.get_running_loop().run_in_executor(
            None, fanout_run_recovery.recover_owned_runs
        )
    except Exception as exc:  # pragma: no cover - shutdown best-effort
        logger.warning("fanout_owned_recovery_failed", extra={"error": str(exc)})
    logger.info("platform-api shut down")


app = FastAPI(title="Platform API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = _new_request_id()
    request.state.request_id = request_id
    logger.info(
        "request_received",
        extra={"request_id": request_id, "method": request.method, "path": request.url.path},
    )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_complete",
        extra={
            "request_id": request_id,
            "status_code": response.status_code,
            "path": request.url.path,
        },
    )
    return response


# CORSMiddleware must be added last so it is outermost in the middleware stack.
# Starlette inserts each add_middleware() call at position 0; reversed() during
# stack build means the last insertion becomes the outermost layer. CORS must be
# outermost so it can short-circuit OPTIONS preflights before BaseHTTPMiddleware
# wraps them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Last-resort handler for unhandled exceptions. Starlette serves this response
# from ServerErrorMiddleware — OUTSIDE CORSMiddleware — so without the manual
# CORS header below the browser drops the 500 and reports "Failed to fetch",
# hiding the real error from the frontend.
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "unhandled_exception",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "path": request.url.path,
        },
    )
    response = JSONResponse(status_code=500, content={"detail": "internal_error"})
    origin = request.headers.get("origin")
    if origin and ("*" in settings.allowed_origins or origin in settings.allowed_origins):
        response.headers["Access-Control-Allow-Origin"] = origin
    return response


app.include_router(activity_router)
app.include_router(asana_router)
app.include_router(assistant_router)
app.include_router(backlinks_router)
app.include_router(brand_router)
app.include_router(brand_voice_router)
app.include_router(briefs_router)
app.include_router(citations_router)
app.include_router(clients_router)
app.include_router(competitors_router)
app.include_router(content_schedule_router)
app.include_router(dashboard_router)
app.include_router(deliverables_router)
app.include_router(domain_intel_router)
app.include_router(ecommerce_router)
app.include_router(keyword_research_router)
app.include_router(files_router)
app.include_router(forecast_router)
app.include_router(freeze_router)
app.include_router(goals_router)
app.include_router(gbp_metrics_router)
app.include_router(gbp_posts_router)
app.include_router(gbp_oauth_router)
app.include_router(gsc_router)
app.include_router(gsc_research_router)
app.include_router(guides_router)
app.include_router(icp_router)
app.include_router(internal_linking_router)
app.include_router(leadoff_router)
app.include_router(local_seo_router)
app.include_router(maps_router)
app.include_router(notifications_router)
app.include_router(outreach_router)
app.include_router(pace_router)
app.include_router(qa_router)
app.include_router(rank_router)
app.include_router(recipe_router)
app.include_router(reopt_router)
app.include_router(reports_router)
app.include_router(slack_events_router)
app.include_router(strategist_router)
app.include_router(runs_router)
app.include_router(silos_router)
app.include_router(sops_router)
app.include_router(syndication_router)
app.include_router(tasks_router)
app.include_router(users_router)
app.include_router(publish_router)
app.include_router(pulse_router)

# Topic Fanout Tool routers, namespaced under /fanout (e.g. /fanout/sessions,
# /fanout/projects, /fanout/healthz). The vendored routers use absolute paths,
# so the prefix is the only thing separating them from the suite's own routes.
_FANOUT_PREFIX = "/fanout"
app.include_router(fanout_health.router, prefix=_FANOUT_PREFIX)
app.include_router(websites_router)

app.include_router(fanout_projects.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_sessions.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_exports.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_reports.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_schedules.router, prefix=_FANOUT_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}
