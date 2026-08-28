"""Run-free 'Score an existing page' endpoints for the Blog + Service writers.

A check-only score of a live URL / pasted content — entity usage + gaps and the
8-engine rubric — that spawns NO run and rewrites nothing (unlike the
reoptimize-existing flow). Local SEO + Ecommerce already have their own run-free
score jobs; these two are the gap. The score runs as a background `score_external`
job (SERP analysis + Claude take a couple of minutes), polled for the ScoreResult.

Scoring is observation, not output, so these are intentionally not freeze-gated.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from middleware.auth import require_auth
from services import score_external

router = APIRouter(tags=["score"])


class ScoreExistingRequest(BaseModel):
    keyword: str
    page_url: Optional[str] = None
    page_content: Optional[str] = None
    # 'textrazor' (default) | 'google' — the SERP entity-extraction engine.
    entity_provider: Optional[str] = None


class ServiceScoreExistingRequest(ScoreExistingRequest):
    # "service_page" (national) | "location_page" (local, geo-anchored).
    page_type: str = "service_page"
    location: Optional[str] = None
    location_code: Optional[int] = None


class ScoreExistingJob(BaseModel):
    job_id: str
    status: str = "pending"


class ScoreExistingStatus(BaseModel):
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None


def _validate_source(body: ScoreExistingRequest) -> None:
    if not (body.keyword or "").strip():
        raise HTTPException(status_code=400, detail="keyword_required")
    if not (body.page_url or "").strip() and not (body.page_content or "").strip():
        raise HTTPException(status_code=400, detail="page_url_or_content_required")


@router.post("/clients/{client_id}/blog/score-existing", response_model=ScoreExistingJob)
async def score_existing_blog_page(
    client_id: UUID,
    body: ScoreExistingRequest,
    auth: dict = Depends(require_auth),
) -> ScoreExistingJob:
    """Score an external blog article (live URL or pasted content) as a background
    job — check only, no run, no rewrite. Poll `GET .../score-existing/{job_id}`."""
    _validate_source(body)
    job_id = score_external.enqueue(
        str(client_id), "blog",
        {
            "keyword": body.keyword,
            "page_url": body.page_url,
            "page_content": body.page_content,
            "entity_provider": body.entity_provider,
        },
        auth["user_id"],
    )
    return ScoreExistingJob(job_id=job_id)


@router.post("/clients/{client_id}/service-pages/score-existing", response_model=ScoreExistingJob)
async def score_existing_service_page(
    client_id: UUID,
    body: ServiceScoreExistingRequest,
    auth: dict = Depends(require_auth),
) -> ScoreExistingJob:
    """Score an external service/location page (live URL or pasted content) as a
    background job — check only, no run, no rewrite. Location pages score against
    the supplied area; service pages score national. Poll the job for the result."""
    _validate_source(body)
    job_id = score_external.enqueue(
        str(client_id), "service",
        {
            "keyword": body.keyword,
            "page_url": body.page_url,
            "page_content": body.page_content,
            "page_type": body.page_type,
            "location": body.location,
            "location_code": body.location_code,
            "entity_provider": body.entity_provider,
        },
        auth["user_id"],
    )
    return ScoreExistingJob(job_id=job_id)


@router.get("/clients/{client_id}/score-existing/{job_id}", response_model=ScoreExistingStatus)
async def get_score_existing_job(
    client_id: UUID,
    job_id: UUID,
    auth: dict = Depends(require_auth),
) -> ScoreExistingStatus:
    """Poll a run-free score job; on completion `result` carries the ScoreResult."""
    row = score_external.get_status(str(client_id), str(job_id))
    if not row:
        raise HTTPException(status_code=404, detail="job_not_found")
    return ScoreExistingStatus(
        status=row.get("status") or "pending",
        result=row.get("result"),
        error=row.get("error"),
    )
