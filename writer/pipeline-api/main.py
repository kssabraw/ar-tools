import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from config import settings
from modules.brief import cost as blog_cost
from modules.brief import router as brief_router
from modules.research import router as research_router
from modules.service_brief import router as service_brief_router
from modules.service_writer import router as service_writer_router
from modules.sie import router as sie_router
from modules.sources_cited import router as sources_cited_router
from modules.writer import router as writer_router

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("pipeline-api starting up")
    yield
    logger.info("pipeline-api shutting down")


app = FastAPI(title="Pipeline API", lifespan=lifespan)

# Blog-pipeline module endpoints (no router prefixes). The orchestrator reads a
# response's top-level `cost_usd` into `module_outputs.cost_usd`.
_BLOG_PATHS = frozenset({"/brief", "/sie", "/research", "/write", "/sources-cited"})


@app.middleware("http")
async def _blog_cost_accounting(request: Request, call_next):
    """Meter blog-pipeline Claude spend.

    Starts a per-request cost tally before the handler (the shared
    `modules/brief/llm.py` transport increments it on every Anthropic call) and
    injects the total as top-level `cost_usd` on the JSON response — which the
    orchestrator persists into `module_outputs.cost_usd`. Before this, blog
    modules reported $0 and their Claude spend was invisible.

    Best-effort and safe by construction: a non-blog path is passed straight
    through; if the cost tally never populated (e.g. context didn't propagate) or
    the body can't be parsed, the ORIGINAL response is re-emitted unchanged — the
    worst case is today's behaviour (no metering), never a broken response.
    """
    if request.url.path not in _BLOG_PATHS:
        return await call_next(request)
    blog_cost.start_accounting()
    response = await call_next(request)
    total = blog_cost.total_cost()
    tokens = blog_cost.total_tokens()
    ctype = response.headers.get("content-type", "")
    if total <= 0 or response.status_code >= 400 or not ctype.startswith("application/json"):
        return response
    body = b"".join([chunk async for chunk in response.body_iterator])
    headers = dict(response.headers)
    headers.pop("content-length", None)  # body length changes; let Response recompute
    try:
        data = json.loads(body)
        if isinstance(data, dict):
            data.setdefault("cost_usd", total)
            # Surface token usage alongside cost so the orchestrator can persist
            # it onto module_outputs.token_usage (blog Claude token accounting).
            if (tokens["input_tokens"] or tokens["output_tokens"]) and "token_usage" not in data:
                data["token_usage"] = tokens
            body = json.dumps(data).encode()
    except Exception:  # noqa: BLE001 — keep the original body on any parse/encode failure
        logger.warning("blog_cost_injection_failed", exc_info=True)
    return Response(content=body, status_code=response.status_code, headers=headers)


app.include_router(brief_router)
app.include_router(sie_router)
app.include_router(research_router)
app.include_router(writer_router)
app.include_router(sources_cited_router)
app.include_router(service_brief_router)
app.include_router(service_writer_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
