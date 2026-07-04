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
from routers.asana import router as asana_router
from routers.brand import router as brand_router
from routers.brand_voice import router as brand_voice_router
from routers.briefs import router as briefs_router
from routers.citations import router as citations_router
from routers.clients import router as clients_router
from routers.dashboard import router as dashboard_router
from routers.files import router as files_router
from routers.freeze import router as freeze_router
from routers.gsc import router as gsc_router
from routers.gsc_research import router as gsc_research_router
from routers.guides import router as guides_router
from routers.icp import router as icp_router
from routers.local_seo import router as local_seo_router
from routers.maps import router as maps_router
from routers.notifications import router as notifications_router
from routers.publish import router as publish_router
from routers.rank import router as rank_router
from routers.recipe import router as recipe_router
from routers.reopt import router as reopt_router
from routers.reports import router as reports_router
from routers.slack_events import router as slack_events_router
from routers.runs import router as runs_router
from routers.silos import router as silos_router
from routers.sops import router as sops_router
from routers.syndication import router as syndication_router
from routers.users import router as users_router
from services.gsc_scheduler import gsc_scheduler
from services.job_worker import job_worker
from services.orchestrator import recover_stuck_runs

# Topic Fanout Tool — vendored sub-package (writer/platform-api/fanout/).
# Self-contained: its own config, fanout-schema-scoped Supabase client, and
# Supabase-JWT auth deps. Mounted here under a /fanout prefix so the suite
# runs one backend / one login. See fanout/ for the original (kssabraw/
# info-site-kw-research-cluster).
from fanout.api import exports as fanout_exports
from fanout.api import health as fanout_health
from fanout.api import projects as fanout_projects
from fanout.api import schedules as fanout_schedules
from fanout.api import sessions as fanout_sessions
from fanout.writer import scheduler as fanout_scheduler

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

_REQUEST_ID_CHARS = string.ascii_uppercase + string.digits


def _new_request_id() -> str:
    return "req_" + "".join(secrets.choice(_REQUEST_ID_CHARS) for _ in range(12))


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
    # Start background job worker + GSC ingest scheduler
    worker_task = asyncio.create_task(job_worker())
    scheduler_task = asyncio.create_task(gsc_scheduler())
    # Start the Topic Fanout in-process content scheduler (its own asyncio loop;
    # claims due scheduled article runs). Driven explicitly here rather than via
    # the vendored sub-app's lifespan, which is not invoked when its routers are
    # mounted into this app.
    await fanout_scheduler.start()
    yield
    await fanout_scheduler.stop()
    for task in (worker_task, scheduler_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
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


app.include_router(asana_router)
app.include_router(brand_router)
app.include_router(brand_voice_router)
app.include_router(briefs_router)
app.include_router(citations_router)
app.include_router(clients_router)
app.include_router(dashboard_router)
app.include_router(files_router)
app.include_router(freeze_router)
app.include_router(gsc_router)
app.include_router(gsc_research_router)
app.include_router(guides_router)
app.include_router(icp_router)
app.include_router(local_seo_router)
app.include_router(maps_router)
app.include_router(notifications_router)
app.include_router(rank_router)
app.include_router(recipe_router)
app.include_router(reopt_router)
app.include_router(reports_router)
app.include_router(slack_events_router)
app.include_router(runs_router)
app.include_router(silos_router)
app.include_router(sops_router)
app.include_router(syndication_router)
app.include_router(users_router)
app.include_router(publish_router)

# Topic Fanout Tool routers, namespaced under /fanout (e.g. /fanout/sessions,
# /fanout/projects, /fanout/healthz). The vendored routers use absolute paths,
# so the prefix is the only thing separating them from the suite's own routes.
_FANOUT_PREFIX = "/fanout"
app.include_router(fanout_health.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_projects.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_sessions.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_exports.router, prefix=_FANOUT_PREFIX)
app.include_router(fanout_schedules.router, prefix=_FANOUT_PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}
