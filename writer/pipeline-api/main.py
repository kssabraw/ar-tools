import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings
from modules.brief import router as brief_router
from modules.research import router as research_router
from modules.sie import router as sie_router
from modules.writer import router as writer_router

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("pipeline-api starting up")
    yield
    logger.info("pipeline-api shutting down")


app = FastAPI(title="Pipeline API", lifespan=lifespan)

app.include_router(brief_router)
app.include_router(sie_router)
app.include_router(research_router)
app.include_router(writer_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
