import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from config import settings

logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("pipeline-api starting up")
    yield
    logger.info("pipeline-api shutting down")


app = FastAPI(title="Pipeline API", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
