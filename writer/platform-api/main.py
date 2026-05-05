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
from routers.briefs import router as briefs_router
from routers.clients import router as clients_router
from routers.files import router as files_router
from routers.publish import router as publish_router
from routers.runs import router as runs_router
from routers.silos import router as silos_router
from routers.users import router as users_router
from services.job_worker import job_worker
from services.orchestrator import recover_stuck_runs

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
    # Start background job worker
    worker_task = asyncio.create_task(job_worker())
    yield
    worker_task.cancel()
    try:
        await worker_task
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


app.include_router(briefs_router)
app.include_router(clients_router)
app.include_router(files_router)
app.include_router(runs_router)
app.include_router(silos_router)
app.include_router(users_router)
app.include_router(publish_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
