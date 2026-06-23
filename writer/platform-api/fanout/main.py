"""FastAPI entry point for the Topic Fanout backend (M1 foundation)."""

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from fanout.api import exports, health, projects, schedules, sessions
from fanout.config import get_settings
from fanout.logging import (
    bind_correlation_id,
    bind_session_id,
    configure_logging,
    new_correlation_id,
)

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("service_startup", extra={"event": "service_startup"})
    from fanout.writer import scheduler
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(title="Topic Fanout Tool", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_and_access_log(request: Request, call_next):
    """Bind a correlation id per request (honoring an inbound header) and emit a
    structured access log (PRD §16.3)."""
    correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
    bind_correlation_id(correlation_id)
    bind_session_id(None)

    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    logger.info(
        "http_request",
        extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    response.headers["x-correlation-id"] = correlation_id
    return response


app.include_router(health.router)
app.include_router(projects.router)
app.include_router(sessions.router)
app.include_router(exports.router)
app.include_router(schedules.router)
