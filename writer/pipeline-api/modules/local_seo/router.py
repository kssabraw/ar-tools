"""Local SEO module — pipeline-api endpoints (suite port of ShowUP Local).

This router owns the real FastAPI surface for the ported NLP engine in
`_service.py`. The engine file keeps its original `@app.post(...)` decorators
(now inert shims) for a clean diff against upstream; here we re-expose only the
**core** endpoints (per the locked Plan C scope: analyze / score / generate /
reoptimize), each under the `/local-seo` prefix.

Auth is NOT enforced here: pipeline-api runs on Railway's private network and is
only ever called by platform-api, which performs user auth at its public edge
(same model as the brief / sie / research / writer / sources_cited modules).

The two long-running handlers (`generate-page`, `reoptimize-page`) were converted
from SSE streaming to plain request/response (`_drain_to_result` in `_service.py`)
per the C-poll decision — platform-api drives them as async_jobs and polls.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from . import _service as engine
from ._service import (
    AnalysisRequest,
    AnalysisResponse,
    GeneratePageRequest,
    GeneratePageResponse,
    ReoptimizePageRequest,
    ReoptimizePageResponse,
    ReoptimizeSectionRequest,
    ReoptimizeSectionResponse,
    ScorePageRequest,
    ScorePageResponse,
)

logger = logging.getLogger(__name__)

# Module schema version. platform-api validates this when it persists Local SEO
# outputs (Local SEO is not an orchestrate_run stage, so validation lives on the
# platform side rather than in services/orchestrator.py's EXPECTED_MODULE_VERSIONS).
SCHEMA_VERSION = "1.0"

router = APIRouter(prefix="/local-seo", tags=["local_seo"])


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: Request, body: AnalysisRequest):
    """Keyword + location competitor analysis (DataForSEO -> ScrapeOwl -> TF-IDF /
    quadgrams / Google NLP entities)."""
    logger.info("local_seo.analyze.start", extra={"keyword": body.keyword})
    try:
        return await engine.analyze(request, body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_seo.analyze.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/score-page", response_model=ScorePageResponse)
async def score_page(request: Request, body: ScorePageRequest):
    """Score a page against the 8 engines (7 Claude-scored + serp_signal_coverage)."""
    logger.info("local_seo.score_page.start", extra={"keyword": body.keyword})
    try:
        return await engine.score_page(request, body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_seo.score_page.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/generate-page", response_model=GeneratePageResponse)
async def generate_page(request: Request, body: GeneratePageRequest):
    """Generate an optimized local-SEO HTML page (+ JSON-LD, content gaps, score).

    Long-running: platform-api invokes this from an async_jobs worker.
    """
    logger.info("local_seo.generate_page.start", extra={"keyword": body.keyword})
    try:
        return await engine.generate_page(request, body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_seo.generate_page.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/reoptimize-page", response_model=ReoptimizePageResponse)
async def reoptimize_page(request: Request, body: ReoptimizePageRequest):
    """Reoptimize an existing page to fix scored deficiencies.

    Long-running: platform-api invokes this from an async_jobs worker.
    """
    logger.info("local_seo.reoptimize_page.start", extra={"keyword": body.keyword})
    try:
        return await engine.reoptimize_page(request, body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_seo.reoptimize_page.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")


@router.post("/reoptimize-section", response_model=ReoptimizeSectionResponse)
async def reoptimize_section(request: Request, body: ReoptimizeSectionRequest):
    """Rewrite a single HTML section to fix a specific deficiency."""
    logger.info("local_seo.reoptimize_section.start")
    try:
        return await engine.reoptimize_section(request, body)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("local_seo.reoptimize_section.unexpected: %s", exc)
        raise HTTPException(status_code=500, detail="internal_error")
